import json
import httpx
import pytest
from app.openai import provider_error_detail
from app.recommendations import RecommendationError
from test_openai import run


@pytest.mark.parametrize('body,reason',[(None,'INVALID_BODY_TYPE'),(b'','EMPTY_BODY'),(b'PRIVATE'*2000,'BODY_TOO_LARGE'),(b'PRIVATE','INVALID_JSON_OR_ENCODING'),(b'\xff','INVALID_JSON_OR_ENCODING'),(b'{}','ERROR_OBJECT_ABSENT'),(b'[]','ERROR_OBJECT_ABSENT')])
def test_unavailable_details_are_distinct_and_never_raw(body,reason):
    result=provider_error_detail(body)
    assert result=={'detail':'UNAVAILABLE','unavailableReason':reason}
    assert 'PRIVATE' not in json.dumps(result)


@pytest.mark.parametrize('status',[400,429,500,503])
def test_failures_do_not_retry_or_echo_body(status,caplog):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,headers={'Retry-After':'3600'},json={'error':{'code':'rate_limit_exceeded' if status==429 else 'invalid_request_error','message':'PRIVATE_PROVIDER_MESSAGE'}})
    with pytest.raises(RecommendationError) as error:run(handler)
    assert len(calls)==1
    assert error.value.code==('AI_RATE_LIMITED' if status==429 else 'AI_PROVIDER_FAILED')
    assert 'PRIVATE_PROVIDER_MESSAGE' not in caplog.text
    assert str(status) in caplog.text
