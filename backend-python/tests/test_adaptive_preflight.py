import asyncio
from app.adaptive_preflight import preflight


def test_preflight_defaults_off_without_touching_configuration_or_network():
    def forbidden(*args,**kwargs):raise AssertionError('must not connect')
    assert asyncio.run(preflight({},gateway_factory=forbidden))=={'ready':False,'code':'PREFLIGHT_DISABLED'}


def test_preflight_only_exact_read_health_not_provider_or_queue_write():
    calls=[]
    class Gateway:
        elevated=True
        def __init__(self,*args,**kwargs):pass
        async def request(self,method,resource,**kwargs):
            calls.append((method,resource,kwargs))
            return [{'schema_version':1,'rpc_version':1,'cleanup_fresh':True}]
    assert asyncio.run(preflight({'ADAPTIVE_PREFLIGHT_APPROVED':'true'},gateway_factory=Gateway))=={'ready':True,'code':'READY'}
    assert calls==[('POST','rpc/adaptive_checkpoint_health',{'payload':{}})]


def test_preflight_hides_all_exception_and_secret_text():
    def failing(*args,**kwargs):raise RuntimeError('private fixture connection password')
    assert asyncio.run(preflight({'ADAPTIVE_PREFLIGHT_APPROVED':'true'},gateway_factory=failing))=={'ready':False,'code':'PREFLIGHT_FAILED'}
