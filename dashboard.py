"""
Antigravity Bridge Web Dashboard & Real-Time Monitoring Interface
Provides a sleek visual monitoring interface and REST APIs at http://127.0.0.1:8000/dashboard
"""

import os
import json
import psutil
from datetime import datetime
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from server import (
    _load_history, _save_history, list_antigravity_conversations,
    send_spark_to_antigravity_task, BRAIN_DIR, tasks
)

PUBLIC_TUNNEL_URL = ""


def set_public_url(url: str):
    global PUBLIC_TUNNEL_URL
    PUBLIC_TUNNEL_URL = url


# ─── API Handlers ────────────────────────────────────────────────────────────

async def api_status(request):
    """Returns real-time status of server, connections, and system resources."""
    cpu_percent = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    history = _load_history()

    return JSONResponse({
        "status": "online",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "public_url": PUBLIC_TUNNEL_URL,
        "mcp_spark_url": f"{PUBLIC_TUNNEL_URL}/mcp" if PUBLIC_TUNNEL_URL else "http://127.0.0.1:8000/mcp",
        "mcp_antigravity_url": "http://127.0.0.1:8000/sse",
        "active_tasks": len(tasks),
        "history_count": len(history),
        "system": {
            "cpu_percent": cpu_percent,
            "memory_used_mb": round((mem.total - mem.available) / (1024 * 1024)),
            "memory_percent": mem.percent
        }
    })


async def api_history(request):
    """Returns recent tool execution history."""
    history = _load_history()
    return JSONResponse({"history": list(reversed(history[-100:]))})


async def api_conversations(request):
    """Returns all Antigravity projects and conversations."""
    conv_text = list_antigravity_conversations()
    return JSONResponse({"raw_text": conv_text})


async def api_inject(request):
    """Injects a task from the dashboard into Antigravity."""
    try:
        data = await request.json()
        objective = data.get("objective", "").strip()
        context = data.get("context", "").strip()
        actions = data.get("actions", [])
        if not objective:
            return JSONResponse({"error": "Objective is required."}, status_code=400)

        result = send_spark_to_antigravity_task(
            objective=objective,
            context=context if context else None,
            required_actions=actions if actions else None,
            source="web_dashboard"
        )
        return JSONResponse({"success": True, "result": result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_clear_history(request):
    """Clears history log."""
    _save_history([])
    return JSONResponse({"success": True, "message": "History cleared."})


from openapi_spec import get_ai_plugin_manifest, get_openapi_schema
from server import (
    run_system_command, write_file, read_file, edit_file, append_file,
    create_full_project, get_antigravity_agent_report
)

def safe_json(data: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        data,
        status_code=status_code,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS, HEAD",
            "Access-Control-Allow-Headers": "*",
            "Content-Type": "application/json; charset=utf-8"
        }
    )

async def api_ai_plugin(request):
    """Returns OpenAI Plugin Manifest."""
    return safe_json(get_ai_plugin_manifest(PUBLIC_TUNNEL_URL))


async def api_openapi_schema(request):
    """Returns OpenAPI 3.0 JSON Schema for Custom GPTs and Actions."""
    return safe_json(get_openapi_schema(PUBLIC_TUNNEL_URL))


async def api_v1_run_system_command(request):
    if request.method == "OPTIONS":
        return safe_json({})
    data = await request.json()
    res = run_system_command(command=data.get("command", ""), working_dir=data.get("working_dir"), source="chatgpt")
    return safe_json({"result": str(res)})


async def api_v1_write_file(request):
    if request.method == "OPTIONS":
        return safe_json({})
    data = await request.json()
    res = write_file(file_path=data.get("file_path", ""), content=data.get("content", ""), source="chatgpt")
    return safe_json({"result": str(res)})


async def api_v1_read_file(request):
    if request.method == "OPTIONS":
        return safe_json({})
    data = await request.json()
    res = read_file(file_path=data.get("file_path", ""), source="chatgpt")
    return safe_json({"content": str(res)})


async def api_v1_create_full_project(request):
    if request.method == "OPTIONS":
        return safe_json({})
    data = await request.json()
    res = create_full_project(
        project_name=data.get("project_name", ""),
        files=data.get("files", {}),
        setup_commands=data.get("setup_commands"),
        source="chatgpt"
    )
    return safe_json({"report": str(res)})


async def api_v1_send_spark_to_antigravity_task(request):
    if request.method == "OPTIONS":
        return safe_json({})
    data = await request.json()
    res = send_spark_to_antigravity_task(
        objective=data.get("objective", ""),
        context=data.get("context"),
        required_actions=data.get("required_actions"),
        source="chatgpt"
    )
    return safe_json({"result": str(res)})


async def api_v1_get_antigravity_agent_report(request):
    if request.method == "OPTIONS":
        return safe_json({})
    res = get_antigravity_agent_report(source="chatgpt")
    return safe_json({"report": str(res)})


async def api_v1_list_antigravity_conversations(request):
    if request.method == "OPTIONS":
        return safe_json({})
    res = list_antigravity_conversations()
    return safe_json({"conversations": str(res)})



# ─── HTML Dashboard Template ─────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>⚡ Gemini Antigravity Bridge | Live Control Center</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #111726;
      --card-border: #1e293b;
      --accent: #6366f1;
      --accent-glow: rgba(99, 102, 241, 0.25);
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --font-sans: 'Plus Jakarta Sans', sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: rgba(17, 23, 38, 0.8);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--card-border);
      padding: 1rem 2rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 0.8rem;
    }
    .brand-icon {
      width: 38px;
      height: 38px;
      background: linear-gradient(135deg, #6366f1, #a855f7);
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.2rem;
      box-shadow: 0 0 16px var(--accent-glow);
    }
    .brand-title {
      font-size: 1.2rem;
      font-weight: 800;
      letter-spacing: -0.5px;
    }
    .brand-subtitle {
      font-size: 0.75rem;
      color: var(--text-muted);
      font-weight: 500;
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      background: rgba(16, 185, 129, 0.1);
      color: var(--success);
      border: 1px solid rgba(16, 185, 129, 0.3);
      padding: 0.4rem 0.9rem;
      border-radius: 9999px;
      font-size: 0.8rem;
      font-weight: 600;
    }
    .pulse-dot {
      width: 8px;
      height: 8px;
      background: var(--success);
      border-radius: 50%;
      box-shadow: 0 0 8px var(--success);
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.4; transform: scale(0.85); }
    }
    main {
      flex: 1;
      max-width: 1400px;
      margin: 0 auto;
      width: 100%;
      padding: 2rem;
      display: grid;
      grid-template-columns: 350px 1fr;
      gap: 1.5rem;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 1.4rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
      box-shadow: 0 4px 20px rgba(0,0,0,0.25);
    }
    .card-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 0.8rem;
    }
    .card-title {
      font-size: 0.95rem;
      font-weight: 700;
      color: var(--text);
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .url-box {
      background: #090d16;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 0.8rem;
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
    }
    .url-label {
      font-size: 0.7rem;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 700;
      letter-spacing: 0.5px;
    }
    .url-value {
      font-family: var(--font-mono);
      font-size: 0.8rem;
      color: #38bdf8;
      word-break: break-all;
      user-select: all;
    }
    .btn {
      background: var(--accent);
      color: white;
      border: none;
      padding: 0.6rem 1.2rem;
      border-radius: 8px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.4rem;
      transition: all 0.2s;
    }
    .btn:hover {
      opacity: 0.9;
      box-shadow: 0 0 12px var(--accent-glow);
    }
    .btn-secondary {
      background: #1e293b;
      color: var(--text);
      border: 1px solid #334155;
    }
    .btn-secondary:hover {
      background: #334155;
    }
    .btn-sm {
      padding: 0.35rem 0.7rem;
      font-size: 0.75rem;
    }
    .stats-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.8rem;
    }
    .stat-box {
      background: #090d16;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 0.8rem;
      text-align: center;
    }
    .stat-num {
      font-size: 1.4rem;
      font-weight: 800;
      color: var(--text);
    }
    .stat-label {
      font-size: 0.7rem;
      color: var(--text-muted);
      margin-top: 0.2rem;
    }
    .feed-container {
      display: flex;
      flex-direction: column;
      gap: 0.8rem;
      max-height: 550px;
      overflow-y: auto;
      padding-right: 0.4rem;
    }
    .feed-item {
      background: #090d16;
      border: 1px solid var(--card-border);
      border-left: 3px solid var(--accent);
      border-radius: 8px;
      padding: 0.9rem;
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
      font-size: 0.85rem;
      transition: border-color 0.2s;
    }
    .feed-item.write_file { border-left-color: #10b981; }
    .feed-item.run_system_command { border-left-color: #38bdf8; }
    .feed-item.inject_message { border-left-color: #f59e0b; }
    .feed-item.create_full_project { border-left-color: #a855f7; }
    .feed-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: var(--text-muted);
      font-size: 0.75rem;
    }
    .feed-tool {
      font-family: var(--font-mono);
      font-weight: 700;
      color: var(--text);
    }
    .feed-body {
      font-family: var(--font-mono);
      font-size: 0.75rem;
      color: #cbd5e1;
      background: rgba(0,0,0,0.3);
      padding: 0.5rem;
      border-radius: 6px;
      white-space: pre-wrap;
      max-height: 120px;
      overflow-y: auto;
    }
    textarea, input[type="text"] {
      width: 100%;
      background: #090d16;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 0.7rem;
      color: var(--text);
      font-family: var(--font-sans);
      font-size: 0.85rem;
      resize: vertical;
    }
    textarea:focus, input[type="text"]:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 8px var(--accent-glow);
    }
    .toast {
      position: fixed;
      bottom: 2rem;
      right: 2rem;
      background: #1e293b;
      border: 1px solid var(--success);
      color: var(--text);
      padding: 0.8rem 1.4rem;
      border-radius: 8px;
      font-size: 0.85rem;
      display: none;
      z-index: 1000;
      box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <div class="brand-icon">⚡</div>
      <div>
        <div class="brand-title">Gemini Antigravity Bridge</div>
        <div class="brand-subtitle">Live Developer Control Center</div>
      </div>
    </div>
    <div style="display: flex; align-items: center; gap: 1rem;">
      <div class="status-badge">
        <div class="pulse-dot"></div>
        <span id="server-status">BRIDGE ONLINE</span>
      </div>
      <button class="btn btn-secondary btn-sm" onclick="fetchData()">🔄 Refresh</button>
    </div>
  </header>

  <main>
    <!-- Left Column: Status & Task Dispatcher -->
    <div style="display: flex; flex-direction: column; gap: 1.5rem;">
      
      <!-- Connection URLs Card -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">🌐 Active Endpoints</div>
        </div>
        <div class="url-box">
          <div class="url-label">Google Gemini Spark (Streamable HTTP)</div>
          <div class="url-value" id="spark-url">Loading tunnel...</div>
          <button class="btn btn-secondary btn-sm" style="margin-top: 0.4rem;" onclick="copyUrl('spark-url')">📋 Copy URL for Spark</button>
        </div>
        <div class="url-box">
          <div class="url-label">Antigravity IDE (SSE Local)</div>
          <div class="url-value" id="antigravity-url">http://127.0.0.1:8000/sse</div>
          <button class="btn btn-secondary btn-sm" style="margin-top: 0.4rem;" onclick="copyUrl('antigravity-url')">📋 Copy SSE URL</button>
        </div>
      </div>

      <!-- Quick Dispatch Task to Antigravity -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">🎯 Dispatch Task to Antigravity</div>
        </div>
        <textarea id="task-objective" rows="3" placeholder="Enter objective (e.g. Build unit tests for auth module and execute them)..."></textarea>
        <button class="btn" onclick="dispatchTask()">🚀 Send Task into Antigravity</button>
      </div>

      <!-- System Health Stats -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">📊 System Resources</div>
        </div>
        <div class="stats-grid">
          <div class="stat-box">
            <div class="stat-num" id="stat-cpu">0%</div>
            <div class="stat-label">CPU LOAD</div>
          </div>
          <div class="stat-box">
            <div class="stat-num" id="stat-ram">0 MB</div>
            <div class="stat-label">RAM USAGE</div>
          </div>
          <div class="stat-box">
            <div class="stat-num" id="stat-history">0</div>
            <div class="stat-label">TOOL CALLS</div>
          </div>
          <div class="stat-box">
            <div class="stat-num" id="stat-tasks">0</div>
            <div class="stat-label">ACTIVE TASKS</div>
          </div>
        </div>
      </div>

    </div>

    <!-- Right Column: Live Event Stream -->
    <div class="card" style="min-height: 600px;">
      <div class="card-header">
        <div class="card-title">📡 Real-Time Tool Execution Feed</div>
        <button class="btn btn-secondary btn-sm" onclick="clearHistory()">🗑️ Clear Log</button>
      </div>
      <div class="feed-container" id="feed-list">
        <div style="color: var(--text-muted); text-align: center; padding: 2rem;">Connecting to live feed...</div>
      </div>
    </div>
  </main>

  <div id="toast" class="toast">Action completed!</div>

  <script>
    function showToast(msg) {
      const toast = document.getElementById('toast');
      toast.innerText = msg;
      toast.style.display = 'block';
      setTimeout(() => { toast.style.display = 'none'; }, 3000);
    }

    function copyUrl(elementId) {
      const text = document.getElementById(elementId).innerText;
      navigator.clipboard.writeText(text);
      showToast('Copied to clipboard: ' + text);
    }

    async function fetchData() {
      try {
        const [statusRes, historyRes] = await Promise.all([
          fetch('/api/status').then(r => r.json()),
          fetch('/api/history').then(r => r.json())
        ]);

        // Status
        document.getElementById('spark-url').innerText = statusRes.mcp_spark_url;
        document.getElementById('antigravity-url').innerText = statusRes.mcp_antigravity_url;
        document.getElementById('stat-cpu').innerText = statusRes.system.cpu_percent + '%';
        document.getElementById('stat-ram').innerText = statusRes.system.memory_used_mb + ' MB';
        document.getElementById('stat-history').innerText = statusRes.history_count;
        document.getElementById('stat-tasks').innerText = statusRes.active_tasks;

        // Feed
        const feedList = document.getElementById('feed-list');
        if (historyRes.history && historyRes.history.length > 0) {
          feedList.innerHTML = historyRes.history.map(item => `
            <div class="feed-item ${item.tool}">
              <div class="feed-header">
                <div><span class="feed-tool">⚡ ${item.tool}</span> &bull; <span style="text-transform: uppercase;">[${item.source}]</span></div>
                <div>${item.timestamp}</div>
              </div>
              <div class="feed-body">${escapeHtml(item.result_preview || JSON.stringify(item.inputs))}</div>
            </div>
          `).join('');
        } else {
          feedList.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 2rem;">No tool calls logged yet. Call tools from Gemini Spark or Antigravity to see real-time events!</div>';
        }
      } catch (err) {
        console.error('Error fetching dashboard data:', err);
      }
    }

    async function dispatchTask() {
      const objective = document.getElementById('task-objective').value.trim();
      if (!objective) return alert('Please enter an objective.');

      try {
        const res = await fetch('/api/inject', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ objective })
        });
        const data = await res.json();
        if (data.success) {
          showToast('Task dispatched into Antigravity!');
          document.getElementById('task-objective').value = '';
          fetchData();
        } else {
          alert('Failed to dispatch: ' + data.error);
        }
      } catch (err) {
        alert('Error: ' + err);
      }
    }

    async function clearHistory() {
      if (!confirm('Clear all tool call history?')) return;
      await fetch('/api/clear-history', { method: 'POST' });
      showToast('History cleared.');
      fetchData();
    }

    function escapeHtml(str) {
      if (!str) return '';
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    // Auto poll every 3 seconds
    fetchData();
    setInterval(fetchData, 3000);
  </script>
</body>
</html>
"""

async def dashboard_page(request):
    return HTMLResponse(DASHBOARD_HTML)


# ─── Dashboard & ChatGPT Actions Routes ──────────────────────────────────────

DASHBOARD_ROUTES = [
    Route("/dashboard", dashboard_page, methods=["GET"]),
    Route("/api/status", api_status, methods=["GET"]),
    Route("/api/history", api_history, methods=["GET"]),
    Route("/api/conversations", api_conversations, methods=["GET"]),
    Route("/api/inject", api_inject, methods=["POST"]),
    Route("/api/clear-history", api_clear_history, methods=["POST"]),
    # ChatGPT Actions & Plugins Discovery
    Route("/.well-known/ai-plugin.json", api_ai_plugin, methods=["GET", "OPTIONS"]),
    Route("/openapi.json", api_openapi_schema, methods=["GET", "OPTIONS"]),
    # ChatGPT REST Tool APIs
    Route("/api/v1/run_system_command", api_v1_run_system_command, methods=["POST", "OPTIONS"]),
    Route("/api/v1/write_file", api_v1_write_file, methods=["POST", "OPTIONS"]),
    Route("/api/v1/read_file", api_v1_read_file, methods=["POST", "OPTIONS"]),
    Route("/api/v1/create_full_project", api_v1_create_full_project, methods=["POST", "OPTIONS"]),
    Route("/api/v1/send_spark_to_antigravity_task", api_v1_send_spark_to_antigravity_task, methods=["POST", "OPTIONS"]),
    Route("/api/v1/get_antigravity_agent_report", api_v1_get_antigravity_agent_report, methods=["GET", "OPTIONS"]),
    Route("/api/v1/list_antigravity_conversations", api_v1_list_antigravity_conversations, methods=["GET", "OPTIONS"]),
]
