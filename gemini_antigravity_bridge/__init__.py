"""Gemini Antigravity Bridge: Bidirectional MCP Bridge between Google Gemini Spark & DeepMind Antigravity."""

__version__ = "1.4.0"

from .server import mcp
from .cli import main

__all__ = ["mcp", "main", "__version__"]
