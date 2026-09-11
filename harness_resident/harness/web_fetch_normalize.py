"""URL syntax normalization only; the fetcher must enforce DNS/IP/redirect policy."""
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit, quote


def normalize_url(raw: str):
    if not isinstance(raw, str) or not raw.strip():
        return None, 'bad_input'
    s = raw.strip(' ')
    if any(ord(c) < 32 or ord(c) == 127 for c in s):
        return None, 'control_character'
    s = s.replace('\\/', '/').replace('\\"', '"')
    # Remove wrapping prose quotes only, not arbitrary punctuation within the URL.
    s = s.strip('"\'`')
    if '\\' in s or re.search(r'%(?![0-9a-fA-F]{2})', s):
        return None, 'bad_escape'
    if re.search(r'%(?:0[0-9a-f]|1[0-9a-f]|7f)', s, re.I):
        return None, 'encoded_control'
    try:
        p = urlsplit(s)
        if p.scheme.lower() not in ('http', 'https') or not p.hostname:
            return None, 'no_scheme_or_host'
        if p.username is not None or p.password is not None:
            return None, 'userinfo_forbidden'
        if any(c.isspace() for c in p.netloc) or '%' in p.netloc:
            return None, 'bad_host'
        host = p.hostname.encode('idna').decode('ascii').lower()
        if ':' in host:
            ipaddress.IPv6Address(host)
            host = '[' + host + ']'
        elif not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.?', host):
            return None, 'bad_host'
        port = p.port
        if port is not None and not 1 <= port <= 65535:
            return None, 'bad_port'
        if p.netloc.endswith(':'):
            return None, 'bad_port'
        netloc = host + (f':{port}' if port is not None else '')
        path = quote(p.path, safe="/%:@!$&'()*+,;=-._~")
        query = quote(p.query, safe="=&%:@!$'()*+,;/?-._~")
        return urlunsplit((p.scheme.lower(), netloc, path, query, '')), 'ok'
    except (ValueError, UnicodeError):
        return None, 'malformed_url'
