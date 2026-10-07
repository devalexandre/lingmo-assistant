"""Web search (DuckDuckGo HTML) and page reading for the web tool (off by default).

HTTPS only, no cookies, size and time limits, and no requests to local or
private addresses (the router, Ollama, CUPS... are never reachable from here).
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from .documents import html_to_text

TIMEOUT = 10
MAX_BYTES = 2 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) LingmoAssistant/1.0"
SEARCH_URL = "https://html.duckduckgo.com/html/"


class WebError(Exception):
    pass


def _check_host(host: str) -> None:
    if not host:
        raise WebError("Endereço inválido.")
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise WebError("Site não encontrado.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise WebError("Endereços locais ou privados não são acessados.")


def check_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2000:
        raise WebError("Endereço inválido.")
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme != "https":
        raise WebError("Só endereços https:// são lidos.")
    if parts.username or parts.password:
        raise WebError("Endereço inválido.")
    _check_host(parts.hostname or "")
    return urllib.parse.urlunsplit(parts)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    # No HTTPCookieProcessor: cookies are never stored or sent
    return urllib.request.build_opener(_SafeRedirect())


def fetch(url: str, data: bytes | None = None) -> tuple[str, str]:
    """(final url, decoded body) of an https page."""
    url = check_url(url)
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
    try:
        with _opener().open(req, timeout=TIMEOUT) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if not any(t in ctype for t in ("text/", "html", "xml", "json")):
                raise WebError("A página não é texto (%s)." % (ctype.split(";")[0] or "desconhecido"))
            body = resp.read(MAX_BYTES + 1)[:MAX_BYTES]
            charset = resp.headers.get_content_charset() or "utf-8"
            final = resp.geturl()
    except WebError:
        raise
    except urllib.error.HTTPError as exc:
        raise WebError("O site respondeu com erro %d." % exc.code) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise WebError("Não foi possível abrir a página.") from exc
    try:
        text = body.decode(charset, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    return final, text


class _Results(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "") or ""
        if tag == "a" and "result__a" in cls:
            self.results.append({"title": "", "url": _unwrap(a.get("href", "")), "snippet": ""})
            self._in_title = True
        elif "result__snippet" in cls and self.results:
            self._in_snippet = True

    def handle_endtag(self, tag):
        if tag == "a":
            self._in_title = False
            self._in_snippet = False if tag == "a" and self._in_snippet else self._in_snippet
        if tag in ("td", "div"):
            self._in_snippet = False

    def handle_data(self, data):
        if self._in_title and self.results:
            self.results[-1]["title"] += data
        elif self._in_snippet and self.results:
            self.results[-1]["snippet"] += data


def _unwrap(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parts = urllib.parse.urlsplit(href)
    if parts.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parts.query).get("uddg", [""])[0]
        return target
    return href


def parse_results(markup: str, limit: int = 8) -> list[dict]:
    parser = _Results()
    try:
        parser.feed(markup)
    except Exception:
        pass
    out = []
    for r in parser.results:
        if r["url"].startswith("https://") and "duckduckgo.com/y.js" not in r["url"]:
            out.append({k: " ".join(v.split()) for k, v in r.items()})
        if len(out) >= limit:
            break
    return out


def search(query: str, limit: int = 8) -> list[dict]:
    query = (query or "").strip()
    if not query or len(query) > 300:
        raise WebError("Busca inválida.")
    data = urllib.parse.urlencode({"q": query, "kl": "br-pt"}).encode()
    _, markup = fetch(SEARCH_URL, data=data)
    return parse_results(markup, limit)


def page_text(url: str, limit: int = 20000) -> tuple[str, str]:
    final, body = fetch(url)
    text = html_to_text(body) if "<" in body[:2000] else body
    return final, text[:limit]
