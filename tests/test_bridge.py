"""
Unit & Integration Test Suite for Gemini Antigravity Bridge
Run via: pytest tests/
"""

import os
import sys
import pytest

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
        "get_antigravity_agent_report"
    }
    
    missing = expected_tools - tool_names
    assert not missing, f"Missing registered tools: {missing}"
    assert len(tools) >= 23, f"Expected at least 23 tools, found {len(tools)}"


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


def test_app_routes():
    """Verify Starlette application route registration."""
    app = run_with_tunnel.create_app()
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    
    assert "/mcp" in paths
    assert "/sse" in paths
    assert "/webhook" in paths
    assert "/api/webhook" in paths
    assert "/dashboard" in paths
