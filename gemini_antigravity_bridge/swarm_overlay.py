"""
Gemini Antigravity Bridge - Agent Swarm Overlay
Full-screen, transparent, always-on-top Tkinter overlay that draws the
agent swarm: one Figma-style cursor per Tier A (GUI-active) agent and a
chip strip along the bottom edge for Tier B / Tier C agents.

DISPLAY ONLY, by design and by construction:
  * The window is created click-through (WS_EX_TRANSPARENT) and
    no-activate (WS_EX_NOACTIVATE) on Windows.
  * This module contains no mouse/keyboard control code at all.
    It never moves the user's real cursor and never clicks anything.

The overlay polls a state provider at ~10 fps and eases cursors toward
their anchors at render rate. Tkinter is imported lazily: if it (or a
display) is unavailable, start() returns a clear failure message instead
of raising, so the bridge keeps running without the visual layer.
"""

import math
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

try:  # package layout (gemini_antigravity_bridge.swarm_overlay)
    from . import swarm_windows as _windows_feed
except ImportError:  # flat layout (files beside server.py)
    try:
        import swarm_windows as _windows_feed
    except ImportError:
        _windows_feed = None  # type: ignore[assignment]

# ─── Overlay Tuning ───────────────────────────────────────────────────────────

TRANSPARENT_KEY = "#010203"        # magic colour treated as transparent
STRIP_HEIGHT = 46                  # px reserved for the bottom chip strip
POLL_MS = 100                      # snapshot poll interval (~10 fps)
FRAME_MS = 33                      # render interval (~30 fps)
EASE = 0.20                        # cursor easing factor per frame
IDLE_FADE_AFTER = 10.0             # s without an event -> dimmed cursor
INTRO_SECONDS = 1.0                # flock-in duration feel (via easing)
FINALE_HOLD_SECONDS = 1.4          # converge hold before fade-out
MAX_CAPTION_CHARS = 42

_STATE_DOT = {
    "thinking": "#a78bfa",
    "acting": "#34d399",
    "waiting": "#fbbf24",
    "done": "#38bdf8",
    "error": "#fb7185",
}

# Figma-style cursor arrow, drawn at the cursor's hot point (0, 0).
_CURSOR_POINTS = [
    0, 0, 0, 19, 5.2, 14.8, 8.2, 22.6, 11.2, 21.2, 8.2, 13.6, 14, 13.6,
]


def _dim_color(hex_color: str, factor: float = 0.45) -> str:
    """Blend a #rrggbb colour toward dark grey (Tkinter has no per-item
    alpha, so idle fade is approximated by dimming)."""
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


def build_default_provider(bus: Any, orchestrator: Any = None
                           ) -> Callable[[], Dict[str, Any]]:
    """Merge the event-bus snapshot with orchestrator tiers into the flat
    agent list the overlay renders. Without an orchestrator, the first
    eight non-done agents are treated as Tier A."""
    def provider() -> Dict[str, Any]:
        snap = bus.snapshot()
        tiers: Dict[str, str] = {}
        if orchestrator is not None:
            try:
                for agent in orchestrator.snapshot()["agents"]:
                    tiers[agent["agent_id"]] = agent["tier"]
            except Exception:
                tiers = {}
        agents: List[Dict[str, Any]] = []
        fallback_a = 0
        for agent in snap["agents"]:
            tier = tiers.get(agent["agent_id"])
            if tier is None:
                if agent["state"] in ("acting", "thinking") and fallback_a < 8:
                    tier = "A"
                    fallback_a += 1
                else:
                    tier = "B"
            agents.append({
                "agent_id": agent["agent_id"],
                "name": agent["name"],
                "color": agent["color"],
                "state": agent["state"],
                "current_action": agent["current_action"],
                "anchor": agent["anchor"],
                "tier": tier,
                "last_seen": agent["last_seen"],
                "event_count": agent["event_count"],
            })
        return {"agents": agents, "generated_at": snap["generated_at"]}
    return provider


class SwarmOverlay:
    """Owns the overlay window on a daemon thread (same pattern as the
    existing DesktopHUD). All public methods are safe to call from any
    thread and never raise."""

    def __init__(self, state_provider: Callable[[], Dict[str, Any]]):
        self._provider = state_provider
        self._thread: Optional[threading.Thread] = None
        self._root = None
        self._canvas = None
        self.is_running = False
        self.last_error: Optional[str] = None
        self._stop_requested = False
        self._visuals: Dict[str, Dict[str, Any]] = {}
        self._state: Dict[str, Any] = {"agents": []}
        self._last_poll = 0.0
        self._windows_cache: List[Dict[str, Any]] = []
        self._windows_cache_at = 0.0
        self._finale_until = 0.0
        self._finale_fade_after = 0.0
        self._finale_signature: Optional[Tuple] = None
        self._hidden_until_event_after = 0.0

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> Tuple[bool, str]:
        if self.is_running:
            return True, "swarm overlay already running"
        try:
            import tkinter  # noqa: F401  (availability probe only)
        except Exception as exc:
            self.last_error = f"Tkinter unavailable: {exc}"
            return False, ("swarm overlay unavailable: Tkinter is not "
                           "installed on this Python; the bridge and swarm "
                           "logic are unaffected")
        self._stop_requested = False
        self.last_error = None
        self._thread = threading.Thread(target=self._run_ui, daemon=True,
                                        name="swarm-overlay")
        self._thread.start()
        # Give the UI thread a moment to report early failure (no display).
        for _ in range(30):
            if self.is_running or self.last_error:
                break
            time.sleep(0.05)
        if self.last_error:
            return False, f"swarm overlay failed to start: {self.last_error}"
        if not self.is_running:
            return False, ("swarm overlay failed to start: UI thread did "
                           "not come up (no interactive display?)")
        return True, "swarm overlay started"

    def stop(self) -> Tuple[bool, str]:
        self._stop_requested = True
        root = self._root
        if root is not None:
            try:
                root.after(0, root.destroy)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.is_running = False
        self._root = None
        self._canvas = None
        self._visuals = {}
        return True, "swarm overlay stopped"

    def trigger_finale(self) -> None:
        """Converge all cursors to the centre, hold, then fade out."""
        now = time.time()
        self._finale_until = now + FINALE_HOLD_SECONDS
        self._finale_fade_after = self._finale_until + 0.9

    # ─── UI Thread ────────────────────────────────────────────────────────────

    def _run_ui(self) -> None:
        try:
            import tkinter as tk
        except Exception as exc:
            self.last_error = f"Tkinter import failed: {exc}"
            return
        try:
            self._attach_desktop()
            root = tk.Tk()
            self._root = root
            root.title("Gemini Swarm Overlay")
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            self._screen_w = root.winfo_screenwidth()
            self._screen_h = root.winfo_screenheight()
            root.geometry(f"{self._screen_w}x{self._screen_h}+0+0")
            root.configure(bg=TRANSPARENT_KEY)
            try:
                root.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
            except Exception:
                pass
            self._make_click_through(root)
            canvas = tk.Canvas(root, width=self._screen_w,
                               height=self._screen_h, bg=TRANSPARENT_KEY,
                               highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            self._canvas = canvas
            self.is_running = True
            self._frame()
            root.mainloop()
        except Exception as exc:
            self.last_error = f"overlay UI error: {exc}"
        finally:
            self.is_running = False

    @staticmethod
    def _attach_desktop() -> None:
        """Attach to the interactive desktop (same helper the HUD uses)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            h_winsta = user32.OpenWindowStationW("WinSta0", False, 0x037F)
            if h_winsta:
                user32.SetProcessWindowStation(h_winsta)
            h_desktop = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if h_desktop:
                user32.SetThreadDesktop(h_desktop)
        except Exception:
            pass

    @staticmethod
    def _make_click_through(root) -> None:
        """WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE: the
        overlay can never receive or block user input."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            root.update_idletasks()
            hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_NOACTIVATE = 0x08000000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
        except Exception:
            pass

    # ─── Frame Loop ───────────────────────────────────────────────────────────

    def _frame(self) -> None:
        if self._stop_requested or self._root is None:
            return
        now = time.time()
        if now - self._last_poll >= POLL_MS / 1000.0:
            self._last_poll = now
            try:
                self._state = self._provider()
            except Exception:
                pass  # keep rendering the last good state
            self._maybe_auto_finale(now)
        if now - self._windows_cache_at >= 0.5:
            self._windows_cache_at = now
            self._refresh_windows()
        self._render(now)
        try:
            self._root.after(FRAME_MS, self._frame)
        except Exception:
            pass

    def _maybe_auto_finale(self, now: float) -> None:
        agents = self._state.get("agents", [])
        if not agents:
            return
        if not all(a["state"] == "done" for a in agents):
            return
        signature = (tuple(sorted(a["agent_id"] for a in agents)),
                     max(a["event_count"] for a in agents))
        if signature == self._finale_signature:
            return
        self._finale_signature = signature
        self.trigger_finale()

    # ─── Rendering ────────────────────────────────────────────────────────────

    def _refresh_windows(self) -> None:
        """Refresh the cached window rectangles (wave 2 geometry feed).
        Any failure simply empties the cache — anchors fall back to the
        deterministic spread, exactly as in wave 1."""
        if _windows_feed is None:
            self._windows_cache = []
            return
        try:
            result = _windows_feed.list_windows()
            self._windows_cache = result.get("windows", []) \
                if result.get("status") == "success" else []
        except Exception:
            self._windows_cache = []

    def _anchor_target(self, agent: Dict[str, Any], index: int,
                       tier_a_count: int) -> Tuple[float, float]:
        anchor = agent.get("anchor")
        if isinstance(anchor, dict):
            try:
                return float(anchor["x"]), float(anchor["y"])
            except Exception:
                pass
        # Wave 2: a window-title anchor resolves to that window's REAL
        # rectangle via the geometry feed (centre + per-agent offset).
        title = None
        if isinstance(anchor, str):
            title = anchor
        elif isinstance(anchor, dict):
            title = anchor.get("window")
        if title and _windows_feed is not None and self._windows_cache:
            point = _windows_feed.anchor_point_for_title(
                title, self._windows_cache, index)
            if point is not None:
                x = max(30, min(self._screen_w - 190, point[0]))
                y = max(30, min(self._screen_h - STRIP_HEIGHT - 90,
                                point[1]))
                return x, y
        # Deterministic spread over the work area (above the strip):
        # golden-angle scatter around the centre keeps labels unstacked.
        cx = self._screen_w / 2.0
        cy = (self._screen_h - STRIP_HEIGHT) / 2.0
        angle = index * 2.399963  # golden angle, radians
        radius = 90 + 55 * math.sqrt(max(index, 0) + 1)
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle) * 0.62
        x = max(30, min(self._screen_w - 190, x))
        y = max(30, min(self._screen_h - STRIP_HEIGHT - 90, y))
        return x, y

    def _render(self, now: float) -> None:
        canvas = self._canvas
        if canvas is None:
            return
        canvas.delete("all")
        agents = self._state.get("agents", [])

        # Post-finale: stay hidden until genuinely new work arrives.
        if self._hidden_until_event_after:
            newest = max((a["last_seen"] for a in agents), default=0.0)
            if newest <= self._hidden_until_event_after:
                self._visuals = {}
                return
            self._hidden_until_event_after = 0.0

        in_finale = now < self._finale_until
        fading = self._finale_until and now >= self._finale_until
        if fading and now > self._finale_fade_after:
            # Finale complete: clear and hide until the next real event.
            self._finale_until = 0.0
            self._hidden_until_event_after = now
            self._visuals = {}
            return

        tier_a = [a for a in agents if a["tier"] == "A"]
        strip_agents = [a for a in agents if a["tier"] != "A"]

        seen_ids = set()
        for index, agent in enumerate(tier_a):
            seen_ids.add(agent["agent_id"])
            if in_finale:
                target = (self._screen_w / 2.0 + (index - len(tier_a) / 2) * 26,
                          (self._screen_h - STRIP_HEIGHT) / 2.0)
            else:
                target = self._anchor_target(agent, index, len(tier_a))
            self._draw_cursor(agent, target, now, dimmed=bool(fading))
        # Drop visuals for agents that left Tier A / the swarm.
        for agent_id in list(self._visuals):
            if agent_id not in seen_ids:
                del self._visuals[agent_id]

        self._draw_strip(strip_agents, now)

    def _draw_cursor(self, agent: Dict[str, Any],
                     target: Tuple[float, float], now: float,
                     dimmed: bool = False) -> None:
        canvas = self._canvas
        agent_id = agent["agent_id"]
        visual = self._visuals.get(agent_id)
        if visual is None:
            # Flock-in: spawn at the nearest screen edge.
            tx, ty = target
            edges = [(tx, 0), (tx, self._screen_h - STRIP_HEIGHT),
                     (0, ty), (self._screen_w, ty)]
            sx, sy = min(edges, key=lambda p: (p[0] - tx) ** 2 + (p[1] - ty) ** 2)
            visual = {"x": sx, "y": sy}
            self._visuals[agent_id] = visual
        visual["x"] += (target[0] - visual["x"]) * EASE
        visual["y"] += (target[1] - visual["y"]) * EASE
        x, y = visual["x"], visual["y"]

        idle = (now - agent["last_seen"]) > IDLE_FADE_AFTER
        color = agent["color"]
        if idle or dimmed:
            color = _dim_color(color)

        points = [v + (x if i % 2 == 0 else y)
                  for i, v in enumerate(_CURSOR_POINTS)]
        canvas.create_polygon(points, fill=color, outline="#ffffff", width=1)

        # Name tag beside the cursor.
        name = agent["name"][:18]
        tag_w = 12 + 7 * len(name)
        canvas.create_rectangle(x + 14, y + 15, x + 14 + tag_w, y + 33,
                                fill=color, outline="")
        canvas.create_text(x + 20, y + 24, anchor="w", text=name,
                           fill="#ffffff", font=("Segoe UI", 9, "bold"))
        # Live action caption under the tag.
        caption = agent["current_action"][:MAX_CAPTION_CHARS]
        if caption:
            cap_w = 10 + 6 * len(caption)
            canvas.create_rectangle(x + 14, y + 35, x + 14 + cap_w, y + 51,
                                    fill="#18181b", outline="")
            canvas.create_text(x + 19, y + 43, anchor="w", text=caption,
                               fill="#f4f4f5", font=("Segoe UI", 8))

    def _draw_strip(self, strip_agents: List[Dict[str, Any]],
                    now: float) -> None:
        canvas = self._canvas
        top = self._screen_h - STRIP_HEIGHT
        canvas.create_rectangle(0, top, self._screen_w, self._screen_h,
                                fill="#18181b", outline="")
        canvas.create_line(0, top, self._screen_w, top, fill="#3f3f46")

        # Working agents first, then waiting, then done.
        order = {"acting": 0, "thinking": 1, "error": 2, "waiting": 3,
                 "done": 4}
        ordered = sorted(strip_agents,
                         key=lambda a: order.get(a["state"], 5))
        x = 10
        shown = 0
        for agent in ordered:
            label = agent["name"][:12]
            chip_w = 34 + 7 * len(label)
            if x + chip_w > self._screen_w - 190:
                break
            dot_color = _STATE_DOT.get(agent["state"], "#71717a")
            if agent["tier"] == "C":
                dot_color = _dim_color(dot_color)
            canvas.create_rectangle(x, top + 9, x + chip_w, top + 37,
                                    fill="#27272a", outline="#3f3f46")
            canvas.create_oval(x + 7, top + 19, x + 15, top + 27,
                               fill=dot_color, outline="")
            canvas.create_text(x + 20, top + 23, anchor="w", text=label,
                               fill="#f4f4f5", font=("Segoe UI", 8, "bold"))
            x += chip_w + 8
            shown += 1
        hidden = len(ordered) - shown
        if hidden > 0:
            working = sum(1 for a in ordered[shown:]
                          if a["state"] in ("acting", "thinking", "waiting"))
            if working:
                text = f"+{working} working in background"
            else:
                text = f"+{hidden} more"
            canvas.create_text(self._screen_w - 12, top + 23, anchor="e",
                               text=text, fill="#a1a1aa",
                               font=("Segoe UI", 9, "bold"))


# ─── Shared Overlay Singleton (same pattern as the HUD) ──────────────────────

_OVERLAY_INSTANCE: Optional[SwarmOverlay] = None
_OVERLAY_LOCK = threading.Lock()


def get_overlay(state_provider: Optional[Callable[[], Dict[str, Any]]] = None
                ) -> SwarmOverlay:
    global _OVERLAY_INSTANCE
    with _OVERLAY_LOCK:
        if _OVERLAY_INSTANCE is None:
            if state_provider is None:
                raise ValueError("first get_overlay() call needs a "
                                 "state_provider")
            _OVERLAY_INSTANCE = SwarmOverlay(state_provider)
        return _OVERLAY_INSTANCE


def show_swarm(state_provider: Optional[Callable[[], Dict[str, Any]]] = None
               ) -> Tuple[bool, str]:
    try:
        return get_overlay(state_provider).start()
    except Exception as exc:
        return False, f"swarm overlay unavailable: {exc}"


def hide_swarm() -> Tuple[bool, str]:
    global _OVERLAY_INSTANCE
    with _OVERLAY_LOCK:
        overlay = _OVERLAY_INSTANCE
    if overlay is None:
        return True, "swarm overlay was not running"
    return overlay.stop()


def overlay_status() -> Dict[str, Any]:
    """Non-creating status probe (used by swarm stats / kill switch):
    whether the overlay singleton exists and whether it is running."""
    with _OVERLAY_LOCK:
        overlay = _OVERLAY_INSTANCE
    if overlay is None:
        return {"created": False, "running": False, "last_error": None}
    return {"created": True, "running": bool(overlay.is_running),
            "last_error": overlay.last_error}
