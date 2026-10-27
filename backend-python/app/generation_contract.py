"""Generation-only proposal shape: ordered activities and constructive scheduling.

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
    def __init__(self,preferences, *, travel_day_dates=(), nested_proposal=False):
        from .itineraries import ItineraryPayload
        from .openai import strict_schema
        self.preferences=preferences
        self.travel_day_dates=frozenset(travel_day_dates)
        self.dates=[(date.fromisoformat(preferences.startDate)+timedelta(days=i)).isoformat()
            for i in range((date.fromisoformat(preferences.endDate)-date.fromisoformat(preferences.startDate)).days+1)]
        self.minimum,self.maximum={'relaxed':(1,2),'balanced':(2,3),'fast':(3,4)}[preferences.travelPace]
        base=ItineraryPayload.model_json_schema();defs=deepcopy(base['$defs'])
        activity=defs['ItineraryActivity']['properties']
        activity.pop('startTime');activity.pop('fixedTime')
        # Share the finite gap domain: duplicating it in both proposal definitions
        # exceeded OpenAI's 1,000-total-enum-value strict-schema limit.
        # OpenAI strict schemas reject sibling keywords beside $ref. Put the
        # shared annotation on the definition, preserving the exact gap domain.
        defs['GapBeforeMinutes']={'type':'integer','enum':list(range(241)),
            'description':'Nonnegative travel/rest gap after the previous entry (or day start for the first), 0-240 minutes. No overlaps.'}
        activity['gapBeforeMinutes']={'$ref':'#/$defs/GapBeforeMinutes'}
        activity['kind']={'type':'string','enum':['main','rest','transfer','meal','accommodation']}
        activity['sequence']={'type':'integer','enum':list(range(1,9)),
            'description':'Unique position across requiredMainActivities and activities together, consecutive 1 through total entries. This specifies the intended chronological order.'}
        defs['ActivityProposal']=obj(activity)
        main=deepcopy(activity);main['kind']={'type':'string','enum':['main']}
        defs['RequiredMainProposal']=obj(main)
        public_day=defs['ItineraryDay']['properties']
        self.narratives=('morning','afternoon','evening','dining','dietaryNotes','mobilityNotes','transitAndRest')
        day={'date':{'type':'string','enum':self.dates},
            **{name:deepcopy(public_day[name]) for name in (*self.narratives,'interestTags','costs')}}
        for name in self.narratives:
            day[name]['description']=f'Required nonblank AI-authored description, 1-{day[name]["maxLength"]} characters. Never empty; explicitly describe any planned rest/return arrangements without inventing bookings.'
        day['dayStart']={'type':'string','enum':[f'{h:02}:{m:02}' for h in range(24) for m in (0,15,30,45)]}
        day['requiredMainActivities']=obj({f'main_{i+1}':{'$ref':'#/$defs/RequiredMainProposal'} for i in range(self.minimum)})
        if self.travel_day_dates:
            for key, value in day['requiredMainActivities']['properties'].items():
                day['requiredMainActivities']['properties'][key]={'anyOf':[value,{'type':'null'}]}
        day['activities']={'type':'array','items':{'$ref':'#/$defs/ActivityProposal'},
            'description':f'Additional entries only, not copies of requiredMainActivities. At most {8-self.minimum} additional entries and at most one additional main. Empty is allowed. Combined sequence specifies order; local validation enforces upper bounds.'}
        if self.travel_day_dates:
            day['activities']['description']='Additional entries only, not copies of non-null requiredMainActivities. At most eight entries total across both containers. Include explicit transport segments; local validation checks pace and travel-day eligibility.'
        defs['GenerationDay']=obj(day)
        # Remove unused public definitions so the private output has no competing
        # absolute-time shape or redundant model-selected mainActivityCount.
        defs.pop('ItineraryDay');defs.pop('ItineraryActivity')
        self.schema=obj({'days':{'type':'array','items':{'$ref':'#/$defs/GenerationDay'},
                'description':f'For planned output include all {len(self.dates)} requested dates exactly once in order. For infeasible output use an empty array. Never omit this property.'},
            'status':{'type':'string','enum':['planned','infeasible']},
            'explanation':deepcopy(base['properties']['explanation']),
            'warnings':obj({'verificationWarning':{'type':'string','description':'Required nonblank warning, 1-500 characters: prices, hours, dining, accessibility and transport are unverified.'},
                'additionalWarnings':{'type':'array','items':{'type':'string'},'description':'Zero to six nonblank additional warnings; each 1-500 characters.'}})})
        self.schema['$defs']=defs
        self.shape=strict_schema(self.schema)
        pace_instructions=(
            f'Ordinary days require {self.minimum}-{self.maximum} genuine main experiences. '
            f'Only explicitly eligible travel dates {sorted(self.travel_day_dates)} may have fewer (including zero) main experiences when explicit kind=transfer entries total at least120 minutes. '
            'An intermediate section boundary alone does not qualify; only an explicit higher-level validated route-transition rule may add another eligible date. Keep all requiredMainActivities keys; use null for omitted main slots only on qualifying travel days. '
            'Put explicit transport segments in activities; never relabel sightseeing as transport. Travel costs, realistic timing and rest still apply. '
            if self.travel_day_dates else
            f'Every day requires {self.minimum}-{self.maximum} real main experiences, including arrival and departure. Travel-only or rest-only days do not satisfy this pace rule. '
        )
        self.instructions=(
            ('\nGENERATION PROPOSAL CONTRACT: The proposal object must contain ALL four fields: days, status, explanation, warnings. Follow the enclosing section schema for root fields. '
             if nested_proposal else '\nGENERATION PROPOSAL CONTRACT: Return one complete JSON object with ALL four root fields: days, status, explanation, warnings. ')
            + 'Write the complete days array first within that object; an explanation and warnings alone are never a planned itinerary. '
            'Each day object must contain date, morning, afternoon, evening, dining, dietaryNotes, mobilityNotes, transitAndRest, interestTags, costs, dayStart, requiredMainActivities and activities. '
            'Each activity must contain id, title, durationMinutes, notes, latitude, longitude, kind, gapBeforeMinutes and sequence. '
            'Do not output destination, currency, travelStyle, travelPace, vibe, mainActivityCount, startTime or fixedTime fields. '
            'The server supplies request metadata and computes counts and schedule times; it does not repair missing content. '
            f'For planned output days must contain exactly {len(self.dates)} complete objects with these dates exactly once in this order: {", ".join(self.dates)}. '
            + pace_instructions +
            'If actual constraints still cannot fit, return status infeasible, explanation and warnings, AND days: []. Never omit days. Never label meals or transfers as main experiences. '
            'The activities array contains only additional entries, optionally one more main experience. Do not repeat the required main experiences there. '
            'Across both containers there must be at most eight total entries. Assign unique consecutive sequence positions 1 through the total count across BOTH containers. '
            'Main, meal, transfer, rest and accommodation entries may appear in any realistic sequence; required main keys do not impose timeline positions. '
            'Use each real activity once and include every main excursion. '
            'Choose dayStart, then for each entry in sequence order compute start = previous end + gapBeforeMinutes; '
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
            'For planned output the server adds a separate disclosure that clock times were computed, not verified or booked.')

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
            if data['status']=='infeasible' and data['days']:raise ValueError()
            if data['status']=='planned' and [day['date'] for day in data['days']]!=self.dates:raise ValueError()
            for day in data['days']:
                # Public validators still enforce all nonblank/length/semantic rules.
                for name in self.narratives:
                    if not day[name].strip():raise ValueError()
                h,m=map(int,day['dayStart'].split(':'));end=60*h+m
                activities=[]
                entries=[*[v for v in day['requiredMainActivities'].values() if v is not None],*day['activities']]
                if not 1<=len(entries)<=8:raise ValueError()
                entries=sorted(entries,key=lambda entry:entry['sequence'])
                if [entry['sequence'] for entry in entries]!=list(range(1,len(entries)+1)):raise ValueError()
                for entry in entries:
                    activity=deepcopy(entry);gap=activity.pop('gapBeforeMinutes');activity.pop('sequence')
                    start=end+gap;end=start+activity['durationMinutes']
                    if end>1440:raise ValueError()
                    activity.update(startTime=f'{start//60:02}:{start%60:02}',fixedTime=False)
                    activities.append(activity)
                count=sum(a['kind']=='main' for a in activities)
                from .itineraries import is_adaptive_travel_day
                minimum=0 if is_adaptive_travel_day(day['date'],activities,self.travel_day_dates) else self.minimum
                if not minimum<=count<=self.maximum:raise ValueError()
                days.append({**{name:day[name] for name in (*self.narratives,'interestTags','costs')},
                    'date':day['date'],'activities':activities,'mainActivityCount':count})
            p=self.preferences
            return {'status':data['status'],'explanation':data['explanation'],'warnings':warnings+([SCHEDULE_NOTICE] if data['status']=='planned' else []),
                'days':days,'destination':p.destination,'currency':p.currency,'travelStyle':p.travelStyle,'travelPace':p.travelPace,'vibe':None}
        except (ValueError,TypeError,KeyError,AttributeError,UnicodeError):
            raise RecommendationError('AI_INVALID_RESPONSE',502,
                'The generated day proposal was incomplete or could not fit a valid schedule. No plan was accepted.',reason='FORMAT_SCHEMA') from None
