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
    pyautogui.FAILSAFE = True   # Move to top-left corner to abort
    pyautogui.PAUSE = 0.1       # 100ms pause between actions (safety)
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False


def _require(module_available: bool, module_name: str):
    if not module_available:
        raise RuntimeError(
            f"Module '{module_name}' is not installed. "
            f"Run: pip install {module_name}"
        )



def take_screenshot(
    region: Optional[Tuple[int, int, int, int]] = None,
    annotate_coords: bool = False,
) -> dict:
    """
    Capture the desktop (or a region) and return as a base64-encoded PNG.

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

    if region:
        left, top, width, height = region
        bbox = (left, top, left + width, top + height)
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        mode = "region"
    else:
        img = ImageGrab.grab(all_screens=True)
        mode = "full"

    img = img.convert("RGB")

    if annotate_coords:
        draw = ImageDraw.Draw(img)
        w, h = img.size
        step = max(100, w // 10)
        for x in range(0, w, step):
            draw.line([(x, 0), (x, h)], fill=(100, 100, 255), width=1)
            draw.text((x + 2, 2), str(x), fill=(255, 50, 50))
        for y in range(0, h, step):
            draw.line([(0, y), (w, y)], fill=(100, 100, 255), width=1)
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
