"""Node is needed for this cross-language test (already needed by the React app)."""
import json
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import httpx
import pytest
import uvicorn
from app.main import create_app
from app.models import TripPreferences
from app.storage import trip_row

ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.skipif(shutil.which('node') is None, reason='Node is needed for the existing frontend client integration test')
def test_existing_frontend_client_reaches_fastapi_and_schema(payload):
    rows = []
    class FakeStore:
        async def save(self, preferences):
            rows.append(trip_row(preferences))
            return 101
    sock = socket.socket()
    sock.bind(('127.0.0.1',0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(FakeStore()), host='127.0.0.1',port=port,log_level='error',lifespan='off'))
    thread = threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True)
    thread.start()
    try:
        deadline = time.monotonic()+5
        while not server.started and time.monotonic()<deadline:
            time.sleep(.01)
        assert server.started
        script = """
          import { createTrip } from './frontend/src/services/api.js';
          import { buildTripPayload, createInitialForm } from './frontend/src/utils/tripPreferences.js';
          const form = {...createInitialForm(), ...JSON.parse(process.argv[1]), travelStyle:'comfort',mobilityConcerns:'Avoid stairs'};
          const checked = buildTripPayload(form);
          if (!checked.valid) throw new Error('Frontend validation failed');
          const saved = await createTrip(checked.value,{baseUrl:process.argv[2]});
          process.stdout.write(JSON.stringify(saved));
        """
        result = subprocess.run(['node','--input-type=module','-e',script,json.dumps(payload),f'http://127.0.0.1:{port}/api'],cwd=ROOT,capture_output=True,text=True,timeout=20,check=True)
        assert json.loads(result.stdout)=={'id':101}
        assert len(rows)==1
        assert json.loads(rows[0]['preferences'])['mobilityConcerns']=='Avoid stairs'
    finally:
        server.should_exit=True
        thread.join(timeout=5)
        sock.close()

@pytest.mark.skipif(shutil.which('node') is None, reason='Node is needed for JS/Python contract comparison')
def test_shared_contract_parity(payload):
    cases=[payload, {**payload,'travelers':2.0}, {**payload,'destination':'\ufeffGoa\ufeff'},
           {**payload,'destination':'😀'*101}, {**payload,'mobilityConcerns':'😀'*251},
           {**payload,'budget':True},{**payload,'travelStyle':'comfort'}, {**payload,'mobilityConcerns':None},
           {**payload,'interests':['food','food']}, {**payload,'endDate':'2026-01-01'}]
    script="import {validateTripPreferences} from './shared/tripPreferences.mjs'; process.stdout.write(JSON.stringify(JSON.parse(process.argv[1]).map(x=>validateTripPreferences(x).valid)));"
    result=subprocess.run(['node','--input-type=module','-e',script,json.dumps(cases)],cwd=ROOT,capture_output=True,text=True,check=True)
    js_valid=json.loads(result.stdout)
    python_valid=[]
    for case in cases:
        try:
            TripPreferences.model_validate(case)
            python_valid.append(True)
        except ValueError:
            python_valid.append(False)
    assert python_valid==js_valid
