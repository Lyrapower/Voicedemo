from urllib.parse import urlsplit, urlunsplit, quote
def normalize_url(raw: str):
    s = raw.strip().replace('\\/', '/').replace('\\"', '"')
    s = ' '.join(s.split()).strip('"\'`\\ ')
    p = urlsplit(s)
    if p.scheme not in ('http', 'https') or not p.netloc:
        return None, 'no_scheme_or_host'
    path = quote(p.path, safe="/%:@!$&'()*+,;=-._~")
    query = quote(p.query, safe="=&%:@!$'()*+,;/?-._~")
    return urlunsplit((p.scheme, p.netloc, path, query, '')), 'ok'
