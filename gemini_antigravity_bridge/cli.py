"""Gemini Antigravity Bridge - CLI Command Entrypoint."""
import sys
import argparse
from .run_with_tunnel import main as run_main

def main():
    parser = argparse.ArgumentParser(
        prog="gemini-bridge",
        description="Gemini Antigravity Bridge: Bidirectional MCP Agent Orchestration between Gemini Spark & Antigravity."
    )
    parser.add_argument("--version", action="version", version="gemini-antigravity-bridge 1.0.1")
    parser.add_argument("--browser", action="store_true", help="Automatically open visual web dashboard in browser.")
    args = parser.parse_args()

    run_main(open_browser=args.browser)

if __name__ == "__main__":
    main()
