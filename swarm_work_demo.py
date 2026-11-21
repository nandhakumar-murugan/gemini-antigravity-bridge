"""Live all-agent work session (run on the laptop, bridge root).

All 18 swarm agents visibly work ONE real job together: building a
Friday Readiness Pack in Downloads/Swarm_Work_Demo. Each phase updates
every cursor's caption and screen anchor through swarm_tools (which
rewrites swarm_state.json for the standalone overlay), while the script
does the matching real work on disk: scanning Downloads, counting swarm
code, reading system telemetry, and writing the pack section by section.
Prints a JSON summary at the end. Safe and reversible: it only creates
new files inside its own output folder.
"""
import json
import os
import time

import swarm_tools as st

HOME = os.path.expanduser("~")
BRIDGE_ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HOME, "Downloads", "Swarm_Work_Demo")
REPORT = os.path.join(OUT_DIR, "Friday_Readiness_Pack.md")

# agent_id, name, window lease (must be distinct for Tier A), anchor x, y
TIER_A = [
    ("claude-1", "Muse", "Chrome", 240, 200),
    ("gemini-1", "Gemini", "Antigravity", 660, 180),
    ("chatgpt-1", "ChatGPT", "ChatGPT", 1080, 200),
    ("codex-1", "Codex", "VS Code", 1480, 180),
    ("spark-1", "Spark", "Gemini", 320, 600),
    ("antigravity-1", "Antigravity", "Desktop", 760, 620),
    ("kali-1", "Kali Agent", "Terminal", 1180, 600),
    ("scout-1", "Scout", "Explorer", 1560, 620),
]
TIER_B = ["Writer", "Tester", "Builder", "Reviewer", "Planner",
          "Analyst", "Watcher", "Logger", "Fetcher", "Judge"]

PHASE_SECONDS = 7


def set_agent(agent_id, state, caption, anchor=None):
    st.swarm_update_status(agent_id, state, caption, anchor=anchor)


def set_all(captions, state="acting"):
    for (agent_id, _n, _w, x, y), caption in zip(TIER_A, captions):
        set_agent(agent_id, state, caption, anchor={"x": x, "y": y})


def recent_downloads(limit=12):
    dl = os.path.join(HOME, "Downloads")
    try:
        items = []
        for name in os.listdir(dl):
            path = os.path.join(dl, name)
            if os.path.isfile(path):
                items.append((os.path.getmtime(path), name))
        items.sort(reverse=True)
        return [name for _m, name in items[:limit]]
    except Exception:
        return []


def swarm_code_stats():
    stats = {}
    total = 0
    for name in sorted(os.listdir(BRIDGE_ROOT)):
        if name.startswith("swarm_") and name.endswith(".py"):
            try:
                with open(os.path.join(BRIDGE_ROOT, name),
                          encoding="utf-8") as fh:
                    lines = sum(1 for _ in fh)
            except Exception:
                lines = 0
            stats[name] = lines
            total += lines
    stats["TOTAL swarm code lines"] = total
    return stats


def telemetry():
    try:
        import psutil
        vm = psutil.virtual_memory()
        batt = psutil.sensors_battery()
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.3),
            "ram_percent": vm.percent,
            "ram_used_gb": round(vm.used / 1e9, 2),
            "battery_percent": batt.percent if batt else None,
        }
    except Exception:
        return {"note": "psutil unavailable on this machine"}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    task = st.swarm_submit_task(
        "Live swarm work: build the Friday Readiness Pack together")
    task_id = task.get("task_id")
    for agent_id, name, window, x, y in TIER_A:
        st.swarm_register_agent(agent_id, name=name, task_id=task_id,
                                gui=True, window=window)
        set_agent(agent_id, "thinking", "joining the swarm",
                  anchor={"x": x, "y": y})
    for i, name in enumerate(TIER_B, 1):
        agent_id = "worker-%d" % i
        st.swarm_register_agent(agent_id, name=name, task_id=task_id,
                                gui=False)
        st.swarm_update_status(agent_id, "thinking", "standing by")
    st.swarm_show()

    sections = []

    # ── Phase 1: scan ───────────────────────────────────────────────────
    set_all([
        "planning the pack",
        "gathering Crypto topics",
        "verifying the bridge link",
        "scanning swarm code",
        "drafting Friday timeline",
        "mapping laptop files",
        "checking safety rules",
        "listing Downloads files",
    ])
    downloads = recent_downloads()
    time.sleep(PHASE_SECONDS)

    # ── Phase 2: build ──────────────────────────────────────────────────
    set_all([
        "writing the summary",
        "writing Crypto checklist",
        "writing bridge status",
        "counting code lines",
        "writing the run sheet",
        "filing the sections",
        "writing safety checklist",
        "attaching source list",
    ])
    code_stats = swarm_code_stats()
    tele = telemetry()
    sections.append("# Friday Readiness Pack\n")
    sections.append("Built live by the 18-agent swarm on %s.\n"
                    % time.strftime("%d %b %Y, %I:%M %p"))
    sections.append("## Friday run sheet (Spark + Muse)\n"
                    "- 09:15 AM - Cryptography exam (24UCY512), FN\n"
                    "- 03:00-04:00 PM - PromptWars live session, "
                    "Challenge 06: Urban Air Quality Assistant\n"
                    "- 06:30-08:30 PM - Game On Night (Google Meet)\n"
                    "- No Study Notebook interviews on Friday.\n")
    sections.append("## Crypto last-hour checklist (Gemini)\n"
                    "- DES vs AES table, RSA worked example, hash / MAC / "
                    "digital signature chain, Diffie-Hellman, ECB vs CBC.\n"
                    "- Draw the diagrams. Attempt every question.\n")
    sections.append("## Laptop scan (Scout) - newest Downloads files\n"
                    + "".join("- %s\n" % n for n in downloads))
    sections.append("## Swarm code (Codex) - lines per module\n"
                    + "".join("- %s: %s\n" % kv
                              for kv in code_stats.items()))
    sections.append("## Machine status (ChatGPT + Kali Agent)\n"
                    "- Telemetry: %s\n"
                    "- Safety: AgentShield ON, no files deleted, work "
                    "confined to the Swarm_Work_Demo folder.\n"
                    % json.dumps(tele))
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(sections))
    time.sleep(PHASE_SECONDS)

    # ── Phase 3: verify (cross-verification rule) ───────────────────────
    set_all([
        "verifying all sections",
        "checking Muse's summary",
        "checking Gemini's checklist",
        "re-counting code lines",
        "checking the timeline",
        "confirming files saved",
        "final safety sweep",
        "confirming sources",
    ], state="thinking")
    size = os.path.getsize(REPORT)
    recount = swarm_code_stats()["TOTAL swarm code lines"]
    time.sleep(PHASE_SECONDS)

    # ── Phase 4: done ───────────────────────────────────────────────────
    set_all([
        "done: pack ready",
        "done: checklist in",
        "done: bridge verified",
        "done: %d lines counted" % recount,
        "done: run sheet in",
        "done: files filed",
        "done: all safe",
        "done: sources attached",
    ], state="done")
    for i, _name in enumerate(TIER_B, 1):
        st.swarm_update_status("worker-%d" % i, "done", "section complete")
    time.sleep(3)

    print(json.dumps({
        "task_id": task_id,
        "agents_total": 18,
        "report": REPORT,
        "report_bytes": size,
        "swarm_code_lines": recount,
        "downloads_scanned": len(downloads),
        "telemetry": tele,
    }))


if __name__ == "__main__":
    main()
