"""Recursive self-improvement engine — Voyager-inspired.

Analyses past performance, extracts skills, generates
self-improvements, and manages a skill library.
"""

from __future__ import annotations

import json
import logging
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple

from ouroboros.utils import utc_now_iso, read_text, write_text, append_jsonl, short

log = logging.getLogger(__name__)

SKILLS_DIR = "memory/skills"


class SkillLibrary:
    """Persistent skill library stored on the data volume."""

    def __init__(self, drive_root: pathlib.Path):
        self.drive_root = drive_root

    def _skills_path(self) -> pathlib.Path:
        return (self.drive_root / SKILLS_DIR).resolve()

    def _index_path(self) -> pathlib.Path:
        return self._skills_path() / "_index.md"

    def ensure_dir(self) -> None:
        self._skills_path().mkdir(parents=True, exist_ok=True)

    def learn(self, name: str, category: str, pattern: str,
              example: str = "", tags: List[str] = None,
              source: str = "") -> str:
        """Save a skill. Returns the filename."""
        self.ensure_dir()
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name.strip().lower())
        if not safe_name:
            safe_name = f"skill_{utc_now_iso()[:10]}"
        fname = f"{safe_name}.md"
        fpath = self._skills_path() / fname

        content = (
            f"# Skill: {name}\n\n"
            f"**Category:** {category}\n"
            f"**Created:** {utc_now_iso()}\n"
            f"**Source:** {source or '(self-learned)'}\n"
            f"**Tags:** {', '.join(tags or [])}\n\n"
            f"## Pattern\n\n{pattern}\n\n"
        )
        if example:
            content += f"## Example\n\n```\n{example}\n```\n"

        write_text(fpath, content)

        # Update index
        index_lines = []
        if self._index_path().exists():
            index_lines = self._index_path().read_text(encoding="utf-8").split("\n")
        tag_str = f"[{', '.join(tags or [])}]"
        index_lines.insert(0, f"- **{name}** ({category}) {tag_str} — {short(pattern, 80)}")
        write_text(self._index_path(), "\n".join(index_lines))

        return fname

    def search(self, query: str, max_results: int = 10) -> str:
        """Search skills by keyword. Returns formatted results."""
        self.ensure_dir()
        if not self._skills_path().exists():
            return "(no skills library)"
        try:
            results = []
            q = query.lower()
            for f in sorted(self._skills_path().iterdir(), reverse=True):
                if f.suffix != ".md" or f.name == "_index.md":
                    continue
                text = f.read_text(encoding="utf-8")
                if q in text.lower():
                    lines = text.split("\n")
                    title = lines[0] if lines else f.name
                    category = ""
                    pattern = ""
                    for l in lines[1:]:
                        if l.startswith("**Category:**"):
                            category = l.replace("**Category:**", "").strip()
                        if l.startswith("## Pattern") and len(lines) > lines.index(l) + 1:
                            pattern = lines[lines.index(l) + 1][:200]
                    snippet = f"{title} ({category}): {pattern}" if category else f"{title}"
                    results.append(snippet)
                    if len(results) >= max_results:
                        break
            if not results:
                return f"(no skills matching '{query}')"
            return "## Skill Library\n\n" + "\n\n".join(results)
        except Exception as e:
            log.warning("skill_search failed: %s", e)
            return "(error searching skills)"

    def list_recent(self, count: int = 10) -> str:
        """List the most recent skills."""
        self.ensure_dir()
        if self._index_path().exists():
            lines = self._index_path().read_text(encoding="utf-8").split("\n")
            recent = [l for l in lines if l.strip()][:count]
            return "## Skill Library\n\n" + "\n".join(recent) if recent else "(empty)"
        return "(no skills yet)"


class SelfImprover:
    """Analyses performance and generates self-improvements."""

    def __init__(self, drive_root: pathlib.Path, repo_dir: pathlib.Path):
        self.drive_root = drive_root
        self.repo_dir = repo_dir
        self.skills = SkillLibrary(drive_root)

    def _log_path(self) -> pathlib.Path:
        return (self.drive_root / "logs").resolve()

    def analyse_recent_tasks(self, count: int = 20) -> str:
        """Analyse recent tasks for failure patterns and improvement opportunities."""
        import json as _json
        events_path = self._log_path() / "events.jsonl"
        if not events_path.exists():
            return "(no event log to analyse)"

        try:
            lines = events_path.read_text(encoding="utf-8").strip().split("\n")
            tail = lines[-count:]
            errors = []
            successes = []
            for line in tail:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = _json.loads(line)
                    evt_type = ev.get("type", "")
                    if evt_type in ("tool_error", "task_error", "tool_rounds_exceeded"):
                        errors.append(ev)
                    elif evt_type in ("task_completed", "evolution_success"):
                        successes.append(ev)
                except Exception:
                    continue

            parts = [f"Analysis of last {len(tail)} events:", ""]
            if errors:
                parts.append(f"**{len(errors)} errors found:**")
                for e in errors[-10:]:
                    text = short(str(e.get("error", e.get("text", "?"))), 120)
                    parts.append(f"- `{e.get('type', '?')}`: {text}")
                parts.append("")
            if successes:
                parts.append(f"**{len(successes)} successes:**")
                for s in successes[-5:]:
                    text = short(str(s.get("text", "?")), 100)
                    parts.append(f"- `{s.get('type', '?')}`: {text}")
                parts.append("")

            if not errors and not successes:
                return "(no significant patterns detected)"

            return "\n".join(parts)
        except Exception as e:
            log.warning("analyse_recent_tasks failed: %s", e)
            return f"(analysis failed: {e})"

    def generate_improvement(self, analysis: str, llm_client=None) -> str:
        """Use LLM to suggest a code improvement based on analysis."""
        prompt = f"""You are Ouroboros's self-improvement engine. Based on this analysis of recent performance:

{analysis}

Available improvement types:
1. **Bug fix** — fix a specific error pattern
2. **Optimization** — reduce token/cost usage
3. **Feature** — add a new capability
4. **Refactor** — clean up code structure
5. **Skill** — extract a reusable pattern

Respond with:
{{
  "type": "bug_fix|optimization|feature|refactor|skill",
  "target_file": "path/to/file.py",
  "description": "short description",
  "rationale": "why this matters",
  "code_diff": "description of what to change"
}}"""

        from ouroboros.llm import LLMClient
        client = llm_client or LLMClient()
        try:
            import os
            model = os.environ.get("OUROBOROS_MODEL_LIGHT") or os.environ.get("DEFAULT_LIGHT_MODEL", "openai/gpt-4o-mini")
            resp_msg, _usage = client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                reasoning_effort="low",
                max_tokens=1024,
            )
            raw = resp_msg.get("content", "")
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                return raw[start:end]
            return raw
        except Exception as e:
            return f'{{"error": "LLM improvement generation failed: {e}"}}'
