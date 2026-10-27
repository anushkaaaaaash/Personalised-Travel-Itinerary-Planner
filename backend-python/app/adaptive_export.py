"""Bounded owner-scoped text export; no archive write or provider operation."""
from datetime import date, timedelta
import re
from fastapi.responses import StreamingResponse
from .planning_repository import JobRepositoryError

MAX_EXPORT_BYTES = 24 * 1024 * 1024
MAX_EXPORT_PAGES = 32768
EXPORT_END = '\nEND OF ROAMORA EXPORT\n'


def _plain(value):
    # Prevent model/user text forging the integrity marker or terminal controls.
    return ''.join(c if c >= ' ' or c == '\n' else ' ' for c in str(value)).replace('END OF ROAMORA EXPORT', 'End of trip notes')


def _lines(value, depth=0):
    if depth > 12:
        raise JobRepositoryError('SECTION_INVALID_RESULT')
    if isinstance(value, dict):
        for key, item in value.items():
            if item is None: continue
            label = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', _plain(key)).replace('_', ' ').capitalize()
            yield '  '*depth + label + ':\n'
            yield from _lines(item, depth+1)
    elif isinstance(value, list):
        for item in value:
            yield '  '*depth + '-\n'
            yield from _lines(item, depth+1)
    else:
        yield '  '*depth + _plain(value) + '\n'


async def export_response(engine, owner, plan_id):
    snapshot = await engine.context(owner, plan_id)
    plan, preferences = snapshot['plan'], snapshot['preferences']
    if preferences is None or plan['status'] == 'expired':
        raise JobRepositoryError('SECTION_NOT_FOUND', 404)
    count = plan['completedDays']
    start = date.fromisoformat(preferences['startDate'])
    complete = plan['status'] == 'completed' and count == plan['totalDays']

    async def stream():
        size = 0
        def encode(text):
            nonlocal size
            data = text.encode('utf-8'); size += len(data)
            if size > MAX_EXPORT_BYTES: raise JobRepositoryError('SECTION_RESOURCE_LIMIT', 413)
            return data
        yield encode('ROAMORA — ' + ('COMPLETE' if complete else 'PARTIAL') + ' TRIP EXPORT\n'
            + 'Destination: ' + _plain(preferences.get('destination','')) + '\n'
            + f"Requested dates: {preferences['startDate']} to {preferences['endDate']}\n"
            + f"Accepted days: {count} of {plan['totalDays']}\n"
            + f"Accepted estimated cost: {plan['spentCents']//100}.{plan['spentCents']%100:02d} {preferences.get('currency','')}\n"
            + 'Prices, travel times and availability are estimates, not bookings or live guarantees.\n'
            + ('Detailed day plans for unfinished dates are not included; the route outline is provisional planning context.\n' if not complete else '')
            + 'This download is complete only when its final END OF ROAMORA EXPORT marker is present.\n\n')
        page = snapshot; cursor = 0; covered = 0; spent = 0; pages = 1
        while covered < count:
            for section in page['sections']:
                checkpoint = section['checkpoint']
                days = checkpoint['itinerary']['days']
                if covered >= count: break
                if len(days) > count-covered:
                    raise JobRepositoryError('SECTION_INVALID_RESULT')
                for day in days:
                    expected = (start+timedelta(days=covered)).isoformat()
                    if day['date'] != expected: raise JobRepositoryError('SECTION_INVALID_RESULT')
                    covered += 1
                spent += checkpoint['spentCents']
                if covered == len(days) and checkpoint.get('journeyStrategy'):
                    for line in _lines({'tripRoute':checkpoint['journeyStrategy']}): yield encode(line)
                yield encode(f"SECTION {section['startDate']} to {section['endDate']}\n")
                for line in _lines({'startLocation':checkpoint['startLocation'], 'endLocation':checkpoint['endLocation'],
                                    'itinerary':checkpoint['itinerary']}):
                    yield encode(line)
            if covered >= count: break
            next_cursor = page['nextCursor']
            if next_cursor is None or next_cursor <= cursor:
                raise JobRepositoryError('SECTION_INVALID_RESULT')
            cursor = next_cursor
            pages += 1
            if pages > MAX_EXPORT_PAGES: raise JobRepositoryError('SECTION_RESOURCE_LIMIT',413)
            page = await engine.context(owner, plan_id, cursor)
            if page['preferences'] is None: raise JobRepositoryError('SECTION_NOT_FOUND',404)
        if covered != count or spent != plan['spentCents']:
            raise JobRepositoryError('SECTION_INVALID_RESULT')
        yield encode(EXPORT_END)
    return StreamingResponse(stream(),media_type='text/plain; charset=utf-8',headers={
        'Content-Disposition':'attachment; filename="roamora-trip.txt"',
        'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'})
