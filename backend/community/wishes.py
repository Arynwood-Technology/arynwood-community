"""The wish lamp: anyone in the Grove asks for something they want in it. Each wish is kept for
the Grove's owners and managers, and emailed to GROVE_WISH_EMAIL when the server can send mail."""
import logging
import re
import smtplib
from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field, field_validator
from backend.routers import mail
from .auth import user, identifier, now, throttle
from .store import db, public_origin, setting
from .activity import record

router = APIRouter()
logger = logging.getLogger(__name__)
ADDRESS = re.compile(r'[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+')
# Wishes one person may make in 15 minutes.
WISHES = 10

class Wish(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    page: str = Field(default='', max_length=40, pattern=r'^[a-z-]*$')
    space_id: str = Field(default='', max_length=64)
    @field_validator('body')
    @classmethod
    def written(cls, v):
        if not v.strip(): raise ValueError('Write your wish.')
        return v.strip()

def recipient():
    address = setting('WISH_EMAIL').strip()
    return address if ADDRESS.fullmatch(address) else ''

@router.post('', status_code=201)
def make_wish(body: Wish, tasks: BackgroundTasks, current=Depends(user)):
    throttle('wish:' + current['id'], WISHES)
    wid, emailing = identifier(), bool(recipient()) and mail.sending_configured()
    with db() as c:
        # Named only if the wisher is in it.
        space = c.execute('SELECT s.id,s.name FROM spaces s JOIN members m ON m.space_id=s.id WHERE s.id=? AND m.user_id=?', (body.space_id, current['id'])).fetchone()
        c.execute('INSERT INTO wishes VALUES (?,?,?,?,?,?,?,?,?)', (wid, now(), current['id'], current['name'], current['email'],
                  body.page, space['name'] if space else '', body.body, 'sending' if emailing else 'kept'))
        record(c, 'wish_made', actor=current['id'], space=space['id'] if space else None)
    # Mail can be slow; the wish is already safe.
    if emailing: tasks.add_task(send_wish, wid)
    return {'id': wid, 'emailed': emailing}

def send_wish(wid):
    with db() as c: wish = c.execute('SELECT * FROM wishes WHERE id=?', (wid,)).fetchone()
    name, grove = ' '.join(wish['author_name'].split()), public_origin() or 'a Grove on this computer'
    where = ' · '.join(filter(None, [f"page: {wish['page']}" if wish['page'] else '', f"space: {wish['space_name']}" if wish['space_name'] else '']))
    text = '\n'.join([wish['body'], '', f"— {name} ({wish['author_email']})", *([where] if where else []), f'Grove: {grove}', f"Sent: {wish['created']}"])
    reply = wish['author_email'] if ADDRESS.fullmatch(wish['author_email']) else ''
    try:
        mail.deliver(recipient(), f"Grove wish from {name} ({grove.split('://')[-1]})", text, reply_to=reply)
        status = 'sent'
    except (smtplib.SMTPException, OSError) as error:
        logger.warning('Wish %s is kept in the Grove but could not be emailed: %s', wid, error)
        status = 'failed'
    with db() as c: c.execute('UPDATE wishes SET delivery=? WHERE id=?', (status, wid))
