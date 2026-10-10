import json
import os
import time
from datetime import datetime
from typing import Literal
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool
from .auth import session_token, invitation, user, administrator, identifier, digest, now
from .store import db, public_origin, VERSION
from . import live

router=APIRouter()

def membership(c, sid, uid, owner=False):
    row=c.execute('SELECT role FROM members WHERE space_id=? AND user_id=?',(sid,uid)).fetchone()
    if not row: raise HTTPException(404,'Space not found.')
    if owner and row['role']!='owner': raise HTTPException(403,'Space owner access required.')
    return row['role']

def owner_count(c, sid):
    return c.execute("SELECT COUNT(*) FROM members WHERE space_id=? AND role='owner'",(sid,)).fetchone()[0]

# A space as one member sees it: its topic, and that member's role.
SPACE='''SELECT s.*,COALESCE(t.topic,'') AS topic,m.role FROM spaces s JOIN members m ON m.space_id=s.id
         LEFT JOIN space_topics t ON t.space_id=s.id'''

def visible_entry(c, sid, eid, uid):
    row=c.execute('SELECT * FROM entries WHERE id=? AND space_id=?',(eid,sid)).fetchone()
    if not row or (row['visibility']=='private' and row['author_id']!=uid): raise HTTPException(404,'Item not found.')
    return row

class SpaceBody(BaseModel):
    name: str=Field(min_length=1,max_length=80)
    @field_validator('name')
    @classmethod
    def name_valid(cls,v):
        if not v.strip(): raise ValueError('Required.')
        return v.strip()

class SpaceDetails(SpaceBody):
    topic: str=Field(default='',max_length=300)
    @field_validator('topic')
    @classmethod
    def one_line(cls,v): return ' '.join(v.split())

@router.get('/spaces')
def spaces(current=Depends(user)):
    with db() as c:
        return [dict(r) for r in c.execute(SPACE+' WHERE m.user_id=? ORDER BY s.created',(current['id'],))]

@router.post('/spaces',status_code=201)
def create_space(body:SpaceBody,current=Depends(user)):
    sid=identifier()
    with db() as c:
        c.execute('INSERT INTO spaces (id,name,created) VALUES (?,?,?)',(sid,body.name,now()))
        c.execute('INSERT INTO members VALUES (?,?,?)',(sid,current['id'],'owner'))
    return {'id':sid,'name':body.name,'topic':'','role':'owner'}

@router.put('/spaces/{sid}')
def update_space(sid:str,body:SpaceDetails,current=Depends(user)):
    with db() as c:
        membership(c,sid,current['id'],owner=True)
        c.execute('UPDATE spaces SET name=? WHERE id=?',(body.name,sid))
        if body.topic: c.execute('INSERT OR REPLACE INTO space_topics VALUES (?,?)',(sid,body.topic))
        else: c.execute('DELETE FROM space_topics WHERE space_id=?',(sid,))
        saved=dict(c.execute(SPACE+' WHERE s.id=? AND m.user_id=?',(sid,current['id'])).fetchone())
    live.publish(sid)
    return saved

@router.delete('/spaces/{sid}')
def delete_space(sid:str,current=Depends(user)):
    """Deletes the space for everyone: its members, invitations and everything written in it."""
    with db() as c:
        membership(c,sid,current['id'],owner=True)
        c.execute('DELETE FROM spaces WHERE id=?',(sid,))
    # Members' open pages refetch, are refused, and move to another space.
    live.publish(sid)
    return {'ok':True}

@router.get('/spaces/{sid}/members')
def members(sid:str,current=Depends(user)):
    with db() as c:
        membership(c,sid,current['id'])
        return [dict(r) for r in c.execute('SELECT u.id,u.name,m.role FROM members m JOIN users u ON u.id=m.user_id WHERE m.space_id=? ORDER BY u.name',(sid,))]

class RoleBody(BaseModel):
    role: Literal['owner','member']

@router.put('/spaces/{sid}/members/{uid}')
def set_role(sid:str,uid:str,body:RoleBody,current=Depends(user)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        membership(c,sid,current['id'],owner=True)
        target=c.execute('SELECT role FROM members WHERE space_id=? AND user_id=?',(sid,uid)).fetchone()
        if not target: raise HTTPException(404,'Member not found.')
        if target['role']=='owner' and body.role=='member' and owner_count(c,sid)==1:
            raise HTTPException(400,'A space needs an owner. Make someone else an owner first.')
        c.execute('UPDATE members SET role=? WHERE space_id=? AND user_id=?',(body.role,sid,uid))
    live.publish(sid)
    return {'id':uid,'role':body.role}

@router.delete('/spaces/{sid}/members/{uid}')
def remove_member(sid:str,uid:str,current=Depends(user)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        # Members may leave a space; only an owner may remove someone else.
        membership(c,sid,current['id'],owner=uid!=current['id'])
        target=c.execute('SELECT role FROM members WHERE space_id=? AND user_id=?',(sid,uid)).fetchone()
        if not target: raise HTTPException(404,'Member not found.')
        if target['role']=='owner' and owner_count(c,sid)==1:
            raise HTTPException(400,'A space needs an owner. Make someone else an owner first, or delete the space.')
        c.execute('DELETE FROM members WHERE space_id=? AND user_id=?',(sid,uid))
        c.execute('UPDATE entries SET assigned_to=NULL WHERE space_id=? AND assigned_to=?',(sid,uid))
    live.publish(sid)
    return {'ok':True}

@router.post('/spaces/{sid}/invites')
def invite(sid:str,current=Depends(user)):
    token=identifier()+identifier()
    with db() as c:
        membership(c,sid,current['id'],owner=True)
        c.execute('DELETE FROM invites WHERE expires<?',(time.time(),))
        c.execute('INSERT INTO invites VALUES (?,?,?,?)',(digest(token),sid,time.time()+86400*7,current['id']))
    return {'token':token,'expires_in_days':7,'url':invite_url(token)}

def invite_url(token):
    # On a server, the link must name the address members reach, not the owner's local page.
    origin=public_origin()
    return origin+'/community?invite='+quote(token) if origin else None

# A public invite link: one per space, reusable, posted wherever the owner likes, and
# turned off by the owner at any time. It is kept readable so the owner can copy it again.
@router.get('/spaces/{sid}/invite-link')
def invite_link(sid:str,current=Depends(user)):
    with db() as c:
        membership(c,sid,current['id'],owner=True)
        row=c.execute('SELECT token,created FROM invite_links WHERE space_id=?',(sid,)).fetchone()
    return {'token':row['token'],'url':invite_url(row['token']),'created':row['created']} if row else {'token':None,'url':None,'created':None}

@router.post('/spaces/{sid}/invite-link')
def create_invite_link(sid:str,current=Depends(user)):
    """Creates the space's public link, replacing any earlier one (which stops working)."""
    token=identifier()+identifier()
    with db() as c:
        membership(c,sid,current['id'],owner=True)
        c.execute('INSERT OR REPLACE INTO invite_links VALUES (?,?,?,?)',(sid,token,now(),current['id']))
    return {'token':token,'url':invite_url(token),'created':now()}

@router.delete('/spaces/{sid}/invite-link')
def delete_invite_link(sid:str,current=Depends(user)):
    with db() as c:
        membership(c,sid,current['id'],owner=True)
        c.execute('DELETE FROM invite_links WHERE space_id=?',(sid,))
    return {'ok':True}

class JoinBody(BaseModel):
    token: str=Field(min_length=1,max_length=128)

@router.post('/join')
def join(body:JoinBody,current=Depends(user)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        sid,one_use=invitation(c,body.token)
        if not sid: raise HTTPException(400,'Invite expired or unavailable.')
        c.execute('INSERT OR IGNORE INTO members VALUES (?,?,?)',(sid,current['id'],'member'))
        if one_use: c.execute('DELETE FROM invites WHERE token=?',(digest(body.token),))
        joined=dict(c.execute(SPACE+' WHERE s.id=? AND m.user_id=?',(sid,current['id'])).fetchone())
    live.publish(joined['id'])
    return joined

Kind=Literal['board','note','task','event','chat','list','item','comment']
class Entry(BaseModel):
    kind: Kind
    title: str=Field(default='',max_length=200)
    body: str=Field(default='',max_length=50000)
    visibility: Literal['shared','private']='shared'
    parent_id: str|None=None
    done: bool=False
    due: str=Field(default='',max_length=32)
    assigned_to: str|None=None
    version: int=Field(default=1,ge=1)
    @field_validator('title','body')
    @classmethod
    def strip(cls,v): return v.strip()
    @field_validator('due')
    @classmethod
    def date_valid(cls,v):
        if v:
            try: datetime.fromisoformat(v)
            except ValueError: raise ValueError('Choose a valid date.')
        return v

def validate_entry(c,sid,body,uid):
    if not body.title and body.kind not in ('chat','comment'): raise HTTPException(422,'Add a title.')
    if body.kind in ('chat','comment') and not body.body: raise HTTPException(422,'Write a message.')
    if body.kind=='event' and not body.due: raise HTTPException(422,'Choose a date.')
    if body.assigned_to and not c.execute('SELECT 1 FROM members WHERE space_id=? AND user_id=?',(sid,body.assigned_to)).fetchone():
        raise HTTPException(422,'Choose someone in this space.')
    if body.kind in ('item','comment'):
        if not body.parent_id: raise HTTPException(422,'Choose a parent item.')
        parent=visible_entry(c,sid,body.parent_id,uid)
        if (body.kind=='item' and parent['kind']!='list') or (body.kind=='comment' and parent['kind']!='board'):
            raise HTTPException(422,'Invalid parent item.')
        body.visibility=parent['visibility']
    elif body.parent_id: raise HTTPException(422,'This item cannot have a parent.')
    if body.visibility=='private' and body.assigned_to and body.assigned_to!=uid:
        raise HTTPException(422,'Only you can see a private item, so only you can be assigned to it.')

@router.get('/spaces/{sid}/entries')
def entries(sid:str,kind:Kind|None=None,q:str='',current=Depends(user)):
    if len(q)>200: raise HTTPException(422,'Search is too long.')
    with db() as c:
        membership(c,sid,current['id'])
        sql='''SELECT e.*,u.name AS author FROM entries e JOIN users u ON u.id=e.author_id
               WHERE e.space_id=? AND (e.visibility='shared' OR e.author_id=?)'''
        args=[sid,current['id']]
        if kind: sql+=' AND e.kind=?'; args.append(kind)
        if q: sql+=' AND (e.title LIKE ? OR e.body LIKE ?)'; args.extend(['%'+q+'%']*2)
        sql+=' ORDER BY e.created DESC LIMIT 2000'
        return [dict(r) for r in c.execute(sql,args)]

@router.post('/spaces/{sid}/entries',status_code=201)
def create_entry(sid:str,body:Entry,current=Depends(user)):
    eid=identifier(); stamp=now()
    with db() as c:
        membership(c,sid,current['id'])
        validate_entry(c,sid,body,current['id'])
        c.execute('INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
          (eid,sid,current['id'],body.kind,body.title,body.body,body.visibility,body.parent_id,int(body.done),body.due,body.assigned_to,stamp,stamp,1))
        saved=dict(c.execute('SELECT e.*,u.name AS author FROM entries e JOIN users u ON u.id=e.author_id WHERE e.id=?',(eid,)).fetchone())
    changed(saved)
    return saved

@router.put('/spaces/{sid}/entries/{eid}')
def update_entry(sid:str,eid:str,body:Entry,current=Depends(user)):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        role=membership(c,sid,current['id'])
        entry=visible_entry(c,sid,eid,current['id'])
        if entry['author_id']!=current['id'] and role!='owner' and entry['kind'] not in ('task','item'):
            raise HTTPException(403,'Only the author or space owner can edit this item.')
        if entry['version']!=body.version: raise HTTPException(409,'This item changed. Refresh and try again.')
        if body.kind!=entry['kind'] or body.parent_id!=entry['parent_id']: raise HTTPException(422,'Item type cannot be changed.')
        if body.visibility!=entry['visibility']: raise HTTPException(422,'Visibility cannot be changed after saving.')
        validate_entry(c,sid,body,current['id'])
        c.execute('UPDATE entries SET title=?,body=?,done=?,due=?,assigned_to=?,updated=?,version=version+1 WHERE id=?',
                  (body.title,body.body,int(body.done),body.due,body.assigned_to,now(),eid))
        saved=dict(c.execute('SELECT e.*,u.name AS author FROM entries e JOIN users u ON u.id=e.author_id WHERE e.id=?',(eid,)).fetchone())
    changed(saved)
    return saved

@router.delete('/spaces/{sid}/entries/{eid}')
def delete_entry(sid:str,eid:str,current=Depends(user)):
    with db() as c:
        role=membership(c,sid,current['id'])
        entry=visible_entry(c,sid,eid,current['id'])
        if entry['author_id']!=current['id'] and role!='owner': raise HTTPException(403,'Only the author or space owner can delete this item.')
        c.execute('DELETE FROM entries WHERE id=?',(eid,))
    changed(entry)
    return {'ok':True}

def changed(entry):
    # A private entry is visible only to its author, so only the author's pages hear about it.
    live.publish(entry['space_id'],only_user=entry['author_id'] if entry['visibility']=='private' else None)

def session_in_space(token,sid,uid):
    with db() as c:
        return c.execute('SELECT 1 FROM sessions s JOIN members m ON m.user_id=s.user_id WHERE s.token=? AND s.expires>? AND s.user_id=? AND m.space_id=?',
                         (token,time.time(),uid,sid)).fetchone() is not None

@router.get('/spaces/{sid}/events')
async def space_events(sid:str,request:Request,current=Depends(user)):
    token=digest(session_token(request))
    def allowed(): return session_in_space(token,sid,current['id'])
    if not await run_in_threadpool(allowed): raise HTTPException(404,'Space not found.')
    if live.streams_for(current['id'])>=live.MAX_STREAMS_PER_USER: raise HTTPException(429,'Too many open pages. Close some and reload.')
    return StreamingResponse(live.stream(sid,current['id'],request.headers.get('last-event-id'),allowed),media_type='text/event-stream',
                             # Nginx would otherwise hold notices in its buffer.
                             headers={'X-Accel-Buffering':'no'})

@router.get('/spaces/{sid}/export')
def export_space(sid:str,current=Depends(user)):
    with db() as c:
        membership(c,sid,current['id'])
        space=dict(c.execute("SELECT s.*,COALESCE(t.topic,'') AS topic FROM spaces s LEFT JOIN space_topics t ON t.space_id=s.id WHERE s.id=?",(sid,)).fetchone())
        records=[dict(r) for r in c.execute("SELECT * FROM entries WHERE space_id=? AND (visibility='shared' OR author_id=?)",(sid,current['id']))]
    data={'format':'arynwood-community','version':1,'exported':now(),'space':space,'entries':records}
    return Response(json.dumps(data,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="community-export.json"'})

@router.get('/connections')
def connections(current=Depends(administrator)):
    return {'mail':bool(os.getenv('MAIL_IMAP_HOST') and os.getenv('MAIL_IMAP_USER') and os.getenv('MAIL_IMAP_PASS')),
            'smtp':bool((os.getenv('MAIL_SMTP_HOST') or os.getenv('MAIL_IMAP_HOST')) and (os.getenv('MAIL_SMTP_USER') or os.getenv('MAIL_IMAP_USER'))),
            'version':VERSION}
