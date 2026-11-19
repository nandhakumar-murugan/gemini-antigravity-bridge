"""
cloud_tools.py — Cloud tools for the Gemini Antigravity Bridge.

Adds the two tools the bridge was missing (Muse / ChatGPT cloud parity):
  - fetch_url(url)     : read any web page as clean text
  - web_search(query)  : search the web (DuckDuckGo HTML, no API key, free)

Pure Python standard library — no pip installs, no subscriptions.

Wiring (in server.py, matching its existing import style):
    from gemini_antigravity_bridge import cloud_tools
    cloud_tools.register(mcp)
Then restart the bridge. Tools appear as fetch_url and web_search.
"""

import asyncio
import html
import json
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0 Safari/537.36",
       "Accept-Encoding": "identity"}


def _ssl_context():
    # Windows Python does not read the OS certificate store, which makes
    # some sites fail with CERTIFICATE_VERIFY_FAILED. certifi's bundle
    # fixes that; verification stays ON either way.
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _http_get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


class _TextExtractor(HTMLParser):
    """Strip a page down to readable text."""
    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        out = html.unescape("".join(self.parts))
        out = re.sub(r"[ \t]+", " ", out)
        out = re.sub(r"\n\s*\n+", "\n", out)
        return out.strip()


def fetch_url(url: str, max_chars: int = 8000) -> dict:
    """Read a web page and return its main text."""
    page = _http_get(url)
    ex = _TextExtractor()
    ex.feed(page)
    text = ex.text()[:max_chars]
    return {"url": url, "chars": len(text), "text": text}


class _DDGParser(HTMLParser):
    """Collect DuckDuckGo HTML results: title links + snippets, in order."""

    def __init__(self):
        super().__init__()
        self.results = []
        self._mode = None  # "a" inside result link, "s" inside snippet
        self._href = ""
        self._buf = []

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class", "")
        if tag == "a" and "result__a" in cls:
            self._mode, self._href, self._buf = "a", dict(attrs).get("href", ""), []
        elif "result__snippet" in cls:
            self._mode, self._buf = "s", []

    def handle_data(self, data):
        if self._mode:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if self._mode == "a" and tag == "a":
            link = self._href
            if "uddg=" in link:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
                link = q.get("uddg", [link])[0]
            self.results.append({"title": "".join(self._buf).strip(),
                                 "url": link, "snippet": ""})
            self._mode = None
        elif self._mode == "s" and tag in ("a", "td", "div"):
            if self.results:
                self.results[-1]["snippet"] = "".join(self._buf).strip()
            self._mode = None


def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web via DuckDuckGo's HTML endpoint (free, no key)."""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query)
    page = _http_get(url)
    parser = _DDGParser()
    parser.feed(page)
    return {"query": query, "results": parser.results[:max_results]}


def register(mcp):
    """Register both tools on a FastMCP instance (server.py's `mcp`)."""

    @mcp.tool()
    async def fetch_url_tool(url: str) -> str:
        """
        🌐 FETCH URL. Read any public web page as clean text.
        Use for reading articles, docs, and pages the user links.
        """
        res = await asyncio.to_thread(fetch_url, url)
        return json.dumps(res)

    @mcp.tool()
    async def web_search_tool(query: str) -> str:
        """
        🔎 WEB SEARCH. Search the web and return top results
        (title, url, snippet). Free — no API key needed.
        """
        res = await asyncio.to_thread(web_search, query)
        return json.dumps(res)


if __name__ == "__main__":
    print("== fetch_url test ==")
    r = fetch_url("https://example.com")
    print("chars:", r["chars"], "| first 120:", r["text"][:120].replace("\n", " "))
    print("== web_search test ==")
    s = web_search("gemini antigravity bridge")
    for item in s["results"]:
        print("-", item["title"], "->", item["url"])
    print("OK" if r["chars"] > 0 and s["results"] else "CHECK OUTPUT ABOVE")
