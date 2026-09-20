"""
Gemini Floating Desktop Overlay Indicator (Project Astra Live Widget)
Provides an always-on-top, draggable, animated floating pill on Windows desktop
that visually responds when Gemini is watching, listening, speaking, or working!
"""

import sys
import time
import math
import threading
import queue
import tkinter as tk
from typing import Optional


class GeminiFloatingWidget:
    def __init__(self, on_close=None):
        self.on_close = on_close
        self.state_queue = queue.Queue()
        self.running = True
        self.root: Optional[tk.Tk] = None
        self.current_state = "idle"  # idle, listening, thinking, talking, working
        self.current_text = "Gemini Live Ready"
        self.anim_frame = 0
        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()

    def set_state(self, state: str, text: str = ""):
        """Thread-safe method to update the widget's visual state and subtitles."""
        self.state_queue.put((state, text))

    def _run_tk(self):
        import ctypes
        try:
            user32 = ctypes.windll.user32
            h_desk = user32.OpenInputDesktop(0, False, 0x01FF)
            if h_desk:
                user32.SetThreadDesktop(h_desk)
        except Exception:
            pass

        root = tk.Tk()
        self.root = root
        root.title("Gemini Live Indicator")
        root.overrideredirect(True)  # Frameless
        root.attributes("-topmost", True)  # Always on top

        # Dimensions & initial position (Bottom-right corner, above taskbar)
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        w = 340
        h = 68
        x = screen_w - w - 30
        y = screen_h - h - 70
        root.geometry(f"{w}x{h}+{x}+{y}")

        # Try transparent / dark acrylic styling
        BG_DARK = "#121316"
        root.configure(bg=BG_DARK)
        try:
            root.wm_attributes("-alpha", 0.94)
        except Exception:
            pass

        # Draggable support
        self.drag_x = 0
        self.drag_y = 0

        def start_drag(e):
            self.drag_x = e.x
            self.drag_y = e.y

        def on_drag(e):
            new_x = root.winfo_x() + (e.x - self.drag_x)
            new_y = root.winfo_y() + (e.y - self.drag_y)
            root.geometry(f"+{new_x}+{new_y}")

        # Canvas for drawing rounded pill and animated glow/emojis
        canvas = tk.Canvas(root, width=w, height=h, bg=BG_DARK, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Button-1>", start_drag)
        canvas.bind("<B1-Motion>", on_drag)
        self.canvas = canvas

        self._draw_pill(w, h)
        self._animate()
        root.mainloop()

    def _draw_pill(self, w, h):
        """Draws the dark pill container with glowing border."""
        self.canvas.delete("bg_pill")
        r = 16  # corner radius
        # Outer glow border
        border_color = "#38bdf8"
        if self.current_state == "talking":
            border_color = "#818cf8"  # purple/violet
        elif self.current_state == "listening":
            border_color = "#34d399"  # neon green/cyan
        elif self.current_state == "thinking":
            border_color = "#f472b6"  # pink
        elif self.current_state == "working":
            border_color = "#fbbf24"  # amber/yellow

        # Rounded rectangle outline & fill
        self.canvas.create_rectangle(
            4, 4, w - 4, h - 4,
            fill="#1e1f24", outline=border_color, width=2,
            tags="bg_pill"
        )

    def _animate(self):
        if not self.root:
            return

        # 1. Process state updates from thread
        while not self.state_queue.empty():
            try:
                state, text = self.state_queue.get_nowait()
                self.current_state = state
                if text:
                    self.current_text = text
                w = self.canvas.winfo_width() or 340
                h = self.canvas.winfo_height() or 68
                self._draw_pill(w, h)
            except queue.Empty:
                break

        # Periodically ensure topmost visibility
        if self.anim_frame % 40 == 0:
            try:
                self.root.attributes("-topmost", True)
                self.root.lift()
            except Exception:
                pass

        # 2. Animate visual icons based on state
        self.anim_frame = (self.anim_frame + 1) % 360
        self.canvas.delete("anim_content")

        # Select Emoji & Animation
        if self.current_state == "listening":
            wave = int(math.sin(self.anim_frame * 0.4) * 3)
            icon = "🎙️"
            status_title = "LISTENING"
            title_color = "#34d399"
        elif self.current_state == "thinking":
            spin_icons = ["🧠", "✨", "💡", "✨"]
            icon = spin_icons[(self.anim_frame // 10) % len(spin_icons)]
            status_title = "THINKING & WATCHING"
            title_color = "#f472b6"
        elif self.current_state == "talking":
            talk_icons = ["🗣️", "💬", "🗣️", "✨"]
            icon = talk_icons[(self.anim_frame // 8) % len(talk_icons)]
            status_title = "SPEAKING"
            title_color = "#818cf8"
        elif self.current_state == "working":
            work_icons = ["⚡", "🖱️", "⌨️", "🛠️"]
            icon = work_icons[(self.anim_frame // 8) % len(work_icons)]
            status_title = "WORKING ON DESKTOP"
            title_color = "#fbbf24"
        else:
            pulse = int(math.sin(self.anim_frame * 0.1) * 2)
            icon = "✨"
            status_title = "WATCHING SCREEN (LIVE)"
            title_color = "#38bdf8"

        # Draw Icon (Left circle avatar)
        self.canvas.create_text(
            32, 34,
            text=icon,
            font=("Segoe UI Emoji", 20),
            tags="anim_content"
        )

        # Status Pill Tag (Small header)
        self.canvas.create_text(
            64, 22,
            text=f"● {status_title}",
            font=("Segoe UI", 9, "bold"),
            fill=title_color,
            anchor="w",
            tags="anim_content"
        )

        # Subtitle / Details Text (Trunkated to fit nicely)
        display_text = self.current_text
        if len(display_text) > 42:
            display_text = display_text[:39] + "..."

        self.canvas.create_text(
            64, 44,
            text=display_text,
            font=("Segoe UI", 10),
            fill="#e2e8f0",
            anchor="w",
            tags="anim_content"
        )

        # Close button (small 'x' at top right)
        self.canvas.create_text(
            326, 16,
            text="✕",
            font=("Segoe UI", 8, "bold"),
            fill="#64748b",
            tags="anim_content"
        )

        # Bind close button click
        def handle_click(event):
            if event.x >= 315 and event.y <= 25:
                self.stop()

        self.canvas.bind("<ButtonRelease-1>", handle_click)

        # 50ms refresh rate (~20 FPS smooth animation)
        self.root.after(50, self._animate)

    def stop(self):
        self.running = False
        if self.root:
            try:
                self.root.destroy()
            except Exception:
                pass
        if self.on_close:
            self.on_close()


if __name__ == "__main__":
    # Test standalone demo
    widget = GeminiFloatingWidget()
    print("Demo widget launched! Cycling states...")
    time.sleep(1.5)
    widget.set_state("listening", "Listening to your microphone...")
    time.sleep(2.5)
    widget.set_state("thinking", "Analyzing 1024x576 video frame...")
    time.sleep(2.5)
    widget.set_state("talking", "I see your desktop with VS Code open!")
    time.sleep(3.5)
    widget.set_state("working", "Clicking inside Notepad editor...")
    time.sleep(2.5)
    widget.set_state("idle", "Gemini Live watching screen...")
    
    # Keep alive for demo
    while widget.running:
        time.sleep(0.5)
