"""
Gemini Antigravity Bridge - Auto-Recovery Watchdog Service (V2.1 - Tunnel & Identity Aware)
Continuously monitors local port 8000 (http://127.0.0.1:8000/health) AND the active public
tunnel configured in .env (NGROK_DOMAIN) or active_tunnel_url.txt.

Verifies BOTH reachability AND instance_id match so another machine holding the same
domain can never silently impersonate this laptop.
"""

import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
import signal
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:
    pass

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(ROOT_DIR, "watchdog.log")
TUNNEL_STATE_FILE = os.path.join(ROOT_DIR, "active_tunnel_url.txt")
PYTHON_DIR = os.path.dirname(sys.executable)
PYTHON_EXE = os.path.join(PYTHON_DIR, "python.exe") if os.path.exists(os.path.join(PYTHON_DIR, "python.exe")) else sys.executable
RUN_SCRIPT = os.path.join(ROOT_DIR, "run_with_tunnel.py")
HEALTH_URL = "http://127.0.0.1:8000/health"
CHECK_INTERVAL_SEC = 20
MAX_FAILURES_BEFORE_RESTART = 2

running_child = None
keep_running = True


def get_tunnel_health_url() -> str:
    """Resolve public tunnel /health URL from active_tunnel_url.txt or .env NGROK_DOMAIN."""
    if os.path.exists(TUNNEL_STATE_FILE):
        try:
            with open(TUNNEL_STATE_FILE, "r", encoding="utf-8") as f:
                active_url = f.read().strip().rstrip("/")
                if active_url.startswith("https://"):
                    return f"{active_url}/health"
        except Exception:
            pass
    domain = os.environ.get("NGROK_DOMAIN", "").strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    if domain:
        return f"https://{domain}/health"
    return ""


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [WATCHDOG] {msg}\n"
    try:
        if sys.stdout is not None:
            print(line, end="", flush=True)
    except Exception:
        pass
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1_000_000:
            os.replace(LOG_FILE, LOG_FILE + ".bak")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except Exception:
        pass


def kill_port_8000():
    """Kill any zombie processes lingering on port 8000 cleanly via taskkill."""
    try:
        output = subprocess.check_output("netstat -ano -p tcp", shell=True, text=True, errors="replace")
        killed_pids = set()
        for line in output.splitlines():
            if ":8000 " in line and "LISTENING" in line:
                parts = line.strip().split()
                try:
                    pid = int(parts[-1])
                    if pid > 4 and pid not in killed_pids:
                        log(f"Killing zombie process PID {pid} listening on port 8000...")
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        killed_pids.add(pid)
                except ValueError:
                    pass
    except Exception as e:
        log(f"Error checking port 8000: {e}")


def get_local_health() -> tuple[bool, str]:
    """Return (is_healthy, local_instance_id)."""
    try:
        req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "BridgeWatchdog/2.1"})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status != 200:
                return False, ""
            body = response.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(body)
                return True, str(data.get("instance_id", ""))
            except Exception:
                return True, ""
    except Exception:
        return False, ""


def is_healthy() -> bool:
    ok, _ = get_local_health()
    return ok


def is_tunnel_alive(expected_instance_id: str = "") -> tuple[bool, str]:
    """
    Check if the public tunnel is reachable and routing to THIS machine.
    - Treat non-ngrok-offline HTTP statuses (200/401/405) as tunnel-alive.
    - If 200 JSON is returned and expected_instance_id is set, verify instance_id matches!
    - Connection errors, timeouts, ngrok offline (ERR_NGROK_3200), or instance mismatch = dead.
    """
    tunnel_url = get_tunnel_health_url()
    if not tunnel_url:
        return True, "no_tunnel_configured"

    try:
        req = urllib.request.Request(
            tunnel_url,
            headers={
                "User-Agent": "BridgeWatchdog/2.1",
                "ngrok-skip-browser-warning": "true",
            }
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            body = response.read().decode("utf-8", errors="replace")
            if expected_instance_id:
                try:
                    remote_id = str(json.loads(body).get("instance_id", ""))
                    if remote_id != expected_instance_id:
                        return False, f"TUNNEL HIJACK/MISMATCH ({tunnel_url} returned instance_id='{remote_id}', expected='{expected_instance_id}')"
                except Exception:
                    pass
            return True, "ok"
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            if "ERR_NGROK" in body or "is offline" in body.lower() or e.code == 530 or "error code: 1033" in body.lower():
                return False, f"tunnel offline (HTTP {e.code})"
        except Exception:
            pass
        if e.code == 530:
            return False, "cloudflare tunnel offline (HTTP 530)"
        # Any other HTTP status (e.g. 401 Unauthorized, 405 Method Not Allowed) means tunnel is routing
        return True, f"http_{e.code}"
    except Exception as e:
        return False, f"connection error: {e}"


def start_bridge() -> subprocess.Popen:
    global running_child
    log("Starting Gemini Antigravity Bridge daemon...")
    kill_port_8000()
    time.sleep(1)

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    env = os.environ.copy()
    bridge_log = os.path.join(ROOT_DIR, "bridge.log")
    try:
        log_out = open(bridge_log, "a", encoding="utf-8")
    except Exception:
        log_out = subprocess.DEVNULL

    proc = subprocess.Popen(
        [PYTHON_EXE, RUN_SCRIPT],
        cwd=ROOT_DIR,
        env=env,
        creationflags=creation_flags,
        stdout=log_out,
        stderr=log_out
    )
    running_child = proc
    log(f"Bridge daemon process spawned with PID {proc.pid}")
    return proc


def stop_bridge():
    global running_child
    if running_child and running_child.poll() is None:
        log(f"Stopping bridge process PID {running_child.pid}...")
        try:
            running_child.terminate()
            running_child.wait(timeout=5)
        except Exception:
            running_child.kill()
    kill_port_8000()
    running_child = None


def signal_handler(sig, frame):
    global keep_running
    log("Received shutdown signal. Stopping watchdog and bridge...")
    keep_running = False
    stop_bridge()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log("=" * 60)
    log("Gemini Antigravity Bridge Watchdog Service Started (V2.1 - Tunnel & Identity Aware).")
    log(f"Target Script: {RUN_SCRIPT}")
    log(f"Local Health Check:  {HEALTH_URL} every {CHECK_INTERVAL_SEC}s")
    log(f"Tunnel Health Check: {get_tunnel_health_url() or '(pending tunnel start)'} every {CHECK_INTERVAL_SEC}s")
    log("=" * 60)

    # Initial start
    start_bridge()
    time.sleep(10)  # Give time to initialize tunnel + uvicorn

    failure_count = 0
    tunnel_failure_count = 0

    while keep_running:
        try:
            # Check if child process died
            if running_child is None or running_child.poll() is not None:
                exit_code = running_child.poll() if running_child else "None"
                log(f"Bridge process is not running (Exit code: {exit_code}). Triggering restart...")
                start_bridge()
                failure_count = 0
                tunnel_failure_count = 0
                time.sleep(10)
                continue

            # Check HTTP health
            local_ok, local_id = get_local_health()
            if local_ok:
                if failure_count > 0:
                    log("Bridge health recovered to 200 OK.")
                failure_count = 0

                # Check tunnel health (only evaluated if local is healthy)
                tunnel_ok, tunnel_reason = is_tunnel_alive(expected_instance_id=local_id)
                if tunnel_ok:
                    if tunnel_failure_count > 0:
                        log("Tunnel health recovered.")
                    tunnel_failure_count = 0
                else:
                    tunnel_failure_count += 1
                    log(f"TUNNEL DOWN — local healthy but public tunnel failed ({tunnel_reason}) ({tunnel_failure_count}/{MAX_FAILURES_BEFORE_RESTART}).")
                    if tunnel_failure_count >= MAX_FAILURES_BEFORE_RESTART:
                        log("TUNNEL DOWN threshold reached. Force restarting bridge to re-establish tunnel...")
                        stop_bridge()
                        time.sleep(2)
                        start_bridge()
                        failure_count = 0
                        tunnel_failure_count = 0
                        time.sleep(10)
            else:
                failure_count += 1
                tunnel_failure_count = 0
                log(f"Health check failed ({failure_count}/{MAX_FAILURES_BEFORE_RESTART}).")

                if failure_count >= MAX_FAILURES_BEFORE_RESTART:
                    log("Threshold reached. Force restarting bridge...")
                    stop_bridge()
                    time.sleep(2)
                    start_bridge()
                    failure_count = 0
                    tunnel_failure_count = 0
                    time.sleep(10)

        except Exception as e:
            log(f"Unexpected error in watchdog loop: {e}")

        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    main()
