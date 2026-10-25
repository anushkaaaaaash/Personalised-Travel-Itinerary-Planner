"""Generation-only proposal shape: named slots and constructive scheduling.

No old absolute-time response is repaired. The model explicitly proposes an
ordered sequence of durations and gaps; the adapter computes its clock times.
"""
from copy import deepcopy
from datetime import date,timedelta
import json
from .refinement_contract import obj,check_shape
from .recommendations import RecommendationError

SCHEDULE_NOTICE=('Schedule times are computed from AI-proposed ordered activities, durations and gaps; '
    'they are not bookings or verified opening/transport times. Confirm feasibility before travel.')

class GenerationContract:
    def __init__(self,preferences):
        from .itineraries import ItineraryPayload
        from .groq import strict_schema
        self.preferences=preferences
        self.dates=[(date.fromisoformat(preferences.startDate)+timedelta(days=i)).isoformat()
            for i in range((date.fromisoformat(preferences.endDate)-date.fromisoformat(preferences.startDate)).days+1)]
        self.minimum,self.maximum={'relaxed':(1,2),'balanced':(2,3),'fast':(3,4)}[preferences.travelPace]
        base=ItineraryPayload.model_json_schema();defs=deepcopy(base['$defs'])
        activity=defs['ItineraryActivity']['properties']
        activity.pop('startTime');activity.pop('fixedTime')
        activity['gapBeforeMinutes']={'type':'integer','enum':list(range(241)),
            'description':'Nonnegative travel/rest gap after the previous entry (or day start for the first), 0-240 minutes. No overlaps.'}
        main=deepcopy(activity);main['kind']={'type':'string','enum':['main']}
        support=deepcopy(activity);support['kind']={'type':'string','enum':['rest','transfer','meal','accommodation']}
        defs['MainProposal']=obj(main);defs['SupportProposal']=obj(support)
        self.slots={}
        for i in range(1,9):
            main_index=i//2 if i%2==0 else 0
            is_main=0<main_index<=self.maximum
            required=is_main and main_index<=self.minimum
            node={'$ref':'#/$defs/MainProposal' if is_main else '#/$defs/SupportProposal'}
            self.slots[f'entry_{i}']=node if required else {'anyOf':[node,{'type':'null'}]}
        public_day=defs['ItineraryDay']['properties']
        self.narratives=('morning','afternoon','evening','dining','dietaryNotes','mobilityNotes','transitAndRest')
        day={name:deepcopy(public_day[name]) for name in (*self.narratives,'interestTags','costs')}
        for name in self.narratives:
            day[name]['description']=f'Required nonblank AI-authored description, 1-{day[name]["maxLength"]} characters. Never empty; explicitly describe any planned rest/return arrangements without inventing bookings.'
        day['dayStart']={'type':'string','enum':[f'{h:02}:{m:02}' for h in range(24) for m in (0,15,30,45)]}
        day['entries']=obj(self.slots)
        defs['GenerationDay']=obj(day)
        # Remove unused public definitions so the private output has no competing
        # absolute-time shape or redundant model-selected mainActivityCount.
        defs.pop('ItineraryDay');defs.pop('ItineraryActivity')
        self.schema=obj({'status':{'type':'string','enum':['planned','infeasible']},
            'explanation':deepcopy(base['properties']['explanation']),
            'warnings':obj({'verificationWarning':{'type':'string','description':'Required nonblank warning, 1-500 characters: prices, hours, dining, accessibility and transport are unverified.'},
                'additionalWarnings':{'type':'array','items':{'type':'string'},'description':'Zero to six nonblank additional warnings; each 1-500 characters.'}}),
            'days':obj({f'day_{i+1}':{'anyOf':[{'$ref':'#/$defs/GenerationDay'},{'type':'null'}]} for i in range(len(self.dates))})})
        self.schema['$defs']=defs
        self.shape=strict_schema(self.schema)
        self.instructions=(
            '\nGENERATION PROPOSAL CONTRACT: Use ONLY the supplied private schema. Do not output the public days array, '
            'date, destination, currency, travelStyle, travelPace, vibe, mainActivityCount, startTime or fixedTime fields. '
            'The server supplies request metadata and computes counts and schedule times; it does not repair missing content. '
            f'Day keys in order represent these inclusive dates: {", ".join(self.dates)}. '
            f'For a planned result ALL day objects must be non-null, including arrival and departure days. Every day requires {self.minimum}-{self.maximum} real main experiences for the requested {preferences.travelPace} pace. '
            'Travel-only or rest-only days do not satisfy this existing pace rule; if these requirements cannot realistically fit, '
            'return infeasible, explain the conflicting constraints, and make ALL day values null. Never label meals or transfers as main experiences. '
            'Each day has eight named ordered slots entry_1 through entry_8. Required main slots must contain main experiences; '
            'nullable slots may be null. Use each real activity once. Include every main excursion in its main slot. '
            'Choose dayStart, then for each non-null entry in numeric order compute start = previous end + gapBeforeMinutes; '
            'for the first entry previous end is dayStart. End = start + durationMinutes. Choose realistic gaps for transport/rest. '
            'Check the entire duration/gap sum fits before midnight. Do not provide absolute entry times or fixed commitments: '
            'these preferences contain none. If real transport/venue constraints cannot be represented safely, report infeasible. '
            'All durations are integer 15-240 minutes. Each gap is integer 0-240 minutes. '
            'Supply every required narrative, including evening and dining, as nonblank text describing the same complete proposed day. '
            'Do not leave departure-day summaries blank. Avoid clock times in prose; the displayed schedule is computed from the sequence. '
            'Keep activity titles 1-160 characters and notes 1-500; dietary/mobility/transit notes at most500, other daily narratives at most700. '
            'Keep the original dates, interests, dietary/mobility needs and whole-group whole-trip budget. All five daily cost categories '
            'are estimates in the requested currency and must sum within that budget. Never invent cheap costs or bookings. '
            'The verificationWarning is mandatory nonblank text for both planned and infeasible outputs; additionalWarnings has at most six entries. '
            'All prices, locations, accessibility, dining, opening hours and transport times remain unverified. '
            'The server will add a separate disclosure that clock times were computed, not verified or booked.')

    def decode(self,raw):
        try:
            text=raw if isinstance(raw,str) else json.dumps(raw,allow_nan=False)
            if len(text.encode('utf-8'))>65536:raise ValueError()
            def unique(pairs):
                result={}
                for key,value in pairs:
                    if key in result:raise ValueError()
                    result[key]=value
                return result
            data=json.loads(text,object_pairs_hook=unique)
            check_shape(data,self.shape,self.shape)
            warning=data['warnings'];additional=warning['additionalWarnings']
            if len(additional)>6:raise ValueError()
            warnings=[warning['verificationWarning'],*additional]
            if any(type(w) is not str or not w.strip() or len(w)>500 for w in warnings):raise ValueError()
            days=[]
            for index in range(len(self.dates)):
                day=data['days'][f'day_{index+1}']
                if data['status']=='infeasible':
                    if day is not None:raise ValueError()
                    continue
                if day is None:raise ValueError()
                # Public validators still enforce all nonblank/length/semantic rules.
                for name in self.narratives:
                    if not day[name].strip():raise ValueError()
                h,m=map(int,day['dayStart'].split(':'));end=60*h+m
                activities=[]
                for name in self.slots:
                    entry=day['entries'][name]
                    if entry is None:continue
                    activity=deepcopy(entry);gap=activity.pop('gapBeforeMinutes')
                    start=end+gap;end=start+activity['durationMinutes']
                    if end>1440:raise ValueError()
                    activity.update(startTime=f'{start//60:02}:{start%60:02}',fixedTime=False)
                    activities.append(activity)
                count=sum(a['kind']=='main' for a in activities)
                if not self.minimum<=count<=self.maximum:raise ValueError()
                days.append({**{name:day[name] for name in (*self.narratives,'interestTags','costs')},
                    'date':self.dates[index],'activities':activities,'mainActivityCount':count})
            p=self.preferences
            return {'status':data['status'],'explanation':data['explanation'],'warnings':warnings+([SCHEDULE_NOTICE] if data['status']=='planned' else []),
                'days':days,'destination':p.destination,'currency':p.currency,'travelStyle':p.travelStyle,'travelPace':p.travelPace,'vibe':None}
        except (ValueError,TypeError,KeyError,AttributeError,UnicodeError):
            raise RecommendationError('AI_INVALID_RESPONSE',502,
                'The generated day proposal was incomplete or could not fit a valid schedule. No plan was accepted.',reason='FORMAT_SCHEMA') from None
