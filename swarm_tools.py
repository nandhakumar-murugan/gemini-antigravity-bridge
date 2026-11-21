"""
Gemini Antigravity Bridge - Agent Swarm Tools
Thin MCP-style tool wrappers over the swarm event bus, orchestrator,
overlay and recorder. Each function returns a plain dict, matching the
bridge's structured tools (e.g. get_agent_status). Register them in
server.py with @mcp.tool() — see INSTALL.md for the exact snippet.

Record Mode is honest by contract: recording shells out to ffmpeg's
gdigrab capture only when ffmpeg is actually installed. When it is not,
swarm_begin_recording reports "unavailable" — it never fakes a recording.
"""

import json
import os
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, Optional

try:  # package layout (gemini_antigravity_bridge.swarm_tools)
    from . import swarm_windows
    from .swarm_events import SwarmEventBus, get_default_bus
    from .swarm_orchestrator import SwarmOrchestrator
    from .swarm_overlay import (
        build_default_provider,
        hide_swarm,
        overlay_status,
        show_swarm,
    )
    from .swarm_replay import ReplayPlayer, load_session
except ImportError:  # flat layout (files beside server.py)
    import swarm_windows
    from swarm_events import SwarmEventBus, get_default_bus
    from swarm_orchestrator import SwarmOrchestrator
    from swarm_overlay import (
        build_default_provider,
        hide_swarm,
        overlay_status,
        show_swarm,
    )
    from swarm_replay import ReplayPlayer, load_session

# ─── Shared Swarm State (module singletons, bridge pattern) ──────────────────

_bus: SwarmEventBus = get_default_bus()
_orchestrator: SwarmOrchestrator = SwarmOrchestrator(bus=_bus)
_provider = build_default_provider(_bus, _orchestrator)

# ─── Wave 3: standalone overlay state file ─────────────────────────────────
# The overlay is a separate detached process (swarm_overlay_standalone.py)
# that polls swarm_state.json. swarm_tools rewrites that file on EVERY
# swarm change, in both the package folder and the bridge root, so the
# overlay finds it whichever copy of the tools the server imported.
_overlay_proc = None


def _state_file_paths():
    here = os.path.dirname(os.path.abspath(__file__))
    return [os.path.join(here, "swarm_state.json"),
            os.path.join(os.path.dirname(here), "swarm_state.json")]


def _current_visible() -> bool:
    for path in _state_file_paths():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return bool(json.load(fh).get("overlay_visible"))
        except Exception:
            continue
    return False


def _write_state_file(visible=None) -> None:
    if visible is None:
        visible = _current_visible()
    try:
        data = _provider()
    except Exception:
        data = {"agents": []}
    data["overlay_visible"] = bool(visible)
    data["written_at"] = time.time()
    for path in _state_file_paths():
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, path)
        except Exception:
            pass


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        pid = int(pid)
    except Exception:
        return False
    if os.name == "nt":
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _overlay_pid():
    for path in _state_file_paths():
        pid_file = os.path.join(os.path.dirname(path),
                                "swarm_overlay.pid")
        try:
            with open(pid_file, "r") as fh:
                return int(fh.read().strip())
        except Exception:
            continue
    return None


def _standalone_overlay_status():
    global _overlay_proc
    pid = None
    running = False
    if _overlay_proc is not None:
        if _overlay_proc.poll() is None:
            running = True
            pid = _overlay_proc.pid
        else:
            _overlay_proc = None
    if not running:
        pid = _overlay_pid()
        running = _pid_alive(pid)
        if not running:
            pid = None
    return {"created": bool(running or _current_visible()),
            "running": running, "last_error": None, "pid": pid,
            "mode": "standalone"}


_recorder_lock = threading.Lock()
_recorder: Dict[str, Any] = {"process": None, "path": None,
                             "started_at": None, "session_log": None}

_replay_lock = threading.Lock()
_replay: Dict[str, Any] = {"player": None, "path": None}


def _ok(**fields: Any) -> Dict[str, Any]:
    result = {"status": "success"}
    result.update(fields)
    return result


def _error(message: str) -> Dict[str, Any]:
    return {"status": "error", "message": message}


# ─── Agent Registration & Status ─────────────────────────────────────────────

def swarm_register_agent(agent_id: str, name: Optional[str] = None,
                         color: Optional[str] = None,
                         task_id: Optional[str] = None,
                         gui: bool = False,
                         window: Optional[str] = None) -> Dict[str, Any]:
    """Register an agent with the swarm. With task_id + gui=True the agent
    also requests a Tier A window lease through the orchestrator."""
    try:
        record = _bus.register_agent(agent_id, name=name, color=color)
        _write_state_file()
        placement = None
        if task_id is not None:
            placement = _orchestrator.attach_agent(
                task_id, agent_id, gui=gui, window=window,
                name=name, color=color)
        return _ok(agent=record, placement=placement)
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:
        return _error(f"swarm_register_agent failed: {exc}")


def swarm_update_status(agent_id: str, state: str,
                        current_action: str = "",
                        progress: Optional[float] = None,
                        anchor: Any = None) -> Dict[str, Any]:
    """Publish a status event (thinking|acting|waiting|done|error).
    `anchor` may be a window title or {"window": ..., "x": ..., "y": ...}."""
    try:
        record = _bus.publish(agent_id, state, current_action,
                              progress=progress, anchor=anchor)
        _write_state_file()
        return _ok(agent=record)
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:
        return _error(f"swarm_update_status failed: {exc}")


def swarm_get_snapshot() -> Dict[str, Any]:
    """Full swarm state: live status feed + orchestration (tiers/leases)."""
    try:
        return _ok(events=_bus.snapshot(),
                   orchestration=_orchestrator.snapshot())
    except Exception as exc:
        return _error(f"swarm_get_snapshot failed: {exc}")


def swarm_submit_task(description: str) -> Dict[str, Any]:
    """Create a swarm task that agents can be attached to."""
    try:
        task_id = _orchestrator.submit_task(description)
        _write_state_file()
        return _ok(task_id=task_id, task=_orchestrator.get_task(task_id))
    except Exception as exc:
        return _error(f"swarm_submit_task failed: {exc}")


def swarm_release_agent(agent_id: str) -> Dict[str, Any]:
    """Release an agent: frees its window lease (promoting the next queued
    agent) and removes it from the status feed."""
    try:
        released = _orchestrator.release_agent(agent_id)
        if not released:
            released = _bus.unregister_agent(agent_id)
        _write_state_file()
        return _ok(agent_id=agent_id, released=released)
    except Exception as exc:
        return _error(f"swarm_release_agent failed: {exc}")


# ─── Overlay Control ─────────────────────────────────────────────────────────

def swarm_show() -> Dict[str, Any]:
    """Start the swarm overlay as a standalone detached process (wave 3).

    The in-process Tkinter overlay could not keep its window alive inside
    the MCP server, so the visual layer now runs as its own pythonw
    process reading swarm_state.json. Falls back to reporting
    "unavailable" honestly if the process does not come up."""
    global _overlay_proc
    status = _standalone_overlay_status()
    if status["running"]:
        _write_state_file(visible=True)
        return _ok(message="swarm overlay already running (standalone)",
                   pid=status["pid"])
    here = os.path.dirname(os.path.abspath(__file__))
    script = None
    for candidate in (os.path.join(here, "swarm_overlay_standalone.py"),
                      os.path.join(os.path.dirname(here),
                                   "swarm_overlay_standalone.py")):
        if os.path.isfile(candidate):
            script = candidate
            break
    if script is None:
        return {"status": "unavailable",
                "message": "swarm_overlay_standalone.py not found beside "
                           "the bridge; install it and try again"}
    _write_state_file(visible=True)
    import sys as _sys
    pythonw = os.path.join(os.path.dirname(_sys.executable), "pythonw.exe")
    exe = pythonw if os.path.isfile(pythonw) else _sys.executable
    try:
        flags = 0
        if os.name == "nt":
            flags = 0x00000008 | 0x00000200  # DETACHED + NEW_PROCESS_GROUP
        _overlay_proc = subprocess.Popen(
            [exe, script], cwd=os.path.dirname(script),
            creationflags=flags, close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
    except Exception as exc:
        return {"status": "unavailable",
                "message": f"could not launch standalone overlay: {exc}"}
    for _ in range(30):
        time.sleep(0.1)
        status = _standalone_overlay_status()
        if status["running"]:
            return _ok(message="swarm overlay started (standalone process)",
                       pid=status["pid"])
    return {"status": "unavailable",
            "message": "standalone overlay process exited immediately; "
                       "check tkinter / interactive desktop session"}


def swarm_hide() -> Dict[str, Any]:
    """Stop the standalone swarm overlay. Safe when it is not running."""
    global _overlay_proc
    _write_state_file(visible=False)
    pid = _overlay_pid()
    stopped = False
    if _overlay_proc is not None:
        try:
            if _overlay_proc.poll() is None:
                _overlay_proc.terminate()
                stopped = True
        except Exception:
            pass
        _overlay_proc = None
    if pid and _pid_alive(pid):
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=10)
            stopped = True
        except Exception:
            pass
    try:
        hide_swarm()
    except Exception:
        pass
    return _ok(message="swarm overlay stopped" if stopped else
               "swarm overlay was not running")


# ─── Record Mode (ffmpeg gdigrab — honest stub) ──────────────────────────────

def _default_record_path() -> str:
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    base = downloads if os.path.isdir(downloads) else os.path.expanduser("~")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return os.path.join(base, f"swarm-record-{stamp}.mp4")


def swarm_begin_recording(output_path: Optional[str] = None) -> Dict[str, Any]:
    """Begin a full-screen capture of the live swarm via ffmpeg gdigrab.

    Returns status "unavailable" (not an error, and never a fake success)
    when ffmpeg is not installed on the laptop.
    """
    with _recorder_lock:
        if _recorder["process"] is not None:
            return _error("a swarm recording is already in progress")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return {
                "status": "unavailable",
                "message": ("Record Mode unavailable: ffmpeg was not found "
                            "on this machine. Install it (see INSTALL.md) "
                            "and try again. The swarm overlay itself works "
                            "without ffmpeg."),
            }
        path = output_path or _default_record_path()
        command = [
            ffmpeg, "-y",
            "-f", "gdigrab", "-framerate", "30", "-i", "desktop",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            path,
        ]
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            return _error(f"could not start ffmpeg: {exc}")
        # gdigrab fails fast when it cannot see an interactive desktop
        # (e.g. bridge running in a non-interactive session). Detect that
        # here instead of claiming a recording that is not happening.
        time.sleep(0.8)
        if process.poll() is not None:
            return _error(
                f"ffmpeg exited immediately (code {process.returncode}); "
                "gdigrab desktop capture is unavailable in this session. "
                "Record Mode needs the bridge running in the interactive "
                "desktop session.")
        _recorder.update(process=process, path=path, started_at=time.time())
        # Wave 2: record the matching JSONL session log beside the video,
        # so the exact swarm work in the clip can be replayed later with
        # swarm_replay_start. Best-effort — the video stands on its own.
        session_log = None
        try:
            candidate = os.path.splitext(path)[0] + ".jsonl"
            _bus.start_recording(candidate)
            _recorder["session_log"] = candidate
            session_log = candidate
        except Exception:
            session_log = None
        return _ok(message="swarm recording started", path=path,
                   session_log=session_log,
                   note=("landscape master; crop to 1080x1920 at edit "
                         "time — see INSTALL.md"))


def swarm_end_recording() -> Dict[str, Any]:
    """Stop the running capture and report the finished file."""
    with _recorder_lock:
        process = _recorder["process"]
        path = _recorder["path"]
        started_at = _recorder["started_at"]
        session_log = _recorder["session_log"]
        if process is None:
            return _error("no swarm recording is in progress")
        try:
            try:
                process.communicate(input=b"q", timeout=20)
            except Exception:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
        finally:
            _recorder.update(process=None, path=None, started_at=None,
                             session_log=None)
            if session_log:
                try:
                    _bus.stop_recording()
                except Exception:
                    pass
        exists = bool(path) and os.path.isfile(path)
        size = os.path.getsize(path) if exists else 0
        if not exists or size == 0:
            return _error(f"recording stopped but no file was produced "
                          f"at {path}")
        return _ok(message="swarm recording finished", path=path,
                   size_bytes=size,
                   duration_seconds=round(time.time() - (started_at or 0), 1),
                   session_log=session_log)


# ─── Window Geometry Feed (wave 2) ───────────────────────────────────────────

def swarm_list_windows() -> Dict[str, Any]:
    """List the visible desktop windows with their real rectangles
    (Windows only). Returns status "unavailable" elsewhere — the swarm
    keeps working with fallback cursor placement."""
    try:
        result = swarm_windows.list_windows()
    except Exception as exc:
        return _error(f"swarm_list_windows failed: {exc}")
    if result.get("status") != "success":
        return {"status": "unavailable",
                "message": result.get("message", ""),
                "windows": []}
    windows = result.get("windows", [])
    return _ok(windows=windows, count=len(windows))


# ─── Session Replay (wave 2) ─────────────────────────────────────────────────

def swarm_replay_start(session_log_path: str,
                       speed: float = 1.0) -> Dict[str, Any]:
    """Replay a recorded JSONL session log into the live swarm feed at
    1x / 2x / 3x speed. Playback runs on a background thread; stop it
    with swarm_replay_stop (or the swarm_stop_all kill switch)."""
    if float(speed) not in (1.0, 2.0, 3.0):
        return _error(f"speed must be 1, 2 or 3, got {speed!r}")
    with _replay_lock:
        player = _replay["player"]
        if player is not None and player.is_playing:
            return _error("a replay is already in progress; call "
                          "swarm_replay_stop first")
        try:
            events = load_session(session_log_path)
        except FileNotFoundError:
            return _error(f"session log not found: {session_log_path}")
        except ValueError as exc:
            return _error(str(exc))
        except Exception as exc:
            return _error(f"could not read session log: {exc}")
        try:
            player = ReplayPlayer(_bus, events, speed=float(speed))
        except ValueError as exc:
            return _error(str(exc))
        if player.total_events == 0:
            return _error("session log contains no replayable events")
        _replay.update(player=player, path=session_log_path)
        player.start()
        return _ok(message="swarm replay started",
                   path=session_log_path, speed=float(speed),
                   events=player.total_events)


def swarm_replay_stop() -> Dict[str, Any]:
    """Stop the running session replay (if any) and report how far it
    got. Safe to call when nothing is replaying."""
    with _replay_lock:
        player = _replay["player"]
        path = _replay["path"]
        if player is None:
            return _ok(stopped=False, message="no replay in progress")
        was_playing = player.is_playing
        player.stop()
        player.join(timeout=2.0)
        published = player.events_published
        _replay.update(player=None, path=None)
        return _ok(stopped=was_playing, path=path,
                   events_published=published)


# ─── Stats (wave 2) ──────────────────────────────────────────────────────────

def swarm_get_stats() -> Dict[str, Any]:
    """Swarm statistics: agents by state and tier, per-agent uptime,
    task totals, bus event count, and recording/replay/overlay status."""
    try:
        now = time.time()
        snap = _bus.snapshot(now=now)
        orch = _orchestrator.snapshot()
        tiers = {a["agent_id"]: a["tier"] for a in orch["agents"]}
        uptimes = [{
            "agent_id": a["agent_id"],
            "name": a["name"],
            "state": a["state"],
            "tier": tiers.get(a["agent_id"]),
            "uptime_seconds": round(now - a["registered_at"], 1),
            "event_count": a["event_count"],
        } for a in snap["agents"]]
        tasks = orch["tasks"]
        with _recorder_lock:
            video_recording = {
                "active": _recorder["process"] is not None,
                "path": _recorder["path"],
                "session_log": _recorder["session_log"],
            }
        with _replay_lock:
            player = _replay["player"]
            replay = (player.status() if player is not None
                      else {"playing": False})
            replay["path"] = _replay["path"]
        return _ok(
            generated_at=now,
            agents={
                "total": snap["agent_count"],
                "by_state": snap["counts_by_state"],
                "by_tier": orch["tier_counts"],
                "uptimes": uptimes,
            },
            tasks={
                "submitted": len(tasks),
                "active": sum(1 for t in tasks if t["status"] == "active"),
                "completed": sum(1 for t in tasks if t["status"] == "done"),
                "cancelled": sum(1 for t in tasks
                                 if t["status"] == "cancelled"),
            },
            bus={"event_count": snap["total_events"],
                 "recent_events": len(snap["recent_events"])},
            session_recording=_bus.recording_info(),
            recording=video_recording,
            replay=replay,
            overlay=_standalone_overlay_status(),
        )
    except Exception as exc:
        return _error(f"swarm_get_stats failed: {exc}")


# ─── Kill Switch (wave 2) ────────────────────────────────────────────────────

def swarm_stop_all() -> Dict[str, Any]:
    """Panic stop: release every lease and agent, mark every agent done,
    hide the overlay immediately, and stop any replay, session recording
    and video recording in progress. Works even if the overlay was never
    shown. Returns a summary of everything that was stopped."""
    summary: Dict[str, Any] = {
        "agents_released": 0,
        "leases_released": 0,
        "overlay_hidden": False,
        "replay_stopped": False,
        "session_recording_stopped": False,
        "video_recording_stopped": False,
    }
    # 1. Replay off first, so it cannot republish into a draining swarm.
    with _replay_lock:
        player = _replay["player"]
        if player is not None:
            if player.is_playing:
                player.stop()
                player.join(timeout=2.0)
                summary["replay_stopped"] = True
            _replay.update(player=None, path=None)
    # 2. Video recording off (terminate ffmpeg; a partial file may
    #    remain on disk — stopping matters more than finalising it).
    with _recorder_lock:
        process = _recorder["process"]
        if process is not None:
            try:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except Exception:
                    process.kill()
            except Exception:
                pass
            summary["video_recording_stopped"] = True
            _recorder.update(process=None, path=None, started_at=None,
                             session_log=None)
    # 3. Session (JSONL) recording off.
    try:
        summary["session_recording_stopped"] = \
            _bus.stop_recording() is not None
    except Exception:
        pass
    # 4. Mark everything done, then release every lease/agent.
    try:
        orch = _orchestrator.snapshot()
        summary["leases_released"] = len(orch["leases"])
        agent_ids = [a["agent_id"] for a in orch["agents"]]
        bus_only = [a["agent_id"] for a in _bus.snapshot()["agents"]
                    if a["agent_id"] not in agent_ids]
        for agent_id in agent_ids + bus_only:
            try:
                _bus.publish(agent_id, "done", "stopped by kill switch")
            except Exception:
                pass
        for agent_id in agent_ids:
            if _orchestrator.release_agent(agent_id):
                summary["agents_released"] += 1
        for agent_id in bus_only:
            if _bus.unregister_agent(agent_id):
                summary["agents_released"] += 1
    except Exception:
        pass
    # 5. Overlay hidden immediately — safe even if it was never shown.
    try:
        swarm_hide()
        summary["overlay_hidden"] = True
    except Exception:
        pass
    _write_state_file(visible=False)
    return _ok(message="swarm stopped", **summary)


# ─── Finale Proof Frame (wave 2) ─────────────────────────────────────────────

def _default_frame_path() -> str:
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    base = downloads if os.path.isdir(downloads) else os.path.expanduser("~")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return os.path.join(base, f"swarm-frame-{stamp}.png")


def swarm_capture_frame(path: Optional[str] = None) -> Dict[str, Any]:
    """Grab the current screen to a PNG proof frame (e.g. the finale
    moment). Needs Pillow, which is OPTIONAL: without it this returns
    status "unavailable" — never a fake success."""
    try:
        from PIL import ImageGrab
    except Exception:
        return {
            "status": "unavailable",
            "message": ("swarm_capture_frame needs Pillow (PIL), which is "
                        "not installed. It is optional — install with "
                        "'python -m pip install Pillow'. Everything else "
                        "in the swarm works without it."),
        }
    try:
        image = ImageGrab.grab()
        target = path or _default_frame_path()
        image.save(target)
        return _ok(message="frame captured", path=target,
                   size_bytes=os.path.getsize(target),
                   width=image.width, height=image.height)
    except Exception as exc:
        return _error(f"swarm_capture_frame failed: {exc}")
