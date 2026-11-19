"""
Gemini Antigravity Bridge - Live Desktop Floating HUD & AI Cursor Follower
Attaches an interactive AI badge right beside the user's physical mouse cursor,
displaying live reasoning ("Thinking..."), tool execution, and smooth cursor automation.
"""

import sys
import time
import queue
import threading
import ctypes
from typing import Optional, Tuple

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

_HUD_INSTANCE = None
_HUD_LOCK = threading.Lock()


def attach_interactive_desktop():
    try:
        h_winsta = user32.OpenWindowStationW("WinSta0", False, 0x037F)
        if h_winsta:
            user32.SetProcessWindowStation(h_winsta)
        h_desktop = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_desktop:
            user32.SetThreadDesktop(h_desktop)
    except Exception:
        pass


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_real_cursor_pos() -> Tuple[int, int]:
    try:
        attach_interactive_desktop()
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    except Exception:
        return 0, 0


class DesktopHUD:
    def __init__(self):
        self.queue = queue.Queue()
        self.root = None
        self.canvas = None
        self.text_id = None
        self.is_running = False
        self.current_text = "AI Connected"
        self.current_state = "idle"
        self.last_update = time.time()
        self.auto_hide_time = None

        self.thread = threading.Thread(target=self._run_ui, daemon=True)
        self.thread.start()

    def update(self, text: str, state: str = "thinking", timeout: Optional[float] = 5.0, pos: Optional[Tuple[int, int]] = None):
        self.queue.put((text, state, timeout, pos))

    def _run_ui(self):
        try:
            import tkinter as tk
        except Exception:
            return

        attach_interactive_desktop()

        root = tk.Tk()
        self.root = root
        root.title("Gemini Cursor HUD")
        root.overrideredirect(True)
        root.attributes("-topmost", True)

        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        w, h = 280, 34

        mx, my = get_real_cursor_pos()
        nx = mx + 22
        ny = my + 14
        root.geometry(f"{w}x{h}+{nx}+{ny}")

        BG_COLOR = "#18181b"
        BORDER_COLOR = "#38bdf8"
        root.configure(bg=BG_COLOR)

        try:
            root.wm_attributes("-alpha", 0.98)
            root.update_idletasks()
            w_hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            cur_style = user32.GetWindowLongW(w_hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(w_hwnd, GWL_EXSTYLE, cur_style | WS_EX_NOACTIVATE)
        except Exception:
            pass

        canvas = tk.Canvas(root, width=w, height=h, bg=BG_COLOR, highlightthickness=1, highlightbackground=BORDER_COLOR)
        canvas.pack(fill="both", expand=True)
        self.canvas = canvas

        # Glowing cyan 4-pointed sparkle (matching user's AI cursor photo)
        self.sparkle_id = canvas.create_text(16, 17, text="✦", font=("Segoe UI Symbol", 12, "bold"), fill="#38bdf8")

        # Status text beside sparkle
        self.text_id = canvas.create_text(
            34, 17,
            anchor="w",
            text="AI Connected",
            fill="#f4f4f5",
            font=("Segoe UI", 9, "bold"),
            tags="status_text"
        )

        self.is_running = True
        self._loop()
        root.mainloop()

    def _loop(self):
        if not self.root:
            return

        now = time.time()
        updated = False

        while not self.queue.empty():
            try:
                text, state, timeout, _ = self.queue.get_nowait()
                self.current_text = text
                self.current_state = state
                self.last_update = now
                if timeout:
                    self.auto_hide_time = now + timeout
                else:
                    self.auto_hide_time = None
                updated = True
            except queue.Empty:
                break

        if updated and self.canvas and self.text_id:
            color_map = {
                "thinking": ("#a78bfa", "#a78bfa"),   # soft purple
                "mouse": ("#38bdf8", "#38bdf8"),      # bright cyan
                "typing": ("#34d399", "#34d399"),     # emerald green
                "task": ("#fbbf24", "#fbbf24"),       # warm amber
                "idle": ("#71717a", "#27272a"),       # muted
            }
            fg, border = color_map.get(self.current_state, ("#f4f4f5", "#38bdf8"))
            display_text = self.current_text
            if len(display_text) > 36:
                display_text = display_text[:33] + "..."
            self.canvas.itemconfig(self.text_id, text=display_text, fill=fg)
            self.canvas.configure(highlightbackground=border)
            self.root.deiconify()

        # Continously anchor badge to REAL physical mouse cursor at 60 FPS
        if self.root:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            w, h = 280, 34
            mx, my = get_real_cursor_pos()
            nx = mx + 22
            ny = my + 14
            if nx + w > screen_w:
                nx = mx - w - 12
            if ny + h > screen_h:
                ny = my - h - 12
            nx = max(8, min(screen_w - w - 8, nx))
            ny = max(8, min(screen_h - h - 8, ny))
            self.root.geometry(f"{w}x{h}+{nx}+{ny}")

        # Fade to idle
        if self.auto_hide_time and now > self.auto_hide_time:
            self.auto_hide_time = None
            if self.current_state != "idle":
                self.current_state = "idle"
                if self.canvas and self.text_id:
                    self.canvas.itemconfig(self.text_id, text="Gemini Bridge Ready", fill="#71717a")
                    self.canvas.configure(highlightbackground="#27272a")

        self.root.after(16, self._loop)


def get_hud() -> DesktopHUD:
    global _HUD_INSTANCE
    with _HUD_LOCK:
        if _HUD_INSTANCE is None:
            _HUD_INSTANCE = DesktopHUD()
        return _HUD_INSTANCE


def show_hud_status(text: str, state: str = "thinking", timeout: Optional[float] = 4.0, pos: Optional[Tuple[int, int]] = None):
    try:
        hud = get_hud()
        hud.update(text=text, state=state, timeout=timeout, pos=pos)
    except Exception:
        pass
