from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from pathlib import Path
import subprocess
import mailbox
import email.utils
import imaplib
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header as _dh, make_header
import re
from typing import Literal

router = APIRouter()


def _tb_profiles():
    """Return all Thunderbird profile directories found under ~/.thunderbird."""
    tb = Path.home() / ".thunderbird"
    return list(tb.glob("*.default*")) if tb.exists() else []


def _dir_to_label(profile: Path) -> dict[str, str]:
    """Parse prefs.js to build a mapping of ImapMail dir name → email address."""
    mapping: dict[str, str] = {}
    prefs = profile / "prefs.js"
    if not prefs.exists():
        return mapping
    try:
        text = prefs.read_text(errors='replace')
        # Find all server numbers that have a 'name' (email address)
        for m in re.finditer(r'mail\.server\.(server\d+)\.name",\s*"([^"]+)"', text):
            srv, name = m.group(1), m.group(2)
            # Find the directory for this server (relative dir name)
            dm = re.search(rf'mail\.server\.{srv}\.directory",\s*"([^"]+)"', text)
            if dm:
                dir_name = Path(dm.group(1)).name
                mapping[dir_name] = name
    except Exception:
        pass
    return mapping


def _decode(value: str) -> str:
    """Decode an RFC 2047-encoded mail header value to a plain Unicode string."""
    if not value:
        return ''
    try:
        return str(make_header(_dh(value)))
    except Exception:
        return str(value)


def _body(msg) -> str:
    """Extract the best plain-text body from a parsed email.message object."""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                cd = part.get('Content-Disposition', '')
                if ct == 'text/plain' and 'attachment' not in cd:
                    p = part.get_payload(decode=True)
                    if p:
                        return p.decode('utf-8', errors='replace')
            for part in msg.walk():
                if part.get_content_type() == 'text/html':
                    p = part.get_payload(decode=True)
                    if p:
                        txt = p.decode('utf-8', errors='replace')
                        txt = re.sub(r'<[^>]+>', ' ', txt)
                        return re.sub(r'\s+', ' ', txt).strip()
        else:
            p = msg.get_payload(decode=True)
            if p:
                return p.decode('utf-8', errors='replace')
    except Exception:
        pass
    return ''


@router.get("/unread")
def get_unread_count():
    """Returns the live UNSEEN count from the IMAP server."""
    host = os.getenv("MAIL_IMAP_HOST", "")
    port = int(os.getenv("MAIL_IMAP_PORT", "993"))
    user = os.getenv("MAIL_IMAP_USER", "")
    passwd = os.getenv("MAIL_IMAP_PASS", "")
    if not (host and user and passwd):
        return {"count": 0, "error": "IMAP credentials not configured"}
    try:
        with imaplib.IMAP4_SSL(host, port) as imap:
            imap.login(user, passwd)
            imap.select("INBOX", readonly=True)
            _, data = imap.search(None, "UNSEEN")
            uids = data[0].split() if data[0] else []
            return {"count": len(uids)}
    except Exception as e:
        return {"count": 0, "error": str(e)}


@router.get("/accounts")
def get_accounts():
    """Returns list of {id, label} for each IMAP account that has a local INBOX."""
    if _imap_creds():
        return [{"id": "imap", "label": os.environ["MAIL_IMAP_USER"]}]
    accounts = []
    seen = set()
    for profile in _tb_profiles():
        imap = profile / "ImapMail"
        if not imap.exists():
            continue
        label_map = _dir_to_label(profile)
        for d in sorted(imap.iterdir()):
            if d.is_dir() and d.name not in seen and (d / "INBOX").is_file():
                seen.add(d.name)
                label = label_map.get(d.name, d.name.replace('mail.', ''))
                accounts.append({"id": d.name, "label": label})
    return accounts


def _check_account(account: str):
    """Account ids are single directory names; reject anything that could walk the filesystem."""
    if account in ('.', '..') or not re.fullmatch(r'[\w.@+-]{1,200}', account):
        raise HTTPException(400, 'Unknown mail account.')


def _imap_creds():
    """Return (host, port, user, passwd) from env vars, or None if incomplete."""
    host   = os.getenv("MAIL_IMAP_HOST", "")
    port   = int(os.getenv("MAIL_IMAP_PORT", "993"))
    user   = os.getenv("MAIL_IMAP_USER", "")
    passwd = os.getenv("MAIL_IMAP_PASS", "")
    return (host, port, user, passwd) if (host and user and passwd) else None


def _imap_inbox(limit: int = 150) -> list[dict]:
    """Fetch inbox directly from IMAP — accurate SEEN/UNSEEN flags."""
    import email as emaillib
    creds = _imap_creds()
    if not creds:
        return []
    host, port, user, passwd = creds
    messages = []
    try:
        with imaplib.IMAP4_SSL(host, port) as imap:
            imap.login(user, passwd)
            imap.select("INBOX", readonly=True)
            # Get the most recent `limit` message sequence numbers
            _, data = imap.search(None, "ALL")
            all_ids = data[0].split() if data[0] else []
            fetch_ids = all_ids[-limit:]
            if not fetch_ids:
                return []
            id_range = b",".join(fetch_ids)
            _, items = imap.fetch(id_range, "(FLAGS RFC822.HEADER)")
            i = 0
            while i < len(items):
                item = items[i]
                if not isinstance(item, tuple):
                    i += 1
                    continue
                meta = item[0].decode()
                flags_m = re.search(r'FLAGS \(([^)]*)\)', meta)
                flags = flags_m.group(1) if flags_m else ""
                is_read = "\\Seen" in flags
                seq_m = re.search(r'^(\d+)', meta)
                seq = seq_m.group(1) if seq_m else str(i)
                raw_headers = item[1]
                msg = emaillib.message_from_bytes(raw_headers)
                date_str = msg.get("Date", "")
                ts = 0.0
                try:
                    ts = email.utils.parsedate_to_datetime(date_str).timestamp()
                except Exception:
                    pass
                # Preview comes from local mbox fallback (headers only here)
                messages.append({
                    'id': f"imap::{seq}",
                    'account': user,
                    'sender': _decode(msg.get("From", "")),
                    'subject': _decode(msg.get("Subject", "(no subject)")),
                    'date': date_str,
                    'ts': ts,
                    'read': is_read,
                    'preview': "",
                })
                i += 1
    except (imaplib.IMAP4.error, OSError) as e:
        raise HTTPException(502, f'Could not read mail: {e}')
    messages.sort(key=lambda m: m['ts'], reverse=True)
    return messages


@router.get("/inbox")
def get_inbox(account: str = "", limit: int = 150):
    """Return inbox messages via live IMAP if configured, else local Thunderbird mbox."""
    limit = max(1, min(limit, 500))
    if account:
        _check_account(account)
    # Prefer live IMAP when credentials are available (gives real unread status)
    if _imap_creds():
        return _imap_inbox(limit)

    # Fallback: local Thunderbird mbox
    messages = []
    for profile in _tb_profiles():
        imap_dir = profile / "ImapMail"
        if not imap_dir.exists():
            continue
        folders = [imap_dir / account / "INBOX"] if account else list(imap_dir.glob("*/INBOX"))
        for inbox_path in folders:
            if not inbox_path.is_file():
                continue
            try:
                mbox = mailbox.mbox(str(inbox_path))
                for i, msg in enumerate(mbox):
                    try:
                        status = int(msg.get('X-Mozilla-Status', '0000').strip(), 16)
                        if status & 0x0008:
                            continue
                        is_read = bool(status & 0x0001)
                        ts = 0.0
                        date_str = msg.get('Date', '')
                        try:
                            ts = email.utils.parsedate_to_datetime(date_str).timestamp()
                        except Exception:
                            pass
                        messages.append({
                            'id': f"{inbox_path.parent.name}::{i}",
                            'account': inbox_path.parent.name,
                            'sender': _decode(msg.get('From', '')),
                            'subject': _decode(msg.get('Subject', '(no subject)')),
                            'date': date_str,
                            'ts': ts,
                            'read': is_read,
                            'preview': _body(msg)[:300],
                        })
                    except Exception:
                        continue
                mbox.close()
            except Exception:
                continue

    messages.sort(key=lambda m: m['ts'], reverse=True)
    return messages[:limit]


@router.get("/message/{account}/{idx}")
def get_message(account: str, idx: int):
    """Fetch full message body by account and sequence number."""
    _check_account(account)
    import email as emaillib
    # IMAP fetch when id is "imap::<seq>"
    if account == "imap":
        creds = _imap_creds()
        if not creds:
            raise HTTPException(400, 'Mail is not configured.')
        host, port, user, passwd = creds
        try:
            with imaplib.IMAP4_SSL(host, port) as imap:
                imap.login(user, passwd)
                imap.select("INBOX", readonly=True)
                _, data = imap.fetch(str(idx), "(BODY.PEEK[])")
                if not data or not isinstance(data[0], tuple):
                    raise HTTPException(404, 'Message not found.')
                raw = data[0][1]
                msg = emaillib.message_from_bytes(raw)
                return {
                    'sender':  _decode(msg.get('From', '')),
                    'to':      _decode(msg.get('To', '')),
                    'subject': _decode(msg.get('Subject', '')),
                    'date':    msg.get('Date', ''),
                    'body':    _body(msg),
                }
        except (imaplib.IMAP4.error, OSError) as e:
            raise HTTPException(502, f'Could not read mail: {e}')

    # Fallback: local mbox
    for profile in _tb_profiles():
        inbox_path = profile / "ImapMail" / account / "INBOX"
        if inbox_path.exists():
            try:
                mbox = mailbox.mbox(str(inbox_path))
                msg = mbox[idx]
                body = _body(msg)
                mbox.close()
                return {
                    'sender': _decode(msg.get('From', '')),
                    'to':     _decode(msg.get('To', '')),
                    'subject': _decode(msg.get('Subject', '')),
                    'date':    msg.get('Date', ''),
                    'body':    body,
                }
            except (KeyError, OSError):
                raise HTTPException(404, 'Message not found.')
    raise HTTPException(404, 'Message not found.')


class SendRequest(BaseModel):
    to: str = Field(min_length=3, max_length=254)
    subject: str = Field(default='', max_length=500)
    body: str = Field(max_length=200_000)

    @field_validator('to', 'subject')
    @classmethod
    def single_line(cls, value):
        # Newlines in headers would allow header injection.
        if '\r' in value or '\n' in value:
            raise ValueError('Use a single line.')
        return value.strip()

    @field_validator('to')
    @classmethod
    def address(cls, value):
        if not re.fullmatch(r'[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+', value):
            raise ValueError('Enter one email address.')
        return value


def sending_configured():
    return bool((os.getenv("MAIL_SMTP_HOST") or os.getenv("MAIL_IMAP_HOST")) and (os.getenv("MAIL_SMTP_USER") or os.getenv("MAIL_IMAP_USER")))


def deliver(to: str, subject: str, body: str, reply_to: str = ""):
    """Send a plain-text email via SMTP. Uses MAIL_SMTP_* env vars, falling back to
    MAIL_IMAP_* credentials on the same host. Raises smtplib.SMTPException or OSError.
    Callers check sending_configured() first, and keep newlines out of the headers."""
    host  = os.getenv("MAIL_SMTP_HOST") or os.getenv("MAIL_IMAP_HOST", "")
    port  = int(os.getenv("MAIL_SMTP_PORT", "587"))
    user  = os.getenv("MAIL_SMTP_USER") or os.getenv("MAIL_IMAP_USER", "")
    passwd = os.getenv("MAIL_SMTP_PASS") or os.getenv("MAIL_IMAP_PASS", "")
    # Build a full from address: if user has no @, append the host
    from_addr = os.getenv("MAIL_FROM") or (user if "@" in user else f"{user}@{host}")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = to
    if reply_to: msg["Reply-To"] = reply_to
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
            smtp.login(user, passwd)
            smtp.sendmail(from_addr, [to], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(user, passwd)
            smtp.sendmail(from_addr, [to], msg.as_string())


@router.post("/send")
def send_email(req: SendRequest):
    if not sending_configured():
        raise HTTPException(400, "Sending is not configured. Set MAIL_SMTP_HOST and MAIL_SMTP_USER in .env.")
    try:
        deliver(req.to, req.subject, req.body)
        return {"ok": True}
    except (smtplib.SMTPException, OSError) as e:
        raise HTTPException(502, f"Could not send: {e}")


class LaunchRequest(BaseModel):
    view: Literal["mail", "calendar", "compose"] = "mail"


@router.post("/launch")
async def launch_thunderbird(req: LaunchRequest):
    """Launch Thunderbird in the specified view (mail, calendar, or compose)."""
    args = ["thunderbird"]
    if req.view == "calendar":
        args += ["-calendar"]
    elif req.view == "compose":
        args += ["-compose"]
    try:
        subprocess.Popen(args, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True}
    except OSError:
        raise HTTPException(404, "Thunderbird is not installed on this computer.")
