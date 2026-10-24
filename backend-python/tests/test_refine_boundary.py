from fastapi.testclient import TestClient
from app.main import create_app

def test_refinement_has_larger_but_bounded_envelope():
    client=TestClient(create_app())
    headers={'Content-Type':'application/json'}
    body='{}'+' '*20000
    # Schema error, not size error: prior itinerary envelopes can exceed 16 KiB.
    assert client.post('/api/itineraries/refine',headers=headers,content=body).status_code==400
    assert client.post('/api/recommendations',headers=headers,content=body).status_code==413
    assert client.post('/api/itineraries/refine',headers=headers,content='x'*(128*1024+1)).status_code==413
