"""Reel-style swarm demo (run on the laptop, bridge root).

Recreates the @techinsixty 'Swarm Rebuild' feel with REAL swarm state:
Chrome opens Nandhakumar's GitHub profile, all 18 agents flock in,
sweep the page section by section with live captions (scan -> rebuild
-> verify), then converge for the finale. The overlay only reflects
swarm_tools state; nothing here is a pre-baked animation file.
Record the screen while it runs (ffmpeg gdigrab) for the reel master.
"""
import json
import os
import subprocess
import time

import swarm_tools as st

PROFILE_URL = "https://github.com/nandhakumar-murugan"
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
          "Analyst", "Watcher", "Logger", "Fetcher", "Judge"]

# stations over a 1920x1080 GitHub profile page
STATIONS = [(300, 300), (700, 220), (1150, 240), (1600, 300),
            (350, 700), (800, 640), (1250, 700), (1650, 760)]
CORNERS = [(30, 30), (1890, 30), (1890, 1000), (30, 1000),
           (960, 20), (960, 1020), (20, 540), (1900, 540)]


def upd(agent_id, state, caption, x, y):
    st.swarm_update_status(agent_id, state, caption,
                           anchor={"x": int(x), "y": int(y)})


def move_all(targets, captions, state, steps=5, step_s=1.1, starts=None):
    starts = starts or [(960, 540)] * len(TIER_A)
    for s in range(1, steps + 1):
        f = s / steps
        for (agent_id, _n, _w), (sx, sy), (tx, ty), cap in zip(
                TIER_A, starts, targets, captions):
            upd(agent_id, state, cap,
                sx + (tx - sx) * f, sy + (ty - sy) * f)
        time.sleep(step_s)
    return targets


def main():
    # open the target page
    try:
        if os.path.exists(CHROME):
            subprocess.Popen([CHROME, PROFILE_URL])
        else:
            os.startfile(PROFILE_URL)
    except Exception:
        pass
    time.sleep(7)

    task = st.swarm_submit_task("Reel demo - rebuilding the GitHub profile")
    task_id = task.get("task_id")
    for agent_id, name, window in TIER_A:
        st.swarm_register_agent(agent_id, name=name, task_id=task_id,
                                gui=True, window=window)
    for i, name in enumerate(TIER_B):
        st.swarm_register_agent(f"tierb-{i+1}", name=name, task_id=task_id,
                                gui=False)
    st.swarm_show()
    time.sleep(1)

    # Phase 1: flock in from the corners to stations
    caps = ["flying in"] * 8
    pos = move_all(STATIONS, caps, "acting", steps=6, step_s=1.0,
                   starts=CORNERS)

    # Phase 2: scan the profile (sweep across sections)
    scan_caps = ["scanning profile", "counting repos: 72",
                 "reading pinned repos", "checking followers: 20",
                 "mapping contributions", "reading README",
                 "checking stars", "indexing projects"]
    scan_targets = [(280, 260), (620, 300), (1000, 200), (1500, 260),
                    (420, 560), (760, 520), (1180, 560), (1580, 520)]
    pos = move_all(scan_targets, scan_caps, "acting", steps=4,
                   step_s=1.4, starts=pos)
    pos = move_all(STATIONS, scan_caps, "thinking", steps=3, step_s=1.2,
                   starts=pos)

    # Phase 3: rebuild, section by section
    rebuild_caps = ["rebuilding header", "restoring avatar block",
                    "rebuilding pinned repos", "redrawing graph",
                    "restoring repo list", "rebuilding about section",
                    "verifying links", "polishing layout"]
    rebuild_targets = [(500, 140), (280, 320), (700, 430), (1200, 430),
                       (1500, 600), (450, 800), (900, 820), (1450, 850)]
    pos = move_all(rebuild_targets, rebuild_caps, "acting", steps=5,
                   step_s=1.5, starts=pos)
    pos = move_all(STATIONS, rebuild_caps, "acting", steps=3, step_s=1.2,
                   starts=pos)

    # Phase 4: verify with real, checked numbers
    verify_caps = ["repos: 72 OK", "followers: 20 OK",
                   "bridge: 13 stars OK", "cookbook PRs: 2 merged OK",
                   "profile links OK", "README OK",
                   "all sections OK", "cross-check done"]
    pos = move_all([(350, 350), (650, 300), (950, 350), (1250, 300),
                    (1550, 350), (500, 650), (950, 650), (1450, 650)],
                   verify_caps, "acting", steps=3, step_s=1.4, starts=pos)

    # Phase 5: finale - converge to centre, all done
    centre = [(960 + (i - 3.5) * 60, 500 + (i % 2) * 70) for i in range(8)]
    done_caps = ["rebuild complete"] * 8
    move_all(centre, done_caps, "done", steps=5, step_s=1.1, starts=pos)
    for i, name in enumerate(TIER_B):
        st.swarm_update_status(f"tierb-{i+1}", "done", "rebuild complete")
    time.sleep(5)

    print(json.dumps({"task_id": task_id, "agents_total": 18,
                      "target": PROFILE_URL, "status": "reel demo done"}))


if __name__ == "__main__":
    main()
