"""Owner tools. Registry entries never grant filesystem or execution access."""
import json
import shutil
import urllib.request
import urllib.error
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from backend.community.auth import administrator, identifier, now
from backend.community.store import db, database_path

router = APIRouter(dependencies=[Depends(administrator)])

class Project(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=4000)

class Chat(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=12000)

def initialize():
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS grove_projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, created TEXT NOT NULL)')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError("Local model redirects are refused.")

def ollama(path, body=None):
    # Fixed loopback endpoint: no client-supplied URL, keys or forwarding of workspace data.
    request = urllib.request.Request('http://127.0.0.1:11434/api/'+path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json'})
    try:
        # Ignore environment proxy settings; this connection stays on loopback.
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(request, timeout=90) as response:
            payload=response.read(2_000_001)
            if len(payload)>2_000_000: raise HTTPException(502,'Local model response exceeded the limit.')
            return json.loads(payload)
    except (OSError, ValueError, urllib.error.URLError):
        raise HTTPException(503,'Local Ollama is unavailable. Start it on this server and try again.')

@router.get('/projects')
def projects():
    """The host's projects (host only)."""
    with db() as c: return [dict(r) for r in c.execute('SELECT * FROM grove_projects ORDER BY created DESC')]

@router.post('/projects',status_code=201)
def create_project(project:Project):
    """Adds a project (host only)."""
    record={'id':identifier(),'name':project.name.strip(),'description':project.description,'created':now()}
    if not record['name']: raise HTTPException(422,'Enter a project name.')
    with db() as c: c.execute('INSERT INTO grove_projects VALUES (:id,:name,:description,:created)',record)
    return record

@router.get('/server')
def server():
    """Disk use of the Grove's data folder and the workspace mode (host only)."""
    usage=shutil.disk_usage(str(database_path().parent))
    return {'storage':{'total':usage.total,'used':usage.used,'free':usage.free},
        'execution_enabled':False,'publishing_enabled':False,'mode':'CPU-compatible workspace'}

@router.get('/models')
def models():
    """The models on the Ollama server the Grove uses (host only)."""
    data=ollama('tags')
    return [{'name':m['name'],'size':m.get('size',0)} for m in data.get('models',[])]

@router.post('/chat')
def chat(message:Chat):
    """One prompt to an Ollama model, answered whole (host only)."""
    data=ollama('chat',{'model':message.model,'messages':[{'role':'user','content':message.prompt}],
        'stream':False,'options':{'num_predict':1024,'num_ctx':4096},'keep_alive':'2m'})
    return {'text':data.get('message',{}).get('content','')}
