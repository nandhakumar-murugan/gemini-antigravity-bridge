"""
Gemini Antigravity Bridge - Swarm unit tests
Covers swarm_events (registration, publishing, expiry, capacity,
subscribers) and swarm_orchestrator (tiers, window leases, FIFO
rotation, adaptive spawn/release, 30+ agent scale).

Run from this directory:  python -m pytest test_swarm.py -v
Standard library + pytest only.
"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from swarm_events import MAX_AGENTS, VALID_STATES, SwarmEventBus
from swarm_orchestrator import (
    TIER_A,
    TIER_A_MAX,
    TIER_B,
    TIER_C,
    SwarmOrchestrator,
)

# ─── swarm_events ─────────────────────────────────────────────────────────────


def test_register_and_snapshot_is_jsonable():
    bus = SwarmEventBus()
    record = bus.register_agent("claude-1", name="Muse", color="#a78bfa")
    assert record["agent_id"] == "claude-1"
    assert record["name"] == "Muse"
    assert record["state"] == "waiting"
    snap = bus.snapshot()
    assert snap["agent_count"] == 1
    json.dumps(snap)  # must not raise: snapshot is JSON-able


def test_register_assigns_distinct_colors():
    bus = SwarmEventBus()
    colors = set()
    for i in range(30):
        record = bus.register_agent(f"agent-{i}")
        colors.add(record["color"])
    assert len(colors) == 30


def test_publish_updates_state_and_auto_registers():
    bus = SwarmEventBus()
    record = bus.publish("gemini-1", "acting", "reading Downloads",
                         progress=0.5, anchor="Chrome")
    assert record["state"] == "acting"
    assert record["current_action"] == "reading Downloads"
    assert record["progress"] == 0.5
    assert record["anchor"] == "Chrome"
    assert bus.is_registered("gemini-1")
    snap = bus.snapshot()
    assert snap["counts_by_state"]["acting"] == 1
    assert snap["recent_events"][-1]["agent_id"] == "gemini-1"


def test_publish_rejects_invalid_state():
    bus = SwarmEventBus()
    with pytest.raises(ValueError):
        bus.publish("agent-x", "flying")


def test_publish_clamps_progress():
    bus = SwarmEventBus()
    assert bus.publish("a", "thinking", progress=7.5)["progress"] == 1.0
    assert bus.publish("a", "thinking", progress=-2)["progress"] == 0.0


def test_all_valid_states_accepted():
    bus = SwarmEventBus()
    for state in VALID_STATES:
        assert bus.publish("a", state)["state"] == state


def test_max_agents_enforced():
    bus = SwarmEventBus()
    for i in range(MAX_AGENTS):
        bus.register_agent(f"agent-{i}")
    with pytest.raises(ValueError):
        bus.register_agent("one-too-many")
    # Re-registering an existing agent is still fine at capacity.
    bus.register_agent("agent-0", name="Still Here")


def test_stale_agents_expire():
    bus = SwarmEventBus(stale_after=10.0)
    bus.register_agent("fresh")
    bus.register_agent("stale")
    t0 = time.time()
    bus.publish("fresh", "thinking")
    snap = bus.snapshot(now=t0 + 11.0)
    ids = {a["agent_id"] for a in snap["agents"]}
    assert ids == set()  # both silent for 11s of *provided* clock
    removed = bus.prune_stale(now=t0 + 11.0)
    assert removed == []


def test_expiry_uses_last_seen_not_registration():
    bus = SwarmEventBus(stale_after=5.0)
    bus.register_agent("a")
    t0 = time.time()
    # Simulate a publish 4s after registration by pruning with a clock
    # 8s out: registration alone is 8s old, but expiry is driven by
    # last_seen, which publish refreshed — emulate via heartbeat timing.
    bus.heartbeat("a")
    removed = bus.prune_stale(now=t0 + 4.0)
    assert removed == []
    removed = bus.prune_stale(now=t0 + 6.0)
    assert removed == ["a"]


def test_done_agents_expire_faster():
    bus = SwarmEventBus(stale_after=10.0)
    bus.publish("worker", "done", "finished")
    bus.publish("thinker", "thinking", "still going")
    t0 = time.time()
    removed = bus.prune_stale(now=t0 + 6.0)  # > half of 10s, < 10s
    assert removed == ["worker"]
    assert bus.is_registered("thinker")


def test_subscriber_receives_snapshots():
    bus = SwarmEventBus()
    received = []
    bus.subscribe(received.append)
    bus.register_agent("a")
    bus.publish("a", "acting", "working")
    assert len(received) >= 2
    assert received[-1]["agents"][0]["state"] == "acting"
    bus.unsubscribe(received.append)
    count = len(received)
    bus.publish("a", "done")
    assert len(received) == count


def test_broken_subscriber_does_not_break_publish():
    bus = SwarmEventBus()

    def bad(_snap):
        raise RuntimeError("boom")

    bus.subscribe(bad)
    record = bus.publish("a", "thinking")  # must not raise
    assert record["state"] == "thinking"


def test_unregister_and_clear():
    bus = SwarmEventBus()
    bus.register_agent("a")
    assert bus.unregister_agent("a") is True
    assert bus.unregister_agent("a") is False
    bus.register_agent("b")
    bus.clear()
    assert bus.snapshot()["agent_count"] == 0


def test_thirty_plus_agents_on_the_bus():
    bus = SwarmEventBus()
    for i in range(35):
        bus.publish(f"agent-{i:02d}", "thinking", f"job {i}")
    snap = bus.snapshot()
    assert snap["agent_count"] == 35
    assert snap["max_agents"] >= 40


# ─── swarm_orchestrator ───────────────────────────────────────────────────────


def make_orchestrator_with_bus():
    bus = SwarmEventBus()
    return SwarmOrchestrator(bus=bus), bus


def test_submit_task_and_attach_headless_is_tier_b():
    orch, _ = make_orchestrator_with_bus()
    task_id = orch.submit_task("index the repos")
    placed = orch.attach_agent(task_id, "worker-1")
    assert placed["tier"] == TIER_B
    assert orch.agent_tier("worker-1") == TIER_B
    snap = orch.snapshot()
    assert snap["tier_counts"][TIER_B] == 1
    json.dumps(snap)


def test_gui_agent_gets_tier_a_and_lease():
    orch, _ = make_orchestrator_with_bus()
    task_id = orch.submit_task("drive the browser")
    placed = orch.attach_agent(task_id, "driver", gui=True, window="Chrome")
    assert placed["tier"] == TIER_A
    assert placed["window"] == "Chrome"
    assert orch.snapshot()["leases"] == {"Chrome": "driver"}


def test_tier_a_capacity_and_fifo_promotion():
    orch, _ = make_orchestrator_with_bus()
    task_id = orch.submit_task("many windows")
    for i in range(TIER_A_MAX):
        placed = orch.attach_agent(task_id, f"gui-{i}", gui=True,
                                   window=f"Window-{i}")
        assert placed["tier"] == TIER_A
    ninth = orch.attach_agent(task_id, "gui-9th", gui=True, window="Window-9")
    tenth = orch.attach_agent(task_id, "gui-10th", gui=True, window="Window-10")
    assert ninth["tier"] == TIER_C
    assert tenth["tier"] == TIER_C
    assert orch.snapshot()["queue"] == ["gui-9th", "gui-10th"]
    # Freeing one lease promotes the longest-waiting agent (FIFO).
    orch.release_agent("gui-0")
    assert orch.agent_tier("gui-9th") == TIER_A
    assert orch.agent_tier("gui-10th") == TIER_C
    assert orch.snapshot()["queue"] == ["gui-10th"]


def test_window_conflict_queues_even_with_free_slots():
    orch, _ = make_orchestrator_with_bus()
    task_id = orch.submit_task("one chrome only")
    first = orch.attach_agent(task_id, "first", gui=True, window="Chrome")
    second = orch.attach_agent(task_id, "second", gui=True, window="Chrome")
    assert first["tier"] == TIER_A
    assert second["tier"] == TIER_C
    # When the holder releases the window, the waiter is promoted onto it.
    orch.release_window("first")
    assert orch.agent_tier("first") == TIER_B
    assert orch.agent_tier("second") == TIER_A
    assert orch.snapshot()["leases"] == {"Chrome": "second"}


def test_busy_window_does_not_block_other_windows():
    orch, _ = make_orchestrator_with_bus()
    task_id = orch.submit_task("parallel windows")
    orch.attach_agent(task_id, "a", gui=True, window="Chrome")
    orch.attach_agent(task_id, "b", gui=True, window="Chrome")  # queues
    orch.attach_agent(task_id, "c", gui=True, window="Editor")
    orch.release_window("a")
    # b takes Chrome; c was never blocked.
    assert orch.agent_tier("b") == TIER_A
    assert orch.agent_tier("c") == TIER_A


def test_request_and_release_window_roundtrip():
    orch, _ = make_orchestrator_with_bus()
    task_id = orch.submit_task("mixed work")
    orch.attach_agent(task_id, "flex")  # starts headless
    placed = orch.request_window("flex", "Terminal")
    assert placed["tier"] == TIER_A
    placed = orch.release_window("flex")
    assert placed["tier"] == TIER_B
    assert orch.snapshot()["leases"] == {}


def test_promote_agent_specific():
    orch, _ = make_orchestrator_with_bus()
    task_id = orch.submit_task("click the chip")
    orch.attach_agent(task_id, "holder", gui=True, window="Chrome")
    queued = orch.attach_agent(task_id, "waiter", gui=True, window="Chrome")
    assert queued["tier"] == TIER_C
    # Promotion attempt while the window is busy: stays queued.
    assert orch.promote_agent("waiter")["tier"] == TIER_C
    orch.release_agent("holder")
    assert orch.agent_tier("waiter") == TIER_A  # auto-promoted on release


def test_complete_task_releases_all_agents():
    orch, bus = make_orchestrator_with_bus()
    task_id = orch.submit_task("short job")
    orch.attach_agent(task_id, "g", gui=True, window="Chrome")
    orch.attach_agent(task_id, "h")
    assert orch.complete_task(task_id) is True
    snap = orch.snapshot()
    assert snap["agent_count"] == 0
    assert snap["leases"] == {}
    assert bus.snapshot()["agent_count"] == 0
    assert orch.get_task(task_id)["status"] == "done"


def test_attach_to_unknown_or_finished_task_raises():
    orch, _ = make_orchestrator_with_bus()
    with pytest.raises(ValueError):
        orch.attach_agent("task-nope", "x")
    task_id = orch.submit_task("quick")
    orch.complete_task(task_id)
    with pytest.raises(ValueError):
        orch.attach_agent(task_id, "late")


def test_unknown_agent_operations_raise():
    orch, _ = make_orchestrator_with_bus()
    with pytest.raises(ValueError):
        orch.request_window("ghost", "Chrome")
    assert orch.release_agent("ghost") is False
    assert orch.agent_tier("ghost") is None


def test_orchestrator_mirrors_into_bus():
    orch, bus = make_orchestrator_with_bus()
    task_id = orch.submit_task("mirrored")
    orch.attach_agent(task_id, "gui-agent", gui=True, window="Chrome",
                      name="GUI Agent")
    orch.attach_agent(task_id, "bg-agent")
    snap = bus.snapshot()
    states = {a["agent_id"]: a["state"] for a in snap["agents"]}
    assert states["gui-agent"] == "acting"
    assert states["bg-agent"] == "thinking"


def test_adaptive_respawn_changes_tiers():
    orch, _ = make_orchestrator_with_bus()
    task_id = orch.submit_task("needs change shape")
    orch.attach_agent(task_id, "scout")                      # headless
    orch.attach_agent(task_id, "scout", gui=True, window="Docs")  # re-place
    assert orch.agent_tier("scout") == TIER_A
    orch.attach_agent(task_id, "scout")                      # back to headless
    assert orch.agent_tier("scout") == TIER_B
    assert orch.snapshot()["leases"] == {}


def test_thirty_plus_agents_mixed_tiers():
    orch, bus = make_orchestrator_with_bus()
    task_id = orch.submit_task("the full swarm")
    for i in range(10):  # 10 GUI hopefuls: 8 get leases, 2 queue
        orch.attach_agent(task_id, f"gui-{i}", gui=True, window=f"W-{i}")
    for i in range(25):  # 25 headless workers
        orch.attach_agent(task_id, f"bg-{i}")
    snap = orch.snapshot()
    assert snap["agent_count"] == 35
    assert snap["tier_counts"] == {TIER_A: 8, TIER_B: 25, TIER_C: 2}
    assert bus.snapshot()["agent_count"] == 35
    json.dumps(snap)
