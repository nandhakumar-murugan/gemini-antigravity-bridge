"""One-shot swarm demo launcher (run on the laptop, bridge root).

Registers the demo swarm through swarm_tools (which rewrites
swarm_state.json on every change) and starts the standalone overlay.
Prints a JSON summary. Safe to re-run: registrations are idempotent
on a fresh bus and swarm_show returns 'already running' if the
overlay process is alive.
"""
import json

import swarm_tools as st

# Each Tier A agent needs its OWN window lease (one holder per window),
# otherwise the orchestrator queues it in Tier C.
TIER_A = [
    ("claude-1", "Muse", "coordinating the swarm", "Chrome"),
    ("gemini-1", "Gemini", "building the Crypto guide", "Antigravity"),
    ("chatgpt-1", "ChatGPT", "checking the bridge", "ChatGPT"),
    ("codex-1", "Codex", "reviewing code", "VS Code"),
    ("spark-1", "Spark", "preparing the briefing", "Gemini"),
    ("antigravity-1", "Antigravity", "planning next steps", "Desktop"),
    ("kali-1", "Kali Agent", "running security checks", "Terminal"),
    ("scout-1", "Scout", "searching files", "Explorer"),
]
TIER_B = ["Writer", "Tester", "Builder", "Reviewer", "Planner",
          "Analyst", "Watcher", "Logger", "Fetcher", "Judge"]


def main():
    task = st.swarm_submit_task(
        "Live swarm cursor demo - all agents working together")
    task_id = task.get("task_id")
    placed = {}
    for agent_id, name, caption, window in TIER_A:
        reg = st.swarm_register_agent(agent_id, name=name, task_id=task_id,
                                      gui=True, window=window)
        placed[agent_id] = (reg.get("placement") or {}).get("tier")
        st.swarm_update_status(agent_id, "acting", caption)
    for i, name in enumerate(TIER_B, 1):
        agent_id = "worker-%d" % i
        st.swarm_register_agent(agent_id, name=name, task_id=task_id,
                                gui=False)
        st.swarm_update_status(agent_id,
                               "thinking" if i % 2 else "acting",
                               "working in background")
    show = st.swarm_show()
    snap = st.swarm_get_snapshot()
    print(json.dumps({
        "task_id": task_id,
        "tier_a": placed,
        "agents_total": snap.get("events", {}).get("agent_count"),
        "show": show,
    }))


if __name__ == "__main__":
    main()
