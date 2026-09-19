"""
Gemini Antigravity Bridge — Multimedia & System Interaction Suite
Provides:
  - speak_to_user: Windows SAPI5 offline text-to-speech through laptop speakers
  - show_desktop_notification: Windows notification banner with sound
  - read_clipboard: Reads current text in clipboard
  - copy_to_clipboard: Copies text directly to Windows clipboard
"""

import sys
import threading
import subprocess
from typing import Optional

# ─── 1. Text-To-Speech (SAPI5 via win32com) ──────────────────────────────────
try:
    import win32com.client
    SAPI_AVAILABLE = True
except ImportError:
    SAPI_AVAILABLE = False


def speak(text: str, rate: int = 0) -> dict:
    """
    Speak text out loud through laptop speakers using Windows SAPI5 voice engine.
    Runs asynchronously in a background thread so the server is not blocked.

    Args:
        text: The text to speak aloud.
        rate: Speech speed (-10 to 10, default 0 = natural).
    """
    if not SAPI_AVAILABLE:
        return {"status": "error", "error": "win32com is not available for SAPI voice"}

    def _speak_thread():
        try:
            import pythoncom
            pythoncom.CoInitialize()
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Rate = rate
            speaker.Speak(text)
            pythoncom.CoUninitialize()
        except Exception as e:
            print(f"[ERROR in speak_thread]: {e}", file=sys.stderr)

    t = threading.Thread(target=_speak_thread, daemon=True)
    t.start()

    return {
        "status": "speaking",
        "text": text,
        "mode": "async_sapi5",
    }


# ─── 2. Clipboard Operations (win32clipboard) ─────────────────────────────────
try:
    import win32clipboard
    import win32con
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False


def read_clipboard() -> dict:
    """Read the current text from the Windows clipboard."""
    if not CLIPBOARD_AVAILABLE:
        return {"status": "error", "error": "win32clipboard not available"}

    try:
        win32clipboard.OpenClipboard()
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        elif win32clipboard.IsClipboardFormatAvailable(win32con.CF_TEXT):
            data = win32clipboard.GetClipboardData(win32con.CF_TEXT).decode("utf-8", errors="ignore")
        else:
            data = ""
        win32clipboard.CloseClipboard()
        return {"status": "ok", "content": data, "length": len(data)}
    except Exception as e:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass
        return {"status": "error", "error": str(e)}


def copy_to_clipboard(text: str) -> dict:
    """Copy text directly into the Windows clipboard."""
    if not CLIPBOARD_AVAILABLE:
        return {"status": "error", "error": "win32clipboard not available"}

    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        win32clipboard.CloseClipboard()
        return {"status": "ok", "copied": text, "chars": len(text)}
    except Exception as e:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass
        return {"status": "error", "error": str(e)}


# ─── 3. Desktop Notification Banner ───────────────────────────────────────────
def show_desktop_notification(title: str, message: str) -> dict:
    """
    Display a native Windows notification banner with sound.
    Uses PowerShell WinForms NotifyIcon balloon tip.
    """
    clean_title = title.replace("'", "''").replace('"', '`"')
    clean_msg = message.replace("'", "''").replace('"', '`"')

    ps_script = f"""
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $notify = New-Object System.Windows.Forms.NotifyIcon
    $notify.Icon = [System.Drawing.SystemIcons]::Information
    $notify.BalloonTipTitle = '{clean_title}'
    $notify.BalloonTipText = '{clean_msg}'
    $notify.Visible = $true
    $notify.ShowBalloonTip(5000)
    Start-Sleep -Seconds 2
    $notify.Dispose()
    """

    def _notify_thread():
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
                capture_output=True,
                timeout=10,
            )
        except Exception as e:
            print(f"[ERROR in notify_thread]: {e}", file=sys.stderr)

    t = threading.Thread(target=_notify_thread, daemon=True)
    t.start()

    return {
        "status": "notified",
        "title": title,
        "message": message,
    }
