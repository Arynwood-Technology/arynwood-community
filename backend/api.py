from contextlib import asynccontextmanager
from pathlib import Path
import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
from backend.routers import mail, irc, p2p
from backend.community import auth, routes, store

@asynccontextmanager
async def lifespan(app):
    store.initialize()
    yield
    await p2p.p2p_stop()

app = FastAPI(title='Arynwood Community', version=store.VERSION, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv('COMMUNITY_HOSTS','localhost,127.0.0.1,[::1]').split(','))

def allowed_origin(origin, host):
    expected = os.getenv('COMMUNITY_ORIGIN','').rstrip('/')
    if expected: return origin == expected
    return origin in ('http://'+host, 'https://'+host)

@app.middleware('http')
async def protections(request, call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin = request.headers.get('origin')
        if request.headers.get('x-community-request') != '1' or (origin and not allowed_origin(origin,request.headers.get('host',''))):
            return JSONResponse({'detail':'Request blocked. Reload and try again.'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    path=request.url.path
    # Vite fingerprints everything under /assets, so it can be cached indefinitely.
    response.headers['Cache-Control']='no-store' if path.startswith('/api') else 'public, max-age=31536000, immutable' if path.startswith('/assets/') else 'no-cache'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response

# Origin checks also cover WebSocket handshakes, which do not run HTTP middleware.
class SocketGuard:
    def __init__(self, app): self.app=app
    async def __call__(self, scope, receive, send):
        if scope['type']=='websocket':
            headers=dict(scope['headers'])
            origin=headers.get(b'origin',b'').decode()
            host=headers.get(b'host',b'').decode()
            if origin and not allowed_origin(origin,host):
                await send({'type':'websocket.close','code':1008})
                return
        await self.app(scope,receive,send)
app.add_middleware(SocketGuard)

app.include_router(auth.router,prefix='/api/auth')
app.include_router(routes.router,prefix='/api/community')
app.include_router(mail.router,prefix='/api/mail',dependencies=[Depends(auth.administrator)])
app.include_router(irc.router,prefix='/api/irc',dependencies=[Depends(auth.administrator)])
app.include_router(p2p.router,prefix='/api/p2p',dependencies=[Depends(auth.administrator)])

@app.get('/api/health')
def health():
    return {'status':'ok','name':'Arynwood Community','version':store.VERSION}

@app.api_route('/{path:path}',methods=['GET','HEAD'],include_in_schema=False)
def frontend(path:str):
    if path=='api' or path.startswith('api/'): raise HTTPException(404)
    dist=ROOT/'frontend'/'dist'
    target=(dist/path).resolve()
    if target.is_relative_to(dist.resolve()) and target.is_file(): return FileResponse(target)
    if path in ('','boards','chat','mail','calendar','irc','p2p','message','household','lists','notes','settings','join') and (dist/'index.html').exists():
        return FileResponse(dist/'index.html')
    raise HTTPException(404)
