"""
Gemini Antigravity Bridge - MCP Server
Exposes system tools, file operations, terminal execution, Antigravity Agent orchestration,
and full cross-client history/session logging to Gemini Spark AND Antigravity over MCP.
"""

import os
import sys
import uuid
import json
import asyncio
import subprocess
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, List
from mcp.server.mcpserver import MCPServer

# Initialize MCP Server
mcp = MCPServer(name="Gemini-Antigravity-Bridge")

# In-memory background task & process tracking
tasks: Dict[str, Dict[str, Any]] = {}
background_processes: Dict[str, Dict[str, Any]] = {}

# Default base directory
BASE_DIR = os.path.abspath(os.getcwd())

# Persistent history log file — shared between Gemini Spark and Antigravity
HISTORY_FILE = os.path.join(BASE_DIR, "bridge_history.json")

# Blocked dangerous system command patterns
BLOCKED_PATTERNS = [
    "format c:", "rmdir /s /q c:\\", "rmdir /s /q c:/", "del /f /s /q c:\\windows",
    ":(){ :|:& };:", "dd if=/dev/zero", "mkfs.", "> /dev/sda"
]


# ─── Security & Safety Helpers ────────────────────────────────────────────────

def _is_safe_command(cmd: str) -> tuple[bool, str]:
    """Check if command contains destructive system commands."""
    cmd_lower = cmd.lower().strip()
    for pattern in BLOCKED_PATTERNS:
        if pattern in cmd_lower:
            return False, f"Blocked dangerous command pattern: '{pattern}'"
    return True, ""


def _resolve_safe_path(file_path: str, working_dir: Optional[str] = None) -> str:
    """Resolves path and prevents illegal null-byte injections."""
    clean_path = file_path.replace("\x00", "")
    base = os.path.abspath(working_dir if working_dir else BASE_DIR)
    if os.path.isabs(clean_path):
        return os.path.abspath(clean_path)
    return os.path.abspath(os.path.join(base, clean_path))


# ─── History Helpers ─────────────────────────────────────────────────────────

def _load_history() -> List[Dict]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_history(history: List[Dict]):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _log_action(tool: str, inputs: Dict, result: str, source: str = "gemini_spark"):
    history = _load_history()
    history.append({
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "tool": tool,
        "inputs": inputs,
        "result_preview": result[:300] + ("..." if len(result) > 300 else ""),
    })
    # Keep last 500 entries
    _save_history(history[-500:])


# ─── Core System Tools ───────────────────────────────────────────────────────

@mcp.tool()
def run_system_command(
    command: str,
    working_dir: Optional[str] = None,
    timeout_seconds: Optional[int] = 180,
    source: Optional[str] = None
) -> str:
    """
    Executes a shell/PowerShell command on the local system (e.g. python, npm, git, tests, pip).
    Includes safety filtering and configurable timeout (default: 180s).
    """
    is_safe, reason = _is_safe_command(command)
    if not is_safe:
        return f"[Security Blocked] {reason}"

    target_dir = os.path.abspath(working_dir) if working_dir else BASE_DIR
    timeout = min(max(timeout_seconds or 180, 5), 600)  # Between 5s and 10 mins

    try:
        process = subprocess.run(
            command, shell=True, cwd=target_dir,
            capture_output=True, text=True, timeout=timeout,
        )
        result = f"[Exit Code: {process.returncode}]\n--- STDOUT ---\n{process.stdout}\n--- STDERR ---\n{process.stderr}"
        _log_action("run_system_command", {"command": command, "working_dir": target_dir},
                    result, source or "gemini_spark")
        return result
    except subprocess.TimeoutExpired:
        return f"[Error] Command timed out after {timeout} seconds."
    except Exception as e:
        return f"[Error] Failed to execute command: {str(e)}"


# ─── File Operations (Read, Write, Edit, Append) ─────────────────────────────

@mcp.tool()
def read_file(file_path: str, source: Optional[str] = None) -> str:
    """
    Reads the content of a file from the local filesystem.
    """
    abs_path = _resolve_safe_path(file_path)
    if not os.path.exists(abs_path):
        return f"[Error] File not found: {abs_path}"
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        _log_action("read_file", {"file_path": abs_path}, content, source or "gemini_spark")
        return content
    except Exception as e:
        return f"[Error] Failed to read file: {str(e)}"


@mcp.tool()
def write_file(file_path: str, content: str, source: Optional[str] = None) -> str:
    """
    Creates or overwrites a file on the local filesystem with specified content.
    Automatically creates parent directories if they don't exist.
    """
    abs_path = _resolve_safe_path(file_path)
    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        result = f"[Success] File written to {abs_path} ({len(content)} bytes)"
        _log_action("write_file", {"file_path": abs_path, "content_length": len(content)},
                    result, source or "gemini_spark")
        return result
    except Exception as e:
        return f"[Error] Failed to write file: {str(e)}"


@mcp.tool()
def edit_file(file_path: str, find_text: str, replace_text: str, source: Optional[str] = None) -> str:
    """
    Performs a precise surgical search-and-replace edit in an existing file.
    Avoids having to rewrite the entire file when making targeted code changes.
    """
    abs_path = _resolve_safe_path(file_path)
    if not os.path.exists(abs_path):
        return f"[Error] File not found: {abs_path}"
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        if find_text not in content:
            return f"[Error] Target string to replace was not found in {os.path.basename(abs_path)}"

        occurrences = content.count(find_text)
        new_content = content.replace(find_text, replace_text, 1)

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        result = f"[Success] Replaced 1 occurrence of target string in {abs_path} (Remaining matches: {occurrences - 1})"
        _log_action("edit_file", {"file_path": abs_path, "find_preview": find_text[:80]},
                    result, source or "gemini_spark")
        return result
    except Exception as e:
        return f"[Error] Failed to edit file: {str(e)}"


@mcp.tool()
def append_file(file_path: str, content: str, source: Optional[str] = None) -> str:
    """
    Appends text to the end of an existing file (or creates it if it doesn't exist).
    """
    abs_path = _resolve_safe_path(file_path)
    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "a", encoding="utf-8") as f:
            f.write(content)
        result = f"[Success] Appended {len(content)} bytes to {abs_path}"
        _log_action("append_file", {"file_path": abs_path, "bytes": len(content)},
                    result, source or "gemini_spark")
        return result
    except Exception as e:
        return f"[Error] Failed to append to file: {str(e)}"


# ─── Composite / Batch Operations (1 Permission Click for Entire Tasks) ───────

@mcp.tool()
def batch_write_files(files: Dict[str, str], base_dir: Optional[str] = None, source: Optional[str] = None) -> str:
    """
    Creates or updates multiple files in a single tool call.
    Reduces permission prompts from N to 1.
    Parameters:
        files: Dictionary of {"relative/or/abs/filepath": "file_content"}
        base_dir: Optional root directory (defaults to server CWD)
    """
    root = _resolve_safe_path(base_dir if base_dir else BASE_DIR)
    results = []
    success_count = 0

    for rel_path, content in files.items():
        abs_path = os.path.abspath(rel_path if os.path.isabs(rel_path) else os.path.join(root, rel_path))
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            results.append(f"  ✅ Written: {os.path.relpath(abs_path, root)} ({len(content)} bytes)")
            success_count += 1
        except Exception as e:
            results.append(f"  ❌ Failed: {rel_path} - {str(e)}")

    summary = f"[Batch Write Complete] {success_count}/{len(files)} files written successfully.\n" + "\n".join(results)
    _log_action("batch_write_files", {"count": len(files), "root": root}, summary, source or "gemini_spark")
    return summary


@mcp.tool()
def run_batch_commands(
    commands: List[str],
    working_dir: Optional[str] = None,
    stop_on_error: Optional[bool] = True,
    timeout_per_command: Optional[int] = 180,
    source: Optional[str] = None,
) -> str:
    """
    Executes multiple shell/PowerShell commands sequentially in a single tool call.
    Reduces permission prompts from N to 1.
    Parameters:
        commands: List of shell command strings to execute in order.
        working_dir: Working directory for all commands.
        stop_on_error: If True, halts execution if any command returns non-zero exit code.
        timeout_per_command: Max seconds per command (default: 180s).
    """
    target_dir = os.path.abspath(working_dir) if working_dir else BASE_DIR
    timeout = min(max(timeout_per_command or 180, 5), 600)
    output_lines = [f"=== Running Batch Commands in: {target_dir} ==="]

    for idx, cmd in enumerate(commands, 1):
        is_safe, reason = _is_safe_command(cmd)
        if not is_safe:
            output_lines.append(f"\n[{idx}/{len(commands)}] Command: {cmd}\n[Security Blocked] {reason}")
            if stop_on_error:
                break
            continue

        output_lines.append(f"\n[{idx}/{len(commands)}] Executing: {cmd}")
        try:
            proc = subprocess.run(cmd, shell=True, cwd=target_dir, capture_output=True, text=True, timeout=timeout)
            out = proc.stdout.strip()
            err = proc.stderr.strip()
            status = "SUCCESS" if proc.returncode == 0 else f"FAILED (Exit Code: {proc.returncode})"
            output_lines.append(f"Status: {status}")
            if out:
                output_lines.append(f"STDOUT:\n{out}")
            if err:
                output_lines.append(f"STDERR:\n{err}")

            if proc.returncode != 0 and stop_on_error:
                output_lines.append(f"\n[Halted] Stopped remaining commands due to failure on step {idx}.")
                break
        except subprocess.TimeoutExpired:
            output_lines.append(f"[Error] Command timed out after {timeout} seconds.")
            if stop_on_error:
                break
        except Exception as e:
            output_lines.append(f"[Error] Execution failed: {str(e)}")
            if stop_on_error:
                break

    full_output = "\n".join(output_lines)
    _log_action("run_batch_commands", {"commands_count": len(commands)}, full_output, source or "gemini_spark")
    return full_output


@mcp.tool()
def create_full_project(
    project_name: str,
    files: Dict[str, str],
    setup_commands: Optional[List[str]] = None,
    working_dir: Optional[str] = None,
    source: Optional[str] = None,
) -> str:
    """
    Creates an entire project directory, writes all code files, and runs initial setup/test commands
    in a SINGLE tool call with 1 permission confirmation.
    Parameters:
        project_name: Name of the project folder to create.
        files: Dictionary of {"rel/path/filename.ext": "file content"}
        setup_commands: Optional list of commands to run inside the new project (e.g. ["pip install -r requirements.txt", "python test.py"])
        working_dir: Parent directory where project folder will be created (defaults to CWD).
    """
    parent = _resolve_safe_path(working_dir if working_dir else BASE_DIR)
    project_root = os.path.join(parent, project_name)
    os.makedirs(project_root, exist_ok=True)

    report = [f"=== Project Created: {project_name} at {project_root} ==="]

    # 1. Write all files
    write_res = batch_write_files(files=files, base_dir=project_root, source=source)
    report.append("\n--- Files Written ---")
    report.append(write_res)

    # 2. Run setup commands if provided
    if setup_commands:
        report.append("\n--- Setup & Verification Commands ---")
        cmd_res = run_batch_commands(commands=setup_commands, working_dir=project_root, source=source)
        report.append(cmd_res)

    final_report = "\n".join(report)
    _log_action("create_full_project", {"project": project_name, "files": len(files)}, final_report, source or "gemini_spark")
    return final_report


@mcp.tool()
def list_directory(directory_path: Optional[str] = None, source: Optional[str] = None) -> str:
    """
    Lists files and directories at the specified path with file sizes.
    """
    target_dir = _resolve_safe_path(directory_path if directory_path else BASE_DIR)
    if not os.path.exists(target_dir):
        return f"[Error] Directory not found: {target_dir}"
    try:
        entries = os.listdir(target_dir)
        output = [f"Directory contents of: {target_dir}"]
        for entry in sorted(entries):
            full_path = os.path.join(target_dir, entry)
            is_dir = "[DIR] " if os.path.isdir(full_path) else "[FILE]"
            size = os.path.getsize(full_path) if not os.path.isdir(full_path) else "-"
            output.append(f"{is_dir} {entry} ({size} bytes)")
        result = "\n".join(output)
        _log_action("list_directory", {"directory_path": target_dir}, result, source or "gemini_spark")
        return result
    except Exception as e:
        return f"[Error] Failed to list directory: {str(e)}"


# ─── Git & Health Utilities ──────────────────────────────────────────────────

@mcp.tool()
def git_quick_status(repo_dir: Optional[str] = None, source: Optional[str] = None) -> str:
    """
    Returns high-level Git status: active branch, changed files, untracked files, and recent commit.
    """
    target_dir = _resolve_safe_path(repo_dir if repo_dir else BASE_DIR)
    try:
        branch = subprocess.run("git branch --show-current", shell=True, cwd=target_dir,
                                capture_output=True, text=True).stdout.strip()
        status = subprocess.run("git status --short", shell=True, cwd=target_dir,
                                capture_output=True, text=True).stdout.strip()
        last_commit = subprocess.run("git log -1 --oneline", shell=True, cwd=target_dir,
                                     capture_output=True, text=True).stdout.strip()

        result = (
            f"=== Git Status: {os.path.basename(target_dir)} ===\n"
            f"Branch: {branch or 'Detached/No branch'}\n"
            f"Last Commit: {last_commit or 'None'}\n"
            f"Changes:\n{status if status else '  (working tree clean)'}"
        )
        _log_action("git_quick_status", {"repo_dir": target_dir}, result, source or "gemini_spark")
        return result
    except Exception as e:
        return f"[Error] Git inspection failed: {str(e)}"


# ─── Autonomous Agent Orchestration ──────────────────────────────────────────

BRAIN_DIR = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity", "brain")


@mcp.tool()
async def run_agent_task(prompt: str, workspace_dir: Optional[str] = None, source: Optional[str] = None) -> str:
    """
    Launches an autonomous Antigravity AI agent task using ANTIGRAVITY's credits and models.
    Routes the task into a real Antigravity conversation via message injection.
    """
    task_id = str(uuid.uuid4())[:8]
    target_dir = _resolve_safe_path(workspace_dir if workspace_dir else BASE_DIR)

    tasks[task_id] = {
        "task_id": task_id,
        "prompt": prompt,
        "status": "running",
        "output": "",
        "error": None,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source or "gemini_spark",
        "routed_to": "antigravity",
    }
    _log_action("run_agent_task", {"prompt": prompt[:200], "task_id": task_id},
                f"Task launched with ID: {task_id}", source or "gemini_spark")

    async def _run():
        try:
            target_conv = None
            if os.path.exists(BRAIN_DIR):
                convs = sorted(
                    [e for e in os.scandir(BRAIN_DIR)
                     if e.is_dir() and len(e.name) == 36 and e.name.count("-") == 4],
                    key=lambda e: e.stat().st_mtime, reverse=True
                )
                if convs:
                    target_conv = convs[0].name

            if target_conv:
                msg_dir = os.path.join(BRAIN_DIR, target_conv, ".system_generated", "messages")
                os.makedirs(msg_dir, exist_ok=True)
                msg_id = str(uuid.uuid4())
                payload = {
                    "id": msg_id,
                    "recipient": target_conv,
                    "sender": f"mcp-bridge/task-{task_id}",
                    "priority": "MESSAGE_PRIORITY_HIGH",
                    "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
                    "renderDetails": {"messageTitle": f"Spark Task [{task_id}]: Autonomous Agent Work"},
                    "content": (
                        f"**Task delegated from Gemini Spark (Task ID: {task_id})**\n\n"
                        f"Working directory: `{target_dir}`\n\n"
                        f"**Your task:**\n{prompt}\n\n"
                        f"Please execute this task using Antigravity AI capabilities. "
                        f"When done, log results via save_session_note with tag='task_result' and task_id='{task_id}'."
                    ),
                    "sourceMetadata": {}
                }
                with open(os.path.join(msg_dir, f"{msg_id}.json"), "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)

                read_path = os.path.join(msg_dir, "read.json")
                read_data = {}
                if os.path.exists(read_path):
                    try:
                        with open(read_path) as f:
                            read_data = json.load(f)
                    except Exception:
                        pass
                read_data.pop(msg_id, None)
                with open(read_path, "w") as f:
                    json.dump(read_data, f)

                tasks[task_id]["output"] = (
                    f"Task successfully routed to Antigravity conversation '{target_conv}'.\n"
                    f"Antigravity AI will execute using its own credits and models.\n"
                    f"Results will appear as a session note with tag='task_result'."
                )
                tasks[task_id]["status"] = "delegated_to_antigravity"
                tasks[task_id]["routed_to_conv"] = target_conv
            else:
                tasks[task_id]["output"] = "[Info] No active Antigravity conversation found to delegate to."
                tasks[task_id]["status"] = "failed"
        except Exception as e:
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = f"{str(e)}\n{traceback.format_exc()}"

    asyncio.create_task(_run())
    return f"Task started successfully. Task ID: {task_id}\nRouting to Antigravity AI — uses Antigravity credits, not Spark credits."


@mcp.tool()
def get_agent_status(task_id: str) -> Dict[str, Any]:
    """
    Fetches the live status and output of a running or completed agent task.
    """
    if task_id not in tasks:
        return {"status": "not_found", "message": f"Task ID {task_id} does not exist."}
    return tasks[task_id]


@mcp.tool()
def terminate_task(task_id: str) -> str:
    """
    Terminates or cancels a running agent task by task ID.
    """
    if task_id in tasks:
        tasks[task_id]["status"] = "cancelled"
        _log_action("terminate_task", {"task_id": task_id}, "Task cancelled.", "system")
        return f"Task {task_id} has been marked as cancelled."
    return f"Task ID {task_id} not found."


# ─── History & Session Memory Tools ──────────────────────────────────────────

@mcp.tool()
def get_bridge_history(limit: Optional[int] = 50, tool_filter: Optional[str] = None,
                       source_filter: Optional[str] = None) -> str:
    """
    Returns the full shared history of all tool calls made through this bridge.
    """
    history = _load_history()

    if tool_filter:
        history = [h for h in history if h.get("tool") == tool_filter]
    if source_filter:
        history = [h for h in history if h.get("source") == source_filter]

    recent = history[-(limit or 50):]
    if not recent:
        return "[Info] No history found."

    lines = [f"=== Bridge History ({len(recent)} entries) ===\n"]
    for entry in reversed(recent):
        lines.append(
            f"[{entry.get('timestamp', '?')}] [{entry.get('source', '?').upper()}] "
            f"Tool: {entry.get('tool', '?')} | ID: {entry.get('id', '?')}\n"
            f"  Input:  {json.dumps(entry.get('inputs', {}), ensure_ascii=False)[:150]}\n"
            f"  Result: {entry.get('result_preview', '')}\n"
            f"  {'─'*60}"
        )
    return "\n".join(lines)


@mcp.tool()
def save_session_note(note: str, tag: Optional[str] = None, source: Optional[str] = None) -> str:
    """
    Saves a note or memory to the shared bridge session log.
    """
    entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source or "gemini_spark",
        "tool": "save_session_note",
        "inputs": {"note": note, "tag": tag or "general"},
        "result_preview": f"Note saved: {note[:200]}",
    }
    history = _load_history()
    history.append(entry)
    _save_history(history[-500:])
    return f"[Success] Note saved with ID {entry['id']} | Tag: {tag or 'general'}"


@mcp.tool()
def get_session_notes(tag_filter: Optional[str] = None) -> str:
    """
    Retrieves all saved session notes from the shared bridge log.
    """
    history = _load_history()
    notes = [h for h in history if h.get("tool") == "save_session_note"]

    if tag_filter:
        notes = [n for n in notes if n.get("inputs", {}).get("tag") == tag_filter]

    if not notes:
        return "[Info] No session notes found."

    lines = [f"=== Session Notes ({len(notes)} entries) ===\n"]
    for n in reversed(notes):
        lines.append(
            f"[{n.get('timestamp')}] [{n.get('source', '?').upper()}] "
            f"Tag: {n.get('inputs', {}).get('tag', 'general')}\n"
            f"  {n.get('inputs', {}).get('note', '')}\n"
            f"  {'─'*60}"
        )
    return "\n".join(lines)


# ─── Antigravity ➔ Gemini Sync & Research Tools ──────────────────────────────

@mcp.tool()
def sync_project_to_gemini(
    project_name: str,
    summary: str,
    tech_stack: Optional[List[str]] = None,
    key_files: Optional[List[str]] = None,
    next_milestone: Optional[str] = None,
    source: Optional[str] = None,
) -> str:
    """
    Called by Antigravity to push a complete project status report and architectural summary
    into the shared bridge memory. Gemini Spark can read this anytime to understand your exact project state.
    """
    dossier = {
        "project_name": project_name,
        "summary": summary,
        "tech_stack": tech_stack or [],
        "key_files": key_files or [],
        "next_milestone": next_milestone or "In Progress",
        "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    note_content = (
        f"📁 PROJECT SYNC: **{project_name}**\n"
        f"• Summary: {summary}\n"
        f"• Tech Stack: {', '.join(tech_stack) if tech_stack else 'N/A'}\n"
        f"• Key Files: {', '.join(key_files) if key_files else 'N/A'}\n"
        f"• Next Milestone: {next_milestone or 'Active Development'}"
    )
    save_session_note(note=note_content, tag="project_sync", source=source or "antigravity")
    return f"[Success] Project '{project_name}' synced to Gemini Spark bridge memory."


@mcp.tool()
def request_spark_connected_app_action(
    app: str,
    action: str,
    details: str,
    context: Optional[str] = None,
    source: Optional[str] = None,
) -> str:
    """
    Dispatches a task from Antigravity to Gemini Spark requesting execution via
    Spark's connected apps (e.g. @Canva, @Google Drive, @Google Docs, @Google Keep, @YouTube, @Gmail, @Dropbox).
    Spark will read this request on sync and execute the tool action in the Google ecosystem.
    """
    valid_apps = [
        "Canva", "Google Drive", "Google Docs", "Google Keep", "YouTube",
        "Gmail", "Google Photos", "Gemini Notebook", "Dropbox", "Zoho Projects", "Wix"
    ]
    formatted_app = app.strip().title() if not app.startswith("@") else app[1:].strip().title()
    
    note_content = (
        f"⚡ SPARK CONNECTED APP REQUEST: **@{formatted_app}**\n"
        f"• Action Required: {action}\n"
        f"• Specifications/Input: {details}\n"
        f"• Context: {context if context else 'None provided'}\n"
        f"• Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    save_session_note(note=note_content, tag="spark_app_request", source=source or "antigravity")
    return f"[Success] Task queued for Spark @{formatted_app}: '{action}'. Spark will process on next sync/schedule."


@mcp.tool()
def get_spark_connected_apps_catalog() -> str:
    """
    Returns the complete list and capabilities of external tools & Google Workspace apps
    connected to Gemini Spark that Antigravity can orchestrate.
    """
    catalog = """=== 🌐 Gemini Spark Connected Apps & Ecosystem Catalog ===
1. 🎨 @Canva: Poster design, infographics, slide decks, social graphics.
2. 📁 @Google Drive: Cloud file search, folder management, large asset sync.
3. 📝 @Google Docs: Academic reports, collaborative documentation, assignment drafts.
4. 📌 @Google Keep: Flashcards, quick study notes, pinned checklists.
5. 🎥 @YouTube: Video search, lecture transcript extraction, tutorial summaries.
6. 📬 @Gmail: Full email reading, URL extraction, notification monitoring.
7. 📓 @Gemini Notebook: Dedicated deep research and multi-project synthesis.
8. 📦 @Dropbox: Cloud storage sync via remote MCP server.
9. 👥 @Contacts: Campus, student, and team directory queries.
10. 💼 @Zoho (Projects/CRM): Task tracking, project sprints, team coordination.
11. ⚡ @Gemini Antigravity Bridge: Bidirectional local machine execution & IDE orchestration.
"""
    return catalog





# ─── Conversation Management ─────────────────────────────────────────────────

def _extract_conversation_title(conv_path: str) -> str:
    import re
    transcript = os.path.join(conv_path, ".system_generated", "logs", "transcript.jsonl")
    if not os.path.exists(transcript):
        return ""
    try:
        with open(transcript, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if data.get("type") == "CONVERSATION_HISTORY":
                        content = data.get("content", "")
                        match = re.search(r"##\s*Conversation\s+[\w-]+:\s*(.+)", content)
                        if match:
                            return match.group(1).strip()
                    elif data.get("type") == "USER_INPUT":
                        content = data.get("content", "").strip()
                        if content:
                            return content[:60] + ("..." if len(content) > 60 else "")
                except Exception:
                    continue
    except Exception:
        pass
    return ""


def _count_conversation_stats(conv_path: str) -> dict:
    transcript = os.path.join(conv_path, ".system_generated", "logs", "transcript.jsonl")
    stats = {"messages": 0, "user_messages": 0, "tasks": 0, "artifacts": 0}
    if not os.path.exists(transcript):
        return stats
    try:
        with open(transcript, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if data.get("type") == "USER_INPUT":
                        stats["user_messages"] += 1
                    stats["messages"] += 1
                except Exception:
                    pass
        tasks_dir = os.path.join(conv_path, ".system_generated", "tasks")
        if os.path.exists(tasks_dir):
            stats["tasks"] = len([f for f in os.listdir(tasks_dir) if f.endswith(".log")])
        for root, dirs, files in os.walk(conv_path):
            dirs[:] = [d for d in dirs if d != ".system_generated"]
            stats["artifacts"] += len([f for f in files if not f.endswith(".metadata.json")])
    except Exception:
        pass
    return stats


@mcp.tool()
def list_antigravity_conversations() -> str:
    """
    Lists ALL Antigravity projects/conversations with their real names,
    conversation IDs, last active time, message count, artifact count, and task count.
    """
    if not os.path.exists(BRAIN_DIR):
        return "[Error] Antigravity brain directory not found."

    results = []
    for entry in sorted(os.scandir(BRAIN_DIR), key=lambda e: e.stat().st_mtime, reverse=True):
        if not (entry.is_dir() and len(entry.name) == 36 and entry.name.count("-") == 4):
            continue

        title = _extract_conversation_title(entry.path) or "(Untitled)"
        stats = _count_conversation_stats(entry.path)
        mtime = datetime.fromtimestamp(entry.stat().st_mtime).strftime("%Y-%m-%d %H:%M")

        results.append(
            f"📁 \"{title}\"\n"
            f"   ID       : {entry.name}\n"
            f"   Last Active: {mtime}\n"
            f"   Messages : {stats['user_messages']} user / {stats['messages']} total\n"
            f"   Tasks    : {stats['tasks']}  |  Artifacts: {stats['artifacts']}"
        )

    if not results:
        return "[Info] No conversations found."
    return "=== Antigravity Conversations & Projects ===\n\n" + "\n\n".join(results)


@mcp.tool()
def inject_message(
    conversation_id: str,
    message: str,
    sender: Optional[str] = None,
    priority: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """
    Injects a message directly into any Antigravity conversation's inbox.
    """
    msg_dir = os.path.join(BRAIN_DIR, conversation_id, ".system_generated", "messages")
    if not os.path.exists(msg_dir):
        return f"[Error] Conversation '{conversation_id}' not found or has no message inbox."

    msg_id = str(uuid.uuid4())
    payload = {
        "id": msg_id,
        "recipient": conversation_id,
        "sender": sender or "mcp-bridge/gemini-spark",
        "priority": priority or "MESSAGE_PRIORITY_HIGH",
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        "renderDetails": {
            "messageTitle": title or "Message from MCP Bridge"
        },
        "content": message,
        "sourceMetadata": {}
    }

    msg_file = os.path.join(msg_dir, f"{msg_id}.json")
    try:
        with open(msg_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        read_file_path = os.path.join(msg_dir, "read.json")
        read_data = {}
        if os.path.exists(read_file_path):
            try:
                with open(read_file_path, "r", encoding="utf-8") as f:
                    read_data = json.load(f)
            except Exception:
                read_data = {}
        read_data.pop(msg_id, None)
        with open(read_file_path, "w", encoding="utf-8") as f:
            json.dump(read_data, f)

        _log_action("inject_message", {
            "conversation_id": conversation_id,
            "message_preview": message[:200],
            "msg_id": msg_id
        }, f"Injected message {msg_id}", "mcp-bridge")

        return (
            f"[Success] Message injected into conversation '{conversation_id}'\n"
            f"Message ID: {msg_id}\n"
            f"Antigravity will pick it up on its next active check or immediately if idle."
        )
    except Exception as e:
        return f"[Error] Failed to inject message: {str(e)}"


# ─── Structured Clear Communication Protocol (Spark ↔ Antigravity) ───────────

@mcp.tool()
def send_spark_to_antigravity_task(
    objective: str,
    context: Optional[str] = None,
    required_actions: Optional[List[str]] = None,
    conversation_id: Optional[str] = None,
    working_dir: Optional[str] = None,
    source: Optional[str] = None,
) -> str:
    """
    Sends a crystal-clear, structured task brief from Gemini Spark to Antigravity IDE.
    Automatically generates a formatted markdown instruction envelope with Task ID,
    objectives, context, step-by-step actions, and reporting instructions.
    
    Parameters:
        objective: Clear 1-2 sentence primary goal.
        context: Optional background, architectural details, or file paths.
        required_actions: Optional ordered list of specific steps (e.g. ["write tests", "run pytest", "fix bugs"]).
        conversation_id: Target Antigravity conversation UUID (if None, targets most recent active).
        working_dir: Target working folder on disk.
    """
    task_id = str(uuid.uuid4())[:8]
    target_dir = _resolve_safe_path(working_dir if working_dir else BASE_DIR)

    # Find target conversation
    target_conv = conversation_id
    if not target_conv and os.path.exists(BRAIN_DIR):
        convs = sorted(
            [e for e in os.scandir(BRAIN_DIR)
             if e.is_dir() and len(e.name) == 36 and e.name.count("-") == 4],
            key=lambda e: e.stat().st_mtime, reverse=True
        )
        if convs:
            target_conv = convs[0].name

    if not target_conv:
        return "[Error] No active Antigravity conversation found to receive task."

    # Build structured, clear communication envelope
    actions_md = ""
    if required_actions:
        actions_md = "\n### ⚡ Required Steps:\n" + "\n".join([f"{i}. {act}" for i, act in enumerate(required_actions, 1)])

    context_md = f"\n### 📋 Context & Specifications:\n{context}\n" if context else ""

    formatted_content = f"""# 📡 TASK BRIEF: GEMINI SPARK ➔ ANTIGRAVITY ENGINE
**Task ID:** `spark-task-{task_id}`
**Timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Working Directory:** `{target_dir}`

---

### 🎯 Primary Objective:
{objective}
{context_md}{actions_md}

---

### 📤 Required Response Back to Spark:
When you have completed this work:
1. Call `save_session_note` with tag="spark_response" and note content structured as:
   - **STATUS**: [SUCCESS / BLOCKED / FAILED]
   - **FILES CREATED/EDITED**: [List of file paths]
   - **VERIFICATION & TESTS**: [Test outputs or compiler status]
   - **EXECUTIVE SUMMARY**: [Brief summary for Spark to report to the user]
"""

    return inject_message(
        conversation_id=target_conv,
        message=formatted_content,
        sender=f"gemini-spark/task-{task_id}",
        priority="MESSAGE_PRIORITY_HIGH",
        title=f"🎯 Spark Task [{task_id}]: {objective[:40]}..."
    )


@mcp.tool()
def get_antigravity_agent_report(
    conversation_id: Optional[str] = None,
    task_id: Optional[str] = None,
    source: Optional[str] = None,
) -> str:
    """
    Retrieves the structured status report and latest responses from Antigravity.
    Shows completion notes, modified files, test outputs, and executive summary.
    """
    history = _load_history()
    spark_responses = [
        h for h in history
        if h.get("tool") == "save_session_note" and h.get("inputs", {}).get("tag") in ["spark_response", "task_result"]
    ]

    report = ["=== 📡 Antigravity Execution Reports for Spark ===\n"]

    if spark_responses:
        report.append("--- Latest Agent Response Notes ---")
        for resp in reversed(spark_responses[-5:]):
            report.append(
                f"[{resp.get('timestamp')}] ID: {resp.get('id')}\n"
                f"{resp.get('inputs', {}).get('note')}\n"
                f"{'─'*60}"
            )
    else:
        report.append("[Info] No structured spark_response notes logged yet.")

    # Also check latest session notes
    recent_notes = [
        h for h in history
        if h.get("tool") == "save_session_note" and h.get("inputs", {}).get("tag") not in ["spark_response", "task_result"]
    ]
    if recent_notes:
        report.append("\n--- Other Recent Session Notes ---")
        for n in reversed(recent_notes[-3:]):
            report.append(f"[{n.get('timestamp')}] ({n.get('inputs', {}).get('tag')}): {n.get('inputs', {}).get('note')}")

    return "\n".join(report)


if __name__ == "__main__":
    print("[INFO] Starting Hardened Antigravity MCP Server...")
    mcp.run(transport="sse")
