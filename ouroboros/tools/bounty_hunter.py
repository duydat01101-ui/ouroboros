"""Bounty hunting tools — thay Purple Flea, kiếm income bằng code."""

from __future__ import annotations

import json
import logging
import re
from typing import List

import requests

from ouroboros.tools.registry import ToolEntry, ToolContext

log = logging.getLogger(__name__)

SUPERPEAM_API = "https://earn.superteam.fun/api"


def handle_bounty_search(ctx: ToolContext, query: str = "", platform: str = "superteam", limit: int = 10) -> str:
    """Search for open bounties on Superteam Earn or Gitcoin."""
    try:
        if platform == "superteam":
            url = f"{SUPERPEAM_API}/listings?take={limit}&type=bounty"
            if query:
                url += f"&search={query}"
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            bounties_raw = data if isinstance(data, list) else data.get("data", [])
            bounties = []
            for item in bounties_raw:
                bounties.append({
                    "title": item.get("title", "N/A"),
                    "reward": str(item.get("reward", {}).get("amount", "N/A")),
                    "token": item.get("reward", {}).get("token", ""),
                    "status": item.get("status", "open"),
                    "url": f"https://earn.superteam.fun/listing/{item.get('slug', '')}",
                })
            return json.dumps({
                "status": "ok", "platform": platform,
                "count": len(bounties), "bounties": bounties,
            }, indent=2)
        else:
            return json.dumps({
                "status": "ok", "platform": platform,
                "note": "Dung web_search + browse_page de kiem tra Gitcoin",
            })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def handle_bounty_info(ctx: ToolContext, url: str) -> str:
    """Get basic info from a bounty URL (title + description)."""
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        text = r.text
        title = ""
        desc = ""
        m = re.search(r'<title>(.*?)</title>', text)
        if m:
            title = m.group(1)
        m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', text)
        if m:
            desc = m.group(1)[:500]
        return json.dumps({
            "status": "ok", "title": title,
            "description": desc, "url": url,
            "note": "Dung browse_page de phan tich chi tiet hon",
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def handle_bounty_submit(ctx: ToolContext, repo_url: str, branch: str = "", message: str = "") -> str:
    """Submit bounty solution via fork + PR pipeline."""
    try:
        parts = repo_url.rstrip("/").split("/")
        owner = parts[-2] if len(parts) >= 2 else "unknown"
        repo = parts[-1].replace(".git", "")
        branch_name = branch or f"bounty-solution-{__import__('uuid').uuid4().hex[:6]}"
        pr_msg = message or "Solution for bounty"
        return json.dumps({
            "status": "ok",
            "repo": f"{owner}/{repo}",
            "branch": branch_name,
            "pr_message": pr_msg,
            "instructions": "Fork -> clone -> code -> git add/commit/push -> PR",
            "next_tools": ["run_shell", "repo_commit_push"],
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("bounty_search", {
            "name": "bounty_search",
            "description": "Search open bounties on Superteam Earn. Returns title, reward, status, URL.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "Search keywords"},
                "platform": {"type": "string", "enum": ["superteam", "gitcoin"], "description": "Platform (default: superteam)"},
                "limit": {"type": "integer", "description": "Max results (default: 10)"},
            }, "required": []},
        }, handle_bounty_search),
        ToolEntry("bounty_info", {
            "name": "bounty_info",
            "description": "Get basic info from a bounty URL (title, description).",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string", "description": "Full URL of bounty listing"},
            }, "required": ["url"]},
        }, handle_bounty_info),
        ToolEntry("bounty_submit", {
            "name": "bounty_submit",
            "description": "Submit bounty solution via fork + PR. Returns step-by-step instructions.",
            "parameters": {"type": "object", "properties": {
                "repo_url": {"type": "string", "description": "GitHub repo URL to submit to"},
                "branch": {"type": "string", "description": "Branch name (auto if empty)"},
                "message": {"type": "string", "description": "Commit/PR message"},
            }, "required": ["repo_url"]},
        }, handle_bounty_submit),
    ]
