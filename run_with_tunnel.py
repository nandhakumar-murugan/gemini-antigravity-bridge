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
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse
from starlette.routing import Route
from server import mcp
from dashboard import DASHBOARD_ROUTES, set_public_url

load_dotenv()

AUTHTOKEN = os.environ.get("NGROK_AUTHTOKEN")
PORT = 8000
HOST = "127.0.0.1"
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

tunnel_process = None


def start_tunnel():
    """Starts ngrok tunnel or falls back to Cloudflare Tunnel if ngrok is blocked."""
    global tunnel_process

    # 1. Try ngrok first
    if AUTHTOKEN:
        try:
            from pyngrok import ngrok, conf
            conf.get_default().auth_token = AUTHTOKEN
            ngrok.kill()
            tunnel = ngrok.connect(PORT, "http", host_header="rewrite")
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
            print(f"[WARNING] ngrok failed or blocked by Windows Defender ({e}).")
            print("[INFO] Automatically falling back to Cloudflare Tunnel (100% Antivirus Immune)...")

    # 2. Fallback to Cloudflare Quick Tunnel (cloudflared.exe)
    cf_exe = os.path.join(ROOT_DIR, "cloudflared.exe")
    if not os.path.exists(cf_exe):
        print("[ERROR] cloudflared.exe not found.")
        return None

    try:
        tunnel_process = subprocess.Popen(
            [cf_exe, "tunnel", "--url", f"http://127.0.0.1:{PORT}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        public_url = None
        for _ in range(25):
            line = tunnel_process.stderr.readline()
            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
            if match:
                public_url = match.group(0)
                set_public_url(public_url)
                print("=" * 65)
                print("[INFO] CLOUDFLARE MCP TUNNEL IS LIVE!")
                print(f"[DASHBOARD]     : http://127.0.0.1:{PORT}/dashboard")
                print(f"[GEMINI SPARK]  : {public_url}/mcp")
                print(f"[ANTIGRAVITY]   : http://127.0.0.1:{PORT}/mcp (or /sse)")
                print("=" * 65)
                return public_url
            time.sleep(0.4)

    except Exception as e:
        print(f"[ERROR] Cloudflare tunnel failed: {e}")

    return None


async def root_handler(request):
    if request.method == "GET":
        return RedirectResponse(url="/dashboard")


def create_app() -> Starlette:
    app_sse = mcp.sse_app()
    app_streamable = mcp.streamable_http_app()
    streamable_endpoint = app_streamable.routes[0].endpoint

    combined_routes = [
        Route("/mcp", streamable_endpoint, methods=["POST", "GET", "OPTIONS"]),
        Route("/sse", streamable_endpoint, methods=["POST"]),
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
