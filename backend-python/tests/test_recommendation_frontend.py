"""Actual frontend HTTP client and React cards with test-only provider over loopback."""
import json
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import pytest
import uvicorn
from app.main import create_app
from app.recommendations import RecommendationService

ROOT=Path(__file__).resolve().parents[2]

@pytest.mark.skipif(shutil.which('node') is None, reason='Node is required for frontend integration')
@pytest.mark.parametrize('configured',[True,False])
def test_client_to_fastapi_and_cards_without_save(payload, configured):
    class NeverSave:
        async def save(self, preferences):
            pytest.fail('Recommendation request must never save')
    class FakeProvider:
        name='test-only-provider'
        model='test-only-model'
        calls=0
        async def generate(self,messages,response_schema):
            self.calls+=1
            assert 'RECOMMENDATION SELECTION STAGE' in messages[0]['content']
            assert response_schema['properties']['recommendations']
            return {'destination':payload['destination'],'currency':payload['currency'],
                    'recommendations':[{'id':str(i),'category':category,'name':'Test '+category,
                    'description':'Test description','whyRecommended':'Matches selected culture',
                    'estimatedGroupCost':100,'interestTags':['culture'],'travelStyle':'',
                    'dietaryNotes':'Unspecified','mobilityNotes':'Unspecified; verify access'}
                    for i,category in enumerate(['attraction','activity','dining'])],
                    'warnings':['Test-only response; not verified travel advice']}
    provider=FakeProvider()
    service=RecommendationService(provider if configured else None)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(create_app(NeverSave(),service),host='127.0.0.1',port=port,log_level='error',lifespan='off'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    try:
        deadline=time.monotonic()+5
        while not server.started and time.monotonic()<deadline:time.sleep(.01)
        assert server.started
        script="""
        import {getRecommendations} from './frontend/src/services/recommendations.js';
        import React from 'react';
        import {renderToStaticMarkup} from 'react-dom/server';
        import {createServer} from 'vite';
        const prefs=JSON.parse(process.argv[1]);
        try {
          const result=await getRecommendations(prefs,{baseUrl:process.argv[2]});
          const vite=await createServer({root:'./frontend',logLevel:'silent',server:{middlewareMode:true,watch:null,hmr:false}});
          try {
            const {default:Cards}=await vite.ssrLoadModule('/src/components/RecommendationResults.jsx');
            const html=renderToStaticMarkup(React.createElement(Cards,{result,loading:false,error:''}));
            process.stdout.write(JSON.stringify({result,html}));
          } finally {await vite.close();}
        } catch(error) {process.stdout.write(JSON.stringify({error:error.message}));}
        """
        result=subprocess.run(['node','--input-type=module','-e',script,json.dumps(payload),f'http://127.0.0.1:{port}/api'],cwd=ROOT,capture_output=True,text=True,timeout=30,check=True)
        received=json.loads(result.stdout)
        if configured:
            assert received['result']['source']=='ai'
            assert all('Test '+category in received['html'] for category in ['attraction','activity','dining'])
            assert provider.calls==1
        else:
            assert 'not configured' in received['error']
            assert 'result' not in received
            assert provider.calls==0
    finally:
        server.should_exit=True;thread.join(timeout=5);sock.close()
