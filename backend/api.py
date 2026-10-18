from contextlib import asynccontextmanager
from pathlib import Path
import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
from backend.routers import chat, mail, irc
from backend.community import admin, auth, editor, files, messages, routes, site_notes, store, webmaster, website, wishes, workspace_setup
from backend import grove, setup, brand

@asynccontextmanager
async def lifespan(app):
    store.initialize()
    grove.initialize()
    yield

app = FastAPI(title='Arynwood Grove', version=store.VERSION, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
hosts = [h.strip() for h in store.setting('HOSTS','localhost,127.0.0.1,[::1]').split(',') if h.strip()]
if store.public_origin(): hosts.append(urlsplit(store.public_origin()).hostname)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

def allowed_origin(origin, host):
    # GROVE_ORIGIN may list several pages, e.g. the owner's local workspace beside the
    # public address members use (GROVE_PUBLIC_URL).
    expected = {o.strip().rstrip('/') for o in store.setting('ORIGIN').split(',') if o.strip()}
    if store.public_origin(): expected.add(store.public_origin())
    if expected: return origin in expected
    return origin in ('http://'+host, 'https://'+host)

@app.middleware('http')
async def protections(request, call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin = request.headers.get('origin')
        if request.headers.get('x-community-request') != '1' or (origin and not allowed_origin(origin,request.headers.get('host',''))):
            return JSONResponse({'detail':'Request blocked. Reload and try again.'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    if 'x-frame-options' not in response.headers: response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    path=request.url.path
    # Vite fingerprints everything under /assets, so it can be cached indefinitely.
    # Live notices must pass through proxies (Cloudflare, nginx) unaltered and unbuffered.
    # A published website's pages say for themselves.
    if path.startswith('/api') or 'cache-control' not in response.headers: response.headers['Cache-Control']=('no-store, no-transform' if path.endswith('/events') else 'no-store') if path.startswith('/api') else 'public, max-age=31536000, immutable' if path.startswith('/assets/') else 'no-cache'
    # A file from the file bank brings its own, stricter policy.
    if 'content-security-policy' not in response.headers: response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
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

# The workspace reaches this service as /community-api (its dev proxy strips the prefix).
# Members' page is served by this service itself, so it answers the same paths directly.
class CommunityApiAlias:
    def __init__(self, app): self.app=app
    async def __call__(self, scope, receive, send):
        if scope['type'] in ('http','websocket') and (scope['path']=='/community-api' or scope['path'].startswith('/community-api/')):
            raw=scope.get('raw_path') or scope['path'].encode()
            scope=dict(scope, path='/api'+scope['path'][len('/community-api'):], raw_path=b'/api'+raw[len(b'/community-api'):])
        await self.app(scope,receive,send)
app.add_middleware(CommunityApiAlias)

app.include_router(grove.router,prefix='/api/grove')
app.include_router(setup.router,prefix='/api/grove-setup')
app.include_router(auth.router,prefix='/api/auth')
app.include_router(routes.router,prefix='/api/community')
app.include_router(files.router,prefix='/api/community')
app.include_router(workspace_setup.router,prefix='/api/community')
app.include_router(editor.router,prefix='/api/community')
app.include_router(admin.router,prefix='/api/admin')
app.include_router(wishes.router,prefix='/api/wishes')
app.include_router(webmaster.router,prefix='/api/webmaster')
app.include_router(website.router,prefix='/api/webmaster')
app.include_router(site_notes.router,prefix='/api/webmaster')
app.include_router(messages.router,prefix='/api/messages')
def host_tools():
    if not store.host_tools(): raise HTTPException(404,'Not found')
app.include_router(mail.router,prefix='/api/mail',dependencies=[Depends(host_tools),Depends(auth.administrator)])
app.include_router(irc.router,prefix='/api/irc',dependencies=[Depends(host_tools),Depends(auth.administrator)])
app.include_router(chat.router,prefix='/api/chat')
app.include_router(brand.router,prefix='/api/brand')

@app.get('/api/source')
def source_offer():
    from backend.source import archive
    return archive()

@app.get('/api/health')
def health():
    return {'status':'ok','name':'Arynwood Grove','version':store.VERSION}

MEMBER_PAGE = ROOT/'frontend'/'dist'
# Community 0.3's page addresses; they open the members' page, which moves them to /community.
LEGACY_ROUTES = ('','boards','chat','mail','calendar','irc','p2p','message','household','lists','notes','settings','join','projects','assistant','server')

def web_dir():
    """The members' page (npm --prefix frontend run build), or GROVE_WEB_DIR."""
    return Path(os.getenv('GROVE_WEB_DIR')) if os.getenv('GROVE_WEB_DIR') else MEMBER_PAGE

@app.api_route('/{path:path}',methods=['GET','HEAD'],include_in_schema=False)
def frontend(path:str,request:Request):
    if path=='api' or path.startswith('api/'): raise HTTPException(404)
    dist=web_dir()
    target=(dist/path).resolve()
    if path!='index.html' and target.is_relative_to(dist.resolve()) and target.is_file(): return FileResponse(target)
    members=path=='community' or path.startswith('community/')
    # The Grove's published website, if it has one, answers everything else, / included.
    page=None if members else website.page(path,request)
    if page: return page
    if (path in LEGACY_ROUTES or members or path=='index.html') and (dist/'index.html').exists():
        return FileResponse(dist/'index.html')
    missing=website.missing(request)
    if missing: return missing
    raise HTTPException(404)
