"""Ouroboros Error Journal — Learning from mistakes.

Records errors, mistakes, and lessons learned to prevent repeating them.
"""

from __future__ import annotations

import json
import logging
import pathlib
from typing import Any, Dict, List, Optional
from collections import Counter

from ouroboros.utils import utc_now_iso, append_jsonl, read_text

log = logging.getLogger(__name__)

class ErrorJournal:
    """Track errors and lessons learned to improve over time."""

    def __init__(self, drive_root: pathlib.Path):
        self.drive_root = drive_root
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Ensure error journal directory exists."""
        journal_dir = self.drive_root / "memory" / "error_journal"
        journal_dir.mkdir(parents=True, exist_ok=True)

    def _journal_path(self) -> pathlib.Path:
        """Path to error journal JSONL file."""
        return self.drive_root / "memory" / "error_journal" / "errors.jsonl"

    def log_error(
        self,
        error_type: str,
        error_msg: str,
        context: str = "",
        lesson: str = "",
        task_id: str = "",
    ) -> None:
        """Log an error with context and lesson learned."""
        entry = {
            "ts": utc_now_iso(),
            "type": error_type,
            "error": error_msg,
            "context": context,
            "lesson": lesson,
            "task_id": task_id,
        }
        append_jsonl(self._journal_path(), entry)
        log.info(f"Error logged: {error_type} — {error_msg[:100]}")

    def get_recent_errors(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent errors from journal."""
        path = self._journal_path()
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            entries = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return entries[-limit:] if limit < len(entries) else entries
        except Exception as e:
            log.warning(f"Failed to read error journal: {e}")
            return []

    def get_errors_by_type(self, error_type: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get errors of a specific type."""
        all_errors = self.get_recent_errors(limit=1000)
        filtered = [e for e in all_errors if e.get("type") == error_type]
        return filtered[-limit:] if limit < len(filtered) else filtered

    def get_lessons_summary(self) -> str:
        """Get summary of lessons learned to avoid repeating mistakes."""
        errors = self.get_recent_errors(limit=100)
        if not errors:
            return "(no errors recorded yet)"

        # Group by error type
        type_counts: Counter = Counter()
        lessons_by_type: Dict[str, List[str]] = {}

        for e in errors:
            error_type = e.get("type", "unknown")
            type_counts[error_type] += 1
            lesson = e.get("lesson", "")
            if lesson:
                if error_type not in lessons_by_type:
                    lessons_by_type[error_type] = []
                lessons_by_type[error_type].append(lesson)

        lines = ["## Error Summary & Lessons Learned\n"]
        lines.append(f"Total errors recorded: {len(errors)}\n")

        # Error type breakdown
        lines.append("### Error Types:")
        for error_type, count in type_counts.most_common(10):
            lines.append(f"- {error_type}: {count}")

        # Lessons learned
        if lessons_by_type:
            lines.append("\n### Lessons Learned:")
            for error_type in sorted(lessons_by_type.keys()):
                lessons = lessons_by_type[error_type]
                unique_lessons = list(set(lessons))  # Remove duplicates
                lines.append(f"\n**{error_type}:**")
                for lesson in unique_lessons[:3]:  # Top 3 lessons per type
                    lines.append(f"- {lesson}")

        return "\n".join(lines)

    def summarize_for_context(self) -> str:
        """Generate a summary for inclusion in LLM context."""
        errors = self.get_recent_errors(limit=50)
        if not errors:
            return ""

        lines = ["## Error Journal (Recent Mistakes & Lessons)\n"]

        # Recent errors with lessons
        recent_with_lessons = [e for e in errors if e.get("lesson")]
        if recent_with_lessons:
            lines.append("### Recent Lessons:")
            for e in recent_with_lessons[-10:]:
                ts = e.get("ts", "")[:16]
                error_type = e.get("type", "?")
                lesson = e.get("lesson", "")
                lines.append(f"- [{ts}] {error_type}: {lesson}")

        # Error type frequency
        type_counts: Counter = Counter(e.get("type", "unknown") for e in errors)
        if type_counts:
            lines.append("\n### Common Error Types:")
            for error_type, count in type_counts.most_common(5):
                lines.append(f"- {error_type}: {count} occurrences")

        return "\n".join(lines)
