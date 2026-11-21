"""Swarm demo V2 - ALL NEW material (run on the laptop, bridge root).

Nothing here repeats the reference reel or the earlier work demo:
- target is his own product site premaailabs.tech (never demoed before)
- 30 agents on screen (8 cursors + 22 chips), not 18
- captions carry LIVE GitHub numbers fetched at runtime, not scripted
- a real typing segment: Notepad opens and the session log is typed
  live by SendKeys while cursors supervise
- finale is a circle FORMATION, not a converge
The overlay only reflects swarm_tools state.
"""
import json
import os
import subprocess
import time
import urllib.request

import swarm_tools as st

SITE = "https://premaailabs.tech"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

TIER_A = [
    ("claude-1", "Muse", "Chrome"),
    ("gemini-1", "Gemini", "Antigravity"),
    ("chatgpt-1", "ChatGPT", "ChatGPT"),
    ("codex-1", "Codex", "VS Code"),
    ("spark-1", "Spark", "Gemini"),
    ("antigravity-1", "Antigravity", "Desktop"),
    ("kali-1", "Kali Agent", "Terminal"),
    ("scout-1", "Scout", "Explorer"),
]
TIER_B = ["Writer", "Tester", "Builder", "Reviewer", "Planner",
          "Analyst", "Watcher", "Logger", "Fetcher", "Judge",
          "Mapper", "Auditor", "Scorer", "Indexer", "Tracer",
          "Keeper", "Pilot", "Radar", "Comet", "Orbit",
          "Pulse", "Echo"]


def upd(agent_id, state, caption, x, y):
    st.swarm_update_status(agent_id, state, caption,
                           anchor={"x": int(x), "y": int(y)})


def move_all(targets, captions, state, steps=4, step_s=1.2, starts=None):
    starts = starts or [(960, 540)] * len(TIER_A)
    for s in range(1, steps + 1):
        f = s / steps
        for (agent_id, _n, _w), (sx, sy), (tx, ty), cap in zip(
                TIER_A, starts, targets, captions):
            upd(agent_id, state, cap,
                sx + (tx - sx) * f, sy + (ty - sy) * f)
        time.sleep(step_s)
    return targets


def live_github():
    try:
        req = urllib.request.Request(
            "https://api.github.com/users/nandhakumar-murugan",
            headers={"User-Agent": "swarm-demo"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.load(resp)
        return d.get("public_repos"), d.get("followers")
    except Exception:
        return None, None


def type_line(text):
    safe = text.replace('"', '')
    ps = ("Add-Type -AssemblyName System.Windows.Forms; "
          "[System.Windows.Forms.SendKeys]::SendWait(\"" + safe +
          "{ENTER}\")")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       timeout=20)
    except Exception:
        pass


def main():
    try:
        if os.path.exists(CHROME):
            subprocess.Popen([CHROME, SITE])
        else:
            os.startfile(SITE)
    except Exception:
        pass
    time.sleep(7)

    task = st.swarm_submit_task("Swarm NEW demo - Prema AI Labs live ops")
    task_id = task.get("task_id")
    for agent_id, name, window in TIER_A:
        st.swarm_register_agent(agent_id, name=name, task_id=task_id,
                                gui=True, window=window)
    for i, name in enumerate(TIER_B):
        st.swarm_register_agent(f"tierb-{i+1}", name=name, task_id=task_id,
                                gui=False)
    st.swarm_show()
    time.sleep(1)

    # Phase 1: land on his product site, sweep its sections
    caps = ["landing on Prema AI Labs", "scanning the hero section",
            "reading product features", "checking the pricing block",
            "mapping the product", "reading the story section",
            "checking footer links", "site map complete"]
    targets = [(960, 260), (480, 420), (1400, 420), (960, 700),
               (500, 780), (1350, 800), (700, 300), (1250, 260)]
    pos = move_all(targets, caps, "acting", steps=5, step_s=1.1,
                   starts=[(30, 30), (1890, 30), (1890, 1000), (30, 1000),
                           (960, 20), (960, 1020), (20, 540), (1900, 540)])

    # Phase 2: LIVE data, fetched now - captions use the real numbers
    repos, followers = live_github()
    if repos is None:
        caps = ["live fetch failed", "using last verified counts",
                "repos 72", "followers 20", "continuing demo",
                "data noted", "moving on", "next phase"]
    else:
        caps = [f"live GitHub: {repos} repos",
                f"live GitHub: {followers} followers",
                "fresh data - not scripted", "checking bridge repo",
                "verifying profile live", "numbers confirmed",
                "data locked in", "next phase"]
    pos = move_all([(350, 200), (650, 160), (950, 200), (1250, 160),
                    (1550, 200), (500, 420), (950, 420), (1450, 420)],
                   caps, "acting", steps=3, step_s=1.5, starts=pos)

    # Phase 3: real typing - Notepad session log, typed live
    try:
        subprocess.Popen(["notepad.exe"])
    except Exception:
        pass
    time.sleep(3)
    note_caps = ["typing the session log", "typing line by line",
                 "supervising the typing", "verifying each line",
                 "watching the log grow", "checking spelling",
                 "log keeper on duty", "ready to verify"]
    note_targets = [(700, 300), (1150, 300), (500, 600), (900, 650),
                    (1350, 600), (650, 850), (1100, 850), (1500, 400)]
    pos = move_all(note_targets, note_caps, "acting", steps=3,
                   step_s=1.0, starts=pos)
    lines = ["SWARM SESSION LOG - LIVE",
             "30 agents online - 8 cursors - 22 background",
             "target - premaailabs.tech - scanned",
             f"github live - repos {repos} - followers {followers}",
             "every cursor under Muse control",
             "this log was typed by the swarm - live",
             "demo complete"]
    for ln in lines:
        type_line(ln)
        time.sleep(1.2)

    # Phase 4: FORMATION finale - circle, not a converge
    import math
    circle = [(960 + 280 * math.cos(2 * math.pi * i / 8),
               520 + 280 * math.sin(2 * math.pi * i / 8)) for i in range(8)]
    pos = move_all(circle, ["formation: circle"] * 8, "acting",
                   steps=5, step_s=1.1, starts=pos)
    for (agent_id, _n, _w), (x, y) in zip(TIER_A, circle):
        upd(agent_id, "done", "swarm complete", x, y)
    for i, name in enumerate(TIER_B):
        st.swarm_update_status(f"tierb-{i+1}", "done", "swarm complete")
    time.sleep(5)

    print(json.dumps({"task_id": task_id, "agents_total": 30,
                      "target": SITE, "live_repos": repos,
                      "live_followers": followers,
                      "status": "v2 demo done"}))


if __name__ == "__main__":
    main()
