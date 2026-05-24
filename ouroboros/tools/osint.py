"""OSINT reconnaissance tools - web-wide username/identity search."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolContext, ToolEntry

OSINT_DIR = Path("/data/osint_results")


def _ensure_maigret():
    """Install maigret if not available."""
    try:
        import maigret
        return True
    except ImportError:
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "maigret", "-q"],
                timeout=120,
            )
            return True
        except Exception as e:
            return str(e)


def _osint_username_search(ctx: ToolContext, username: str, top_sites: int = 500) -> str:
    """Search username across social networks and websites."""
    OSINT_DIR.mkdir(parents=True, exist_ok=True)

    installed = _ensure_maigret()
    if installed is not True:
        return json.dumps({"error": f"Failed to install maigret: {installed}"})

    output_file = OSINT_DIR / f"{username}_report"

    try:
        cmd = [
            sys.executable, "-m", "maigret",
            username,
            "--json", str(output_file) + ".json",
            "--top-sites", str(top_sites),
            "--timeout", "30",
            "--no-color",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

        # Try to read JSON results
        json_path = Path(str(output_file) + ".json")
        if json_path.exists():
            with open(json_path) as f:
                data = json.load(f)

            # Summarize results
            found = []
            if isinstance(data, dict):
                for site, info in data.items():
                    if isinstance(info, dict) and info.get("status", "").lower() in ("claimed", "found"):
                        found.append({
                            "site": site,
                            "url": info.get("url_user", ""),
                            "status": info.get("status", ""),
                        })
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        found.append({
                            "site": item.get("sitename", item.get("site", "")),
                            "url": item.get("url_user", item.get("url", "")),
                            "status": item.get("status", ""),
                        })

            return json.dumps({
                "username": username,
                "total_found": len(found),
                "accounts": found[:50],
                "full_results_path": str(json_path),
                "stdout_excerpt": result.stdout[-500:] if result.stdout else "",
            }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({
                "username": username,
                "stdout": result.stdout[-1000:] if result.stdout else "",
                "stderr": result.stderr[-500:] if result.stderr else "",
                "note": "JSON output not found, check stdout for results",
            }, ensure_ascii=False, indent=2)

    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Search timed out after 300s", "username": username})
    except Exception as e:
        return json.dumps({"error": repr(e), "username": username})


def _osint_full_scan(ctx: ToolContext, username: str) -> str:
    """Deep scan across ALL 3000+ sites (slower but comprehensive)."""
    OSINT_DIR.mkdir(parents=True, exist_ok=True)

    installed = _ensure_maigret()
    if installed is not True:
        return json.dumps({"error": f"Failed to install maigret: {installed}"})

    output_file = OSINT_DIR / f"{username}_full_report"

    try:
        cmd = [
            sys.executable, "-m", "maigret",
            username,
            "-a",
            "--json", str(output_file) + ".json",
            "--timeout", "30",
            "--no-color",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )

        json_path = Path(str(output_file) + ".json")
        if json_path.exists():
            with open(json_path) as f:
                data = json.load(f)

            found = []
            if isinstance(data, dict):
                for site, info in data.items():
                    if isinstance(info, dict) and info.get("status", "").lower() in ("claimed", "found"):
                        found.append({
                            "site": site,
                            "url": info.get("url_user", ""),
                        })
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        found.append({
                            "site": item.get("sitename", item.get("site", "")),
                            "url": item.get("url_user", item.get("url", "")),
                        })

            return json.dumps({
                "username": username,
                "scan_type": "full (3000+ sites)",
                "total_found": len(found),
                "accounts": found,
                "full_results_path": str(json_path),
            }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({
                "username": username,
                "stdout": result.stdout[-1000:] if result.stdout else "",
                "stderr": result.stderr[-500:] if result.stderr else "",
            }, ensure_ascii=False, indent=2)

    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Full scan timed out after 600s", "username": username})
    except Exception as e:
        return json.dumps({"error": repr(e), "username": username})


def _osint_info(ctx: ToolContext) -> str:
    """Show available OSINT tools and capabilities."""
    tools = {
        "integrated": {
            "maigret": {
                "description": "Username search across 3000+ sites. No API keys needed.",
                "github": "https://github.com/soxoj/maigret",
                "stars": "30.2k",
                "features": [
                    "3000+ sites supported",
                    "AI profiling",
                    "HTML/PDF/JSON/CSV reports",
                    "No API keys required",
                    "Tags & country filtering",
                ],
            },
        },
        "recommended_for_manual_install": {
            "sherlock": {
                "description": "Hunt usernames across 400+ social networks",
                "github": "https://github.com/sherlock-project/sherlock",
                "stars": "83.7k",
                "install": "pip install sherlock-project",
            },
            "spiderfoot": {
                "description": "OSINT automation - 200+ modules, web UI, TOR support",
                "github": "https://github.com/smicallef/spiderfoot",
                "stars": "17.9k",
                "install": "pip install spiderfoot",
            },
            "theHarvester": {
                "description": "Email, subdomain, IP gathering from public sources",
                "github": "https://github.com/laramies/theHarvester",
                "stars": "16.3k",
                "install": "pip install theHarvester",
            },
            "recon-ng": {
                "description": "Web reconnaissance framework (Metasploit-style)",
                "github": "https://github.com/lanmaster53/recon-ng",
                "stars": "5.6k",
            },
            "osintgram": {
                "description": "Instagram OSINT - followers, emails, phones, photos",
                "github": "https://github.com/Datalux/Osintgram",
                "stars": "12.9k",
            },
        },
        "reference": {
            "awesome-osint": {
                "description": "Curated list of 500+ OSINT tools & resources",
                "github": "https://github.com/jivoi/awesome-osint",
                "stars": "26.5k",
            },
        },
    }

    return json.dumps(tools, ensure_ascii=False, indent=2)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("osint_username_search", {
            "name": "osint_username_search",
            "description": "Search a username across 3000+ websites and social networks using Maigret. Returns found accounts with URLs.",
            "parameters": {"type": "object", "properties": {
                "username": {"type": "string", "description": "Username to search"},
                "top_sites": {"type": "integer", "description": "Number of top sites to check (default 500, max ~3000)", "default": 500},
            }, "required": ["username"]},
        }, _osint_username_search),

        ToolEntry("osint_full_scan", {
            "name": "osint_full_scan",
            "description": "Deep OSINT scan across ALL 3000+ sites for a username. Slower but comprehensive. Results saved to /data/osint_results/.",
            "parameters": {"type": "object", "properties": {
                "username": {"type": "string", "description": "Username to deep scan"},
            }, "required": ["username"]},
        }, _osint_full_scan),

        ToolEntry("osint_info", {
            "name": "osint_info",
            "description": "Show all available OSINT tools, their capabilities, and integration status.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, _osint_info),
    ]
