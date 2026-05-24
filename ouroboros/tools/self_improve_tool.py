"""Self-improvement tools — Voyager-inspired recursive improvement.

Enables Ouroboros to analyse its own performance, generate improvements,
and build a skill library of reusable patterns.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolEntry, ToolContext
from ouroboros.self_improve import SelfImprover, SkillLibrary

log = logging.getLogger(__name__)

_registry: Any = None


def _set_registry(reg: Any) -> None:
    global _registry
    _registry = reg


def _make_improver(ctx: ToolContext) -> SelfImprover:
    return SelfImprover(drive_root=ctx.drive_root, repo_dir=ctx.repo_dir)


def handle_self_analyze(ctx: ToolContext, count: int = 20) -> str:
    """Analyse recent tasks for failure patterns and improvement opportunities."""
    improver = _make_improver(ctx)
    return improver.analyse_recent_tasks(count=count)


def handle_self_improve(ctx: ToolContext, analysis: str = "") -> str:
    """Generate a self-improvement suggestion using LLM analysis.

    Provide 'analysis' from self_analyze, or leave empty to auto-analyse.
    """
    improver = _make_improver(ctx)
    if not analysis:
        analysis = improver.analyse_recent_tasks(count=20)
    suggestion = improver.generate_improvement(analysis)
    try:
        data = json.loads(suggestion)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        return suggestion


def handle_skill_learn(ctx: ToolContext, name: str = "",
                       category: str = "code",
                       pattern: str = "",
                       example: str = "",
                       tags: str = "",
                       source: str = "") -> str:
    """Save a reusable skill/pattern to the skill library."""
    if not name or not pattern:
        return "⚠️ Provide 'name' and 'pattern'."
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    improver = _make_improver(ctx)
    fname = improver.skills.learn(name, category, pattern, example, tag_list, source)
    return json.dumps({
        "status": "ok",
        "skill": name,
        "file": fname,
        "category": category,
    }, indent=2)


def handle_skill_search(ctx: ToolContext, query: str = "",
                        max_results: int = 10, list_all: bool = False) -> str:
    """Search or list the skill library."""
    improver = _make_improver(ctx)
    if list_all:
        return improver.skills.list_recent()
    if not query:
        return "⚠️ Provide 'query' or set list_all=true."
    return improver.skills.search(query, max_results)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("self_analyze", {
            "name": "self_analyze",
            "description": "Analyse recent tasks for failure patterns and improvement opportunities.",
            "parameters": {"type": "object", "properties": {
                "count": {"type": "integer", "description": "Number of recent events to analyse (default 20)"},
            }, "required": []},
        }, handle_self_analyze),
        ToolEntry("self_improve", {
            "name": "self_improve",
            "description": "Generate a self-improvement suggestion. Optionally pass 'analysis' from self_analyze, or leave empty to auto-analyse.",
            "parameters": {"type": "object", "properties": {
                "analysis": {"type": "string", "description": "Analysis text from self_analyze (optional)"},
            }, "required": []},
        }, handle_self_improve),
        ToolEntry("skill_learn", {
            "name": "skill_learn",
            "description": "Save a reusable pattern to the skill library. Skills persist across restarts and can be searched later.",
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "description": "Skill name"},
                "category": {"type": "string", "description": "Category: code/tool/prompt/architecture/workflow"},
                "pattern": {"type": "string", "description": "Description of the pattern"},
                "example": {"type": "string", "description": "Code example (optional)"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "source": {"type": "string", "description": "Where this skill came from (e.g. task_id)"},
            }, "required": ["name", "pattern"]},
        }, handle_skill_learn),
        ToolEntry("skill_search", {
            "name": "skill_search",
            "description": "Search the skill library for reusable patterns. Set list_all=true to see all skills.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "Keywords to search for"},
                "max_results": {"type": "integer", "description": "Max results (default 10)"},
                "list_all": {"type": "boolean", "description": "Set true to list all skills"},
            }, "required": []},
        }, handle_skill_search),
    ]
