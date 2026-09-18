"""
Unit & Integration Test Suite for Gemini Antigravity Bridge
Run via: pytest tests/
"""

import os
import sys
import pytest
import json

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server import (
    mcp, save_session_note, _load_history, get_spark_connected_apps_catalog,
    list_antigravity_conversations, get_antigravity_agent_report
)
import run_with_tunnel


def test_tools_registered():
    """Verify that all core MCP tools are registered."""
    tools = mcp._tool_manager.list_tools()
    tool_names = {t.name for t in tools}
    
    expected_tools = {
        "run_system_command", "read_file", "write_file", "edit_file",
        "append_file", "batch_write_files", "run_batch_commands",
        "create_full_project", "list_directory", "git_quick_status",
        "run_agent_task", "get_agent_status", "terminate_task",
        "get_bridge_history", "save_session_note", "get_session_notes",
        "sync_project_to_gemini", "request_spark_connected_app_action",
        "get_spark_connected_apps_catalog", "list_antigravity_conversations",
        "inject_message", "send_spark_to_antigravity_task",
        "get_antigravity_agent_report", "get_security_audit_log"
    }
    
    missing = expected_tools - tool_names
    assert not missing, f"Missing registered tools: {missing}"
    assert len(tools) >= 24, f"Expected at least 24 tools, found {len(tools)}"


def test_session_note_lifecycle():
    """Verify note saving and history retrieval."""
    test_note = "Pytest Automated Verification Note"
    res = save_session_note(note=test_note, tag="pytest", source="test_suite")
    assert "[Success]" in res
    
    history = _load_history()
    assert len(history) > 0
    latest = history[-1]
    assert latest.get("tool") == "save_session_note"
    assert latest.get("inputs", {}).get("tag") == "pytest"


def test_spark_connected_apps_catalog():
    """Verify Spark connected apps catalog output."""
    catalog = get_spark_connected_apps_catalog()
    assert "@Canva" in catalog
    assert "@Google Drive" in catalog
    assert "@Google Docs" in catalog
    assert "@YouTube" in catalog
    assert "@Gmail" in catalog


def test_antigravity_conversations_listing():
    """Verify Antigravity conversation scanner executes cleanly."""
    output = list_antigravity_conversations()
    assert isinstance(output, str)
    assert len(output) > 0


def test_agent_report_generation():
    """Verify formatted execution report generator."""
    report = get_antigravity_agent_report()
    assert "Antigravity Execution Reports" in report
    assert isinstance(report, str)


def test_security_command_sandboxing():
    """Verify OpenAgentShield AST sandboxing blocks dangerous commands and allows safe ones."""
    from server import run_system_command

    # Benign command
    benign_res = run_system_command(command="echo 'Hello Shield'")
    assert "[Exit Code: 0]" in benign_res
    assert "Hello Shield" in benign_res

    # Malicious root wipe command
    blocked_res = run_system_command(command="rm -rf /")
    assert "[Security Blocked]" in blocked_res
    assert "[OpenAgentShield Blocked]" in blocked_res

    # Chained reboot injection
    blocked_chain = run_system_command(command="echo 'test'; reboot")
    assert "[Security Blocked]" in blocked_chain


def test_security_sensitive_file_protection(tmp_path):
    """Verify OpenAgentShield blocks access to sensitive environment files."""
    from server import read_file, write_file

    # Block reading .env
    env_read = read_file(file_path="/app/production/.env")
    assert "[Security Blocked]" in env_read
    assert ".env" in env_read

    # Block writing to .env
    env_write = write_file(file_path=str(tmp_path / ".env"), content="SECRET=123")
    assert "[Security Blocked]" in env_write


def test_security_secret_redaction(tmp_path):
    """Verify OpenAgentShield redacts credentials in tool operations and audit logs."""
    from server import write_file, _log_action, _load_history

    mock_key = "".join(["AIza", "SyD9x8y7Z6w5V4u3T2s1R0qP_", "unitTestKey123"])
    test_file = tmp_path / "safe_config.txt"

    # Writing file with API key should sanitize the key
    res = write_file(file_path=str(test_file), content=f"API_KEY={mock_key}")
    assert "[Success]" in res
    
    with open(test_file, "r") as f:
        written_content = f.read()
    assert mock_key not in written_content
    assert "[REDACTED:GOOGLE_API_KEY]" in written_content

    # Logging action with secret should also redact in history
    _log_action("test_tool", {"secret_param": mock_key}, f"Key used: {mock_key}")
    history = _load_history()
    latest = history[-1]
    assert mock_key not in json.dumps(latest)
    assert "[REDACTED:GOOGLE_API_KEY]" in json.dumps(latest)


def test_security_audit_log():
    """Verify OpenAgentShield telemetry tool output."""
    from server import get_security_audit_log

    audit_json = get_security_audit_log(limit=5)
    data = json.loads(audit_json)
    assert data["shield_engine"] == "OpenAgentShield Zero-Trust AI Firewall"
    assert data["paper_doi"] == "10.5281/zenodo.22259022"
    assert "policy_active" in data
    assert "total_audited_events" in data


def test_app_routes():
    """Verify Starlette application route registration including /api/security."""
    app = run_with_tunnel.create_app()
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    
    assert "/mcp" in paths
    assert "/sse" in paths
    assert "/webhook" in paths
    assert "/api/webhook" in paths
    assert "/dashboard" in paths
    assert "/api/security" in paths
