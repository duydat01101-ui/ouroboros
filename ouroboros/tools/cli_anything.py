"""CLI-Anything integration for Ouroboros.

Provides tools to discover, install, and call CLI-Anything harnesses.
"""

import subprocess
import json
import os
import sys
from typing import Any, Dict, List, Optional
from pathlib import Path

from ouroboros.tools.registry import ToolContext, ToolEntry

class CLIAnythingManager:
    """Manages CLI-Anything harnesses."""

    def __init__(self):
        """Initialize manager."""
        self.cache = {}
        self.installed = set()
        self._refresh_installed()

    def _refresh_installed(self) -> None:
        """Refresh list of installed harnesses."""
        try:
            result = subprocess.run(
                ["pip", "list", "--format=json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                packages = json.loads(result.stdout)
                self.installed = {
                    p["name"].replace("cli-anything-", "")
                    for p in packages
                    if p["name"].startswith("cli-anything-")
                }
        except Exception as e:
            print(f"Error refreshing installed harnesses: {e}")

    def list_harnesses(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """List available harnesses."""
        try:
            cmd = ["cli-hub", "list", "--json"]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                harnesses = json.loads(result.stdout)
                if category:
                    harnesses = [h for h in harnesses if h.get("category") == category]
                return harnesses
            return []
        except Exception as e:
            print(f"Error listing harnesses: {e}")
            return []

    def search_harnesses(self, query: str) -> List[Dict[str, Any]]:
        """Search harnesses by name/description."""
        try:
            cmd = ["cli-hub", "search", query, "--json"]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
            return []
        except Exception as e:
            print(f"Error searching harnesses: {e}")
            return []

    def install_harness(self, name: str) -> bool:
        """Install a harness."""
        try:
            cmd = ["cli-hub", "install", name]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                self._refresh_installed()
                return True
            print(f"Install failed: {result.stderr}")
            return False
        except Exception as e:
            print(f"Error installing harness: {e}")
            return False

    def is_installed(self, name: str) -> bool:
        """Check if harness is installed."""
        return name in self.installed

    def get_harness_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get harness metadata."""
        try:
            cmd = ["cli-hub", "info", name, "--json"]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
            return None
        except Exception as e:
            print(f"Error getting harness info: {e}")
            return None

    def call_harness(
        self, name: str, args: List[str], json_output: bool = True
    ) -> Dict[str, Any]:
        """Call a harness command."""
        if not self.is_installed(name):
            return {
                "success": False,
                "error": f"Harness '{name}' not installed",
                "stdout": "",
                "stderr": "",
                "returncode": 1,
            }

        try:
            entry_point = f"cli-anything-{name}"
            cmd = [entry_point] + args
            if json_output and "--json" not in args:
                cmd.append("--json")

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60
            )

            output = result.stdout
            if json_output and result.returncode == 0:
                try:
                    output = json.loads(result.stdout)
                except json.JSONDecodeError:
                    pass

            return {
                "success": result.returncode == 0,
                "stdout": output,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Command timeout",
                "stdout": "",
                "stderr": "Command exceeded 60 second timeout",
                "returncode": 124,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": str(e),
                "returncode": 1,
            }

# Global manager instance
_manager = CLIAnythingManager()

# Tool functions
def _cli_anything_list(ctx: ToolContext, category: Optional[str] = None) -> str:
    """List available CLI-Anything harnesses."""
    harnesses = _manager.list_harnesses(category)
    return json.dumps({
        "success": True,
        "count": len(harnesses),
        "harnesses": harnesses,
    }, ensure_ascii=False, indent=2)

def _cli_anything_search(ctx: ToolContext, query: str) -> str:
    """Search CLI-Anything harnesses."""
    results = _manager.search_harnesses(query)
    return json.dumps({
        "success": True,
        "count": len(results),
        "results": results,
    }, ensure_ascii=False, indent=2)

def _cli_anything_install(ctx: ToolContext, name: str) -> str:
    """Install a CLI-Anything harness."""
    success = _manager.install_harness(name)
    return json.dumps({
        "success": success,
        "name": name,
        "message": f"Harness '{name}' installed successfully"
        if success
        else f"Failed to install harness '{name}'",
    }, ensure_ascii=False, indent=2)

def _cli_anything_info(ctx: ToolContext, name: str) -> str:
    """Get CLI-Anything harness info."""
    info = _manager.get_harness_info(name)
    if info:
        return json.dumps({"success": True, "info": info}, ensure_ascii=False, indent=2)
    return json.dumps({"success": False, "error": f"Harness '{name}' not found"}, ensure_ascii=False, indent=2)

def _cli_anything_call(ctx: ToolContext, name: str, command: str, args: Optional[str] = None) -> str:
    """Call a CLI-Anything harness command."""
    cmd_args = [command]
    if args:
        cmd_args.extend(args.split())
    result = _manager.call_harness(name, cmd_args)
    return json.dumps(result, ensure_ascii=False, indent=2)

def get_tools() -> List[ToolEntry]:
    """Return tool definitions for CLI-Anything integration."""
    return [
        ToolEntry("cli_anything_list", {
            "name": "cli_anything_list",
            "description": "List available CLI-Anything harnesses",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional category filter (3d, ai, audio, image, video, etc.)",
                    }
                },
            },
        }, _cli_anything_list),
        ToolEntry("cli_anything_search", {
            "name": "cli_anything_search",
            "description": "Search CLI-Anything harnesses by name or description",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    }
                },
                "required": ["query"],
            },
        }, _cli_anything_search),
        ToolEntry("cli_anything_install", {
            "name": "cli_anything_install",
            "description": "Install a CLI-Anything harness",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Harness name (e.g., 'gimp', 'blender', 'browser')",
                    }
                },
                "required": ["name"],
            },
        }, _cli_anything_install),
        ToolEntry("cli_anything_info", {
            "name": "cli_anything_info",
            "description": "Get information about a CLI-Anything harness",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Harness name",
                    }
                },
                "required": ["name"],
            },
        }, _cli_anything_info),
        ToolEntry("cli_anything_call", {
            "name": "cli_anything_call",
            "description": "Call a CLI-Anything harness command",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Harness name",
                    },
                    "command": {
                        "type": "string",
                        "description": "Command to run",
                    },
                    "args": {
                        "type": "string",
                        "description": "Additional arguments (space-separated)",
                    },
                },
                "required": ["name", "command"],
            },
        }, _cli_anything_call),
    ]
