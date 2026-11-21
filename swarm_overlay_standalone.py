"""
Gemini Antigravity Bridge - Swarm Overlay (standalone process, wave 3)

WHY THIS EXISTS: the in-process Tkinter overlay (swarm_overlay.py) could
not keep its window alive inside the MCP server's worker threads. This
version runs as its OWN detached process (pythonw) on the interactive
desktop. It is display-only by construction: click-through, no-activate,
no input code at all.

STATE CONTRACT: it polls swarm_state.json (written by swarm_tools on
every swarm change) in, in order:
  1. the folder this script lives in
  2. <that folder>/gemini_antigravity_bridge/
  3. the parent folder of this script
The file shape is {"overlay_visible": bool, "agents": [ {agent_id, name,
color, state, current_action, anchor, tier, last_seen, event_count} ]}.
When overlay_visible becomes false, the process exits cleanly.
It writes swarm_overlay.pid + swarm_overlay_heartbeat.json beside the
state file it is using, so the bridge can check it is really alive.
"""

import ctypes
import json
import math
import os
import sys
import time

TRANSPARENT_KEY = "#010203"
STRIP_HEIGHT = 46
FRAME_MS = 33
EASE = 0.22
MAX_CAPTION_CHARS = 42

_STATE_DOT = {
    "thinking": "#a78bfa",
    "acting": "#34d399",
    "waiting": "#fbbf24",
    "done": "#38bdf8",
    "error": "#fb7185",
}

_CURSOR_POINTS = [
    0, 0, 0, 19, 5.2, 14.8, 8.2, 22.6, 11.2, 21.2, 8.2, 13.6, 14, 13.6,
]

HERE = os.path.dirname(os.path.abspath(__file__))


def _candidate_state_paths():
    return [
        os.path.join(HERE, "swarm_state.json"),
        os.path.join(HERE, "gemini_antigravity_bridge", "swarm_state.json"),
        os.path.join(os.path.dirname(HERE), "swarm_state.json"),
    ]


def _attach_desktop():
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        h_winsta = user32.OpenWindowStationW("WinSta0", False, 0x037F)
        if h_winsta:
            user32.SetProcessWindowStation(h_winsta)
        h_desktop = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_desktop:
            user32.SetThreadDesktop(h_desktop)
    except Exception:
        pass


def _make_click_through(root):
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        root.update_idletasks()
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        GWL_EXSTYLE = -20
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE,
            style | 0x00080000 | 0x00000020 | 0x08000000)
    except Exception:
        pass


def _dim(hex_color, factor=0.45):
    try:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
    except Exception:
        return hex_color
    r = int(r * factor + 40 * (1 - factor))
    g = int(g * factor + 40 * (1 - factor))
    b = int(b * factor + 46 * (1 - factor))
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


class StandaloneOverlay:
    def __init__(self):
        self.state = {"agents": [], "overlay_visible": True}
        self.state_path = None
        self.state_mtime = 0.0
        self.visuals = {}
        self.screen_w = 1920
        self.screen_h = 1080
        self.last_heartbeat = 0.0
        self.started_at = time.time()

    # ── state file ──────────────────────────────────────────────────────
    def _poll_state(self):
        for path in _candidate_state_paths():
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if path != self.state_path or mtime != self.state_mtime:
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    if isinstance(data, dict) and "agents" in data:
                        self.state = data
                        self.state_path = path
                        self.state_mtime = mtime
                except Exception:
                    pass
            return  # first existing file wins

    def _heartbeat(self, root):
        now = time.time()
        if now - self.last_heartbeat < 1.0:
            return
        self.last_heartbeat = now
        base = os.path.dirname(self.state_path) if self.state_path else HERE
        try:
            with open(os.path.join(base, "swarm_overlay.pid"), "w") as fh:
                fh.write(str(os.getpid()))
            with open(os.path.join(base, "swarm_overlay_heartbeat.json"),
                      "w", encoding="utf-8") as fh:
                json.dump({"pid": os.getpid(), "at": now,
                           "agents": len(self.state.get("agents", [])),
                           "running": True}, fh)
        except Exception:
            pass

    # ── geometry ────────────────────────────────────────────────────────
    def _target(self, agent, index, now):
        anchor = agent.get("anchor")
        if isinstance(anchor, dict):
            try:
                return float(anchor["x"]), float(anchor["y"])
            except Exception:
                pass
        cx = self.screen_w / 2.0
        cy = (self.screen_h - STRIP_HEIGHT) / 2.0
        angle = index * 2.399963
        radius = 110 + 60 * math.sqrt(max(index, 0) + 1)
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle) * 0.62
        # Gentle live drift so cursors visibly move while they "work".
        x += 26 * math.sin(now / 1.6 + index * 1.7)
        y += 18 * math.cos(now / 2.1 + index * 2.3)
        x = max(30, min(self.screen_w - 200, x))
        y = max(30, min(self.screen_h - STRIP_HEIGHT - 100, y))
        return x, y

    # ── rendering ───────────────────────────────────────────────────────
    def _draw_cursor(self, canvas, agent, target, now):
        agent_id = agent["agent_id"]
        visual = self.visuals.get(agent_id)
        if visual is None:
            tx, ty = target
            edges = [(tx, 0), (tx, self.screen_h - STRIP_HEIGHT),
                     (0, ty), (self.screen_w, ty)]
            sx, sy = min(edges,
                         key=lambda p: (p[0] - tx) ** 2 + (p[1] - ty) ** 2)
            visual = {"x": sx, "y": sy}
            self.visuals[agent_id] = visual
        visual["x"] += (target[0] - visual["x"]) * EASE
        visual["y"] += (target[1] - visual["y"]) * EASE
        x, y = visual["x"], visual["y"]
        color = agent.get("color") or "#38bdf8"
        if (now - float(agent.get("last_seen") or now)) > 3600:
            color = _dim(color)
        points = [v + (x if i % 2 == 0 else y)
                  for i, v in enumerate(_CURSOR_POINTS)]
        canvas.create_polygon(points, fill=color, outline="#ffffff", width=1)
        name = str(agent.get("name") or agent_id)[:18]
        tag_w = 12 + 7 * len(name)
        canvas.create_rectangle(x + 14, y + 15, x + 14 + tag_w, y + 33,
                                fill=color, outline="")
        canvas.create_text(x + 20, y + 24, anchor="w", text=name,
                           fill="#ffffff", font=("Segoe UI", 9, "bold"))
        caption = str(agent.get("current_action") or "")[:MAX_CAPTION_CHARS]
        if caption:
            cap_w = 10 + 6 * len(caption)
            canvas.create_rectangle(x + 14, y + 35, x + 14 + cap_w, y + 51,
                                    fill="#18181b", outline="")
            canvas.create_text(x + 19, y + 43, anchor="w", text=caption,
                               fill="#f4f4f5", font=("Segoe UI", 8))

    def _draw_strip(self, canvas, strip_agents):
        top = self.screen_h - STRIP_HEIGHT
        if not strip_agents:
            return
        canvas.create_rectangle(0, top, self.screen_w, self.screen_h,
                                fill="#18181b", outline="")
        canvas.create_line(0, top, self.screen_w, top, fill="#3f3f46")
        order = {"acting": 0, "thinking": 1, "error": 2, "waiting": 3,
                 "done": 4}
        ordered = sorted(strip_agents,
                         key=lambda a: order.get(a.get("state"), 5))
        x = 10
        shown = 0
        for agent in ordered:
            label = str(agent.get("name") or "")[:12]
            chip_w = 34 + 7 * len(label)
            if x + chip_w > self.screen_w - 190:
                break
            dot = _STATE_DOT.get(agent.get("state"), "#71717a")
            if agent.get("tier") == "C":
                dot = _dim(dot)
            canvas.create_rectangle(x, top + 9, x + chip_w, top + 37,
                                    fill="#27272a", outline="#3f3f46")
            canvas.create_oval(x + 7, top + 19, x + 15, top + 27,
                               fill=dot, outline="")
            canvas.create_text(x + 20, top + 23, anchor="w", text=label,
                               fill="#f4f4f5", font=("Segoe UI", 8, "bold"))
            x += chip_w + 8
            shown += 1
        hidden = len(ordered) - shown
        if hidden > 0:
            canvas.create_text(self.screen_w - 12, top + 23, anchor="e",
                               text="+{} more in swarm".format(hidden),
                               fill="#a1a1aa", font=("Segoe UI", 9, "bold"))

    # ── main loop ───────────────────────────────────────────────────────
    def run(self):
        _attach_desktop()
        import tkinter as tk
        root = tk.Tk()
        root.title("Gemini Swarm Overlay")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        self.screen_w = root.winfo_screenwidth()
        self.screen_h = root.winfo_screenheight()
        root.geometry("{}x{}+0+0".format(self.screen_w, self.screen_h))
        root.configure(bg=TRANSPARENT_KEY)
        try:
            root.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
        except Exception:
            pass
        _make_click_through(root)
        canvas = tk.Canvas(root, width=self.screen_w, height=self.screen_h,
                           bg=TRANSPARENT_KEY, highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        def frame():
            self._poll_state()
            if not self.state.get("overlay_visible", True):
                root.destroy()
                return
            now = time.time()
            canvas.delete("all")
            agents = self.state.get("agents", [])
            tier_a = [a for a in agents if a.get("tier") == "A"]
            strip = [a for a in agents if a.get("tier") != "A"]
            seen = set()
            for index, agent in enumerate(tier_a):
                seen.add(agent["agent_id"])
                self._draw_cursor(canvas, agent,
                                  self._target(agent, index, now), now)
            for agent_id in list(self.visuals):
                if agent_id not in seen:
                    del self.visuals[agent_id]
            self._draw_strip(canvas, strip)
            self._heartbeat(root)
            root.after(FRAME_MS, frame)

        frame()
        root.mainloop()


if __name__ == "__main__":
    StandaloneOverlay().run()
