"""
Gemini Antigravity Bridge - Agent Swarm Event Bus
Thread-safe in-memory status feed for the multi-agent cursor swarm.
Agents register once, then publish lightweight status events
(thinking / acting / waiting / done / error); the overlay and any other
subscriber read consistent JSON-able snapshots of the whole swarm.

Standard library only. No GUI imports — safe to load inside the MCP server.
"""

import colorsys
import json
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional

# ─── Swarm Limits & Vocabulary ────────────────────────────────────────────────

MAX_AGENTS = 48                      # spec target is 30+; headroom included
VALID_STATES = ("thinking", "acting", "waiting", "done", "error")
DEFAULT_STALE_AFTER = 45.0           # seconds without an update -> expired
MAX_ACTION_CHARS = 80                # captions stay short on screen
EVENT_HISTORY_SIZE = 200

# Hand-picked, mutually distinct cursor colours (identity = colour + name tag).
_BASE_PALETTE = [
    "#38bdf8", "#a78bfa", "#34d399", "#fbbf24", "#fb7185", "#f472b6",
    "#60a5fa", "#4ade80", "#facc15", "#fb923c", "#e879f9", "#2dd4bf",
    "#94a3b8", "#f87171", "#818cf8", "#a3e635", "#fda4af", "#7dd3fc",
    "#c084fc", "#6ee7b7", "#fde047", "#fdba74", "#f0abfc", "#5eead4",
]


def _auto_color(index: int) -> str:
    """Deterministic distinct colour for agent slot `index`."""
    if index < len(_BASE_PALETTE):
        return _BASE_PALETTE[index]
    # Beyond the palette: walk the hue wheel by the golden angle.
    hue = ((index * 137.508) % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.95)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


# ─── Known-Agent Identity Themes ─────────────────────────────────────────────
# The user's real agents get a recognisable fixed colour + display name when
# they register under their usual id prefix (or a matching display name):
# "claude-1", "gemini_worker", "spark" all theme automatically. An explicit
# colour/name passed to register_agent always wins over the theme.

KNOWN_AGENT_THEMES: Dict[str, Dict[str, str]] = {
    "Muse":      {"name": "Muse",      "color": "#38bdf8"},
    "gemini":      {"name": "Gemini",      "color": "#a78bfa"},
    "chatgpt":     {"name": "ChatGPT",     "color": "#34d399"},
    "claude":      {"name": "Claude",      "color": "#fb923c"},
    "codex":       {"name": "Codex",       "color": "#facc15"},
    "spark":       {"name": "Spark",       "color": "#f472b6"},
    "antigravity": {"name": "Antigravity", "color": "#818cf8"},
}


def _theme_for(agent_id: str, name: Optional[str] = None
               ) -> Optional[Dict[str, str]]:
    """Return the known-agent theme matching `agent_id` (by prefix) or the
    supplied display `name` (by prefix), else None."""
    candidates = [agent_id.lower()]
    if name:
        candidates.append(name.lower())
    for key, theme in KNOWN_AGENT_THEMES.items():
        for candidate in candidates:
            if candidate == key or candidate.startswith(key):
                return theme
    return None


class SwarmEventBus:
    """In-memory, thread-safe registry of live agent status.

    Publishers never block for long and never crash the host: unknown agents
    are auto-registered on first publish, invalid states raise ValueError
    (a programming error the caller should see), and stale agents expire
    automatically so a crashed agent's cursor does not linger forever.
    """

    def __init__(self, stale_after: float = DEFAULT_STALE_AFTER,
                 max_agents: int = MAX_AGENTS):
        self._lock = threading.RLock()
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []
        self._events: deque = deque(maxlen=EVENT_HISTORY_SIZE)
        self._stale_after = float(stale_after)
        self._max_agents = int(max_agents)
        self._next_color_slot = 0
        self._total_events = 0
        # Session recorder (optional JSONL event log for later replay).
        self._record_file = None
        self._record_path: Optional[str] = None
        self._record_t0 = 0.0
        self._record_written = 0
        self._record_errors = 0

    # ─── Registration ─────────────────────────────────────────────────────────

    def register_agent(self, agent_id: str, name: Optional[str] = None,
                       color: Optional[str] = None) -> Dict[str, Any]:
        """Register (or refresh) an agent. Returns its public record.

        Colour/name resolution for a NEW agent: explicit arguments win;
        then the known-agent theme (id/name prefix match — see
        KNOWN_AGENT_THEMES); then the auto palette. The theme also
        supplies the display name when the agent id is exactly the theme
        key (e.g. id "gemini" displays as "Gemini").
        """
        if not agent_id or not isinstance(agent_id, str):
            raise ValueError("agent_id must be a non-empty string")
        with self._lock:
            record = self._agents.get(agent_id)
            if record is None:
                if len(self._agents) >= self._max_agents:
                    raise ValueError(
                        f"swarm is full ({self._max_agents} agents max)")
                theme = _theme_for(agent_id, name)
                if color is None and theme is not None:
                    color = theme["color"]
                if name is None and theme is not None \
                        and agent_id.lower() in KNOWN_AGENT_THEMES:
                    name = theme["name"]
                record = {
                    "agent_id": agent_id,
                    "name": name or agent_id,
                    "color": color or _auto_color(self._next_color_slot),
                    "state": "waiting",
                    "current_action": "",
                    "progress": None,
                    "anchor": None,
                    "registered_at": time.time(),
                    "last_seen": time.time(),
                    "event_count": 0,
                }
                self._next_color_slot += 1
                self._agents[agent_id] = record
            else:
                if name:
                    record["name"] = name
                if color:
                    record["color"] = color
                record["last_seen"] = time.time()
            result = self._public(record)
            self._total_events += 1
            self._record_event("register", agent_id,
                               name=record["name"], color=record["color"])
        self._notify()
        return result

    def unregister_agent(self, agent_id: str) -> bool:
        """Remove an agent from the swarm. Returns True if it existed."""
        with self._lock:
            existed = self._agents.pop(agent_id, None) is not None
            if existed:
                self._total_events += 1
                self._record_event("unregister", agent_id)
        if existed:
            self._notify()
        return existed

    def is_registered(self, agent_id: str) -> bool:
        with self._lock:
            return agent_id in self._agents

    # ─── Publishing ───────────────────────────────────────────────────────────

    def publish(self, agent_id: str, state: str,
                current_action: str = "",
                progress: Optional[float] = None,
                anchor: Any = None) -> Dict[str, Any]:
        """Publish one status event for an agent.

        `state` must be one of VALID_STATES. `anchor` is optional and stored
        as given (JSON-able): a window title string, or a dict such as
        {"window": "Chrome", "x": 640, "y": 300} when the publisher knows
        where on screen the agent is working.
        """
        if state not in VALID_STATES:
            raise ValueError(
                f"invalid state {state!r}; expected one of {VALID_STATES}")
        if progress is not None:
            progress = max(0.0, min(1.0, float(progress)))
        action = (current_action or "")[:MAX_ACTION_CHARS]
        with self._lock:
            if agent_id not in self._agents:
                self.register_agent(agent_id)  # RLock: safe re-entry
            record = self._agents[agent_id]
            record["state"] = state
            record["current_action"] = action
            record["progress"] = progress
            if anchor is not None:
                record["anchor"] = anchor
            record["last_seen"] = time.time()
            record["event_count"] += 1
            self._events.append({
                "ts": record["last_seen"],
                "agent_id": agent_id,
                "state": state,
                "current_action": action,
            })
            self._total_events += 1
            self._record_event("publish", agent_id, state=state,
                               current_action=action, progress=progress,
                               anchor=anchor)
            result = self._public(record)
        self._notify()
        return result

    def heartbeat(self, agent_id: str) -> bool:
        """Refresh an agent's liveness without changing its status."""
        with self._lock:
            record = self._agents.get(agent_id)
            if record is None:
                return False
            record["last_seen"] = time.time()
            return True

    # ─── Expiry ───────────────────────────────────────────────────────────────

    def prune_stale(self, now: Optional[float] = None) -> List[str]:
        """Drop agents that have been silent longer than `stale_after`.

        Agents in state "done" expire twice as fast — their work is over,
        so their cursor should clear quickly. Returns removed agent ids.
        """
        now = time.time() if now is None else now
        removed: List[str] = []
        with self._lock:
            for agent_id, record in list(self._agents.items()):
                limit = self._stale_after
                if record["state"] == "done":
                    limit = self._stale_after / 2.0
                if now - record["last_seen"] > limit:
                    removed.append(agent_id)
                    del self._agents[agent_id]
        if removed:
            self._notify()
        return removed

    # ─── Session Recording (JSONL event log for replay) ───────────────────────

    def start_recording(self, path: str) -> Dict[str, Any]:
        """Start appending every lifecycle/status event to a JSONL session
        log at `path`, each line stamped with a monotonic offset `t`
        (seconds since recording started). Raises RuntimeError if a
        recording is already in progress on this bus."""
        with self._lock:
            if self._record_file is not None:
                raise RuntimeError(
                    f"already recording to {self._record_path}")
            handle = open(path, "a", encoding="utf-8")
            self._record_file = handle
            self._record_path = path
            self._record_t0 = time.monotonic()
            self._record_written = 0
            self._record_errors = 0
            self._write_record_line({
                "t": 0.0, "ts": time.time(), "type": "session_start",
                "version": 1, "max_agents": self._max_agents,
            })
            return self.recording_info()

    def stop_recording(self) -> Optional[str]:
        """Stop the session recording. Returns the log path, or None if
        no recording was in progress."""
        with self._lock:
            if self._record_file is None:
                return None
            path = self._record_path
            try:
                self._write_record_line({
                    "t": time.monotonic() - self._record_t0,
                    "ts": time.time(), "type": "session_end",
                    "events_written": self._record_written,
                })
                self._record_file.close()
            except Exception:
                pass
            self._record_file = None
            self._record_path = None
            return path

    def recording_info(self) -> Dict[str, Any]:
        """Current session-recorder state (JSON-able)."""
        with self._lock:
            return {
                "active": self._record_file is not None,
                "path": self._record_path,
                "events_written": self._record_written,
                "write_errors": self._record_errors,
            }

    def _record_event(self, event_type: str, agent_id: str,
                      **fields: Any) -> None:
        """Append one event to the session log (caller holds the lock).
        A failing log must never break a publisher: errors are counted
        in recording_info() instead of raised."""
        if self._record_file is None:
            return
        event = {
            "t": time.monotonic() - self._record_t0,
            "ts": time.time(),
            "type": event_type,
            "agent_id": agent_id,
        }
        event.update(fields)
        self._write_record_line(event)

    def _write_record_line(self, event: Dict[str, Any]) -> None:
        try:
            line = json.dumps(event, ensure_ascii=False, default=str)
        except Exception:
            self._record_errors += 1
            return
        try:
            self._record_file.write(line + "\n")
            self._record_file.flush()
            self._record_written += 1
        except Exception:
            self._record_errors += 1

    @property
    def total_events(self) -> int:
        """Lifetime count of register/publish/unregister events."""
        with self._lock:
            return self._total_events

    # ─── Subscribers & Snapshots ──────────────────────────────────────────────

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback invoked with a fresh snapshot on every change."""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def _notify(self) -> None:
        # Callbacks run outside the lock and each is isolated: a broken
        # subscriber must never break a publisher or the other subscribers.
        with self._lock:
            subscribers = list(self._subscribers)
        if not subscribers:
            return
        snap = self.snapshot()
        for callback in subscribers:
            try:
                callback(snap)
            except Exception:
                pass

    def snapshot(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Full swarm state as a JSON-able dict (stale agents pruned first)."""
        self.prune_stale(now=now)
        now = time.time() if now is None else now
        with self._lock:
            agents = [self._public(r) for r in self._agents.values()]
            counts = {state: 0 for state in VALID_STATES}
            for agent in agents:
                counts[agent["state"]] = counts.get(agent["state"], 0) + 1
            return {
                "generated_at": now,
                "agent_count": len(agents),
                "max_agents": self._max_agents,
                "total_events": self._total_events,
                "counts_by_state": counts,
                "agents": agents,
                "recent_events": list(self._events)[-25:],
            }

    def clear(self) -> None:
        with self._lock:
            self._agents.clear()
            self._events.clear()
        self._notify()

    # ─── Internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _public(record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "agent_id": record["agent_id"],
            "name": record["name"],
            "color": record["color"],
            "state": record["state"],
            "current_action": record["current_action"],
            "progress": record["progress"],
            "anchor": record["anchor"],
            "registered_at": record["registered_at"],
            "last_seen": record["last_seen"],
            "event_count": record["event_count"],
        }


# ─── Shared Default Bus (bridge-wide singleton, same pattern as the HUD) ─────

_DEFAULT_BUS: Optional[SwarmEventBus] = None
_DEFAULT_BUS_LOCK = threading.Lock()


def get_default_bus() -> SwarmEventBus:
    global _DEFAULT_BUS
    with _DEFAULT_BUS_LOCK:
        if _DEFAULT_BUS is None:
            _DEFAULT_BUS = SwarmEventBus()
        return _DEFAULT_BUS
