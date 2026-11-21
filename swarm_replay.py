"""
Gemini Antigravity Bridge - Swarm Session Replay
Loads a JSONL session log recorded by SwarmEventBus.start_recording()
and re-publishes its events into a (fresh) bus on a timed player —
mirroring the reference product's Replay, except what replays here is
REAL recorded agent work: the registrations, status changes and
unregistrations that actually happened, at their original spacing.

The player runs on a background thread (it never blocks the caller),
supports play / pause / resume / stop, and playback speeds of
1x / 2x / 3x which can be changed mid-play. Pausing freezes the event
timeline rather than skipping it. Standard library only.
"""

import json
import threading
import time
from typing import Any, Dict, List, Optional

try:  # package layout
    from .swarm_events import VALID_STATES
except ImportError:  # flat layout
    from swarm_events import VALID_STATES

__all__ = ["ReplayPlayer", "load_session", "play_session"]

VALID_SPEEDS = (1.0, 2.0, 3.0)
_DISPATCHABLE = ("register", "publish", "unregister")


# ─── Session Loading ──────────────────────────────────────────────────────────

def load_session(path: str) -> List[Dict[str, Any]]:
    """Read a JSONL session log and return its events in file order.

    Raises FileNotFoundError if the log does not exist and ValueError
    on a corrupt (non-JSON) line — callers turn both into error dicts.
    Blank lines are skipped.
    """
    events: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError as exc:
                raise ValueError(
                    f"corrupt session log {path!r} line {line_no}: {exc}")
            if isinstance(event, dict):
                events.append(event)
    return events


# ─── Timed Player ─────────────────────────────────────────────────────────────

class ReplayPlayer:
    """Re-publishes recorded events into a target bus, in order, with
    the original inter-event spacing divided by the playback speed."""

    def __init__(self, bus: Any, events: List[Dict[str, Any]],
                 speed: float = 1.0):
        if float(speed) not in VALID_SPEEDS:
            raise ValueError(
                f"speed must be one of {VALID_SPEEDS}, got {speed!r}")
        self._bus = bus
        self._events = [e for e in events
                        if e.get("type") in _DISPATCHABLE]
        self._speed = float(speed)
        self._cond = threading.Condition()
        self._thread: Optional[threading.Thread] = None
        self._playing = False
        self._paused = False
        self._stop_flag = False
        self._published = 0
        self._skipped = 0

    # ─── Transport Controls ───────────────────────────────────────────────────

    def start(self) -> None:
        """Begin playback on a background thread. Returns immediately."""
        with self._cond:
            if self._playing:
                return
            self._stop_flag = False
            self._paused = False
            self._playing = True
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="swarm-replay")
            self._thread.start()

    def pause(self) -> None:
        with self._cond:
            self._paused = True
            self._cond.notify_all()

    def resume(self) -> None:
        with self._cond:
            self._paused = False
            self._cond.notify_all()

    def stop(self) -> None:
        """Stop playback (idempotent). The thread winds down promptly;
        call join() if the caller needs it fully finished."""
        with self._cond:
            self._stop_flag = True
            self._paused = False
            self._cond.notify_all()

    def join(self, timeout: Optional[float] = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def set_speed(self, speed: float) -> None:
        if float(speed) not in VALID_SPEEDS:
            raise ValueError(
                f"speed must be one of {VALID_SPEEDS}, got {speed!r}")
        with self._cond:
            self._speed = float(speed)
            self._cond.notify_all()

    # ─── State ────────────────────────────────────────────────────────────────

    @property
    def is_playing(self) -> bool:
        with self._cond:
            return self._playing

    @property
    def is_paused(self) -> bool:
        with self._cond:
            return self._paused

    @property
    def speed(self) -> float:
        with self._cond:
            return self._speed

    @property
    def events_published(self) -> int:
        with self._cond:
            return self._published

    @property
    def events_skipped(self) -> int:
        with self._cond:
            return self._skipped

    @property
    def total_events(self) -> int:
        return len(self._events)

    def status(self) -> Dict[str, Any]:
        with self._cond:
            return {
                "playing": self._playing,
                "paused": self._paused,
                "speed": self._speed,
                "events_published": self._published,
                "events_skipped": self._skipped,
                "total_events": len(self._events),
            }

    # ─── Playback Loop ────────────────────────────────────────────────────────

    def _wait(self, event_delay: float) -> bool:
        """Wait out `event_delay` seconds of *event time* (scaled by the
        current speed, frozen while paused). Returns False if stopped."""
        remaining = max(0.0, event_delay)
        last = time.monotonic()
        with self._cond:
            while True:
                if self._stop_flag:
                    return False
                now = time.monotonic()
                if not self._paused:
                    remaining -= (now - last) * self._speed
                    if remaining <= 0:
                        return True
                last = now
                self._cond.wait(timeout=0.01)

    def _run(self) -> None:
        prev_t: Optional[float] = None
        try:
            for event in self._events:
                try:
                    t = float(event.get("t", 0.0))
                except Exception:
                    t = prev_t or 0.0
                delay = 0.0 if prev_t is None else max(0.0, t - prev_t)
                if not self._wait(delay):
                    break
                dispatched = self._dispatch(event)
                prev_t = t
                with self._cond:
                    if dispatched:
                        self._published += 1
        finally:
            with self._cond:
                self._playing = False
                self._paused = False
                self._cond.notify_all()

    def _dispatch(self, event: Dict[str, Any]) -> bool:
        """Apply one recorded event to the target bus. Returns True when
        the event was applied; bad events are counted as skipped, never
        raised — one corrupt line must not kill the whole replay."""
        agent_id = event.get("agent_id")
        if not agent_id:
            with self._cond:
                self._skipped += 1
            return False
        try:
            kind = event.get("type")
            if kind == "register":
                self._bus.register_agent(agent_id,
                                         name=event.get("name"),
                                         color=event.get("color"))
            elif kind == "publish":
                state = event.get("state")
                if state not in VALID_STATES:
                    raise ValueError(f"bad recorded state {state!r}")
                self._bus.publish(agent_id, state,
                                  event.get("current_action") or "",
                                  progress=event.get("progress"),
                                  anchor=event.get("anchor"))
            elif kind == "unregister":
                self._bus.unregister_agent(agent_id)
            else:
                raise ValueError(f"unknown event type {kind!r}")
        except Exception:
            with self._cond:
                self._skipped += 1
            return False
        return True


def play_session(bus: Any, path: str, speed: float = 1.0) -> ReplayPlayer:
    """Load a session log from `path` and start replaying it into `bus`.
    Returns the running player. Raises FileNotFoundError / ValueError
    from load_session, ValueError on an invalid speed."""
    player = ReplayPlayer(bus, load_session(path), speed=speed)
    player.start()
    return player
