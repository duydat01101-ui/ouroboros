"""Tool synthesis — CodeAct-inspired dynamic tool creation.

Lets Ouroboros write tool code, register it live, and call it
in the same session.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import logging
import os
import pathlib
import textwrap
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolEntry, ToolContext

log = logging.getLogger(__name__)

# Set by loop.py to inject the ToolRegistry
_registry: Any = None
_tools_dir: pathlib.Path = None


def _set_registry(reg: Any) -> None:
    global _registry
    _registry = reg


def _set_tools_dir(path: pathlib.Path) -> None:
    global _tools_dir
    _tools_dir = path


_TOOL_TEMPLATE = '''"""Auto-generated tool: {name}."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolEntry, ToolContext

log = logging.getLogger(__name__)


{code}


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("{name}", {{
            "name": "{name}",
            "description": {desc_json},
            "parameters": {params_json},
        }}, handle_{name}),
    ]
'''


def _validate_code(code: str) -> str:
    """Check code compiles. Returns empty string or error message."""
    try:
        ast.parse(code)
        return ""
    except SyntaxError as e:
        return f"SyntaxError: {e}"


def handle_create_tool(
    ctx: ToolContext,
    name: str = "",
    code: str = "",
    description: str = "",
    params: str = "",
) -> str:
    """Create a new tool by writing its source file and registering it.

    The 'params' should be a JSON object with 'properties' and 'required' keys.
    The 'code' must define a function named 'handle_{name}(ctx, **args)' returning str.
    """
    if not name or not code:
        return "⚠️ Provide 'name' and 'code' (Python source)."

    # Validate no special chars in name
    if not name.isidentifier():
        return f"⚠️ '{name}' is not a valid Python identifier."

    # Validate code compiles
    err = _validate_code(code)
    if err:
        return f"⚠️ Code has errors: {err}"

    # Build params schema
    try:
        params_obj = json.loads(params) if params else {"properties": {}, "required": []}
    except json.JSONDecodeError as e:
        return f"⚠️ Invalid params JSON: {e}"

    params_schema = {
        "type": "object",
        "properties": params_obj.get("properties", {}),
        "required": params_obj.get("required", []),
    }
    desc_json = json.dumps(description or f"Auto-generated tool: {name}")
    params_json = json.dumps(params_schema, ensure_ascii=False)

    # Generate file content
    file_content = _TOOL_TEMPLATE.format(
        name=name,
        code=code,
        desc_json=desc_json,
        params_json=params_json,
    )

    # Write file — prefer injected dir, fall back to ctx.repo_dir
    tools_dir = _tools_dir
    if tools_dir is None:
        try:
            tools_dir = ctx.repo_dir / "ouroboros" / "tools"
        except Exception:
            tools_dir = pathlib.Path("/app/ouroboros/tools")
    file_path = tools_dir / f"{name}.py"

    if file_path.exists():
        return f"⚠️ Tool file already exists: {file_path}"

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(file_content, encoding="utf-8")
    except Exception as e:
        return f"⚠️ Failed to write file: {e}"

    # Import and register
    try:
        mod = importlib.import_module(f"ouroboros.tools.{name}")
        importlib.reload(mod)
        if not hasattr(mod, "get_tools"):
            return f"⚠️ File written but module has no get_tools(). Manual fix needed."

        count = 0
        for entry in mod.get_tools():
            if _registry is not None:
                _registry.register(entry)
            count += 1

        return json.dumps({
            "status": "ok",
            "file": str(file_path),
            "tools_registered": count,
            "tool_names": [entry.name for entry in mod.get_tools()],
        }, indent=2)
    except Exception as e:
        return f"⚠️ File written ({file_path}) but registration failed: {e}"


def handle_tool_factory(
    ctx: ToolContext,
    name: str = "",
    description: str = "",
    params: str = "",
    code_body: str = "",
) -> str:
    """Create a lightweight tool on-the-fly (no file written).

    'params' is a JSON object with 'properties' and 'required'.
    'code_body' is the function body (indented). The handler is:
        def handle_{name}(ctx, **kwargs):
            {code_body}
    """
    if not name or not code_body:
        return "⚠️ Provide 'name' and 'code_body'."

    if not name.isidentifier():
        return f"⚠️ '{name}' is not a valid Python identifier."

    # Parse params
    try:
        params_obj = json.loads(params) if params else {"properties": {}, "required": []}
    except json.JSONDecodeError as e:
        return f"⚠️ Invalid params JSON: {e}"

    params_schema = {
        "type": "object",
        "properties": params_obj.get("properties", {}),
        "required": params_obj.get("required", []),
    }

    # Build and validate the full handler code
    indented_body = textwrap.indent(code_body, "    ")
    handler_src = f"def handle_{name}(ctx, **kwargs):\n{indented_body}"

    err = _validate_code(handler_src)
    if err:
        return f"⚠️ Code body has errors: {err}"

    # Compile and create handler
    try:
        import json as _json_mod
        local_ns: Dict[str, Any] = {"json": _json_mod, "logging": logging}
        exec(compile(ast.parse(handler_src), f"<{name}>", "exec"), local_ns)
        handler = local_ns.get(f"handle_{name}")
        if handler is None:
            return f"⚠️ Compiled but handle_{name} not found in namespace."
    except Exception as e:
        return f"⚠️ Compilation failed: {e}"

    # Register
    entry = ToolEntry(
        name=name,
        schema={
            "name": name,
            "description": description or f"Auto-generated tool: {name}",
            "parameters": params_schema,
        },
        handler=handler,
    )

    if _registry is not None:
        _registry.register(entry)

    return json.dumps({
        "status": "ok",
        "tool": name,
        "description": description,
        "method": "runtime (no file written)",
        "registered": _registry is not None,
    }, indent=2)


def handle_list_synthesized(ctx: ToolContext) -> str:
    """List all tools created via tool_factory (runtime-only)."""
    if _registry is None:
        return "(no registry)"

    avail = _registry.available_tools()
    core = {"repo_read", "repo_list", "repo_commit_push", "drive_read", "drive_list",
            "drive_write", "run_shell", "claude_code_edit", "git_status", "git_diff",
            "schedule_task", "wait_for_task", "get_task_result", "update_scratchpad",
            "update_identity", "update_user_context", "chat_history", "web_search",
            "send_owner_message", "switch_model", "request_restart", "promote_to_stable",
            "knowledge_read", "knowledge_write", "browse_page", "browser_action",
            "analyze_screenshot", "list_available_tools", "enable_tools"}

    non_core = sorted(set(avail) - core)
    return json.dumps({"all_tools": len(avail), "non_core": non_core}, indent=2)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("create_tool", {
            "name": "create_tool",
            "description": "Create a new tool by writing a .py file to ouroboros/tools/ and registering it live. Provide name (identifier), code (Python source with handle_{name}(ctx, **args) function), description, and params JSON.",
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "description": "Tool name (valid Python identifier)"},
                "code": {"type": "string", "description": "Python source defining handle_{name}(ctx, **kwargs) returning str"},
                "description": {"type": "string", "description": "Tool description"},
                "params": {"type": "string", "description": "JSON: {\"properties\": {...}, \"required\": [...]}"},
            }, "required": ["name", "code"]},
        }, handle_create_tool),
        ToolEntry("tool_factory", {
            "name": "tool_factory",
            "description": "Create a lightweight tool on-the-fly (no file written, runtime only). Provide name, code_body (function body), description, and params JSON.",
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "description": "Tool name (valid Python identifier)"},
                "description": {"type": "string", "description": "Tool description"},
                "params": {"type": "string", "description": "JSON: {\"properties\": {...}, \"required\": [...]}"},
                "code_body": {"type": "string", "description": "Function body for handle_{name}(ctx, **kwargs)"},
            }, "required": ["name", "code_body"]},
        }, handle_tool_factory),
        ToolEntry("list_synthesized", {
            "name": "list_synthesized",
            "description": "List all currently-registered non-core tools (including synthesized ones).",
            "parameters": {"type": "object", "properties": {}},
        }, handle_list_synthesized),
    ]
