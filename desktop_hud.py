"""
Gemini Antigravity Bridge - Live Desktop Floating HUD & Reasoning Indicator
Provides an always-on-top, draggable, non-intrusive floating pill indicator
that displays real-time AI reasoning ("Thinking..."), mouse actions, and keystrokes.
"""

import sys
import time
import queue
import threading
from typing import Optional

_HUD_INSTANCE = None
_HUD_LOCK = threading.Lock()


class DesktopHUD:
    def __init__(self):
        self.queue = queue.Queue()
        self.root = None
        self.canvas = None
        self.text_id = None
        self.dots_ids = []
        self.is_running = False
        self.current_text = "Ready"
        self.current_state = "idle"
        self.last_update = time.time()
        self.auto_hide_time = None
        self.drag_x = 0
        self.drag_y = 0

        self.thread = threading.Thread(target=self._run_ui, daemon=True)
        self.thread.start()

    def update(self, text: str, state: str = "thinking", timeout: Optional[float] = 5.0):
        """Thread-safe update of the HUD indicator."""
        self.queue.put((text, state, timeout))

    def _run_ui(self):
        try:
            import tkinter as tk
            import ctypes
        except Exception:
            return

        try:
            user32 = ctypes.windll.user32
            h_desk = user32.OpenInputDesktop(0, False, 0x01FF)
            if h_desk:
                user32.SetThreadDesktop(h_desk)
        except Exception:
            pass

        root = tk.Tk()
        self.root = root
        root.title("Gemini HUD")
        root.overrideredirect(True)
        root.attributes("-topmost", True)

        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        w = 360
        h = 38
        x = (screen_w - w) // 2
        y = 45
        root.geometry(f"{w}x{h}+{x}+{y}")

        BG_COLOR = "#18181b"
        BORDER_COLOR = "#27272a"
        root.configure(bg=BG_COLOR)

        try:
            root.wm_attributes("-alpha", 0.95)
            root.update_idletasks()
            w_hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            if not w_hwnd:
                w_hwnd = root.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            cur_style = ctypes.windll.user32.GetWindowLongW(w_hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(w_hwnd, GWL_EXSTYLE, cur_style | WS_EX_NOACTIVATE)
        except Exception:
            pass

        # Draggable pill support
        def start_drag(e):
            self.drag_x = e.x
            self.drag_y = e.y

        def on_drag(e):
            new_x = root.winfo_x() + (e.x - self.drag_x)
            new_y = root.winfo_y() + (e.y - self.drag_y)
            root.geometry(f"+{new_x}+{new_y}")

        canvas = tk.Canvas(root, width=w, height=h, bg=BG_COLOR, highlightthickness=1, highlightbackground=BORDER_COLOR)
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Button-1>", start_drag)
        canvas.bind("<B1-Motion>", on_drag)
        self.canvas = canvas

        # 4-dot drag handle (2x2 grid)
        dot_color = "#71717a"
        canvas.create_oval(14, 13, 18, 17, fill=dot_color, outline="", tags="handle")
        canvas.create_oval(22, 13, 26, 17, fill=dot_color, outline="", tags="handle")
        canvas.create_oval(14, 21, 18, 25, fill=dot_color, outline="", tags="handle")
        canvas.create_oval(22, 21, 26, 25, fill=dot_color, outline="", tags="handle")

        # Status text
        self.text_id = canvas.create_text(
            38, 19,
            anchor="w",
            text="Gemini Bridge Active",
            fill="#e4e4e7",
            font=("Segoe UI", 9, "normal"),
            tags="status_text"
        )

        self.is_running = True
        self._loop()
        root.mainloop()

    def _loop(self):
        if not self.root:
            return

        # Process incoming status updates
        now = time.time()
        updated = False
        while not self.queue.empty():
            try:
                text, state, timeout = self.queue.get_nowait()
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
            # Color coding based on state
            color_map = {
                "thinking": "#a78bfa",   # soft purple (reasoning)
                "mouse": "#38bdf8",      # light cyan (mouse/cursor)
                "typing": "#34d399",     # emerald green (typing)
                "task": "#fbbf24",       # warm amber (general task)
                "idle": "#a1a1aa",       # muted grey
            }
            fg = color_map.get(self.current_state, "#e4e4e7")
            # Truncate text if too long to fit cleanly
            display_text = self.current_text
            if len(display_text) > 42:
                display_text = display_text[:39] + "..."
            self.canvas.itemconfig(self.text_id, text=display_text, fill=fg)
            self.root.deiconify()

        # Handle auto-fading to idle
        if self.auto_hide_time and now > self.auto_hide_time:
            self.auto_hide_time = None
            if self.current_state != "idle":
                self.current_state = "idle"
                if self.canvas and self.text_id:
                    self.canvas.itemconfig(self.text_id, text="Gemini Bridge Ready", fill="#71717a")

        self.root.after(100, self._loop)


def get_hud() -> DesktopHUD:
    global _HUD_INSTANCE
    with _HUD_LOCK:
        if _HUD_INSTANCE is None:
            _HUD_INSTANCE = DesktopHUD()
        return _HUD_INSTANCE


def show_hud_status(text: str, state: str = "thinking", timeout: Optional[float] = 4.0):
    """Global helper to show a status message on the floating desktop HUD."""
    try:
        hud = get_hud()
        hud.update(text=text, state=state, timeout=timeout)
    except Exception:
        pass
