"""Memory compression tools — Letta-inspired archival + recall."""

from __future__ import annotations

import json
import logging
from typing import List

from ouroboros.memory import Memory
from ouroboros.tools.registry import ToolEntry, ToolContext

log = logging.getLogger(__name__)


def handle_memory_compress(ctx: ToolContext, keep_recent: int = 30) -> str:
    """Compress old chat history into archived summaries."""
    try:
        mem = Memory(drive_root=ctx.drive_root)
        archived = mem.archive_chat(keep_recent=keep_recent)
        return json.dumps({
            "status": "ok",
            "archived_messages": archived,
            "kept_recent": keep_recent,
            "note": "Old messages summarized and stored. Use memory_search to find them.",
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def handle_memory_search(ctx: ToolContext, query: str, max_results: int = 5) -> str:
    """Search through archived chat summaries."""
    try:
        mem = Memory(drive_root=ctx.drive_root)
        result = mem.search_archives(query, max_results=max_results)
        return result
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("memory_compress", {
            "name": "memory_compress",
            "description": "Compress old chat history into archived summaries. Saves context window space. Old messages still searchable via memory_search.",
            "parameters": {"type": "object", "properties": {
                "keep_recent": {"type": "integer", "description": "Keep last N messages as working memory (default: 30)"},
            }, "required": []},
        }, handle_memory_compress),
        ToolEntry("memory_search", {
            "name": "memory_search",
            "description": "Search through archived memory. Use when you need to recall details from compressed conversations.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "Keywords to search for (case-insensitive)"},
                "max_results": {"type": "integer", "description": "Max results (default: 5)"},
            }, "required": ["query"]},
        }, handle_memory_search),
    ]
