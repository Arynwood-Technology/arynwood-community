import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from starlette.requests import HTTPConnection
from pydantic import BaseModel, Field, field_validator
from .store import db, public_origin, setting, grove_setting, host_tools, log_name, public_chat, GROVE_ROLE, WEBMASTER
from .activity import record, name_of
from . import live
import os

router = APIRouter()
COOKIE = 'grove_session'
# Members signed in to Community 0.3 stay signed in through the upgrade.
LEGACY_COOKIE = 'community_session'
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

def session_token(connection: HTTPConnection):
    return connection.cookies.get(COOKIE) or connection.cookies.get(LEGACY_COOKIE) or ''

def user(connection: HTTPConnection):
    token = session_token(connection)
    with db() as c:
        row = c.execute(f'''SELECT u.id,u.name,u.email,u.admin,{GROVE_ROLE} AS role,{WEBMASTER} AS webmaster FROM users u JOIN sessions s ON s.user_id=u.id
                            LEFT JOIN grove_roles r ON r.user_id=u.id WHERE s.token=? AND s.expires>?''', (digest(token), time.time())).fetchone()
    if not row: raise HTTPException(401, 'Sign in to continue.')
    return dict(row)

def administrator(current=Depends(user)):
    if not current['admin']: raise HTTPException(403, 'Host access required.')
    return current

# Grove-wide roles: owners run the Grove and appoint owners and managers; managers see
# everything owners see, but change no roles or Grove settings. The host is always an owner.
def grove_manager(current=Depends(user)):
    if current['role'] == 'member': raise HTTPException(403, 'Only the Grove’s owners and managers can do this.')
    return current

def grove_owner(current=Depends(user)):
    if current['role'] != 'owner': raise HTTPException(403, 'Only the Grove’s owners can do this.')
    return current

# The website: owners, and the webmasters they choose, change and publish it; everyone previews it.
def looks_after_website(person): return person['role'] == 'owner' or bool(person['webmaster'])

def webmaster(current=Depends(user)):
    if not looks_after_website(current): raise HTTPException(403, 'Only this Grove’s owners and webmasters can do this.')
    return current

def may_start_spaces(c, role):
    return role != 'member' or grove_setting(c, 'space_creation', 'everyone') == 'everyone'

def profile(c, uid):
    """The signed-in person as the members' page sees them."""
    row = dict(c.execute(f'SELECT u.id,u.name,u.email,u.admin,{GROVE_ROLE} AS role,{WEBMASTER} AS webmaster FROM users u LEFT JOIN grove_roles r ON r.user_id=u.id WHERE u.id=?', (uid,)).fetchone())
    row['webmaster'] = looks_after_website(row)
    chat = public_chat()
    return {**row, 'can_start_spaces': may_start_spaces(c, row['role']), 'host_tools': bool(row['admin']) and host_tools(),
            'public_chat': chat and {'channel': chat['channel'], 'nick': chat['nick'], 'server': chat['server'],
                                     'private': grove_setting(c, 'chat_privacy', 'private') == 'private'}, 'log_name': log_name()}

def session(request, response, uid):
    token = secrets.token_urlsafe(32)
    with db() as c:
        c.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
        c.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token), uid, time.time()+SESSION_AGE))
    # Behind the server's HTTPS proxy the scheme arrives as https (uvicorn trusts the
    # loopback proxy's X-Forwarded-Proto), so members' cookies are Secure there.
    secure = setting('SECURE_COOKIE') == '1' or request.url.scheme == 'https'
    response.set_cookie(COOKIE, token, httponly=True, secure=secure, samesite='strict', max_age=SESSION_AGE, path='/')

def client_address(request):
    return request.client.host if request.client else 'local'

def count_use(c, key, limit):
    """At most `limit` uses of `key` in 15 minutes, counted in transaction `c`."""
    key = digest(key)
    c.execute('DELETE FROM attempts WHERE at < ?', (time.time()-900,))
    if c.execute('SELECT count(*) FROM attempts WHERE key=?', (key,)).fetchone()[0] >= limit:
        raise HTTPException(429, 'Try again in 15 minutes.')
    c.execute('INSERT INTO attempts VALUES (?,?)', (key, time.time()))

def throttle(key, limit):
    with db() as c: count_use(c, key, limit)

def rate_limit(request, email):
    throttle(client_address(request) + ':' + email.lower(), 12)

# Accounts one address may open through public invite links in 15 minutes.
PUBLIC_LINK_SIGNUPS = 10

def setup_code():
    """Set by the server installer, so only the person installing can create the host account."""
    return os.getenv('GROVE_SETUP_CODE', '').strip()

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
    space: str = Field(default='My Grove', min_length=1, max_length=80)
    invite: str = Field(default='', max_length=128)
    setup_code: str = Field(default='', max_length=128)
    @field_validator('name','space')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('Required.')
        return value.strip()

@router.get('/status')
def status():
    with db() as c: setup = c.execute('SELECT count(*) FROM users').fetchone()[0] == 0
    return {'setup': setup, 'setup_code': setup and bool(setup_code()), 'recovery': 'host-code', 'public_url': public_origin() or None}

def invitation(c, token):
    """(space id, one-use, who made it) for a one-use invite or a space's public link, or (None, False, None)."""
    if not token: return None, False, None
    row = c.execute('SELECT space_id,created_by FROM invites WHERE token=? AND expires>?', (digest(token), time.time())).fetchone()
    if row: return row['space_id'], True, row['created_by']
    row = c.execute('SELECT space_id,created_by FROM invite_links WHERE token=?', (token,)).fetchone()
    return (row['space_id'], False, row['created_by']) if row else (None, False, None)

def joined_through(c, one_use, inviter):
    """How someone came into a space, for the activity log."""
    return {'via': 'invitation' if one_use else 'public link', 'invited_by': name_of(c, 'users', inviter)}

@router.post('/signup')
def signup(body: Signup, request: Request, response: Response):
    rate_limit(request, body.email)
    hashed=password_hash(body.password)
    uid=identifier()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        first=c.execute('SELECT count(*) FROM users').fetchone()[0] == 0
        sid, one_use, inviter = None, False, None
        if first:
            if setup_code() and not hmac.compare_digest(body.setup_code.strip().encode(), setup_code().encode()):
                raise HTTPException(403, 'Enter the setup code the installer printed.')
        else:
            sid, one_use, inviter = invitation(c, body.invite)
            if not sid: raise HTTPException(400, 'Invite expired or unavailable.')
            # A public link can be posted anywhere, so one address may open only a few accounts through it.
            if not one_use: count_use(c, 'public-link:' + client_address(request), PUBLIC_LINK_SIGNUPS)
        if c.execute('SELECT 1 FROM users WHERE email=?',(body.email,)).fetchone(): raise HTTPException(409, 'This email is already registered.')
        c.execute('INSERT INTO users VALUES (?,?,?,?,?,?)',(uid,body.name,body.email,hashed,int(first),now()))
        if first:
            sid=identifier()
            c.execute('INSERT INTO spaces (id,name,created) VALUES (?,?,?)',(sid,body.space,now()))
        c.execute('INSERT INTO members VALUES (?,?,?)',(sid,uid,'owner' if first else 'member'))
        if one_use: c.execute('DELETE FROM invites WHERE token=?',(digest(body.invite),))
        if first: record(c,'signed_up',actor=uid,space=sid,via='setup')
        else: record(c,'signed_up',actor=uid,space=sid,**joined_through(c,one_use,inviter))
        created=profile(c,uid)
    if not first: live.publish(sid)
    session(request,response,uid)
    return created

@router.post('/login')
def login(body: Credentials, request: Request, response: Response):
    rate_limit(request, body.email)
    with db() as c: row=c.execute('SELECT * FROM users WHERE email=?',(body.email,)).fetchone()
    # Spend the same hashing work for unknown accounts.
    stored=row['password'] if row else '0'*32+':'+'0'*64
    if not password_matches(body.password,stored) or not row:
        # Someone may be guessing at a real account, so the log says whose.
        if row:
            with db() as c: record(c,'sign_in_failed',target=row['id'])
        raise HTTPException(401, 'Email or password is incorrect.')
    session(request,response,row['id'])
    with db() as c:
        record(c,'signed_in',actor=row['id'])
        return profile(c,row['id'])

@router.get('/me')
def me(current=Depends(user)):
    with db() as c: return profile(c,current['id'])

@router.post('/logout')
def logout(request: Request, response: Response):
    with db() as c: c.execute('DELETE FROM sessions WHERE token=?',(digest(session_token(request)),))
    response.delete_cookie(COOKIE, path='/'); response.delete_cookie(LEGACY_COOKIE, path='/')
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
        c.execute('DELETE FROM password_resets WHERE user_id=?',(current['id'],))
        c.execute('DELETE FROM sessions WHERE user_id=?',(current['id'],))
        record(c,'password_changed',actor=current['id'])
    session(request,response,current['id'])
    return {'ok':True}


class PasswordReset(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=256)

@router.post('/password/reset')
def reset_password(body: PasswordReset, request: Request, response: Response):
    # Rate limiting is per client, not per supplied token, to bound guessing attempts.
    rate_limit(request, 'password-reset')
    hashed = password_hash(body.password)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        reset = c.execute('SELECT user_id FROM password_resets WHERE token=? AND expires>?',
                          (digest(body.token), time.time())).fetchone()
        if not reset: raise HTTPException(400, 'Reset code expired or unavailable. Ask the host for a new code.')
        uid = reset['user_id']
        c.execute('UPDATE users SET password=? WHERE id=?', (hashed, uid))
        c.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
        c.execute('DELETE FROM password_resets WHERE user_id=?', (uid,))
        record(c, 'password_reset', actor=uid)
    response.delete_cookie(COOKIE, path='/')
    return {'ok': True}
