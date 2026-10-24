"""Keep trip preferences, AI output and sessions out of shared HTTP caches."""
class NoStoreBoundary:
    def __init__(self, app):self.app=app
    async def __call__(self,scope,receive,send):
        async def private_send(message):
            if scope.get('path','').startswith('/api/') and message['type']=='http.response.start':
                message={**message,'headers':[(k,v) for k,v in message.get('headers',[]) if k.lower()!=b'cache-control']+[(b'cache-control',b'no-store')]}
            await send(message)
        return await self.app(scope,receive,private_send)
