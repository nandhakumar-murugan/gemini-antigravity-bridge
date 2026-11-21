"""
Gemini Antigravity Bridge - Swarm wave 2 unit tests
Covers identity themes, the JSONL session recorder, timed replay
(order / speeds / pause / stop), the window-geometry feed's graceful
paths and pure matchers, overlay window anchoring, and the wave 2
tools (stats, kill switch, replay tools, capture frame).

Run from this directory:  python -m pytest test_swarm_wave2.py -v
Standard library + pytest only.
"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import swarm_tools
import swarm_windows
from swarm_events import KNOWN_AGENT_THEMES, SwarmEventBus
from swarm_overlay import SwarmOverlay
from swarm_replay import ReplayPlayer, load_session, play_session

# ─── Identity themes ──────────────────────────────────────────────────────────


def test_theme_color_by_id_prefix():
    bus = SwarmEventBus()
    record = bus.register_agent("claude-1")
    assert record["color"] == KNOWN_AGENT_THEMES["claude"]["color"]
    record = bus.register_agent("chatgpt-main")
    assert record["color"] == KNOWN_AGENT_THEMES["chatgpt"]["color"]


def test_theme_display_name_for_exact_id():
    bus = SwarmEventBus()
    record = bus.register_agent("gemini")
    assert record["name"] == "Gemini"
    assert record["color"] == KNOWN_AGENT_THEMES["gemini"]["color"]


def test_theme_match_by_supplied_name():
    bus = SwarmEventBus()
    record = bus.register_agent("worker-7", name="Spark helper")
    assert record["color"] == KNOWN_AGENT_THEMES["spark"]["color"]
    assert record["name"] == "Spark helper"  # explicit name kept


def test_explicit_color_and_name_override_theme():
    bus = SwarmEventBus()
    record = bus.register_agent("codex-9", color="#123456")
    assert record["color"] == "#123456"
    record = bus.register_agent("claude-2", name="Boss")
    assert record["name"] == "Boss"
    # A name override does not block the theme colour.
    assert record["color"] == KNOWN_AGENT_THEMES["claude"]["color"]


def test_unknown_agent_keeps_auto_color():
    bus = SwarmEventBus()
    record = bus.register_agent("worker-1")
    assert record["name"] == "worker-1"
    assert record["color"].startswith("#") and len(record["color"]) == 7
    other = bus.register_agent("worker-2")
    assert other["color"] != record["color"]


# ─── Session recorder ─────────────────────────────────────────────────────────


def _record_sample_session(bus, path):
    bus.start_recording(path)
    bus.register_agent("rec-a", name="Recorder A")
    bus.publish("rec-a", "thinking", "warming up")
    bus.publish("rec-a", "acting", "doing the thing", progress=0.5)
    bus.unregister_agent("rec-a")
    return bus.stop_recording()


def test_recorder_writes_jsonl_with_monotonic_t(tmp_path):
    bus = SwarmEventBus()
    path = str(tmp_path / "session.jsonl")
    returned = _record_sample_session(bus, path)
    assert returned == path
    assert bus.stop_recording() is None  # already stopped
    with open(path, encoding="utf-8") as handle:
        events = [json.loads(line) for line in handle if line.strip()]
    types = [e["type"] for e in events]
    assert types == ["session_start", "register", "publish", "publish",
                     "unregister", "session_end"]
    stamps = [e["t"] for e in events]
    assert stamps == sorted(stamps)  # monotonic non-decreasing
    register = events[1]
    assert register["agent_id"] == "rec-a"
    assert register["name"] == "Recorder A"
    publish = events[2]
    assert publish["state"] == "thinking"


def test_recorder_double_start_raises_and_info_reports(tmp_path):
    bus = SwarmEventBus()
    path = str(tmp_path / "s.jsonl")
    info = bus.start_recording(path)
    assert info["active"] is True and info["path"] == path
    with pytest.raises(RuntimeError):
        bus.start_recording(str(tmp_path / "other.jsonl"))
    bus.publish("x", "thinking")
    info = bus.recording_info()
    assert info["events_written"] >= 2  # session_start + publish
    bus.stop_recording()
    assert bus.recording_info()["active"] is False


def test_recorder_captures_theme_identity(tmp_path):
    bus = SwarmEventBus()
    path = str(tmp_path / "themed.jsonl")
    bus.start_recording(path)
    bus.register_agent("gemini")
    bus.stop_recording()
    events = load_session(path)
    register = next(e for e in events if e["type"] == "register")
    assert register["name"] == "Gemini"
    assert register["color"] == KNOWN_AGENT_THEMES["gemini"]["color"]


# ─── Replay ───────────────────────────────────────────────────────────────────


def _events(*specs):
    """Build replay events from (t, type, agent_id, state) tuples."""
    out = []
    for t, kind, agent_id, state in specs:
        event = {"t": t, "type": kind, "agent_id": agent_id}
        if kind == "publish":
            event["state"] = state
        out.append(event)
    return out


@pytest.mark.parametrize("speed", [1.0, 2.0, 3.0])
def test_replay_republishes_in_order_at_each_speed(speed):
    source = _events(
        (0.0, "register", "w1", None),
        (0.0, "publish", "w1", "thinking"),
        (0.0, "publish", "w1", "acting"),
        (0.0, "publish", "w1", "done"),
    )
    target = SwarmEventBus()
    player = ReplayPlayer(target, source, speed=speed)
    player.start()
    player.join(timeout=5.0)
    assert not player.is_playing
    assert player.events_published == 4
    snap = target.snapshot()
    assert snap["agents"][0]["state"] == "done"
    states = [e["state"] for e in snap["recent_events"]]
    assert states == ["thinking", "acting", "done"]  # original order


def test_replay_pause_freezes_timeline():
    source = _events(
        (0.0, "register", "p1", None),
        (0.0, "publish", "p1", "thinking"),
        (0.6, "publish", "p1", "acting"),
        (1.2, "publish", "p1", "done"),
    )
    target = SwarmEventBus()
    player = ReplayPlayer(target, source, speed=1.0)
    player.start()
    deadline = time.time() + 2.0
    while time.time() < deadline:
        snap = target.snapshot()
        if snap["agents"] and snap["agents"][0]["state"] == "thinking" \
                and player.events_published >= 2:
            break
        time.sleep(0.01)
    player.pause()
    published_at_pause = player.events_published
    time.sleep(0.8)  # well past the 0.6s gap to the next event
    assert player.events_published == published_at_pause
    assert target.snapshot()["agents"][0]["state"] == "thinking"
    player.resume()
    player.join(timeout=5.0)
    assert target.snapshot()["agents"][0]["state"] == "done"


def test_replay_stop_halts_playback():
    source = _events(
        (0.0, "register", "s1", None),
        (0.0, "publish", "s1", "thinking"),
        (30.0, "publish", "s1", "done"),
    )
    target = SwarmEventBus()
    player = ReplayPlayer(target, source, speed=1.0)
    player.start()
    deadline = time.time() + 2.0
    while time.time() < deadline and player.events_published < 2:
        time.sleep(0.01)
    player.stop()
    player.join(timeout=2.0)
    assert not player.is_playing
    assert player.events_published == 2  # the 30s-late event never fired


def test_replay_rejects_bad_speed():
    with pytest.raises(ValueError):
        ReplayPlayer(SwarmEventBus(), [], speed=2.5)
    player = ReplayPlayer(SwarmEventBus(), [], speed=1.0)
    with pytest.raises(ValueError):
        player.set_speed(4.0)
    player.set_speed(3.0)
    assert player.speed == 3.0


def test_load_session_missing_and_corrupt(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_session(str(tmp_path / "nope.jsonl"))
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"type": "register", "agent_id": "a"}\nnot json\n',
                   encoding="utf-8")
    with pytest.raises(ValueError):
        load_session(str(bad))


def test_record_then_replay_roundtrip(tmp_path):
    source_bus = SwarmEventBus()
    path = str(tmp_path / "roundtrip.jsonl")
    _record_sample_session(source_bus, path)
    target = SwarmEventBus()
    player = play_session(target, path, speed=3.0)
    player.join(timeout=5.0)
    assert not player.is_playing
    assert player.events_published >= 4
    # rec-a was unregistered at the end of the recorded session.
    assert target.snapshot()["agent_count"] == 0


# ─── Window geometry feed ─────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32",
                    reason="graceful-unavailable path is for non-Windows")
def test_list_windows_unavailable_off_windows():
    result = swarm_windows.list_windows()
    assert result["status"] == "unavailable"
    assert result["windows"] == []


def _fake_windows():
    return [
        {"title": "Settings", "rect": {"x": 0, "y": 0, "w": 800, "h": 600},
         "is_foreground": False},
        {"title": "Google Chrome - GitHub",
         "rect": {"x": 100, "y": 100, "w": 400, "h": 300},
         "is_foreground": True},
        {"title": "Chrome", "rect": {"x": 50, "y": 50, "w": 200, "h": 200},
         "is_foreground": False},
    ]


def test_find_window_matching_rules():
    windows = _fake_windows()
    # Exact match beats a partial match.
    assert swarm_windows.find_window("Chrome", windows)["title"] == "Chrome"
    # Substring match finds the longer title.
    found = swarm_windows.find_window("github", windows)
    assert found["title"] == "Google Chrome - GitHub"
    # Case-insensitive; no match and empty query return None.
    assert swarm_windows.find_window("SETTINGS", windows) is not None
    assert swarm_windows.find_window("nope", windows) is None
    assert swarm_windows.find_window("", windows) is None


def test_anchor_point_uses_real_rect_and_offsets_per_index():
    windows = _fake_windows()
    point0 = swarm_windows.anchor_point_for_title("Chrome", windows, 0)
    # "Chrome" rect is x=50,y=50,w=200,h=200 -> centre (150, 150);
    # index 0 offset is (-51, -30).
    assert point0 == (99.0, 120.0)
    point1 = swarm_windows.anchor_point_for_title("Chrome", windows, 1)
    assert point1 != point0  # same window, different agent -> no stacking
    assert swarm_windows.anchor_point_for_title("Missing", windows) is None


def test_overlay_anchor_resolves_window_title():
    overlay = SwarmOverlay(lambda: {"agents": []})
    overlay._screen_w, overlay._screen_h = 1920, 1080
    overlay._windows_cache = _fake_windows()
    agent = {"agent_id": "a", "anchor": "Google Chrome - GitHub"}
    x, y = overlay._anchor_target(agent, 0, 1)
    # Rect centre is (300, 250); index-0 offset (-51, -30) -> (249, 220).
    assert (x, y) == (249.0, 220.0)
    # Dict anchor with a window title resolves the same way.
    agent2 = {"agent_id": "b", "anchor": {"window": "Settings"}}
    x2, y2 = overlay._anchor_target(agent2, 0, 1)
    assert (x2, y2) == (349.0, 270.0)
    # Unknown window falls back to an in-bounds spread point.
    agent3 = {"agent_id": "c", "anchor": "No Such Window"}
    x3, y3 = overlay._anchor_target(agent3, 2, 3)
    assert 0 <= x3 <= 1920 and 0 <= y3 <= 1080


# ─── Wave 2 tools (shared default bus — reset via the kill switch) ───────────


def test_replay_start_missing_file_returns_error_dict():
    result = swarm_tools.swarm_replay_start("/nonexistent/nope.jsonl")
    assert result["status"] == "error"
    assert "not found" in result["message"]


def test_stats_shape_and_uptime():
    swarm_tools.swarm_stop_all()
    task = swarm_tools.swarm_submit_task("stats job")
    assert task["status"] == "success"
    placed = swarm_tools.swarm_register_agent(
        "claude-1", task_id=task["task_id"], gui=True, window="Chrome")
    assert placed["status"] == "success"
    swarm_tools.swarm_update_status("claude-1", "acting", "measuring")
    stats = swarm_tools.swarm_get_stats()
    assert stats["status"] == "success"
    assert stats["agents"]["by_state"]["acting"] == 1
    assert stats["agents"]["by_tier"]["A"] == 1
    uptime = stats["agents"]["uptimes"][0]
    assert uptime["agent_id"] == "claude-1"
    assert uptime["uptime_seconds"] >= 0
    assert stats["tasks"]["submitted"] >= 1
    assert stats["bus"]["event_count"] >= 2
    assert stats["recording"]["active"] is False
    assert stats["session_recording"]["active"] is False
    json.dumps(stats)  # stats must stay JSON-able
    swarm_tools.swarm_stop_all()


def test_stop_all_releases_everything_without_overlay():
    swarm_tools.swarm_stop_all()
    task = swarm_tools.swarm_submit_task("panic drill")
    swarm_tools.swarm_register_agent("gui-1", task_id=task["task_id"],
                                     gui=True, window="Chrome")
    swarm_tools.swarm_register_agent("bus-only-1")  # no task, bus only
    before = swarm_tools.swarm_get_snapshot()
    assert before["orchestration"]["leases"] == {"Chrome": "gui-1"}
    result = swarm_tools.swarm_stop_all()
    assert result["status"] == "success"
    assert result["leases_released"] == 1
    assert result["agents_released"] == 2
    assert result["overlay_hidden"] is True  # never shown — still fine
    after = swarm_tools.swarm_get_snapshot()
    assert after["events"]["agent_count"] == 0
    assert after["orchestration"]["leases"] == {}


def test_tools_replay_roundtrip_and_stop():
    swarm_tools.swarm_stop_all()
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        bus = SwarmEventBus()
        bus.start_recording(path)
        bus.register_agent("replay-bot-1")
        bus.publish("replay-bot-1", "acting", "from the log")
        bus.publish("replay-bot-1", "done", "logged done")
        bus.stop_recording()
        started = swarm_tools.swarm_replay_start(path, speed=3)
        assert started["status"] == "success"
        deadline = time.time() + 3.0
        seen = {}
        while time.time() < deadline:
            snap = swarm_tools.swarm_get_snapshot()
            seen = {a["agent_id"]: a["state"]
                    for a in snap["events"]["agents"]}
            if seen.get("replay-bot-1") == "done":
                break
            time.sleep(0.02)
        assert seen.get("replay-bot-1") == "done"
        stopped = swarm_tools.swarm_replay_stop()
        assert stopped["status"] == "success"
    finally:
        swarm_tools.swarm_stop_all()
        os.unlink(path)


def test_capture_frame_honest_without_pillow():
    try:
        import PIL  # noqa: F401
        pillow_available = True
    except ImportError:
        pillow_available = False
    result = swarm_tools.swarm_capture_frame()
    if not pillow_available:
        assert result["status"] == "unavailable"
        assert "Pillow" in result["message"]
    else:
        # With Pillow present a headless grab may still fail — but it
        # must never report a fake success without a real file.
        assert result["status"] in ("success", "error", "unavailable")
        if result["status"] == "success":
            assert os.path.isfile(result["path"])
            os.unlink(result["path"])


def test_list_windows_tool_shape():
    result = swarm_tools.swarm_list_windows()
    if sys.platform == "win32":
        assert result["status"] in ("success", "unavailable")
    else:
        assert result["status"] == "unavailable"
        assert result["windows"] == []
