"""
OpenAPI 3.0 Specification & Plugin Manifest Generator for ChatGPT & Claude Actions
Enables ChatGPT to call all 22 bridge tools via Custom GPT Actions or OpenAI Plugins.
"""

from typing import Dict, Any

def get_ai_plugin_manifest(public_url: str) -> Dict[str, Any]:
    base_url = public_url if public_url else "http://127.0.0.1:8000"
    return {
        "schema_version": "v1",
        "name_for_human": "Gemini Antigravity Bridge",
        "name_for_model": "gemini_antigravity_bridge",
        "description_for_human": "Bridge to control local machine files, terminal, compilers, and Antigravity IDE.",
        "description_for_model": "Plugin for executing local system commands, writing files, reading files, creating projects, and dispatching agent tasks to Antigravity IDE on the user PC.",
        "auth": {
            "type": "none"
        },
        "api": {
            "type": "openapi",
            "url": f"{base_url}/openapi.json"
        },
        "logo_url": f"{base_url}/dashboard",
        "contact_email": "admin@local.bridge",
        "legal_info_url": "https://github.com/nandhakumar-murugan/gemini-antigravity-bridge"
    }


def get_openapi_schema(public_url: str) -> Dict[str, Any]:
    base_url = public_url if public_url else "http://127.0.0.1:8000"
    return {
        "openapi": "3.0.1",
        "info": {
            "title": "Gemini Antigravity Bridge API",
            "description": "API for executing terminal commands, file operations, and Antigravity IDE agent tasks.",
            "version": "v1.0.0"
        },
        "servers": [
            {
                "url": base_url
            }
        ],
        "paths": {
            "/api/v1/run_system_command": {
                "post": {
                    "operationId": "run_system_command",
                    "summary": "Execute a shell or PowerShell command on the user's PC",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "command": {"type": "string", "description": "Shell command to run (e.g. python test.py, git status)"},
                                        "working_dir": {"type": "string", "description": "Working directory (optional)"}
                                    },
                                    "required": ["command"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Command execution result",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "result": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/api/v1/write_file": {
                "post": {
                    "operationId": "write_file",
                    "summary": "Create or overwrite a file on the local computer",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "file_path": {"type": "string", "description": "File path to write"},
                                        "content": {"type": "string", "description": "Full file content"}
                                    },
                                    "required": ["file_path", "content"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Write status",
                            "content": {"application/json": {"schema": {"type": "object", "properties": {"result": {"type": "string"}}}}}
                        }
                    }
                }
            },
            "/api/v1/read_file": {
                "post": {
                    "operationId": "read_file",
                    "summary": "Read content of a file from the local computer",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "file_path": {"type": "string", "description": "File path to read"}
                                    },
                                    "required": ["file_path"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "File content",
                            "content": {"application/json": {"schema": {"type": "object", "properties": {"content": {"type": "string"}}}}}
                        }
                    }
                }
            },
            "/api/v1/create_full_project": {
                "post": {
                    "operationId": "create_full_project",
                    "summary": "Create a full project directory, write all files, and run tests in 1 shot",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "project_name": {"type": "string", "description": "Name of the project folder"},
                                        "files": {"type": "object", "additionalProperties": {"type": "string"}, "description": "Dictionary of filename to content"},
                                        "setup_commands": {"type": "array", "items": {"type": "string"}, "description": "Commands to execute (e.g. pytest)"}
                                    },
                                    "required": ["project_name", "files"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Project creation report",
                            "content": {"application/json": {"schema": {"type": "object", "properties": {"report": {"type": "string"}}}}}
                        }
                    }
                }
            },
            "/api/v1/send_spark_to_antigravity_task": {
                "post": {
                    "operationId": "send_spark_to_antigravity_task",
                    "summary": "Dispatch a structured task brief into Antigravity IDE workspace",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "objective": {"type": "string", "description": "Primary goal for Antigravity"},
                                        "context": {"type": "string", "description": "Context or file paths"},
                                        "required_actions": {"type": "array", "items": {"type": "string"}, "description": "Step by step actions"}
                                    },
                                    "required": ["objective"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Task dispatch confirmation",
                            "content": {"application/json": {"schema": {"type": "object", "properties": {"result": {"type": "string"}}}}}
                        }
                    }
                }
            },
            "/api/v1/get_antigravity_agent_report": {
                "get": {
                    "operationId": "get_antigravity_agent_report",
                    "summary": "Get Antigravity IDE execution report, modified files, and test results",
                    "responses": {
                        "200": {
                            "description": "Antigravity execution status",
                            "content": {"application/json": {"schema": {"type": "object", "properties": {"report": {"type": "string"}}}}}
                        }
                    }
                }
            },
            "/api/v1/list_antigravity_conversations": {
                "get": {
                    "operationId": "list_antigravity_conversations",
                    "summary": "List all active Antigravity conversations and projects",
                    "responses": {
                        "200": {
                            "description": "Conversation list",
                            "content": {"application/json": {"schema": {"type": "object", "properties": {"conversations": {"type": "string"}}}}}
                        }
                    }
                }
            }
        }
    }
