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

# ─── OpenAgentShield Zero-Trust Security Gateway ─────────────────────────────
# Based on research DOI: 10.5281/zenodo.22259022
try:
    from .security import (
        AgentFirewall,
        SecretSanitizer,
        ActionVerdict,
        EvaluationResult,
        SecurityPolicy,
    )
except ImportError:
    from gemini_antigravity_bridge.security import (
        AgentFirewall,
        SecretSanitizer,
        ActionVerdict,
        EvaluationResult,
        SecurityPolicy,
    )

# Initialize global Zero-Trust Firewall
firewall = AgentFirewall()


# ─── Security & Safety Helpers ────────────────────────────────────────────────

def _is_safe_command(cmd: str) -> tuple[bool, str]:
    """Check if command contains destructive system commands using OpenAgentShield AST rules."""
    eval_res = firewall.inspect_tool_call("run_command", {"CommandLine": cmd})
    if eval_res.verdict == ActionVerdict.BLOCK:
        return False, f"[OpenAgentShield Blocked] (Risk: {eval_res.risk_score}/100) {', '.join(eval_res.reasons)}"
    return True, ""


def _is_safe_file_access(file_path: str, tool_name: str = "read_file", content: Optional[str] = None) -> tuple[bool, str, Optional[str]]:
    """Validates file access against OpenAgentShield policy and redacts sensitive credentials."""
    args = {"AbsolutePath": file_path}
    if content:
        args["CodeContent"] = content
    eval_res = firewall.inspect_tool_call(tool_name, args)
    if eval_res.verdict == ActionVerdict.BLOCK:
        return False, f"[OpenAgentShield Blocked] (Risk: {eval_res.risk_score}/100) {', '.join(eval_res.reasons)}", None
    sanitized_content = eval_res.sanitized_arguments.get("CodeContent", content)
    return True, "", sanitized_content


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
    # Sanitize inputs to prevent credentials leaking into bridge_history.json
    sanitized_inputs = {}
    for k, v in inputs.items():
        if isinstance(v, str):
            clean_val, _ = SecretSanitizer.scan_and_redact(v)
            sanitized_inputs[k] = clean_val
        elif isinstance(v, dict):
            clean_dict = {}
            for sub_k, sub_v in v.items():
                if isinstance(sub_v, str):
                    clean_sub, _ = SecretSanitizer.scan_and_redact(sub_v)
                    clean_dict[sub_k] = clean_sub
                else:
                    clean_dict[sub_k] = sub_v
            sanitized_inputs[k] = clean_dict
        else:
            sanitized_inputs[k] = v

    clean_result, _ = SecretSanitizer.scan_and_redact(result)

    history.append({
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "tool": tool,
        "inputs": sanitized_inputs,
        "result_preview": clean_result[:300] + ("..." if len(clean_result) > 300 else ""),
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
    Reads the content of a file from the local filesystem with OpenAgentShield validation.
    """
    abs_path = _resolve_safe_path(file_path)
    is_safe, reason, _ = _is_safe_file_access(abs_path, "read_file")
    if not is_safe:
        return f"[Security Blocked] {reason}"

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
    Enforces OpenAgentShield file safety checks and secret redaction.
    """
    abs_path = _resolve_safe_path(file_path)
    is_safe, reason, sanitized_content = _is_safe_file_access(abs_path, "write_file", content)
    if not is_safe:
        return f"[Security Blocked] {reason}"
    final_content = sanitized_content if sanitized_content is not None else content

    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(final_content)
        result = f"[Success] File written to {abs_path} ({len(final_content)} bytes)"
        _log_action("write_file", {"file_path": abs_path, "content_length": len(final_content)},
                    result, source or "gemini_spark")
        return result
    except Exception as e:
        return f"[Error] Failed to write file: {str(e)}"


@mcp.tool()
def edit_file(file_path: str, find_text: str, replace_text: str, source: Optional[str] = None) -> str:
    """
    Performs a precise surgical search-and-replace edit in an existing file.
    Avoids having to rewrite the entire file when making targeted code changes.
    Enforces OpenAgentShield sensitive file access boundaries.
    """
    abs_path = _resolve_safe_path(file_path)
    is_safe, reason, _ = _is_safe_file_access(abs_path, "write_to_file")
    if not is_safe:
        return f"[Security Blocked] {reason}"

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
    Enforces OpenAgentShield sensitive file access boundaries.
    """
    abs_path = _resolve_safe_path(file_path)
    is_safe, reason, sanitized_content = _is_safe_file_access(abs_path, "write_to_file", content)
    if not is_safe:
        return f"[Security Blocked] {reason}"
    final_content = sanitized_content if sanitized_content is not None else content

    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "a", encoding="utf-8") as f:
            f.write(final_content)
        result = f"[Success] Appended {len(final_content)} bytes to {abs_path}"
        _log_action("append_file", {"file_path": abs_path, "bytes": len(final_content)},
                    result, source or "gemini_spark")
        return result
    except Exception as e:
        return f"[Error] Failed to append to file: {str(e)}"


# ─── Composite / Batch Operations (1 Permission Click for Entire Tasks) ───────

@mcp.tool()
def batch_write_files(files: Dict[str, str], base_dir: Optional[str] = None, source: Optional[str] = None) -> str:
    """
    Creates or updates multiple files in a single tool call.
    Includes OpenAgentShield security validation for all target paths.
    """
    root = _resolve_safe_path(base_dir if base_dir else BASE_DIR)
    results = []
    success_count = 0

    for rel_path, content in files.items():
        abs_path = os.path.abspath(rel_path if os.path.isabs(rel_path) else os.path.join(root, rel_path))
        is_safe, reason, sanitized_content = _is_safe_file_access(abs_path, "write_file", content)
        if not is_safe:
            results.append(f"  🛡️ Blocked: {rel_path} - {reason}")
            continue
        final_content = sanitized_content if sanitized_content is not None else content

        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(final_content)
            results.append(f"  ✅ Written: {os.path.relpath(abs_path, root)} ({len(final_content)} bytes)")
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


# ─── OpenAgentShield Telemetry Tool ──────────────────────────────────────────

@mcp.tool()
def get_security_audit_log(limit: Optional[int] = 20, source: Optional[str] = None) -> str:
    """
    Retrieves the OpenAgentShield Zero-Trust security audit log and risk telemetry.
    Shows intercepted, blocked, and redacted tool invocations.
    Based on research DOI: 10.5281/zenodo.22259022
    """
    events = firewall.audit_log[-limit:] if hasattr(firewall, "audit_log") and firewall.audit_log else []

    summary = {
        "shield_engine": "OpenAgentShield Zero-Trust AI Firewall",
        "paper_doi": "10.5281/zenodo.22259022",
        "policy_active": firewall.policy.policy_name,
        "enforce_secret_redaction": firewall.policy.enforce_secret_redaction,
        "enforce_shell_sandboxing": firewall.policy.enforce_shell_sandboxing,
        "total_audited_events": len(firewall.audit_log),
        "recent_intercepted_events": [
            {
                "tool": e.tool_name,
                "verdict": e.verdict.value if hasattr(e.verdict, "value") else str(e.verdict),
                "risk_score": e.risk_score,
                "reasons": e.reasons,
                "timestamp": e.timestamp,
            }
            for e in events
        ]
    }
    return json.dumps(summary, indent=2)


# ─── Screen Vision & Desktop Control (Astra-like Computer Use) ───────────────

try:
    from .screen_vision import (
        take_screenshot as _take_screenshot,
        get_screen_size,
        get_mouse_position,
        get_open_windows,
        get_desktop_overview,
        execute_action_plan as _execute_action_plan,
        move_mouse as _move_mouse,
        click_mouse as _click_mouse,
        type_text as _type_text,
        press_key as _press_key,
        scroll_screen as _scroll_screen,
        drag_mouse as _drag_mouse,
    )
except ImportError:
    from gemini_antigravity_bridge.screen_vision import (
        take_screenshot as _take_screenshot,
        get_screen_size,
        get_mouse_position,
        get_open_windows,
        get_desktop_overview,
        execute_action_plan as _execute_action_plan,
        move_mouse as _move_mouse,
        click_mouse as _click_mouse,
        type_text as _type_text,
        press_key as _press_key,
        scroll_screen as _scroll_screen,
        drag_mouse as _drag_mouse,
    )


try:
    from .multimedia import (
        speak as _speak,
        read_clipboard as _read_clipboard,
        copy_to_clipboard as _copy_to_clipboard,
        show_desktop_notification as _show_desktop_notification,
    )
except ImportError:
    from gemini_antigravity_bridge.multimedia import (
        speak as _speak,
        read_clipboard as _read_clipboard,
        copy_to_clipboard as _copy_to_clipboard,
        show_desktop_notification as _show_desktop_notification,
    )


@mcp.tool()
async def speak_to_user(text: str, rate: int = 0) -> str:
    """
    🔊 SPEAK OUT LOUD THROUGH LAPTOP SPEAKERS (Windows SAPI5 Voice).
    Use this whenever you want to audibly alert or speak directly to the user through their laptop speakers
    (e.g., announcing task completion, warning about an urgent deadline, or talking aloud to the user).

    Args:
        text: The text to speak aloud through laptop speakers.
        rate: Speech speed rate (-10 to 10, default 0 = normal speed).
    """
    res = _speak(text, rate=rate)
    return json.dumps(res)


@mcp.tool()
async def show_desktop_notification(title: str, message: str) -> str:
    """
    🔔 NATIVE WINDOWS DESKTOP NOTIFICATION.
    Pops up a Windows notification banner in the bottom-right corner of the user's screen with sound.

    Args:
        title: Notification title (e.g. 'KGiSL Academic Alert' or 'Gemini Antigravity').
        message: Notification message content.
    """
    res = _show_desktop_notification(title=title, message=message)
    return json.dumps(res)


@mcp.tool()
async def read_clipboard() -> str:
    """
    📋 READ WINDOWS CLIPBOARD.
    Reads the text currently stored in the user's Windows clipboard.
    """
    res = _read_clipboard()
    return json.dumps(res)


@mcp.tool()
async def copy_to_clipboard(text: str) -> str:
    """
    📋 COPY TO WINDOWS CLIPBOARD.
    Copies text or code directly to the user's Windows clipboard so they can press Ctrl+V to paste it anywhere.

    Args:
        text: The text or code to copy.
    """
    res = _copy_to_clipboard(text)
    return json.dumps(res)


# ─── Window Management & System Telemetry Suite ──────────────────────────────
try:
    from .window_manager import (
        get_active_window as _get_active_window,
        focus_window as _focus_window,
        maximize_window as _maximize_window,
        minimize_window as _minimize_window,
        close_window as _close_window,
        get_system_telemetry as _get_system_telemetry,
    )
except ImportError:
    from gemini_antigravity_bridge.window_manager import (
        get_active_window as _get_active_window,
        focus_window as _focus_window,
        maximize_window as _maximize_window,
        minimize_window as _minimize_window,
        close_window as _close_window,
        get_system_telemetry as _get_system_telemetry,
    )


@mcp.tool()
async def focus_window(title_substring: str) -> str:
    """
    🪟 FOCUS APPLICATION WINDOW.
    Brings any open window matching title_substring to the front of the screen and restores it.
    Use this before typing into an application to guarantee it has active focus.

    Args:
        title_substring: Part of the window title (e.g. 'Visual Studio Code', 'Chrome', 'Notepad').
    """
    res = _focus_window(title_substring)
    return json.dumps(res)


@mcp.tool()
async def get_active_window() -> str:
    """
    🔍 GET CURRENT FOREGROUND WINDOW.
    Returns the exact title, process name, PID, and pixel bounding box of the currently active window.
    """
    res = _get_active_window()
    return json.dumps(res)


@mcp.tool()
async def maximize_window(title_substring: str) -> str:
    """
    🔲 MAXIMIZE APPLICATION WINDOW.
    Maximizes the window matching title_substring on screen.

    Args:
        title_substring: Part of the window title.
    """
    res = _maximize_window(title_substring)
    return json.dumps(res)


@mcp.tool()
async def minimize_window(title_substring: str) -> str:
    """
    ➖ MINIMIZE APPLICATION WINDOW.
    Minimizes the window matching title_substring to the taskbar.

    Args:
        title_substring: Part of the window title.
    """
    res = _minimize_window(title_substring)
    return json.dumps(res)


@mcp.tool()
async def close_window(title_substring: str) -> str:
    """
    ❌ CLOSE APPLICATION WINDOW.
    Gracefully closes the application matching title_substring (equivalent to clicking the X button).

    Args:
        title_substring: Part of the window title.
    """
    res = _close_window(title_substring)
    return json.dumps(res)


@mcp.tool()
async def get_system_telemetry() -> str:
    """
    🔋 GET LAPTOP HARDWARE TELEMETRY & BATTERY.
    Returns real-time laptop health: battery percentage, charging state, CPU %, and available RAM.
    """
    res = _get_system_telemetry()
    return json.dumps(res)


@mcp.tool()
async def inspect_desktop_overview(include_screenshot: bool = True) -> str:


    """
    🖥️ UNIFIED DESKTOP & SCREEN INSPECTOR (Astra Computer Vision).
    Use this tool whenever the user naturally asks about their computer, what is on screen,
    which apps or windows are open, or asks you to 'look at my screen', 'see my computer',
    'what am I doing?', or for general computer assistance.

    Returns in ONE SINGLE CALL (requiring only 1 user permission):
      1. Full visual desktop screenshot (base64 PNG)
      2. List of all active application windows and their titles
      3. Screen resolution and current mouse coordinates

    Args:
        include_screenshot: True to capture the full visual image, False for window list only.
    """
    try:
        data = get_desktop_overview(include_screenshot=include_screenshot)
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def perform_computer_task(
    task_summary: str,
    launch_app_via_search: Optional[str] = None,
    focus_window_first: Optional[str] = None,
    type_text_into_window: Optional[str] = None,
    gui_steps: Optional[list[dict]] = None,
    launch_command: Optional[str] = None,
    file_path: Optional[str] = None,
    file_content: Optional[str] = None,
    verify_screen: bool = True,
    speak_announcement: Optional[str] = None,
) -> str:
    """
    🚀 MASTER COMPUTER AGENT — ALWAYS USE THIS TOOL FIRST FOR ANY USER COMPUTER WORK!

    🚨 CRITICAL OPERATING PRINCIPLE: 100% HUMAN DESKTOP INTERACTION BY DEFAULT
    - BY DEFAULT, YOU MUST ALWAYS ACT LIKE A REAL HUMAN SITTING AT THE COMPUTER:
      1. To open ANY application (Notepad, VS Code, Browser, Settings, Calculator, etc.):
         Use `launch_app_via_search="Notepad"` (or `"Visual Studio Code"`).
         The bridge interacts exactly like a human:
         Presses Windows key -> types the app name into Start Menu search -> presses Enter!
         This completely avoids terminal glitches and ensures clean GUI app launches.
      2. To write text, numbers, or code into an open app:
         Use `type_text_into_window="your text here"`. The bridge will click inside the document area,
         focus the editor, and paste the content cleanly.
      3. To save files or perform app shortcuts:
         Use `gui_steps` with `{"action": "hotkey", "keys": ["ctrl", "s"]}`.
      4. STRICT COMMAND RULE:
         DO NOT use `launch_command` or terminal commands UNLESS the user EXPLICITLY says:
         'use terminal', 'use command line', or 'run in cmd'.
         For all normal user requests, ALWAYS default to human mouse and keyboard interaction!

    Args:
      task_summary: A concise, human-readable summary of the implementation plan.
      launch_app_via_search: Preferred app name to launch via Start Menu (e.g. "Notepad", "Visual Studio Code").
      focus_window_first: Target window title to focus and verify before GUI typing (e.g. 'Notepad', 'Visual Studio Code').
      type_text_into_window: Optional text, numbers, or code to write directly into the active window.
      gui_steps: Optional sequence of mouse/keyboard actions (clicks, typing, hotkeys).
      launch_command: ONLY use if user explicitly asked for command-line execution (e.g. "cmd.exe", "python ...").
      file_path: Optional backend file path if explicitly requested.
      file_content: Optional backend file content if explicitly requested.
      verify_screen: Automatically confirms active windows after execution.
      speak_announcement: Spoken voice confirmation through laptop speakers upon completion.
    """

    results = {"task_summary": task_summary, "status": "ok", "steps_completed": []}

    # Step 1: Write file if explicitly requested
    if file_path and file_content is not None:
        try:
            resolved = _resolve_safe_path(file_path)
            safe, msg, sanitized = _is_safe_file_access(resolved, "write_file", file_content)
            if not safe:
                results["status"] = "blocked"
                results["error"] = f"File write blocked by security policy: {msg}"
                _log_action("perform_computer_task", {"task_summary": task_summary, "file_path": resolved}, json.dumps(results))
                return json.dumps(results)
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(sanitized if sanitized is not None else file_content)
            results["steps_completed"].append(f"Written file: {resolved}")
        except Exception as e:
            results["steps_completed"].append(f"File write error: {e}")

    # Step 2: Launch application via Start Menu search (Human style, DEFAULT)
    app_to_search = launch_app_via_search
    if not app_to_search and launch_command:
        cmd_clean = launch_command.lower().strip()
        if cmd_clean in ("code", "visual studio code", "vs code", "vscode"):
            app_to_search = "visual studio code"
        elif cmd_clean in ("notepad", "notepad.exe", "wordpad", "wordpad.exe"):
            app_to_search = "notepad"

    if app_to_search:
        try:
            _press_key("win")
            await asyncio.sleep(0.6)
            _type_text(app_to_search, interval=0.03)
            await asyncio.sleep(0.6)
            _press_key("enter")
            results["steps_completed"].append(f"Launched '{app_to_search}' via Windows Start search (human-like)")
            await asyncio.sleep(2.5)
        except Exception as e:
            results["steps_completed"].append(f"Start search launch error: {e}")
    elif launch_command and not any("Launched" in s for s in results["steps_completed"]):
        try:
            safe, msg = _is_safe_command(launch_command)
            if not safe:
                results["status"] = "blocked"
                results["error"] = f"Command blocked by policy: {msg}"
                _log_action("perform_computer_task", {"task_summary": task_summary, "launch_command": launch_command}, json.dumps(results))
                return json.dumps(results)
            subprocess.Popen(f'cmd.exe /c start "" {launch_command}', shell=True)
            results["steps_completed"].append(f"Launched command: {launch_command}")
            await asyncio.sleep(2.0)
        except Exception as e:
            results["steps_completed"].append(f"Launch error: {e}")

    # Step 2.5: Focus target window with polling and STRICT safety verification
    if focus_window_first:
        focused = False
        focused_title = ""
        # Poll up to 10 seconds (20 iterations x 0.5s) for the app window to render
        for _ in range(20):
            res = _focus_window(focus_window_first)
            if res.get("status") == "ok":
                focused = True
                focused_title = res.get("focused", focus_window_first)
                results["steps_completed"].append(f"Focused window: '{focused_title}'")
                await asyncio.sleep(1.0)
                break
            await asyncio.sleep(0.5)

        if not focused:
            results["status"] = "failed"
            results["error"] = (
                f"Target window matching '{focus_window_first}' did not appear after launching. "
                f"GUI actions were ABORTED for safety to prevent typing into the wrong window."
            )
            _log_action("perform_computer_task", {"task_summary": task_summary, "target_window": focus_window_first}, json.dumps(results))
            return json.dumps(results)

    # Step 2.7: Human-like typing into active document window
    if type_text_into_window:
        try:
            from .window_manager import get_active_window
            from .multimedia import copy_to_clipboard
        except ImportError:
            from gemini_antigravity_bridge.window_manager import get_active_window
            from gemini_antigravity_bridge.multimedia import copy_to_clipboard

        try:
            active_info = get_active_window()
            if active_info.get("status") == "ok" and "bounds" in active_info:
                b = active_info["bounds"]
                cx = b["left"] + max(50, b["width"] // 2)
                cy = b["top"] + max(50, b["height"] // 2)
                _click_mouse(cx, cy)
            else:
                _click_mouse(350, 350)
            await asyncio.sleep(0.4)

            copy_to_clipboard(type_text_into_window)
            await asyncio.sleep(0.2)
            _press_key("ctrl+v")
            await asyncio.sleep(0.5)
            results["steps_completed"].append(f"Wrote {len(type_text_into_window)} characters directly into active window (human-like)")
        except Exception as e:
            results["steps_completed"].append(f"Window writing error: {e}")

    # Step 3: Execute GUI steps into the verified focused window
    if gui_steps:
        try:
            gui_res = _execute_action_plan(gui_steps, task_summary)
            results["gui_results"] = gui_res
            results["steps_completed"].append(f"Executed {len(gui_steps)} GUI action steps")
        except Exception as e:
            results["steps_completed"].append(f"GUI action error: {e}")

    # Step 4: Verify screen state automatically
    if verify_screen:
        try:
            overview = get_desktop_overview(include_screenshot=False)
            results["active_windows_after_task"] = overview.get("active_windows", [])
        except Exception as e:
            results["verification_error"] = str(e)

    # Step 5: Speak announcement out loud if requested
    if speak_announcement:
        try:
            _speak(speak_announcement)
            results["steps_completed"].append(f"Spoke aloud: '{speak_announcement}'")
        except Exception as e:
            results["speech_error"] = str(e)

    _log_action("perform_computer_task", {"task_summary": task_summary, "steps": len(results["steps_completed"])}, json.dumps(results))
    return json.dumps(results)



@mcp.tool()
async def execute_action_plan(plan_description: str, steps: list[dict]) -> str:

    """
    ⚡ AUTONOMOUS COMPUTER ACTION PLAN (Single Permission Execution).
    Use this to execute an entire plan of mouse and keyboard actions with a SINGLE user approval.
    Presents the plan description and executes all steps in sequence.

    Args:
        plan_description: A clear explanation of what this action sequence will do.
        steps: List of action dictionaries in order. Supported actions:
               - {"action": "move", "x": 500, "y": 500, "duration": 0.2}
               - {"action": "click", "x": 500, "y": 500, "button": "left", "clicks": 1}
               - {"action": "type", "text": "Hello World", "interval": 0.05}
               - {"action": "key", "key": "enter"}
               - {"action": "hotkey", "keys": ["ctrl", "c"]}
               - {"action": "scroll", "x": 500, "y": 500, "clicks": -3}
               - {"action": "wait", "seconds": 1.0}
    """
    try:
        result = _execute_action_plan(steps=steps, plan_description=plan_description)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})



@mcp.tool()
async def take_screenshot(region_left: int = 0, region_top: int = 0,
                           region_width: int = 0, region_height: int = 0,
                           annotate_coords: bool = False) -> str:
    """
    📸 Capture the full desktop screen (or a specific region) and return it as a
    base64-encoded PNG image. Use this to SEE the current state of the computer.

    Args:
        region_left: Left pixel of region (0 = full screen).
        region_top: Top pixel of region (0 = full screen).
        region_width: Width of region (0 = full screen).
        region_height: Height of region (0 = full screen).
        annotate_coords: If True, overlays pixel coordinate grid on the image.

    Returns:
        JSON with image_b64 (base64 PNG), width, height, and timestamp.
    """
    try:
        region = None
        if region_width > 0 and region_height > 0:
            region = (region_left, region_top, region_width, region_height)
        result = _take_screenshot(region=region, annotate_coords=annotate_coords)
        return json.dumps({
            "status": "ok",
            "width": result["width"],
            "height": result["height"],
            "mode": result["mode"],
            "timestamp": result["timestamp"],
            "image_b64": result["image_b64"],
            "note": f"Screenshot captured ({result['width']}x{result['height']} px). image_b64 contains the full PNG."
        })
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def get_screen_info() -> str:
    """
    🖥️ Get the current screen resolution and mouse cursor position.
    Use this before taking a screenshot or moving the mouse.

    Returns:
        JSON with screen width/height and current mouse x/y position.
    """
    try:
        screen = get_screen_size()
        mouse = get_mouse_position()
        return json.dumps({"status": "ok", "screen": screen, "mouse_position": mouse})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def move_mouse(x: int, y: int, duration: float = 0.3) -> str:
    """
    🖱️ Move the mouse cursor to a specific pixel position on screen.

    Args:
        x: Target X coordinate in pixels.
        y: Target Y coordinate in pixels.
        duration: Smooth animation time in seconds (0 = instant, 0.3 = smooth).
    """
    try:
        result = _move_mouse(x, y, duration=duration)
        return json.dumps({"status": "ok", **result})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def click_mouse(x: int = -1, y: int = -1, button: str = "left",
                       clicks: int = 1, interval: float = 0.1) -> str:
    """
    🖱️ Click the mouse at a position. Supports left/right/middle and double-click.

    Args:
        x: X coordinate (-1 = current position).
        y: Y coordinate (-1 = current position).
        button: 'left', 'right', or 'middle'.
        clicks: 1 = single click, 2 = double-click.
        interval: Seconds between clicks.
    """
    try:
        px = x if x >= 0 else None
        py = y if y >= 0 else None
        result = _click_mouse(px, py, button=button, clicks=clicks, interval=interval)
        return json.dumps({"status": "ok", **result})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def type_text(text: str, interval: float = 0.05) -> str:
    """
    ⌨️ Type a string of text using the keyboard at the current cursor focus.
    Works in any focused text field, terminal, browser, app window, etc.

    Args:
        text: The text to type.
        interval: Seconds between each key press (0.05 = natural speed).
    """
    try:
        result = _type_text(text, interval=interval)
        return json.dumps({"status": "ok", **result})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def press_key(key: str, presses: int = 1, interval: float = 0.1) -> str:
    """
    ⌨️ Press a keyboard key or hotkey combination.

    Keys: 'enter', 'escape', 'tab', 'space', 'backspace', 'delete',
          'up', 'down', 'left', 'right', 'f1'-'f12', 'win', 'home', 'end'

    Hotkeys (use +): 'ctrl+c', 'ctrl+v', 'ctrl+z', 'alt+tab',
                     'ctrl+alt+delete', 'win+d', 'ctrl+shift+t'

    Args:
        key: Key name or '+'-joined hotkey combo.
        presses: Number of times to press the key.
        interval: Seconds between repeated presses.
    """
    try:
        result = _press_key(key, presses=presses, interval=interval)
        return json.dumps({"status": "ok", **result})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def scroll_screen(x: int, y: int, clicks: int = 3, direction: str = "down") -> str:
    """
    🖱️ Scroll the mouse wheel at a specific position on screen.

    Args:
        x: X coordinate to scroll at.
        y: Y coordinate to scroll at.
        clicks: Number of scroll clicks (magnitude).
        direction: 'up' or 'down'.
    """
    try:
        result = _scroll_screen(x, y, clicks=clicks, direction=direction)
        return json.dumps({"status": "ok", **result})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def drag_mouse(from_x: int, from_y: int, to_x: int, to_y: int,
                      duration: float = 0.5, button: str = "left") -> str:
    """
    🖱️ Click and drag the mouse from one position to another.
    Useful for moving windows, selecting text, drawing, or drag-and-drop.

    Args:
        from_x, from_y: Starting pixel coordinates.
        to_x, to_y: Ending pixel coordinates.
        duration: Drag animation time in seconds.
        button: Mouse button to hold during drag ('left', 'right', 'middle').
    """
    try:
        result = _drag_mouse(from_x, from_y, to_x, to_y, duration=duration, button=button)
        return json.dumps({"status": "ok", **result})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Gemini Antigravity Bridge MCP Server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse"], help="MCP transport mode")
    args, _ = parser.parse_known_args()

    if args.transport == "sse":
        print("[INFO] Starting Hardened Antigravity MCP Server on SSE...")
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

