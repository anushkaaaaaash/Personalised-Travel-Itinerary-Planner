"""Read-only, paginated PDF rendering. Never calls a provider or persists a trip."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
import json
import asyncio
import threading
import time
from functools import wraps
from fastapi.responses import Response, JSONResponse
from starlette.concurrency import run_in_threadpool
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, CondPageBreak
from .planning_repository import JobRepositoryError

MAX_BYTES = 24 * 1024 * 1024
MAX_INPUT_BYTES = 2 * 1024 * 1024
_EXPORT_SLOT = threading.BoundedSemaphore(1)
MAX_RENDER_SECONDS = 30
MAX_RENDER_PAGES = 2000
_RENDER_SLOT = threading.BoundedSemaphore(1)

def pdf_admission(function):
    """Reject concurrent exports before collecting pages; cancellation never frees a live worker's slot."""
    @wraps(function)
    async def guarded(*args,**kwargs):
        if not _EXPORT_SLOT.acquire(blocking=False):return JSONResponse({'error':{'code':'PDF_BUSY','message':'Another PDF is being prepared. Please try again shortly.'}},status_code=429)
        async def admitted():
            try:return await function(*args,**kwargs)
            finally:_EXPORT_SLOT.release()
        task=asyncio.create_task(admitted())
        # Retrieve exceptions even when the requesting client has gone away.
        task.add_done_callback(lambda done:done.exception() if not done.cancelled() else None)
        return await asyncio.shield(task)
    return guarded

class CappedBuffer(BytesIO):
    def write(self, data):
        if self.tell()+len(data)>MAX_BYTES:raise JobRepositoryError('SECTION_RESOURCE_LIMIT',413)
        return super().write(data)

class BoundedDocument(SimpleDocTemplate):
    def __init__(self,*args,deadline,**kwargs):
        self.deadline=deadline
        super().__init__(*args,**kwargs)
    def afterFlowable(self,flowable):
        if time.monotonic()>self.deadline or self.page>MAX_RENDER_PAGES:
            raise JobRepositoryError('SECTION_RESOURCE_LIMIT',413)

def bounded_renderer(function):
    @wraps(function)
    def guarded(*args,**kwargs):
        if not _RENDER_SLOT.acquire(blocking=False):raise JobRepositoryError('SECTION_RESOURCE_LIMIT',429)
        try:return function(*args,**kwargs)
        finally:_RENDER_SLOT.release()
    return guarded

COSTS = {'accommodation':'Accommodation','meals':'Meals','localTransport':'Local transport','activities':'Activities','departureTravel':'Travel to / from destination'}
FONTS = Path(__file__).with_name('pdf_fonts')
pdfmetrics.registerFont(TTFont('Trip',str(FONTS/'DejaVuSans.ttf')))
pdfmetrics.registerFont(TTFont('TripBold',str(FONTS/'DejaVuSans-Bold.ttf')))
pdfmetrics.registerFontFamily('Trip',normal='Trip',bold='TripBold',italic='Trip',boldItalic='TripBold')
pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))


def cents(value):
    value=Decimal(str(value))*100
    if not value.is_finite() or value<0: raise JobRepositoryError('SECTION_INVALID_RESULT')
    return int(value.quantize(Decimal('1'),rounding=ROUND_HALF_UP))


def text(value):
    # Escape model/user text before Paragraph's tiny XML grammar; no links or markup.
    value=str(value)
    out=[]
    cmap=pdfmetrics.getFont('Trip').face.charToGlyph
    for char in value:
        cp=ord(char)
        if char=='\n':out.append('<br/>')
        elif char in '\t\r':out.append(' ')
        elif cp in cmap:out.append(escape(char))
        elif 0x3000<=cp<=0x9fff or 0xff00<=cp<=0xffef:
            out.append('<font name="HeiseiKakuGo-W5">'+escape(char)+'</font>')
        else:
            # Preserve uncommon glyphs as explicit code points rather than silent boxes.
            out.append(escape(f'[U+{cp:04X}]'))
    return ''.join(out)


@bounded_renderer
def render_pdf(preferences,plan,sections):
    """Split paragraphs across pages, not screenshots or fixed-height day cards."""
    if len(json.dumps({'preferences':preferences,'sections':sections},ensure_ascii=False).encode())>MAX_INPUT_BYTES:raise JobRepositoryError('SECTION_RESOURCE_LIMIT',413)
    deadline=time.monotonic()+MAX_RENDER_SECONDS
    buffer=CappedBuffer(); ink=colors.HexColor('#173B38'); teal=colors.HexColor('#176960')
    body=ParagraphStyle('body',fontName='Trip',fontSize=10.5,leading=16,textColor=ink,spaceAfter=8,splitLongWords=True)
    small=ParagraphStyle('small',parent=body,fontSize=9,leading=13,textColor=colors.HexColor('#49635F'))
    heading=ParagraphStyle('heading',parent=body,fontName='TripBold',fontSize=17,leading=23,spaceBefore=14,spaceAfter=10,keepWithNext=True)
    title=ParagraphStyle('title',parent=heading,fontSize=27,leading=34)
    sub=ParagraphStyle('sub',parent=heading,fontSize=11,leading=16,spaceBefore=8,spaceAfter=5)
    p=lambda value,style=body:Paragraph(text(value),style)
    currency=preferences.get('currency',''); money=lambda v:f'{currency} {v//100:,}.{v%100:02d}'
    days=[day for section in sections for day in section['checkpoint']['itinerary']['days']]
    totals={key:sum(cents(day['costs'][key]) for day in days) for key in COSTS}
    spent=sum(totals.values())
    if len(days)!=plan['completedDays'] or spent!=plan['spentCents']:raise JobRepositoryError('SECTION_INVALID_RESULT')
    complete=len(days)==plan['totalDays']; budget=plan.get('totalBudgetCents',cents(preferences.get('budget',0)))
    story=[p('PERSONALISED TRAVEL PLANNER',small),p(preferences.get('destination','Your journey'),title),
        p(f"{preferences['startDate']} to {preferences['endDate']}  |  {preferences.get('travelers',1)} travelers",body),
        p(('COMPLETE ITINERARY' if complete else 'PARTIAL ITINERARY')+f"  |  {len(days)} of {plan['totalDays']} days",sub),
        p('Estimates, not bookings. Verify prices, opening hours, availability and accessibility before travel. This private PDF includes activity and personal travel notes; review it before sharing.',small)]
    if not complete:story.append(p('Unfinished dates are not included. The estimate below covers completed days only, not the whole requested journey.',body))
    story.append(p('Your expense overview',heading))
    def cost_table(rows):
        table=Table([[p(label,small),p(value,body)] for label,value in rows],colWidths=[290,170],hAlign='LEFT')
        table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#EFF5F2')),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),4),('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#D4E2DC'))]))
        return table
    story.append(p('Whole-group estimates, not per-person prices. Amounts are shown in '+currency+'.',small))
    story.append(cost_table([(label,money(totals[key])) for key,label in COSTS.items()]+[('Accepted estimate',money(spent)),('Original group budget',money(budget)),('Budget not allocated',money(max(0,budget-spent)))]))
    strategy=sections[0]['checkpoint'].get('journeyStrategy') if sections else None
    if strategy:
        story.extend([p('The route',heading),p(strategy.get('summary',''))])
        for stay in strategy.get('stays',[]):story.append(p(f"{stay['startDate']} to {stay['endDate']} | {stay['location']}",small))
    day_number=0
    for section in sections:
        itinerary=section['checkpoint']['itinerary']
        if itinerary.get('explanation'):story.extend([p('Planning notes',sub),p(itinerary['explanation'])])
        for warning in itinerary.get('warnings',[]):story.append(p('Check: '+warning,small))
        for day in itinerary['days']:
            if time.monotonic()>deadline:raise JobRepositoryError('SECTION_RESOURCE_LIMIT',413)
            day_number+=1;story.extend([CondPageBreak(115),p(f"Day {day_number:02d}  |  {date.fromisoformat(day['date']).strftime('%A, %d %B %Y')}",heading)])
            for activity in day.get('activities',[]):
                story.append(p(f"{activity['startTime']}  |  {activity['title']}  ({activity['durationMinutes']} min)",sub))
                if activity.get('notes'):story.append(p(activity['notes']))
                if activity.get('latitude') is not None:story.append(p(f"Map coordinates: {activity['latitude']}, {activity['longitude']}",small))
            for key,label in [('morning','Morning'),('afternoon','Afternoon'),('evening','Evening'),('dining','Dining'),('dietaryNotes','Dietary notes'),('mobilityNotes','Accessibility and mobility'),('transitAndRest','Transport and rest')]:
                if day.get(key):story.extend([p(label,sub),p(day[key])])
            story.append(p('Day expense breakdown',sub))
            story.append(cost_table([(label,money(cents(day['costs'][key]))) for key,label in COSTS.items()]+[('Daily group total',money(sum(cents(v) for v in day['costs'].values())))]))
    story.extend([Spacer(1,18),p(f'End of itinerary | {len(days)} dated days included. No reservation or account save is made by this download.',small)])
    def footer(canvas,doc):
        canvas.saveState();canvas.setStrokeColor(teal);canvas.line(48,42,547,42);canvas.setFont('Trip',8);canvas.setFillColor(ink)
        canvas.drawString(48,28,'Personalised Travel Planner  |  Private travel copy');canvas.drawRightString(547,28,f'Page {doc.page}');canvas.restoreState()
    doc=BoundedDocument(buffer,deadline=deadline,pagesize=(595.28,841.89),rightMargin=67,leftMargin=68,topMargin=46,bottomMargin=60,
        title='Personalised travel itinerary',author='Personalised Travel Planner',subject='Private trip itinerary and estimated expenses')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    data=buffer.getvalue()
    if len(data)>MAX_BYTES:raise JobRepositoryError('SECTION_RESOURCE_LIMIT',413)
    return data


@pdf_admission
async def pdf_response(engine,owner,plan_id):
    first=await engine.context(owner,plan_id);plan=first['plan'];preferences=first['preferences']
    if preferences is None or plan['status']=='expired':raise JobRepositoryError('SECTION_NOT_FOUND',404)
    sections=[];covered=spent=cursor=size=0;page=first;count=plan['completedDays'];start=date.fromisoformat(preferences['startDate'])
    while covered<count:
        for section in page['sections']:
            if covered==count:break
            cp=section['checkpoint'];days=cp['itinerary']['days']
            if not days or len(days)>count-covered:raise JobRepositoryError('SECTION_INVALID_RESULT')
            for day in days:
                if day['date']!=(start+timedelta(days=covered)).isoformat():raise JobRepositoryError('SECTION_INVALID_RESULT')
                covered+=1
            spent+=cp['spentCents'];size+=len(json.dumps(section,ensure_ascii=False).encode())
            if size>MAX_INPUT_BYTES or len(sections)>=32768:raise JobRepositoryError('SECTION_RESOURCE_LIMIT',413)
            sections.append(section)
        if covered==count:break
        next_cursor=page['nextCursor']
        if next_cursor is None or next_cursor<=cursor:raise JobRepositoryError('SECTION_INVALID_RESULT')
        cursor=next_cursor;page=await engine.context(owner,plan_id,cursor)
        if page.get('preferences')!=preferences or (plan.get('version') is not None and page['plan'].get('version')!=plan['version']):raise JobRepositoryError('SECTION_INVALID_RESULT')
    if covered!=count or spent!=plan['spentCents']:raise JobRepositoryError('SECTION_INVALID_RESULT')
    data=await run_in_threadpool(render_pdf,preferences,plan,sections)
    return Response(data,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="personalised-travel-itinerary.pdf"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


async def archived_pdf_response(service,saved_id):
    class ArchiveReader:
        async def context(self,owner,plan_id,cursor=0):
            value=await service.get(plan_id,cursor);saved=value['saved']
            return {'plan':{**saved,'status':'completed','completedDays':saved['totalDays']},'preferences':value['preferences'],'sections':value['sections'],'nextCursor':value['nextCursor']}
    return await pdf_response(ArchiveReader(),None,saved_id)
