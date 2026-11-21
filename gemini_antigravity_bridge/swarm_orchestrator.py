"""
Gemini Antigravity Bridge - Agent Swarm Orchestrator
Task intake, agent registry and window-lease management for the swarm.

Implements the spec's three tiers:
  Tier A - GUI-active agents. Each holds a lease on one window; at most
           TIER_A_MAX agents hold leases at once. Leases rotate FIFO:
           when a lease frees, the longest-waiting queued agent whose
           window is free is promoted automatically.
  Tier B - Headless agents (shell / file / API / research). Unlimited;
           they never touch the mouse, so they scale freely.
  Tier C - Queued agents. Registered and visible, waiting for a Tier A
           lease (window busy or all Tier A slots taken).

Adaptive by design: there is no fixed roster. Tasks are submitted, agents
are attached / spawned / released as the task's needs change, and the
orchestrator rebalances tiers on every change.

Pure logic — no GUI imports, no I/O. Unit-testable in isolation.
If a SwarmEventBus is supplied, agent lifecycle and tier changes are
mirrored into it so the overlay sees one consistent picture.
"""

import threading
import time
import uuid
from typing import Any, Dict, List, Optional

TIER_A = "A"
TIER_B = "B"
TIER_C = "C"
TIER_A_MAX = 8

TASK_ACTIVE = "active"
TASK_DONE = "done"
TASK_CANCELLED = "cancelled"


class SwarmOrchestrator:
    """Registry of tasks, agents, tiers and per-window leases."""

    def __init__(self, bus: Any = None, tier_a_max: int = TIER_A_MAX):
        self._lock = threading.RLock()
        self._bus = bus
        self._tier_a_max = int(tier_a_max)
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._leases: Dict[str, str] = {}        # window title -> agent_id
        self._queue: List[str] = []              # Tier C agent ids, FIFO

    # ─── Task Intake ──────────────────────────────────────────────────────────

    def submit_task(self, description: str) -> str:
        """Create a task record and return its task_id."""
        task_id = "task-" + uuid.uuid4().hex[:10]
        with self._lock:
            self._tasks[task_id] = {
                "task_id": task_id,
                "description": (description or "")[:300],
                "status": TASK_ACTIVE,
                "created_at": time.time(),
                "finished_at": None,
                "agent_ids": [],
            }
        return task_id

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def complete_task(self, task_id: str) -> bool:
        """Mark a task done and release every agent attached to it."""
        return self._finish_task(task_id, TASK_DONE)

    def cancel_task(self, task_id: str) -> bool:
        """Mark a task cancelled and release every agent attached to it."""
        return self._finish_task(task_id, TASK_CANCELLED)

    def _finish_task(self, task_id: str, status: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task["status"] = status
            task["finished_at"] = time.time()
            agent_ids = list(task["agent_ids"])
        for agent_id in agent_ids:
            self.release_agent(agent_id)
        return True

    # ─── Agent Lifecycle (adaptive spawn / release) ───────────────────────────

    def attach_agent(self, task_id: str, agent_id: str,
                     gui: bool = False, window: Optional[str] = None,
                     name: Optional[str] = None,
                     color: Optional[str] = None) -> Dict[str, Any]:
        """Spawn an agent into a task and place it in a tier.

        gui=False -> Tier B (headless). gui=True -> requests a Tier A lease
        on `window`; granted immediately if a slot and the window are free,
        otherwise the agent lands in Tier C (queued, FIFO).
        Re-attaching an existing agent updates its placement.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise ValueError(f"unknown task_id: {task_id}")
            if task["status"] != TASK_ACTIVE:
                raise ValueError(f"task {task_id} is {task['status']}")
            agent = self._agents.get(agent_id)
            if agent is None:
                agent = {
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "tier": TIER_B,
                    "window": None,
                    "wants_window": None,
                    "attached_at": time.time(),
                }
                self._agents[agent_id] = agent
                if agent_id not in task["agent_ids"]:
                    task["agent_ids"].append(agent_id)
            else:
                self._strip_placement(agent)

            if gui:
                agent["wants_window"] = window
                if not self._try_grant_lease(agent):
                    agent["tier"] = TIER_C
                    if agent_id not in self._queue:
                        self._queue.append(agent_id)
            else:
                agent["wants_window"] = None
                agent["tier"] = TIER_B
            result = self._public_agent(agent)

        self._mirror_register(agent_id, name, color)
        self._mirror_state(agent_id)
        return result

    def release_agent(self, agent_id: str) -> bool:
        """Remove an agent entirely, freeing its lease and promoting the
        longest-waiting queued agent(s) that can now be served."""
        with self._lock:
            agent = self._agents.pop(agent_id, None)
            if agent is None:
                return False
            self._strip_placement(agent)
            task = self._tasks.get(agent["task_id"])
            if task and agent_id in task["agent_ids"]:
                task["agent_ids"].remove(agent_id)
            self._promote_waiting()
        self._mirror_unregister(agent_id)
        return True

    # ─── Window Leases ────────────────────────────────────────────────────────

    def request_window(self, agent_id: str, window: str) -> Dict[str, Any]:
        """An existing agent asks for GUI control of `window`.

        Granted -> Tier A. Denied (window leased by another agent, or all
        Tier A slots taken) -> Tier C, queued FIFO.
        """
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                raise ValueError(f"unknown agent_id: {agent_id}")
            self._strip_placement(agent)
            agent["wants_window"] = window
            if not self._try_grant_lease(agent):
                agent["tier"] = TIER_C
                if agent_id not in self._queue:
                    self._queue.append(agent_id)
            result = self._public_agent(agent)
        self._mirror_state(agent_id)
        return result

    def release_window(self, agent_id: str) -> Dict[str, Any]:
        """Give up the GUI lease (agent drops to Tier B) and promote the
        next waiting agent if one can now be served."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                raise ValueError(f"unknown agent_id: {agent_id}")
            self._strip_placement(agent)
            agent["wants_window"] = None
            agent["tier"] = TIER_B
            self._promote_waiting()
            result = self._public_agent(agent)
        self._mirror_state(agent_id)
        return result

    def promote_agent(self, agent_id: str) -> Dict[str, Any]:
        """Try to promote one specific queued agent now (e.g. its strip
        chip was clicked). Succeeds only if its window is free and a
        Tier A slot is open; otherwise it keeps its queue position."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                raise ValueError(f"unknown agent_id: {agent_id}")
            if agent["tier"] == TIER_C and self._try_grant_lease(agent):
                if agent_id in self._queue:
                    self._queue.remove(agent_id)
            result = self._public_agent(agent)
        self._mirror_state(agent_id)
        return result

    def agent_tier(self, agent_id: str) -> Optional[str]:
        with self._lock:
            agent = self._agents.get(agent_id)
            return agent["tier"] if agent else None

    # ─── Lease Internals ──────────────────────────────────────────────────────

    def _strip_placement(self, agent: Dict[str, Any]) -> None:
        """Remove the agent's lease / queue entry (caller holds the lock)."""
        window = agent.get("window")
        if window and self._leases.get(window) == agent["agent_id"]:
            del self._leases[window]
        agent["window"] = None
        if agent["agent_id"] in self._queue:
            self._queue.remove(agent["agent_id"])

    def _try_grant_lease(self, agent: Dict[str, Any]) -> bool:
        """Grant a Tier A lease if a slot and the wanted window are free."""
        window = agent.get("wants_window")
        if window is None:
            return False
        holder = self._leases.get(window)
        if holder is not None and holder != agent["agent_id"]:
            return False
        tier_a_count = sum(1 for a in self._agents.values()
                           if a["tier"] == TIER_A)
        if agent["tier"] != TIER_A and tier_a_count >= self._tier_a_max:
            return False
        self._leases[window] = agent["agent_id"]
        agent["window"] = window
        agent["tier"] = TIER_A
        return True

    def _promote_waiting(self) -> None:
        """FIFO promotion: walk the queue in order and grant every agent
        that can be served (free window + free Tier A slot). Agents whose
        window is still busy keep waiting without blocking the others."""
        still_waiting: List[str] = []
        for agent_id in self._queue:
            agent = self._agents.get(agent_id)
            if agent is None:
                continue
            if self._try_grant_lease(agent):
                self._mirror_state(agent_id)
            else:
                still_waiting.append(agent_id)
        self._queue = still_waiting

    # ─── Event-Bus Mirroring (optional) ───────────────────────────────────────

    def _mirror_register(self, agent_id: str, name: Optional[str],
                         color: Optional[str]) -> None:
        if self._bus is None:
            return
        try:
            self._bus.register_agent(agent_id, name=name, color=color)
        except Exception:
            pass

    def _mirror_unregister(self, agent_id: str) -> None:
        if self._bus is None:
            return
        try:
            self._bus.unregister_agent(agent_id)
        except Exception:
            pass

    def _mirror_state(self, agent_id: str) -> None:
        if self._bus is None:
            return
        try:
            tier = self.agent_tier(agent_id)
            if tier == TIER_A:
                self._bus.publish(agent_id, "acting", "working on screen")
            elif tier == TIER_C:
                self._bus.publish(agent_id, "waiting", "queued for a window")
            elif tier == TIER_B:
                self._bus.publish(agent_id, "thinking", "working in background")
        except Exception:
            pass

    # ─── Snapshots ────────────────────────────────────────────────────────────

    @staticmethod
    def _public_agent(agent: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "agent_id": agent["agent_id"],
            "task_id": agent["task_id"],
            "tier": agent["tier"],
            "window": agent["window"],
            "wants_window": agent["wants_window"],
            "attached_at": agent["attached_at"],
        }

    def snapshot(self) -> Dict[str, Any]:
        """Full orchestration state as a JSON-able dict."""
        with self._lock:
            agents = [self._public_agent(a) for a in self._agents.values()]
            counts = {TIER_A: 0, TIER_B: 0, TIER_C: 0}
            for agent in agents:
                counts[agent["tier"]] += 1
            return {
                "generated_at": time.time(),
                "tier_a_max": self._tier_a_max,
                "tier_counts": counts,
                "agent_count": len(agents),
                "agents": agents,
                "leases": dict(self._leases),
                "queue": list(self._queue),
                "tasks": [dict(t) for t in self._tasks.values()],
            }
