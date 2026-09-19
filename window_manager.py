"""
Gemini Antigravity Bridge — Window Manager & System Telemetry Suite
Provides:
  - get_active_window: Returns title, process, PID, and bounding box of current focused window
  - focus_window: Brings any matching window to the foreground and restores it
  - maximize_window: Maximizes matching window
  - minimize_window: Minimizes matching window
  - close_window: Sends graceful WM_CLOSE to matching window
  - get_system_telemetry: Battery %, charging state, CPU/RAM stats
"""

import sys
import ctypes
from ctypes import wintypes
import psutil
from typing import Optional, List, Dict
from contextlib import contextmanager

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


@contextmanager
def attach_desktop():
    h_winsta_orig = user32.GetProcessWindowStation()
    h_winsta = user32.OpenWindowStationW("WinSta0", False, 0x037F)
    if h_winsta:
        user32.SetProcessWindowStation(h_winsta)

    h_desktop_orig = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    h_desktop = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if h_desktop:
        user32.SetThreadDesktop(h_desktop)
    try:
        yield
    finally:
        if h_desktop:
            user32.SetThreadDesktop(h_desktop_orig)
            user32.CloseDesktop(h_desktop)
        if h_winsta:
            user32.SetProcessWindowStation(h_winsta_orig)
            user32.CloseWindowStation(h_winsta)


def get_active_window() -> dict:
    """Returns title, process name, PID, and rectangle coordinates of the foreground window."""
    with attach_desktop():
        found = None
        def enum_proc(hwnd, lparam):
            nonlocal found
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    t = buf.value.strip()
                    if t and t not in ("Program Manager", "Windows Input Experience"):
                        pid = wintypes.DWORD()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        try:
                            p = psutil.Process(pid.value)
                            proc_name = p.name()
                        except Exception:
                            proc_name = "Unknown"
                        rect = wintypes.RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        found = {
                            "status": "ok",
                            "title": t,
                            "process": proc_name,
                            "pid": pid.value,
                            "bounds": {
                                "left": rect.left,
                                "top": rect.top,
                                "right": rect.right,
                                "bottom": rect.bottom,
                                "width": rect.right - rect.left,
                                "height": rect.bottom - rect.top,
                            },
                        }
                        return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        h_desktop = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_desktop:
            user32.EnumDesktopWindows(h_desktop, WNDENUMPROC(enum_proc), 0)
            user32.CloseDesktop(h_desktop)
        else:
            user32.EnumWindows(WNDENUMPROC(enum_proc), 0)

        return found if found else {"status": "error", "error": "No visible foreground window found"}



def _find_window_hwnd(title_sub: str):
    target = title_sub.lower().strip()
    found_hwnd = None
    found_title = None

    def enum_proc(hwnd, lparam):
        nonlocal found_hwnd, found_title
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                t = buf.value
                if target in t.lower():
                    found_hwnd = hwnd
                    found_title = t
                    return False
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    h_desktop = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if h_desktop:
        user32.EnumDesktopWindows(h_desktop, WNDENUMPROC(enum_proc), 0)
        user32.CloseDesktop(h_desktop)
    else:
        user32.EnumWindows(WNDENUMPROC(enum_proc), 0)

    return found_hwnd, found_title


def focus_window(title_substring: str) -> dict:
    """Bring the window matching title_substring to the front and restore it."""
    with attach_desktop():
        hwnd, title = _find_window_hwnd(title_substring)
        if not hwnd:
            return {"status": "error", "error": f"No visible window matching '{title_substring}' found."}

        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return {"status": "ok", "focused": title, "hwnd": hwnd}


def maximize_window(title_substring: str) -> dict:
    """Maximize the window matching title_substring."""
    with attach_desktop():
        hwnd, title = _find_window_hwnd(title_substring)
        if not hwnd:
            return {"status": "error", "error": f"No visible window matching '{title_substring}' found."}

        SW_MAXIMIZE = 3
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
        user32.SetForegroundWindow(hwnd)
        return {"status": "ok", "maximized": title}


def minimize_window(title_substring: str) -> dict:
    """Minimize the window matching title_substring."""
    with attach_desktop():
        hwnd, title = _find_window_hwnd(title_substring)
        if not hwnd:
            return {"status": "error", "error": f"No visible window matching '{title_substring}' found."}

        SW_MINIMIZE = 6
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        return {"status": "ok", "minimized": title}


def close_window(title_substring: str) -> dict:
    """Gracefully close the window matching title_substring (sends WM_CLOSE)."""
    with attach_desktop():
        hwnd, title = _find_window_hwnd(title_substring)
        if not hwnd:
            return {"status": "error", "error": f"No visible window matching '{title_substring}' found."}

        WM_CLOSE = 0x0010
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return {"status": "ok", "closed": title}


def get_system_telemetry() -> dict:
    """Returns instant hardware telemetry: battery, power, CPU, RAM, and uptime."""
    telemetry = {
        "status": "ok",
        "cpu_percent": psutil.cpu_percent(interval=0.1),
    }

    ram = psutil.virtual_memory()
    telemetry["ram"] = {
        "percent": ram.percent,
        "used_gb": round((ram.total - ram.available) / (1024**3), 2),
        "available_gb": round(ram.available / (1024**3), 2),
        "total_gb": round(ram.total / (1024**3), 2),
    }

    battery = psutil.sensors_battery()
    if battery:
        telemetry["battery"] = {
            "percent": battery.percent,
            "plugged_in": battery.power_plugged,
            "status": "Charging" if battery.power_plugged else f"{battery.secsleft // 60} minutes remaining" if battery.secsleft != -1 else "Calculating",
        }
    else:
        telemetry["battery"] = {"status": "AC Desktop (No battery)"}

    return telemetry
