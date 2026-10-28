"""Executed inside the actual no-network, non-root production image by CI.

Synthetic content only. No auth, provider, storage mutation or external fetch.
"""
from pathlib import Path
import app.main  # Normal application imports must work with the packaged assets.
from app.itinerary_pdf import render_pdf

root = Path(app.main.__file__).parent / 'pdf_fonts'
for filename in ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf', 'LICENSE.txt'):
    assert (root / filename).is_file(), 'Required licensed PDF asset missing'
preferences = {'destination': 'Paris', 'departureCity': 'Paris', 'startDate': '2028-01-01',
               'endDate': '2028-01-01', 'travelers': 1, 'budget': 100, 'currency': 'EUR'}
costs = {'accommodation': 10, 'meals': 10, 'localTransport': 0, 'activities': 0, 'departureTravel': 0}
day = {'date': '2028-01-01', 'activities': [{'startTime': '09:00', 'title': 'Café visit',
        'durationMinutes': 60, 'notes': 'Synthetic private PDF smoke test.'}], 'costs': costs,
       'morning': 'Walk in the city.', 'afternoon': 'Rest.', 'evening': 'Dinner.'}
plan = {'completedDays': 1, 'totalDays': 1, 'spentCents': 2000, 'totalBudgetCents': 10000}
data = render_pdf(preferences, plan, [{'checkpoint': {'itinerary': {'days': [day]}}}])
assert data.startswith(b'%PDF-') and data.rstrip().endswith(b'%%EOF')
assert b'/FontFile2' in data, 'Embedded TrueType fonts missing from PDF'
assert len(data) > 1000
print('PASS: packaged fonts/license, application import and real embedded-font PDF render; no network or paid calls')
