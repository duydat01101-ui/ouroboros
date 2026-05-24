"""Task analytics tool — analyze task history and provide insights."""

from __future__ import annotations

import json
import logging
import pathlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from ouroboros.tools.registry import ToolContext, ToolEntry
from ouroboros.utils import read_text, utc_now_iso

log = logging.getLogger(__name__)

def _parse_iso_timestamp(ts_str: str) -> float:
    """Parse ISO timestamp to Unix timestamp."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0

def _analyze_tasks(ctx: ToolContext, days: int = 7) -> str:
    """Analyze tasks from last N days."""
    try:
        events_path = ctx.drive_path("logs/events.jsonl")
        if not events_path.exists():
            return "⚠️ events.jsonl not found"
        
        cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
        tasks = defaultdict(lambda: {"count": 0, "success": 0, "failed": 0, "total_cost": 0.0, "total_duration": 0.0})
        
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line.strip())
                    if not event:
                        continue
                    
                    ts = _parse_iso_timestamp(event.get("ts", ""))
                    if ts < cutoff_ts:
                        continue
                    
                    event_type = event.get("type", "")
                    
                    if event_type == "task_received":
                        task_data = event.get("task", {})
                        task_type = task_data.get("type", "unknown")
                        tasks[task_type]["count"] += 1
                    
                    elif event_type == "llm_usage":
                        usage = event.get("usage", {})
                        cost = float(usage.get("cost", 0))
                        if cost > 0:
                            for task_type in tasks:
                                tasks[task_type]["total_cost"] += cost / max(1, len(tasks))
                
                except json.JSONDecodeError:
                    continue
        
        if not tasks:
            return f"No tasks found in last {days} days"
        
        result = [f"Task Analytics (last {days} days)
"]
        result.append(f"Total task types: {len(tasks)}
")
        
        for task_type in sorted(tasks.keys()):
            stats = tasks[task_type]
            result.append(f"  {task_type}: {stats["count"]} tasks, ${stats["total_cost"]:.2f} cost")
        
        return "
".join(result)
    
    except Exception as e:
        log.warning("Failed to analyze tasks", exc_info=True)
        return f"⚠️ Error: {repr(e)}"

def _get_task_metrics(ctx: ToolContext) -> str:
    """Get aggregated task metrics."""
    try:
        events_path = ctx.drive_path("logs/events.jsonl")
        if not events_path.exists():
            return "⚠️ events.jsonl not found"
        
        metrics = {
            "total_tasks": 0,
            "total_cost": 0.0,
            "task_types": defaultdict(int),
        }
        
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line.strip())
                    if event.get("type") == "task_received":
                        metrics["total_tasks"] += 1
                        task_type = event.get("task", {}).get("type", "unknown")
                        metrics["task_types"][task_type] += 1
                    elif event.get("type") == "llm_usage":
                        cost = float(event.get("usage", {}).get("cost", 0))
                        metrics["total_cost"] += cost
                except json.JSONDecodeError:
                    continue
        
        result = [
            f"Total tasks: {metrics["total_tasks"]}",
            f"Total cost: ${metrics["total_cost"]:.2f}",
            f"Task types: {dict(metrics["task_types"])}",
        ]
        return "
".join(result)
    
    except Exception as e:
        log.warning("Failed to get task metrics", exc_info=True)
        return f"⚠️ Error: {repr(e)}"

def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("analyze_tasks", {
            "name": "analyze_tasks",
            "description": "Analyze task history from last N days. Returns task counts, costs, and patterns.",
            "parameters": {"type": "object", "properties": {
                "days": {"type": "integer", "default": 7, "description": "Number of days to analyze"},
            }, "required": []},
        }, lambda ctx, days=7: _analyze_tasks(ctx, days)),
        ToolEntry("get_task_metrics", {
            "name": "get_task_metrics",
            "description": "Get aggregated task metrics: total tasks, total cost, task type breakdown.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, lambda ctx: _get_task_metrics(ctx)),
    ]
