"""The host moves their Grove to their own domain from Settings.

The service never touches nginx or certificates itself. It checks the domain's DNS, then
writes one request file; a root helper installed by deploy/install.sh (arynwood-grove
apply-domain-request, started by a systemd path unit) re-validates the name, publishes it
with nginx and Let's Encrypt, and writes back the result.
"""
import ipaddress
import json
import os
import re
import socket
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from backend.community.auth import administrator
from backend.community.store import database_path, public_origin

router = APIRouter(dependencies=[Depends(administrator)])

# Same rule as the root helper: lowercase labels, at least one dot, nothing else.
DOMAIN = re.compile(r'^(?=.{4,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$')
EMAIL = re.compile(r'^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$')
TEMPORARY_SUFFIXES = ('.sslip.io', '.nip.io')


def requests_dir():
    return database_path().parent / 'requests'


def helper_installed():
    return os.getenv('GROVE_DOMAIN_HELPER') == '1'


def server_ip():
    value = os.getenv('GROVE_SERVER_IP', '').strip()
    try: return str(ipaddress.IPv4Address(value))
    except ValueError: return ''


def is_temporary(host):
    if not host: return True
    try:
        ipaddress.ip_address(host.strip('[]')); return True
    except ValueError:
        return host.endswith(TEMPORARY_SUFFIXES)


def read_json(path):
    try: return json.loads(path.read_text()) if path.stat().st_size < 8192 else None
    except (OSError, ValueError): return None


def clean_domain(value):
    domain = value.strip().lower().removeprefix('https://').removeprefix('http://').split('/')[0].rstrip('.')
    if not DOMAIN.fullmatch(domain): raise HTTPException(400, 'Enter a web address like grove.example.com.')
    try:
        ipaddress.ip_address(domain); raise HTTPException(400, 'Enter a domain name, not an IP address.')
    except ValueError:
        pass
    return domain


class DomainBody(BaseModel):
    domain: str = Field(min_length=1, max_length=260)
    email: str = Field(default='', max_length=254)


@router.get('/address')
def address():
    origin = public_origin()
    host = origin.split('://', 1)[1].split(':')[0] if origin else ''
    request = read_json(requests_dir() / 'domain.json')
    result = read_json(requests_dir() / 'domain.result.json')
    return {'address': origin or None, 'host': host or None, 'temporary': is_temporary(host), 'server_ip': server_ip() or None,
            'can_change': helper_installed(), 'pending': request.get('domain') if request else None, 'result': result}


def lookup(domain):
    try: return sorted({info[4][0] for info in socket.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM)})
    except (socket.gaierror, UnicodeError): return []


@router.post('/check-domain')
async def check_domain(body: DomainBody):
    domain = clean_domain(body.domain)
    addresses = await run_in_threadpool(lookup, domain)
    ip = server_ip()
    labels = domain.split('.')
    # At most providers the record name is the part before the registered domain ("grove"),
    # or "@" for the bare domain. Two-part suffixes (co.uk) make this a hint, not a rule.
    name = '.'.join(labels[:-2]) or '@'
    return {'domain': domain, 'addresses': addresses, 'points_here': bool(ip) and ip in addresses,
            'record': {'type': 'A', 'name': name, 'value': ip or None}}


@router.post('/domain', status_code=202)
def request_domain(body: DomainBody):
    if not helper_installed():
        raise HTTPException(409, 'This Grove was not installed with the server installer, so its address is set on the server (GROVE_PUBLIC_URL).')
    domain = clean_domain(body.domain)
    email = body.email.strip()
    if email and not EMAIL.fullmatch(email): raise HTTPException(400, 'Enter a valid email address, or leave it empty.')
    folder = requests_dir()
    folder.mkdir(mode=0o750, parents=True, exist_ok=True)
    if (folder / 'domain.json').exists(): raise HTTPException(409, 'A change of address is already in progress.')
    (folder / 'domain.result.json').unlink(missing_ok=True)
    staging = folder / 'domain.json.tmp'
    staging.write_text(json.dumps({'domain': domain, 'email': email, 'requested': time.time()}))
    os.replace(staging, folder / 'domain.json')  # the helper starts when this file appears
    return {'pending': domain}
