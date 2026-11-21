"""
Gemini Antigravity Bridge - Swarm Window-Geometry Feed
Read-only enumeration of the visible windows on the user's desktop, so
the swarm overlay can anchor a Tier A cursor to the REAL rectangle of
the window an agent is working in instead of a synthetic spread.

Windows implementation uses ctypes against user32 (EnumWindows /
GetWindowRect / GetWindowTextW) — standard library only, no new
permissions. Enumeration is strictly read-only: this module never moves,
focuses, resizes or closes any window.

On non-Windows platforms, or if enumeration fails for any reason,
list_windows() returns an "unavailable" status with an empty list —
it never raises, so callers can always fall back gracefully.

The matching helpers (find_window / anchor_point_for_title) are pure
functions over a window list, so they are testable anywhere.
"""

import sys
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["list_windows", "find_window", "anchor_point_for_title"]


# ─── Pure Matching Helpers (platform-independent) ─────────────────────────────

def find_window(title_query: str,
                windows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Best match for `title_query` in a window list: an exact
    case-insensitive title match wins, then a substring match; the
    foreground window is preferred within each class."""
    if not title_query:
        return None
    query = title_query.strip().lower()
    if not query:
        return None
    exact = [w for w in windows if w.get("title", "").lower() == query]
    partial = [w for w in windows if query in w.get("title", "").lower()]
    for pool in (exact, partial):
        if pool:
            for window in pool:
                if window.get("is_foreground"):
                    return window
            return pool[0]
    return None


def anchor_point_for_title(title_query: str,
                           windows: List[Dict[str, Any]],
                           index: int = 0) -> Optional[Tuple[float, float]]:
    """Screen point for an agent anchored to the window named by
    `title_query`: the centre of the window's real rectangle, nudged by
    a small deterministic offset per agent `index` so several cursors
    working the same window do not stack on one pixel. None when the
    window is not in the list (caller falls back to its own spread)."""
    window = find_window(title_query, windows)
    if window is None:
        return None
    rect = window.get("rect") or {}
    try:
        cx = float(rect["x"]) + float(rect["w"]) / 2.0
        cy = float(rect["y"]) + float(rect["h"]) / 2.0
    except Exception:
        return None
    dx = ((index % 4) - 1.5) * 34.0
    dy = (((index // 4) % 3) - 1) * 30.0
    return (cx + dx, cy + dy)


# ─── Live Enumeration ─────────────────────────────────────────────────────────

def list_windows() -> Dict[str, Any]:
    """Enumerate visible top-level windows.

    Returns {"status": "success", "windows": [...], "count": n} where
    each window is {"title": str, "rect": {"x","y","w","h"},
    "is_foreground": bool} — or {"status": "unavailable", "message": ...,
    "windows": []} on non-Windows platforms and on any failure.
    Never raises.
    """
    if sys.platform != "win32":
        return {
            "status": "unavailable",
            "message": ("window geometry feed is Windows-only; this "
                        "platform cannot enumerate desktop windows"),
            "windows": [],
        }
    try:
        return {"status": "success", "windows": _enumerate_windows()}
    except Exception as exc:
        return {
            "status": "unavailable",
            "message": f"window enumeration failed: {exc}",
            "windows": [],
        }


def _enumerate_windows() -> List[Dict[str, Any]]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                     ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND,
                                     ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL

    foreground = user32.GetForegroundWindow()
    results: List[Dict[str, Any]] = []

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND,
                                   wintypes.LPARAM)

    def _callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if not title:
                return True
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width <= 0 or height <= 0:
                return True
            results.append({
                "title": title,
                "rect": {"x": rect.left, "y": rect.top,
                         "w": width, "h": height},
                "is_foreground": bool(hwnd == foreground),
            })
        except Exception:
            pass  # one bad window must not sink the whole enumeration
        return True

    callback = enum_proc(_callback)  # keep a reference alive for the call
    user32.EnumWindows(callback, 0)
    results.sort(key=lambda w: 0 if w["is_foreground"] else 1)
    return results
