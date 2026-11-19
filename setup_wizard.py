#!/usr/bin/env python3
"""
⚡ Gemini Antigravity Bridge - Interactive Setup & Configuration Wizard
Guides users through configuring their tunnel, security keys, and connectors.
"""

import os
import sys
import secrets
import shutil
import subprocess

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(ROOT_DIR, ".env")
ENV_EXAMPLE_PATH = os.path.join(ROOT_DIR, ".env.example")


def print_banner():
    print("""
===================================================================
      ⚡ GEMINI ANTIGRAVITY BRIDGE - SETUP WIZARD (v1.4) ⚡
===================================================================
  Secure bidirectional MCP bridge between Google Gemini Spark,
  Meta Muse, Claude, ChatGPT, and DeepMind Antigravity IDE.
===================================================================
""")


def prompt(text: str, default: str = "") -> str:
    if default:
        res = input(f"{text} [{default}]: ").strip()
        return res if res else default
    return input(f"{text}: ").strip()


def main():
    print_banner()

    # 1. Check Python version
    if sys.version_info < (3, 10):
        print(f"[ERROR] Python 3.10+ required. You are running Python {sys.version_info.major}.{sys.version_info.minor}")
        sys.exit(1)

    print("[1/4] Select Public Ingress / Tunnel Mode:")
    print("  1) ngrok (Recommended - permanent reserved domain & fastest latency)")
    print("  2) Cloudflare Quick Tunnel (Free, zero-account, random temporary domain)")
    print("  3) Localhost Only (http://127.0.0.1:8000 - no public access)")

    tunnel_choice = prompt("Choose option (1/2/3)", "1")

    authtoken = ""
    domain = ""
    use_cf = "0"

    if tunnel_choice == "1":
        print("\n--- ngrok Configuration ---")
        print("Get your free authtoken at: https://dashboard.ngrok.com/get-started/your-authtoken")
        authtoken = prompt("Enter your ngrok Authtoken")
        while not authtoken:
            print("Authtoken cannot be empty for ngrok mode.")
            authtoken = prompt("Enter your ngrok Authtoken")

        print("\nOptional: If you reserved a free static domain at: https://dashboard.ngrok.com/domains")
        domain = prompt("Enter your reserved domain (or press enter for ephemeral domain)", "")
        domain = domain.removeprefix("https://").removeprefix("http://").rstrip("/")
    elif tunnel_choice == "2":
        use_cf = "1"
        print("\n[OK] Cloudflare Quick Tunnel mode selected. A trycloudflare.com URL will be automatically generated.")
    else:
        print("\n[OK] Localhost-only mode selected. No external tunnel will be launched.")

    # 2. Bridge API Key
    print("\n[2/4] Bridge Security & Zero-Trust Authentication:")
    existing_key = ""
    if os.path.exists(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("BRIDGE_API_KEY="):
                        existing_key = line.split("=", 1)[1].strip()
        except Exception:
            pass

    default_key = existing_key if existing_key else f"bridge_{secrets.token_hex(24)}"
    bridge_key = prompt("Set your secret Bridge API Key", default_key)

    # 3. Write .env
    print("\n[3/4] Writing configuration to .env...")
    env_content = [
        "# Gemini Antigravity Bridge Configuration",
        f"BRIDGE_API_KEY={bridge_key}",
    ]
    if authtoken:
        env_content.append(f"NGROK_AUTHTOKEN={authtoken}")
    if domain:
        env_content.append(f"NGROK_DOMAIN={domain}")
    if use_cf == "1":
        env_content.append("USE_CLOUDFLARE=1")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(env_content) + "\n")

    print("[SUCCESS] .env file written successfully!")

    # 4. Connector Guide
    print("\n[4/4] Your Bridge Endpoints & Connector URLs:")
    base_url = f"https://{domain}" if domain else "https://<your-tunnel-url>"
    print("-------------------------------------------------------------------")
    print(f"• Local Dashboard   : http://127.0.0.1:8000/dashboard")
    print(f"• Gemini Spark MCP  : {base_url}/mcp?key={bridge_key}")
    print(f"• Claude Desktop    : Add MCP remote with URL: {base_url}/mcp?key={bridge_key}")
    print(f"• OpenAI ChatGPT    : Custom Action OpenAPI: {base_url}/openapi.json?key={bridge_key}")
    print(f"• Meta Muse         : Pass query parameter: ?key={bridge_key}")
    print("-------------------------------------------------------------------")

    start_now = prompt("\nWould you like to start the bridge now? (y/n)", "y").lower()
    if start_now.startswith("y"):
        print("\nStarting Gemini Antigravity Bridge...\n")
        subprocess.run([sys.executable, os.path.join(ROOT_DIR, "run_with_tunnel.py")])


if __name__ == "__main__":
    main()
