"""
Gemini Floating Desktop Overlay Indicator (Project Astra Live Widget)
Provides an always-on-top, draggable, animated floating pill on Windows desktop
with interactive toggle buttons for Camera, Screen Vision, Watchdog Alerts, and Mic!
"""

import sys
import time
import math
import threading
import queue
import tkinter as tk
from typing import Optional, Callable


class GeminiFloatingWidget:
    def __init__(
        self,
        on_close: Optional[Callable] = None,
        on_toggle_camera: Optional[Callable[[bool], None]] = None,
        on_toggle_screen: Optional[Callable[[bool], None]] = None,
        on_toggle_alert: Optional[Callable[[bool], None]] = None,
        on_toggle_mic: Optional[Callable[[bool], None]] = None,
        initial_camera: bool = True,
        initial_screen: bool = True,
        initial_alert: bool = False,
        initial_mic: bool = True,
    ):
        self.on_close = on_close
        self.on_toggle_camera = on_toggle_camera
        self.on_toggle_screen = on_toggle_screen
        self.on_toggle_alert = on_toggle_alert
        self.on_toggle_mic = on_toggle_mic

        # Toggle States
        self.camera_on = initial_camera
        self.screen_on = initial_screen
        self.alert_on = initial_alert
        self.mic_on = initial_mic

        self.state_queue = queue.Queue()
        self.running = True
        self.root: Optional[tk.Tk] = None
        self.current_state = "idle"  # idle, listening, thinking, talking, working
        self.current_text = "Gemini Live Ready (Fast Mode)"
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

        # Dimensions & initial position (Bottom-right corner)
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        w = 420
        h = 105
        x = screen_w - w - 25
        y = screen_h - h - 65
        root.geometry(f"{w}x{h}+{x}+{y}")

        BG_DARK = "#121316"
        root.configure(bg=BG_DARK)
        try:
            root.wm_attributes("-alpha", 0.98)
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

        # Draggable support
        self.drag_x = 0
        self.drag_y = 0
        self.has_dragged = False
        self.press_x = 0
        self.press_y = 0

        def start_drag(e):
            self.drag_x = e.x
            self.drag_y = e.y
            self.press_x = e.x
            self.press_y = e.y
            self.has_dragged = False

        def on_drag(e):
            if abs(e.x - self.press_x) > 4 or abs(e.y - self.press_y) > 4:
                self.has_dragged = True
            new_x = root.winfo_x() + (e.x - self.drag_x)
            new_y = root.winfo_y() + (e.y - self.drag_y)
            root.geometry(f"+{new_x}+{new_y}")

        canvas = tk.Canvas(root, width=w, height=h, bg=BG_DARK, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Button-1>", start_drag)
        canvas.bind("<B1-Motion>", on_drag)
        self.canvas = canvas

        # Handle button clicks
        def handle_click(event):
            if self.has_dragged:
                self.has_dragged = False
                return
            cx, cy = event.x, event.y
            # Close button [X] at top-right
            if cx >= 388 and cy <= 26:
                self.stop()
                return

            # Button Row is between y=70 and y=96
            if 70 <= cy <= 96:
                # 1. CAM button (x: 12 to 105)
                if 12 <= cx <= 105:
                    self.camera_on = not self.camera_on
                    if self.on_toggle_camera:
                        self.on_toggle_camera(self.camera_on)
                    self._update_status_on_toggle("CAM", self.camera_on)

                # 2. SCREEN button (x: 113 to 206)
                elif 113 <= cx <= 206:
                    self.screen_on = not self.screen_on
                    if self.on_toggle_screen:
                        self.on_toggle_screen(self.screen_on)
                    self._update_status_on_toggle("SCREEN", self.screen_on)

                # 3. ALERT button (x: 214 to 307)
                elif 214 <= cx <= 307:
                    self.alert_on = not self.alert_on
                    if self.on_toggle_alert:
                        self.on_toggle_alert(self.alert_on)
                    self._update_status_on_toggle("ALERT", self.alert_on)

                # 4. MIC button (x: 315 to 408)
                elif 315 <= cx <= 408:
                    self.mic_on = not self.mic_on
                    if self.on_toggle_mic:
                        self.on_toggle_mic(self.mic_on)
                    self._update_status_on_toggle("MIC", self.mic_on)

        canvas.bind("<ButtonRelease-1>", handle_click)

        self._draw_pill(w, h)
        self._animate()
        root.mainloop()

    def _update_status_on_toggle(self, btn_name: str, state: bool):
        val = "ON" if state else "OFF"
        if btn_name == "SCREEN" and not state:
            self.current_text = "⚡ Pure Voice Mode (Ultra Fast)"
        else:
            self.current_text = f"{btn_name} toggled {val}"

    def _draw_pill(self, w, h):
        """Draws the dark pill container with glowing border."""
        self.canvas.delete("bg_pill")
        border_color = "#38bdf8"
        if self.current_state == "talking":
            border_color = "#818cf8"  # purple/violet
        elif self.current_state == "listening":
            border_color = "#34d399"  # neon green
        elif self.current_state == "thinking":
            border_color = "#f472b6"  # pink
        elif self.current_state == "working":
            border_color = "#fbbf24"  # amber

        self.canvas.create_rectangle(
            3, 3, w - 3, h - 3,
            fill="#1e1f24", outline=border_color, width=2,
            tags="bg_pill"
        )

    def _draw_btn(self, x1, y1, x2, y2, label: str, is_active: bool, active_color: str, active_bg: str):
        bg = active_bg if is_active else "#27282e"
        fg = active_color if is_active else "#64748b"
        border = active_color if is_active else "#3b3e47"
        self.canvas.create_rectangle(x1, y1, x2, y2, fill=bg, outline=border, width=1, tags="anim_content")
        self.canvas.create_text((x1 + x2) // 2, (y1 + y2) // 2, text=label, font=("Segoe UI", 8, "bold"), fill=fg, tags="anim_content")

    def _animate(self):
        if not self.root:
            return

        # 1. Process state updates from queue
        while not self.state_queue.empty():
            try:
                state, text = self.state_queue.get_nowait()
                self.current_state = state
                if text:
                    self.current_text = text
                w = self.canvas.winfo_width() or 420
                h = self.canvas.winfo_height() or 105
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

        self.anim_frame = (self.anim_frame + 1) % 360
        self.canvas.delete("anim_content")

        # Select Emoji & Animation
        if self.current_state == "listening":
            icon = "🎙️"
            status_title = "LISTENING"
            title_color = "#34d399"
        elif self.current_state == "thinking":
            spin_icons = ["🧠", "✨", "💡"]
            icon = spin_icons[(self.anim_frame // 10) % len(spin_icons)]
            status_title = "THINKING"
            title_color = "#f472b6"
        elif self.current_state == "talking":
            talk_icons = ["🗣️", "💬", "✨"]
            icon = talk_icons[(self.anim_frame // 8) % len(talk_icons)]
            status_title = "SPEAKING (FAST)"
            title_color = "#818cf8"
        elif self.current_state == "working":
            work_icons = ["⚡", "🖱️", "🛠️"]
            icon = work_icons[(self.anim_frame // 8) % len(work_icons)]
            status_title = "WORKING"
            title_color = "#fbbf24"
        else:
            icon = "✨"
            mode_lbl = "VOICE ONLY" if not self.screen_on else "LIVE VISION"
            status_title = f"READY ({mode_lbl})"
            title_color = "#38bdf8"

        # Avatar Icon
        self.canvas.create_text(
            26, 24,
            text=icon,
            font=("Segoe UI Emoji", 16),
            tags="anim_content"
        )

        # Status Header Tag
        self.canvas.create_text(
            50, 16,
            text=f"● {status_title}",
            font=("Segoe UI", 9, "bold"),
            fill=title_color,
            anchor="w",
            tags="anim_content"
        )

        # Close button [X]
        self.canvas.create_text(
            402, 14,
            text="✕",
            font=("Segoe UI", 10, "bold"),
            fill="#64748b",
            tags="anim_content"
        )

        # Subtitle Text with auto word-wrap (shows up to 2 lines cleanly)
        display_text = self.current_text or ""
        if len(display_text) > 115:
            display_text = "..." + display_text[-112:]

        self.canvas.create_text(
            50, 30,
            text=display_text,
            font=("Segoe UI", 9),
            fill="#f1f5f9",
            anchor="nw",
            width=350,
            tags="anim_content"
        )

        # Row of 4 Interactive Toggle Buttons (y=70 to y=96)
        # 1. CAM
        cam_label = "CAM: ON" if self.camera_on else "CAM: OFF"
        self._draw_btn(12, 70, 105, 96, cam_label, self.camera_on, "#34d399", "#064e3b")

        # 2. SCREEN (Turning off enables Ultra-Fast Voice Mode)
        scr_label = "SCREEN: ON" if self.screen_on else "⚡ FAST MODE"
        self._draw_btn(113, 70, 206, 96, scr_label, self.screen_on, "#38bdf8", "#0c4a6e")

        # 3. ALERT (Watchdog)
        alert_label = "ALERT: ON" if self.alert_on else "ALERT: OFF"
        self._draw_btn(214, 70, 307, 96, alert_label, self.alert_on, "#f59e0b", "#78350f")

        # 4. MIC
        mic_label = "MIC: ON" if self.mic_on else "MIC: MUTE"
        self._draw_btn(315, 70, 408, 96, mic_label, self.mic_on, "#c084fc", "#581c87")

        self.root.after(50, self._animate)

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self.root:
            try:
                self.root.after(0, self._safe_destroy)
            except Exception:
                pass
        cb = self.on_close
        self.on_close = None
        if cb:
            try:
                cb()
            except Exception:
                pass

    def _safe_destroy(self):
        if self.root:
            try:
                self.root.quit()
                self.root.destroy()
            except Exception:
                pass
            self.root = None
