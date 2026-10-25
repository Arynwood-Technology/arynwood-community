"""Running the Grove: its people, their Grove-wide roles and who looks after the website, who
may start spaces, who can find Public chat's room, and the activity log. Owners and managers see all of it; only owners change
roles and settings."""
import json
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from .auth import grove_manager, grove_owner
from .store import db, grove_setting, GROVE_ROLE, WEBMASTER
from .activity import record
from .files import used

router = APIRouter()

class RoleBody(BaseModel):
    role: Literal['owner','manager','member']

class WebmasterBody(BaseModel):
    webmaster: bool

class SettingsBody(BaseModel):
    space_creation: Literal['everyone','managers']|None=None
    # Public chat's room: private to this Grove on the IRC network, or open to anyone on it.
    chat_privacy: Literal['private','open']|None=None

DEFAULTS={'space_creation':'everyone','chat_privacy':'private'}

@router.get('/people')
def people(current=Depends(grove_manager)):
    """Everyone with an account: Grove role, host and webmaster, how many spaces, and when last active (Grove
    owners and managers)."""
    with db() as c:
        return [dict(r) for r in c.execute(f'''SELECT u.id,u.name,u.email,u.admin AS host,u.created,{GROVE_ROLE} AS role,{WEBMASTER} AS webmaster,
            (SELECT COUNT(*) FROM members m WHERE m.user_id=u.id) AS spaces,
            (SELECT a.at FROM activity a WHERE a.actor_id=u.id ORDER BY a.id DESC LIMIT 1) AS last_active
            FROM users u LEFT JOIN grove_roles r ON r.user_id=u.id ORDER BY u.name COLLATE NOCASE''')]

@router.put('/people/{uid}/role')
def set_role(uid:str,body:RoleBody,current=Depends(grove_owner)):
    """Makes someone a Grove owner, manager or member (Grove owners). The host is always an owner."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute(f'SELECT u.admin,{GROVE_ROLE} AS role FROM users u LEFT JOIN grove_roles r ON r.user_id=u.id WHERE u.id=?',(uid,)).fetchone()
        if not row: raise HTTPException(404,'Person not found.')
        # The host can always reach the Grove's server tools, so a Grove never runs out of owners.
        if row['admin']: raise HTTPException(400,'The host is always an owner.')
        if row['role']!=body.role:
            if body.role=='member': c.execute('DELETE FROM grove_roles WHERE user_id=?',(uid,))
            else: c.execute('INSERT OR REPLACE INTO grove_roles VALUES (?,?)',(uid,body.role))
            record(c,'grove_role_changed',actor=current['id'],target=uid,role=body.role)
    return {'id':uid,'role':body.role}

@router.put('/people/{uid}/webmaster')
def set_webmaster(uid:str,body:WebmasterBody,current=Depends(grove_owner)):
    """Webmasters change the Website folders and publish the Grove's website, as owners do."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone(): raise HTTPException(404,'Person not found.')
        was=c.execute('SELECT 1 FROM webmasters WHERE user_id=?',(uid,)).fetchone() is not None
        if was!=body.webmaster:
            if body.webmaster: c.execute('INSERT INTO webmasters VALUES (?)',(uid,))
            else: c.execute('DELETE FROM webmasters WHERE user_id=?',(uid,))
            record(c,'webmaster_changed',actor=current['id'],target=uid,webmaster=body.webmaster)
    return {'id':uid,'webmaster':body.webmaster}

@router.get('/settings')
def settings(current=Depends(grove_manager)):
    """The Grove-wide settings (Grove owners and managers)."""
    with db() as c: return {k:grove_setting(c,k,v) for k,v in DEFAULTS.items()}

@router.put('/settings')
def save_settings(body:SettingsBody,current=Depends(grove_owner)):
    """Changes the settings sent; the others stay as they are."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        for key,value in body.model_dump(exclude_none=True).items():
            if grove_setting(c,key,DEFAULTS[key])!=value:
                c.execute('INSERT OR REPLACE INTO grove_settings VALUES (?,?)',(key,value))
                record(c,'grove_setting_changed',actor=current['id'],**{key:value})
        return {k:grove_setting(c,k,v) for k,v in DEFAULTS.items()}

@router.get('/spaces')
def spaces(current=Depends(grove_manager)):
    """Every space, whoever started it, and the room its files take."""
    with db() as c:
        return [{**dict(r), 'used': used(c, r['id'])} for r in c.execute('SELECT id,name,created FROM spaces ORDER BY name COLLATE NOCASE')]

@router.get('/activity')
def activity(before:int|None=None,space:str='',person:str='',limit:int=Query(100,ge=1,le=500),current=Depends(grove_manager)):
    """Newest first. `person` matches what someone did and what was done to them; pass the
    returned `next` as `before` for older rows."""
    sql,args='SELECT * FROM activity WHERE 1=1',[]
    if before: sql+=' AND id<?'; args.append(before)
    if space: sql+=' AND space_id=?'; args.append(space)
    if person: sql+=' AND (actor_id=? OR target_id=?)'; args+=[person,person]
    with db() as c: rows=[dict(r) for r in c.execute(sql+' ORDER BY id DESC LIMIT ?',args+[limit])]
    for row in rows: row['details']=json.loads(row['details'])
    return {'items':rows,'next':rows[-1]['id'] if len(rows)==limit else None}

@router.get('/wishes')
def wishes(current=Depends(grove_manager)):
    """What people asked for with the wish lamp, newest first."""
    with db() as c:
        return [dict(r) for r in c.execute('SELECT id,created,author_name,author_email,page,space_name,body,delivery FROM wishes ORDER BY created DESC LIMIT 500')]
