"""Private Groq refinement shape. No provider calls, repairs, or storage."""
from copy import deepcopy
import json
from .recommendations import RecommendationError


def invalid(reason='FORMAT_SCHEMA'):
    return RecommendationError('AI_INVALID_RESPONSE', 502,
        'The refined plan failed required checks. Your previous plan is unchanged.', reason=reason)


def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def check_shape(value, schema, root):
    """Recheck the exact projected subset even when a fake provider ignores it."""
    if '$ref' in schema:
        ref=schema['$ref']
        if not ref.startswith('#/$defs/'):
            raise ValueError()
        return check_shape(value,root['$defs'][ref[len('#/$defs/'):]],root)
    if 'anyOf' in schema:
        for branch in schema['anyOf']:
            try:
                check_shape(value,branch,root)
                return
            except (ValueError,TypeError,KeyError):
                pass
        raise ValueError()
    kind=schema.get('type')
    if kind=='object':
        props=schema['properties']
        if type(value) is not dict or set(value)!=set(props):
            raise ValueError()
        for key,child in props.items():
            check_shape(value[key],child,root)
    elif kind=='array':
        if type(value) is not list:
            raise ValueError()
        for item in value:
            check_shape(item,schema['items'],root)
    elif kind=='string' and type(value) is not str:
        raise ValueError()
    elif kind=='integer' and type(value) is not int:
        raise ValueError()
    elif kind=='number' and type(value) not in (int,float):
        raise ValueError()
    elif kind=='boolean' and type(value) is not bool:
        raise ValueError()
    elif kind=='null' and value is not None:
        raise ValueError()
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError()


class RefinementContract:
    def __init__(self, request):
        from .itineraries import ItineraryPayload
        from .groq import strict_schema
        self.request=request
        self.selected=[d for d in request.previous.days if request.targetDate is None or d.date==request.targetDate]
        public_schema=ItineraryPayload.model_json_schema()
        base=strict_schema(public_schema)
        # Unsupported length/numeric keywords remain local checks; describe every
        # public bound in the provider-visible schema without pretending enforcement.
        def describe_bounds(node, public):
            clauses=[]
            for key,label in (('minLength','Minimum characters'),('maxLength','Maximum characters'),
                              ('minimum','Minimum numeric value'),('maximum','Maximum numeric value'),
                              ('minItems','Minimum items'),('maxItems','Maximum items')):
                if key in public: clauses.append(f'{label}: {public[key]}.')
            if public.get('minLength',0)>0: clauses.append('Must contain non-whitespace text.')
            if clauses: node['description']=' '.join([node.get('description','')]+clauses).strip()
            for group in ('properties','$defs'):
                for name,child in node.get(group,{}).items(): describe_bounds(child,public[group][name])
            for index,child in enumerate(node.get('anyOf',[])): describe_bounds(child,public['anyOf'][index])
            if 'items' in node: describe_bounds(node['items'],public['items'])
        describe_bounds(base,public_schema)
        definitions=deepcopy(base['$defs'])
        activity=deepcopy(definitions['ItineraryActivity'])
        activity['properties']['kind']={'type':'string','enum':['main']}
        activity['properties']['fixedTime']={'type':'boolean','enum':[False]}
        definitions['NewMainActivity']=activity
        minimum,maximum={'relaxed':(1,2),'balanced':(2,3),'fast':(3,4)}[request.preferences.travelPace]
        self.pace_bounds = (minimum, maximum)
        cap=min(request.maxMainActivitiesPerDay,maximum)
        self.mapping={}
        self.slot_names={}
        day_properties={}
        for index,day in enumerate(self.selected):
            fixed=[a.model_dump() for a in day.activities if a.fixedTime]
            if any(a['kind']=='unknown' for a in fixed):
                raise RecommendationError('REFINEMENT_FIXED_CONFLICT',422,
                    'Classify fixed legacy activities before capped refinement. Your previous plan is unchanged.')
            fixed_main=sum(a['kind']=='main' for a in fixed)
            if fixed_main>cap or len(fixed)+max(0,minimum-fixed_main)>8:
                raise RecommendationError('REFINEMENT_FIXED_CONFLICT',422,
                    'Fixed commitments do not fit this activity limit. Your previous plan is unchanged.')
            slots={}
            for n in range(min(cap-fixed_main,8-len(fixed))):
                item={'$ref':'#/$defs/NewMainActivity'}
                if n>=max(0,minimum-fixed_main):
                    item={'anyOf':[item,{'type':'null'}]}
                slots[f'main_{n+1}']=item
            props={k:deepcopy(v) for k,v in definitions['ItineraryDay']['properties'].items()
                   if k not in {'date','activities','mainActivityCount'}}
            props['mainSlots']=obj(slots)
            key=f'day_{index+1}'
            day_properties[key]=obj(props)
            day_properties[key]['description']=f'Revise only {day.date}. Fixed commitments are preserved by the server; include their costs and context, not duplicate timeline entries.'
            self.mapping[key]=(day,fixed)
            self.slot_names[key]=list(slots)
        self.schema=obj({'status':{'type':'string','enum':['planned','infeasible']},
                         'explanation':deepcopy(base['properties']['explanation']),
                         'verificationWarning':{'type':'string','description':'One nonempty, non-whitespace verification caveat of 1-500 characters, authored for this revised plan. State that estimates are unverified and prices, hours, availability, dietary suitability and accessibility need checking. Retain relevant original uncertainties concisely; do not invent assurances.'},
                         'days':{'anyOf':[obj(day_properties),{'type':'null'}]}})
        self.schema['$defs']={name:definitions[name] for name in ('DayCosts','NewMainActivity')}
        self.instructions=('\nPRIVATE REFINEMENT RESPONSE CONTRACT: Return the supplied private schema, not the full public itinerary shape. '
            'days is an object with exactly these required key-to-date mappings: '+json.dumps({k:d.date for k,(d,_) in self.mapping.items()})+'. '
            'For planned status fill every day and all required narrative/cost fields; for infeasible use days=null and explain why. '
            'Always supply a nonempty verificationWarning; this single AI-authored caveat becomes the public warnings array. Do not emit a warnings array in the private response. '
            'mainSlots contains ONLY new or revised non-fixed main activities in chronological order; never relabel meals, rest, transfers or lodging as main. '
            'Nullable main slots may be null only when the original pace minimum remains satisfied. '
            'All original fixed commitments are explicitly preserved by the server unchanged; do not return duplicates or replacements for them. '
            'Account for their times, travel gaps and whole-day costs when planning the new main slots. '
            'Retain meal, transfer, rest, dietary and mobility requirements in dining, transitAndRest and day-part narratives; do not omit requirements. '
            'New slots must not overlap each other or the fixed commitments and must end by midnight. '
            'Do not change the original trip constraints. The server maps dates and requested vibe from the request, merges fixed commitments, '
            'and validates the entire result; it never repairs invalid times or drops an invalid activity.')

    def decode(self, raw):
        from .itineraries import ItineraryActivity, ItineraryPayload
        try:
            text=raw if isinstance(raw,str) else json.dumps(raw,allow_nan=False)
            if len(text.encode('utf-8'))>65536:
                raise ValueError()
            def unique(pairs):
                result={}
                for key,value in pairs:
                    if key in result:
                        raise ValueError()
                    result[key]=value
                return result
            data=json.loads(text,object_pairs_hook=unique)
            check_shape(data,self.schema,self.schema)
            if (not data['verificationWarning'].strip() or len(data['verificationWarning'])>500
                    or not data['explanation'].strip() or len(data['explanation'])>1000):
                raise ValueError()
            if data['status']=='infeasible':
                if data['days'] is not None:
                    raise ValueError()
                raise RecommendationError('REFINEMENT_INFEASIBLE',422,
                    'The requested revision could not fit the constraints. Your previous plan is unchanged.')
            if data['days'] is None:
                raise ValueError()
            revised={}
            for key,(original,fixed) in self.mapping.items():
                day=deepcopy(data['days'][key])
                slots=day.pop('mainSlots')
                activities=[ItineraryActivity.model_validate(slots[name]).model_dump() for name in self.slot_names[key] if slots[name] is not None]
                end=0
                for activity in activities:
                    h,m=map(int,activity['startTime'].split(':'))
                    start=h*60+m
                    if start<end or start+activity['durationMinutes']>1440:
                        raise invalid('TIMELINE')
                    end=start+activity['durationMinutes']
                # This is an explicit merge with immutable input commitments, never a time repair.
                activities=sorted(activities+deepcopy(fixed),key=lambda a:a['startTime'])
                day.update(date=original.date,activities=activities,
                           mainActivityCount=sum(a['kind']=='main' for a in activities))
                revised[original.date]=day
            result={k:v for k,v in self.request.previous.model_dump().items() if k in ItineraryPayload.model_fields}
            result.update(status='planned',explanation=data['explanation'],warnings=[data['verificationWarning']],vibe=self.request.vibe,
                          days=[revised.get(d.date,d.model_dump()) for d in self.request.previous.days])
            return result
        except RecommendationError:
            raise
        except (ValueError,TypeError,KeyError,AttributeError):
            raise invalid() from None
