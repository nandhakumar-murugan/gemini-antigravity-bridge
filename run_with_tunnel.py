"""
Dual-Transport Launcher & Live Dashboard for Gemini Antigravity Bridge
Serves Streamable HTTP (/mcp), SSE (/sse, /messages), and Live Visual Web Dashboard (/dashboard, /)
on the SAME port (8000) with automatic Smart Tunneling (ngrok + Cloudflare Tunnel fallback).
"""

import os
import sys
import re
import time
import subprocess
import webbrowser
import threading
import uvicorn
from datetime import datetime
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse, JSONResponse
from starlette.routing import Route
from server import mcp
from dashboard import DASHBOARD_ROUTES, set_public_url

load_dotenv()

AUTHTOKEN = os.environ.get("NGROK_AUTHTOKEN", "36nOKqLSzMkccTe8rmIIsWeoF3n_6SQiDNeFQoB8AvVGLSDHT")
DOMAIN = os.environ.get("NGROK_DOMAIN", "subfastigiate-censurably-estell.ngrok-free.dev")
PORT = 8000
HOST = "0.0.0.0"
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

tunnel_process = None


def _cf_reader(pipe):
    """Continuously drains stderr pipe from cloudflared so buffer never blocks."""
    for line in iter(pipe.readline, ""):
        match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
        if match:
            public_url = match.group(0)
            set_public_url(public_url)
            print("=" * 65)
            print("[INFO] CLOUDFLARE MCP TUNNEL IS LIVE & ROUTING!")
            print(f"[DASHBOARD]     : http://127.0.0.1:{PORT}/dashboard")
            print(f"[OPENAPI SCHEMA]: {public_url}/openapi.json")
            print(f"[GEMINI / GPT]  : {public_url}/mcp (or /sse)")
            print(f"[ANTIGRAVITY]   : http://127.0.0.1:{PORT}/mcp")
            print("=" * 65)


def start_tunnel():
    """Starts ngrok tunnel or falls back to Cloudflare Tunnel if ngrok is blocked."""
    global tunnel_process

    # 1. Try ngrok first
    if AUTHTOKEN:
        try:
            from pyngrok import ngrok, conf
            conf.get_default().auth_token = AUTHTOKEN
            local_ngrok = os.path.join(ROOT_DIR, "ngrok.exe")
            if os.path.exists(local_ngrok):
                conf.get_default().ngrok_path = local_ngrok
            if DOMAIN:
                connect_kwargs["domain"] = DOMAIN
            tunnel = ngrok.connect(PORT, "http", **connect_kwargs)
            public_url = tunnel.public_url.replace("http://", "https://")
            set_public_url(public_url)
            print("=" * 65)
            print("[INFO] NGROK MCP TUNNEL IS LIVE!")
            print(f"[DASHBOARD]     : http://127.0.0.1:{PORT}/dashboard")
            print(f"[GEMINI SPARK]  : {public_url}/mcp")
            print(f"[ANTIGRAVITY]   : http://127.0.0.1:{PORT}/mcp (or /sse)")
            print("=" * 65)
            return public_url
        except Exception as e:
            print(f"[WARNING] ngrok unavailable ({e}). Falling back to Cloudflare Tunnel...")

    # 2. Fallback to Cloudflare Quick Tunnel (cloudflared.exe)
    cf_exe = os.path.join(ROOT_DIR, "cloudflared.exe")
    if not os.path.exists(cf_exe):
        print("[ERROR] cloudflared.exe not found.")
        return None

    try:
        cf_path = cf_exe if os.path.exists(cf_exe) else "cloudflared"
        tunnel_process = subprocess.Popen(
            [
                cf_path, "tunnel",
                "--url", f"http://127.0.0.1:{PORT}"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        threading.Thread(target=_cf_reader, args=(tunnel_process.stderr,), daemon=True).start()

    except Exception as e:
        print(f"[ERROR] Cloudflare tunnel failed to start: {e}")

    return None


async def root_handler(request):
    if request.method == "GET":
        return RedirectResponse(url="/dashboard")


async def webhook_handler(request):
    """
    Direct ingestion endpoint for Google Apps Script, GitHub, or n8n webhooks.
    POST /webhook or /api/webhook
    """
    from server import save_session_note, inject_message

    # Optional API key check if BRIDGE_API_KEY is configured
    bridge_key = os.environ.get("BRIDGE_API_KEY")
    if bridge_key:
        auth_hdr = request.headers.get("Authorization", "")
        custom_hdr = request.headers.get("X-Bridge-Key", "")
        param_key = request.query_params.get("key", "")
        expected = f"Bearer {bridge_key}"
        if auth_hdr != expected and custom_hdr != bridge_key and param_key != bridge_key:
            return JSONResponse({"error": "Unauthorized", "message": "Invalid or missing Bridge API Key"}, status_code=401)

    try:
        data = await request.json()
    except Exception:
        data = {"raw": await request.body().decode("utf-8", errors="replace")}

    source = data.get("source", "webhook")
    event = data.get("event", "notification")
    title = data.get("title", f"Webhook from {source}")
    content = data.get("content") or data.get("message") or json.dumps(data, indent=2)
    conv_id = data.get("conversation_id") or os.environ.get("DEFAULT_CONVERSATION_ID", "0a709f67-66b5-4427-ae96-fd5256a64ba3")

    note_text = f"⚡ WEBHOOK EVENT: [{source.upper()}] {title}\n• Event: {event}\n• Content: {content[:1000]}"
    save_session_note(note=note_text, tag="webhook_event", source=source)

    delivered = False
    if conv_id:
        try:
            msg_payload = f"# 🔔 WEBHOOK ALERT: {title}\n**Source:** `{source}` | **Event:** `{event}`\n\n{content}"
            inject_message(conversation_id=conv_id, message=msg_payload, title=f"🔔 {title[:50]}", sender=f"webhook/{source}")
            delivered = True
        except Exception:
            pass

    return JSONResponse({
        "status": "success",
        "event": event,
        "source": source,
        "session_note_saved": True,
        "antigravity_injected": delivered,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


def create_app() -> Starlette:
    app_sse = mcp.sse_app()
    app_streamable = mcp.streamable_http_app()
    streamable_endpoint = app_streamable.routes[0].endpoint

    combined_routes = [
        Route("/mcp", streamable_endpoint, methods=["POST", "GET", "OPTIONS"]),
        Route("/sse", streamable_endpoint, methods=["POST"]),
        Route("/webhook", webhook_handler, methods=["POST"]),
        Route("/api/webhook", webhook_handler, methods=["POST"]),
        Route("/", root_handler, methods=["GET"]),
    ] + DASHBOARD_ROUTES + list(app_sse.routes)

    combined_middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True,
            expose_headers=["*"],
        )
    ]

    return Starlette(
        routes=combined_routes,
        middleware=combined_middleware,
        lifespan=app_streamable.router.lifespan_context,
    )


def open_browser_delayed():
    time.sleep(1.5)
    webbrowser.open(f"http://127.0.0.1:{PORT}/dashboard")


def main(open_browser: bool = False):
    print("[1/2] Initializing Smart Public HTTPS Tunnel (ngrok / Cloudflare)...")
    threading.Thread(target=start_tunnel, daemon=True).start()

    app = create_app()

    if open_browser:
        threading.Thread(target=open_browser_delayed, daemon=True).start()

    print(f"\n[2/2] Starting Universal MCP Server & Dashboard on {HOST}:{PORT}...")
    print(f"      - Web Dashboard: http://{HOST}:{PORT}/dashboard")
    print(f"      - Universal MCP: http://{HOST}:{PORT}/mcp")
    print(f"      - SSE Stream:   http://{HOST}:{PORT}/sse")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    should_open = "--open" in sys.argv or "-o" in sys.argv
    main(open_browser=should_open)
