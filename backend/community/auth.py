import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from starlette.requests import HTTPConnection
from pydantic import BaseModel, Field, field_validator
from .store import db
import os

router = APIRouter()
COOKIE = 'community_session'
SESSION_AGE = 60 * 60 * 24 * 14

def now(): return datetime.now(timezone.utc).isoformat()
def identifier(): return secrets.token_hex(16)
def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def password_hash(value):
    salt = secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256', value.encode(), salt.encode(), 600_000).hex()
def password_matches(value, stored):
    salt, _, expected = stored.partition(':')
    actual = hashlib.pbkdf2_hmac('sha256', value.encode(), salt.encode(), 600_000).hex()
    return hmac.compare_digest(actual, expected)

def user(connection: HTTPConnection):
    token = connection.cookies.get(COOKIE, '')
    with db() as c:
        row = c.execute('SELECT u.id,u.name,u.email,u.admin FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>?', (digest(token), time.time())).fetchone()
    if not row: raise HTTPException(401, 'Sign in to continue.')
    return dict(row)

def administrator(current=Depends(user)):
    if not current['admin']: raise HTTPException(403, 'Host access required.')
    return current

def session(response, uid):
    token = secrets.token_urlsafe(32)
    with db() as c:
        c.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
        c.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token), uid, time.time()+SESSION_AGE))
    response.set_cookie(COOKIE, token, httponly=True, secure=os.getenv('COMMUNITY_SECURE_COOKIE') == '1', samesite='strict', max_age=SESSION_AGE, path='/')

def rate_limit(request, email):
    key = digest((request.client.host if request.client else 'local') + ':' + email.lower())
    with db() as c:
        c.execute('DELETE FROM attempts WHERE at < ?', (time.time()-900,))
        count = c.execute('SELECT count(*) FROM attempts WHERE key=?', (key,)).fetchone()[0]
        if count >= 12: raise HTTPException(429, 'Try again in 15 minutes.')
        c.execute('INSERT INTO attempts VALUES (?,?)', (key, time.time()))

class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    @field_validator('email')
    @classmethod
    def email_valid(cls, value):
        value=value.strip().lower()
        if '@' not in value or any(ch.isspace() for ch in value): raise ValueError('Enter an email address.')
        return value

class Signup(Credentials):
    name: str = Field(min_length=1, max_length=80)
    space: str = Field(default='My community', min_length=1, max_length=80)
    invite: str = Field(default='', max_length=128)
    @field_validator('name','space')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('Required.')
        return value.strip()

@router.get('/status')
def status():
    with db() as c: return {'setup': c.execute('SELECT count(*) FROM users').fetchone()[0] == 0}

@router.post('/signup')
def signup(body: Signup, request: Request, response: Response):
    rate_limit(request, body.email)
    hashed=password_hash(body.password)
    uid=identifier()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        first=c.execute('SELECT count(*) FROM users').fetchone()[0] == 0
        invite=None
        if not first:
            invite=c.execute('SELECT * FROM invites WHERE token=? AND expires>?', (digest(body.invite),time.time())).fetchone()
            if not invite: raise HTTPException(400, 'Invite expired or unavailable.')
        if c.execute('SELECT 1 FROM users WHERE email=?',(body.email,)).fetchone(): raise HTTPException(409, 'This email is already registered.')
        c.execute('INSERT INTO users VALUES (?,?,?,?,?,?)',(uid,body.name,body.email,hashed,int(first),now()))
        if first:
            sid=identifier()
            c.execute('INSERT INTO spaces VALUES (?,?,?)',(sid,body.space,now()))
        else: sid=invite['space_id']
        c.execute('INSERT INTO members VALUES (?,?,?)',(sid,uid,'owner' if first else 'member'))
        if invite: c.execute('DELETE FROM invites WHERE token=?',(digest(body.invite),))
    session(response,uid)
    return {'id':uid, 'name':body.name,'email':body.email,'admin':int(first)}

@router.post('/login')
def login(body: Credentials, request: Request, response: Response):
    rate_limit(request, body.email)
    with db() as c: row=c.execute('SELECT * FROM users WHERE email=?',(body.email,)).fetchone()
    # Spend the same hashing work for unknown accounts.
    stored=row['password'] if row else '0'*32+':'+'0'*64
    if not password_matches(body.password,stored) or not row: raise HTTPException(401, 'Email or password is incorrect.')
    session(response,row['id'])
    return {k:row[k] for k in ('id','name','email','admin')}

@router.get('/me')
def me(current=Depends(user)): return current

@router.post('/logout')
def logout(request: Request, response: Response):
    with db() as c: c.execute('DELETE FROM sessions WHERE token=?',(digest(request.cookies.get(COOKIE,'')),))
    response.delete_cookie(COOKIE, path='/')
    return {'ok':True}

class PasswordChange(BaseModel):
    current: str = Field(max_length=256)
    password: str = Field(min_length=12,max_length=256)

@router.post('/password')
def change_password(body: PasswordChange, request: Request, response: Response, current=Depends(user)):
    rate_limit(request, 'password:' + current['id'])
    with db() as c:
        row=c.execute('SELECT password FROM users WHERE id=?',(current['id'],)).fetchone()
        if not password_matches(body.current,row['password']): raise HTTPException(400,'Current password is incorrect.')
        c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(body.password),current['id']))
        c.execute('DELETE FROM sessions WHERE user_id=?',(current['id'],))
    session(response,current['id'])
    return {'ok':True}
