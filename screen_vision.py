"""
Gemini Antigravity Bridge — Screen Vision & Desktop Control Module
Gives Gemini Spark the ability to:
  - Take screenshots of the full desktop or a specific region
  - Find what's on screen using image analysis
  - Move mouse, click, double-click, right-click
  - Type text and press keyboard keys
  - Scroll the screen

This module bridges the "Computer Use / Astra" gap, giving Gemini Spark
the same native computer control that GPT-4o Computer Use / Project Astra offers.
"""

import io
import base64
import time
from typing import Optional, Tuple

# ─── Image processing + Screenshot (PIL ImageGrab works in all Windows sessions) ─
try:
    from PIL import Image, ImageDraw, ImageGrab
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

# ─── Mouse & keyboard control ─────────────────────────────────────────────────
try:
    import pyautogui
    pyautogui.FAILSAFE = False  # Disabled so (0,0) or corners don't trigger fail-safe crash
    pyautogui.PAUSE = 0.05
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

from contextlib import contextmanager

@contextmanager
def attach_desktop():
    """
    Attaches thread to interactive window station (WinSta0) and Default desktop.
    Required for synthetic mouse and keyboard input on Windows.
    """
    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

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


def _require(module_available: bool, module_name: str):
    if not module_available:
        raise RuntimeError(
            f"Module '{module_name}' is not installed. "
            f"Run: pip install {module_name}"
        )




def _screenshot_win32_ctypes(region=None):
    """
    Screenshot using raw Win32 GDI + WinSta0 attachment.
    Attaches to the interactive Window Station (WinSta0\\Default) before BitBlt
    so it works correctly from background/daemon processes on Windows.
    """
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32
    gdi32  = ctypes.windll.gdi32

    # ── Step 1: Attach to WinSta0 (interactive window station) ───────────────
    WINSTA_ALL_ACCESS  = 0x037F
    DESKTOP_ALL_ACCESS = 0x01FF

    h_winsta_orig = user32.GetProcessWindowStation()
    h_winsta = ctypes.windll.user32.OpenWindowStationW("WinSta0", False, WINSTA_ALL_ACCESS)
    if h_winsta:
        user32.SetProcessWindowStation(h_winsta)

    # ── Step 2: Attach thread to Default desktop ──────────────────────────────
    h_desktop_orig = user32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
    h_desktop = user32.OpenDesktopW("Default", 0, False, DESKTOP_ALL_ACCESS)
    if h_desktop:
        user32.SetThreadDesktop(h_desktop)

    try:
        if region:
            left, top, width, height = region
        else:
            left, top = 0, 0
            user32.SetProcessDPIAware()
            width  = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
            height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN

        # ── Step 3: BitBlt from screen to memory ─────────────────────────────
        hdc_screen = user32.GetDC(None)
        hdc_mem    = gdi32.CreateCompatibleDC(hdc_screen)
        hbitmap    = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
        gdi32.SelectObject(hdc_mem, hbitmap)

        SRCCOPY    = 0x00CC0020
        CAPTUREBLT = 0x40000000
        gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, left, top, SRCCOPY | CAPTUREBLT)

        # ── Step 4: Extract pixels via GetDIBits ─────────────────────────────
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize",          ctypes.wintypes.DWORD),
                ("biWidth",         ctypes.wintypes.LONG),
                ("biHeight",        ctypes.wintypes.LONG),
                ("biPlanes",        ctypes.wintypes.WORD),
                ("biBitCount",      ctypes.wintypes.WORD),
                ("biCompression",   ctypes.wintypes.DWORD),
                ("biSizeImage",     ctypes.wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.wintypes.LONG),
                ("biYPelsPerMeter", ctypes.wintypes.LONG),
                ("biClrUsed",       ctypes.wintypes.DWORD),
                ("biClrImportant",  ctypes.wintypes.DWORD),
            ]

        bmi            = BITMAPINFOHEADER()
        bmi.biSize     = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth    = width
        bmi.biHeight   = -height   # top-down
        bmi.biPlanes   = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0      # BI_RGB

        buf_size = width * height * 4
        raw_buf  = (ctypes.c_ubyte * buf_size)()
        gdi32.GetDIBits(hdc_mem, hbitmap, 0, height, raw_buf, ctypes.byref(bmi), 0)

        # Cleanup GDI
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)

    finally:
        # ── Step 5: Restore original window station / desktop ─────────────────
        if h_desktop:
            user32.SetThreadDesktop(h_desktop_orig)
            user32.CloseDesktop(h_desktop)
        if h_winsta:
            user32.SetProcessWindowStation(h_winsta_orig)
            user32.CloseWindowStation(h_winsta)

    img = Image.frombuffer("RGBA", (width, height), bytes(raw_buf), "raw", "BGRA", 0, 1)
    return img.convert("RGB"), width, height



def take_screenshot(
    region: Optional[Tuple[int, int, int, int]] = None,
    annotate_coords: bool = False,
) -> dict:
    """
    Capture the desktop (or a region) and return as a base64-encoded PNG.
    Uses Win32 GDI via ctypes — works from background bridge process on Windows.

    Args:
        region: Optional (left, top, width, height) tuple to capture a sub-region.
        annotate_coords: If True, overlays a grid with pixel coordinates on the image.

    Returns:
        dict with keys:
            - image_b64: base64-encoded PNG string
            - width: image width in pixels
            - height: image height in pixels
            - mode: 'full' or 'region'
    """
    _require(PILLOW_AVAILABLE, "Pillow")

    img, width, height = _screenshot_win32_ctypes(region=region)
    mode = "region" if region else "full"

    if annotate_coords:
        draw = ImageDraw.Draw(img)
        step = max(100, width // 10)
        for x in range(0, width, step):
            draw.line([(x, 0), (x, height)], fill=(100, 100, 255), width=1)
            draw.text((x + 2, 2), str(x), fill=(255, 50, 50))
        for y in range(0, height, step):
            draw.line([(0, y), (width, y)], fill=(100, 100, 255), width=1)
            draw.text((2, y + 2), str(y), fill=(255, 50, 50))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    return {
        "image_b64": image_b64,
        "width": img.width,
        "height": img.height,
        "mode": mode,
        "region": region,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }




def get_screen_size() -> dict:
    """Return the current screen resolution."""
    _require(PYAUTOGUI_AVAILABLE, "pyautogui")
    w, h = pyautogui.size()
    return {"width": w, "height": h}


def get_mouse_position() -> dict:
    """Return the current mouse cursor position."""
    _require(PYAUTOGUI_AVAILABLE, "pyautogui")
    x, y = pyautogui.position()
    return {"x": x, "y": y}


def move_mouse(x: int, y: int, duration: float = 0.3) -> dict:
    """
    Move the mouse cursor to (x, y).

    Args:
        x: Target X coordinate in pixels.
        y: Target Y coordinate in pixels.
        duration: Animation duration in seconds (0 = instant).
    """
    _require(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.moveTo(x, y, duration=duration)
    return {"moved_to": {"x": x, "y": y}, "duration": duration}


def click_mouse(
    x: Optional[int] = None,
    y: Optional[int] = None,
    button: str = "left",
    clicks: int = 1,
    interval: float = 0.1,
) -> dict:
    """
    Click the mouse at (x, y). If no coordinates given, clicks at current position.

    Args:
        x: X coordinate (optional).
        y: Y coordinate (optional).
        button: 'left', 'right', or 'middle'.
        clicks: Number of clicks (2 for double-click).
        interval: Seconds between clicks.
    """
    _require(PYAUTOGUI_AVAILABLE, "pyautogui")
    if x is not None and y is not None:
        pyautogui.click(x, y, button=button, clicks=clicks, interval=interval)
        return {"clicked": {"x": x, "y": y}, "button": button, "clicks": clicks}
    else:
        pyautogui.click(button=button, clicks=clicks, interval=interval)
        pos = pyautogui.position()
        return {"clicked": {"x": pos.x, "y": pos.y}, "button": button, "clicks": clicks}


def type_text(text: str, interval: float = 0.05) -> dict:
    """
    Type a string of text using the keyboard.

    Args:
        text: The text to type.
        interval: Seconds between each key press.
    """
    _require(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.typewrite(text, interval=interval)
    return {"typed": text, "chars": len(text)}


def press_key(key: str, presses: int = 1, interval: float = 0.1) -> dict:
    """
    Press a keyboard key or key combination.

    Args:
        key: Key name e.g. 'enter', 'ctrl+c', 'alt+tab', 'f5', 'escape', 'win'.
              For combinations use '+' separator: 'ctrl+alt+delete'.
    """
    _require(PYAUTOGUI_AVAILABLE, "pyautogui")
    if "+" in key:
        keys = [k.strip() for k in key.split("+")]
        pyautogui.hotkey(*keys)
        return {"pressed": key, "type": "hotkey"}
    else:
        pyautogui.press(key, presses=presses, interval=interval)
        return {"pressed": key, "presses": presses}


def scroll_screen(x: int, y: int, clicks: int, direction: str = "up") -> dict:
    """
    Scroll the mouse wheel at a given position.

    Args:
        x: X coordinate to scroll at.
        y: Y coordinate to scroll at.
        clicks: Number of scroll clicks (positive = up, negative = down).
        direction: 'up' or 'down' (overridden by sign of clicks).
    """
    _require(PYAUTOGUI_AVAILABLE, "pyautogui")
    amount = abs(clicks) if direction == "up" else -abs(clicks)
    pyautogui.scroll(amount, x=x, y=y)
    return {"scrolled": {"x": x, "y": y}, "clicks": amount, "direction": direction}


def drag_mouse(
    from_x: int, from_y: int,
    to_x: int, to_y: int,
    duration: float = 0.5,
    button: str = "left"
) -> dict:
    """
    Click and drag from one position to another.

    Args:
        from_x, from_y: Starting position.
        to_x, to_y: Ending position.
        duration: Drag animation time in seconds.
        button: Mouse button to hold during drag.
    """
    _require(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.moveTo(from_x, from_y, duration=0.2)
    pyautogui.dragTo(to_x, to_y, duration=duration, button=button)
    return {
        "dragged": {"from": {"x": from_x, "y": from_y}, "to": {"x": to_x, "y": to_y}},
        "duration": duration,
        "button": button,
    }


def get_open_windows() -> list[str]:
    """Return titles of currently open visible windows on the interactive desktop in <15ms."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    windows = []
    h_winsta_orig = user32.GetProcessWindowStation()
    h_winsta = user32.OpenWindowStationW("WinSta0", False, 0x037F)
    if h_winsta:
        user32.SetProcessWindowStation(h_winsta)

    h_desktop_orig = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    h_desktop = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if h_desktop:
        user32.SetThreadDesktop(h_desktop)

    try:
        def enum_proc(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()
                    if title and title not in ("Program Manager", "Windows Input Experience"):
                        windows.append(title)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumDesktopWindows(h_desktop, WNDENUMPROC(enum_proc), 0)
    finally:
        if h_desktop:
            user32.SetThreadDesktop(h_desktop_orig)
            user32.CloseDesktop(h_desktop)
        if h_winsta:
            user32.SetProcessWindowStation(h_winsta_orig)
            user32.CloseWindowStation(h_winsta)

    return windows


def get_desktop_overview(include_screenshot: bool = True) -> dict:
    """
    Unified Astra-style single-call desktop inspector.
    Returns in one shot:
      - Active visible windows
      - Screen resolution
      - Mouse cursor position
      - Base64 full desktop screenshot
    Allows Gemini Spark to answer natural user questions with EXACTLY ONE permission prompt.
    """
    resolution = get_screen_size() if PYAUTOGUI_AVAILABLE else {"width": 1920, "height": 1080}
    mouse_pos = get_mouse_position() if PYAUTOGUI_AVAILABLE else {"x": 0, "y": 0}
    windows = get_open_windows()

    result = {
        "status": "ok",
        "screen_resolution": resolution,
        "mouse_position": mouse_pos,
        "active_windows": windows,
        "active_windows_count": len(windows),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if include_screenshot:
        shot = take_screenshot()
        result["image_b64"] = shot.get("image_b64", "")
        result["screenshot_mode"] = shot.get("mode", "full")

    return result


def execute_action_plan(steps: list[dict], plan_description: str = "") -> dict:
    """
    Execute a sequence of computer actions under a single permission grant.
    Fully attached to the interactive desktop with FAILSAFE=False.
    """
    _require(PYAUTOGUI_AVAILABLE, "pyautogui")
    import subprocess

    pyautogui.FAILSAFE = False
    results = []

    with attach_desktop():
        for i, step in enumerate(steps):
            action = step.get("action", "").lower()
            try:
                if action in ("launch", "open", "run"):
                    cmd = step.get("command") or step.get("app") or step.get("target") or "notepad.exe"
                    subprocess.Popen(f"start {cmd}", shell=True)
                    wait_sec = step.get("seconds") or step.get("wait") or 1.5
                    time.sleep(wait_sec)
                    res = {"launched": cmd}
                elif action == "move":
                    res = move_mouse(step["x"], step["y"], step.get("duration", 0.2))
                elif action == "click":
                    res = click_mouse(step.get("x"), step.get("y"), step.get("button", "left"), step.get("clicks", 1))
                elif action == "type":
                    res = type_text(step["text"], step.get("interval", 0.01))
                elif action in ("key", "hotkey"):
                    keys = step.get("keys") or step.get("key")
                    if isinstance(keys, list):
                        mapped = ["winleft" if k.lower() == "win" else k.lower() for k in keys]
                        pyautogui.hotkey(*mapped)
                        res = {"hotkey": mapped}
                    else:
                        k = str(keys)
                        if k.lower() == "win":
                            k = "winleft"
                        res = press_key(k)
                elif action == "scroll":
                    x = step.get("x", 500)
                    y = step.get("y", 500)
                    res = scroll_screen(x, y, step.get("clicks", 3), step.get("direction", "down"))
                elif action == "wait":
                    time.sleep(step.get("seconds", 0.5))
                    res = {"waited": step.get("seconds", 0.5)}
                else:
                    res = {"error": f"Unknown action '{action}'"}
                results.append({"step": i + 1, "action": action, "status": "ok", "detail": res})
            except Exception as e:
                results.append({"step": i + 1, "action": action, "status": "error", "error": str(e)})
                break

    return {
        "status": "completed",
        "plan_description": plan_description,
        "steps_executed": len(results),
        "results": results,
    }


