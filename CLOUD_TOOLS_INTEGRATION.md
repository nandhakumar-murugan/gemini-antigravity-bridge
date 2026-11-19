# Cloud tools for the bridge — integration note

Built by Muse on 2026-11-15 night, at Nandhakumar's request ("think like me and build").
Status: module written and SELF-TEST PASSED on this laptop. Not yet wired into the running server.

## What was added
File: gemini_antigravity_bridge/cloud_tools.py (pure stdlib, no pip installs, no API keys)
- fetch_url(url)   -> reads any public web page as clean text
- web_search(query)-> DuckDuckGo HTML search, top results (title, url, snippet)

Self-test (python cloud_tools.py): fetch_url read example.com (156 chars);
web_search for "gemini antigravity bridge" returned the bridge's own GitHub
repo as result #1 and its PyPI page as #2.

## Bug found and fixed during testing
Windows Python does not read the OS certificate store, so some sites failed
with SSL CERTIFICATE_VERIFY_FAILED. Fixed by using certifi's CA bundle when
available (it is installed). Verification stays ON — no unverified fallback.

## To switch it on (2 lines + restart)
In gemini_antigravity_bridge/server.py, near the other imports / before the
server starts serving, add (match server.py's existing import style):

    from gemini_antigravity_bridge import cloud_tools
    cloud_tools.register(mcp)

Then restart the bridge. fetch_url_tool and web_search_tool appear in the
tool list (as fetch_url / web_search on the client side once allowlisted in
Muse's connector client, ALLOWED_TOOLS in bin/client.py).

## Next tools in the parity plan (from the cloud comparison)
Browser automation (Playwright, persistent profile) -> long-term memory ->
scheduler -> credential vault -> Gmail/Calendar connectors.
