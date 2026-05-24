"""Quoroom integration tools — control autonomous swarm via REST API."""

import json
import logging
import os

try:
    import requests
except ImportError:
    requests = None

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)


def _quoroom_api(method: str, endpoint: str, body: dict | None = None) -> str:
    """Call Quoroom REST API."""
    if requests is None:
        return "Error: 'requests' module not installed. Run: pip install requests"
    base = os.environ.get("QUOROOM_URL", "")
    token = os.environ.get("QUOROOM_TOKEN", "")
    if not base or not token:
        return "Error: set QUOROOM_URL and QUOROOM_TOKEN env vars"
    try:
        url = f"{base.rstrip('/')}/api/{endpoint.lstrip('/')}"
        headers = {"Authorization": f"Bearer {token}"}
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=15)
        else:
            headers["Content-Type"] = "application/json"
            r = requests.post(url, headers=headers, json=body, timeout=15)
        r.raise_for_status()
        return json.dumps(r.json(), indent=2)
    except Exception as e:
        return f"Quoroom API error: {e}"


def _quoroom_get(ctx: ToolContext, endpoint: str) -> str:
    """GET request to any Quoroom endpoint."""
    return _quoroom_api("GET", endpoint)


def _quoroom_post(ctx: ToolContext, endpoint: str, body: str) -> str:
    """POST request with JSON body."""
    try:
        return _quoroom_api("POST", endpoint, json.loads(body))
    except json.JSONDecodeError as e:
        return f"Invalid JSON body: {e}"


def _quoroom_wallet(ctx: ToolContext) -> str:
    """Check wallet balance."""
    rid = os.environ.get("QUOROOM_ROOM_ID", "")
    if not rid:
        return "Error: set QUOROOM_ROOM_ID env var"
    return _quoroom_api("GET", f"rooms/{rid}/wallet/balance")


def _quoroom_set_goal(ctx: ToolContext, description: str) -> str:
    """Set a goal for the swarm room."""
    rid = os.environ.get("QUOROOM_ROOM_ID", "")
    if not rid:
        return "Error: set QUOROOM_ROOM_ID env var"
    return _quoroom_api("POST", f"rooms/{rid}/goals", {"description": description})


def _quoroom_create_worker(ctx: ToolContext, name: str, prompt: str) -> str:
    """Create a new worker in the swarm."""
    rid = os.environ.get("QUOROOM_ROOM_ID", "")
    if not rid:
        return "Error: set QUOROOM_ROOM_ID env var"
    return _quoroom_api("POST", f"rooms/{rid}/workers", {
        "name": name,
        "systemPrompt": prompt,
    })


def _quoroom_list_rooms(ctx: ToolContext) -> str:
    """List all rooms."""
    return _quoroom_api("GET", "rooms")


def _quoroom_list_goals(ctx: ToolContext) -> str:
    """List goals for the current room."""
    rid = os.environ.get("QUOROOM_ROOM_ID", "")
    if not rid:
        return "Error: set QUOROOM_ROOM_ID env var"
    return _quoroom_api("GET", f"rooms/{rid}/goals")


def _quoroom_room_status(ctx: ToolContext) -> str:
    """Get full room status."""
    rid = os.environ.get("QUOROOM_ROOM_ID", "")
    if not rid:
        return "Error: set QUOROOM_ROOM_ID env var"
    return _quoroom_api("GET", f"rooms/{rid}/status")


def _quoroom_send_usdc(ctx: ToolContext, to: str, amount: str) -> str:
    """Send USDC from room wallet to an address."""
    rid = os.environ.get("QUOROOM_ROOM_ID", "")
    if not rid:
        return "Error: set QUOROOM_ROOM_ID env var"
    return _quoroom_api("POST", f"rooms/{rid}/wallet/withdraw", {
        "to": to,
        "amount": amount,
        "chain": "base",
        "token": "usdc",
    })


def get_tools():
    return [
        ToolEntry("quoroom_wallet", {
            "name": "quoroom_wallet",
            "description": "Check Quoroom room wallet balance (USDC/USDT on Base, Ethereum, Arbitrum, Optimism, Polygon)",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, _quoroom_wallet, timeout_sec=20),
        ToolEntry("quoroom_set_goal", {
            "name": "quoroom_set_goal",
            "description": "Set a new objective for the Quoroom swarm to pursue autonomously",
            "parameters": {"type": "object", "properties": {
                "description": {"type": "string", "description": "What the swarm should achieve, e.g. Earn $50 by fixing GitHub issues"}
            }, "required": ["description"]},
        }, _quoroom_set_goal, timeout_sec=20),
        ToolEntry("quoroom_create_worker", {
            "name": "quoroom_create_worker",
            "description": "Create a specialized AI worker agent in the Quoroom swarm",
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "description": "Worker name, e.g. bounty-hunter"},
                "prompt": {"type": "string", "description": "Full system prompt defining the worker's role, skills, and constraints"}
            }, "required": ["name", "prompt"]},
        }, _quoroom_create_worker, timeout_sec=20),
        ToolEntry("quoroom_list_rooms", {
            "name": "quoroom_list_rooms",
            "description": "List all Quoroom rooms and their statuses",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, _quoroom_list_rooms, timeout_sec=20),
        ToolEntry("quoroom_room_status", {
            "name": "quoroom_room_status",
            "description": "Get detailed status of the current Quoroom room (queen, workers, goals, wallet)",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, _quoroom_room_status, timeout_sec=20),
        ToolEntry("quoroom_list_goals", {
            "name": "quoroom_list_goals",
            "description": "List all goals for the current room with progress",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, _quoroom_list_goals, timeout_sec=20),
        ToolEntry("quoroom_send_usdc", {
            "name": "quoroom_send_usdc",
            "description": "Send USDC from the room wallet to any address on Base chain",
            "parameters": {"type": "object", "properties": {
                "to": {"type": "string", "description": "Destination wallet address (0x...)"},
                "amount": {"type": "string", "description": "Amount in USDC, e.g. 5.50"}
            }, "required": ["to", "amount"]},
        }, _quoroom_send_usdc, timeout_sec=30),
        ToolEntry("quoroom_api_get", {
            "name": "quoroom_api_get",
            "description": "Send GET to any Quoroom REST API endpoint (rooms, goals, workers, tasks, wallet, memory, skills, inbox, identity)",
            "parameters": {"type": "object", "properties": {
                "endpoint": {"type": "string", "description": "API path, e.g. rooms/1/goals or rooms/1/wallet/transactions"}
            }, "required": ["endpoint"]},
        }, _quoroom_get, timeout_sec=20),
        ToolEntry("quoroom_api_post", {
            "name": "quoroom_api_post",
            "description": "Send POST to any Quoroom REST API endpoint with JSON body",
            "parameters": {"type": "object", "properties": {
                "endpoint": {"type": "string", "description": "API path, e.g. rooms/1/goals"},
                "body": {"type": "string", "description": "JSON body as string, e.g. {\"description\": \"Earn money\"}"}
            }, "required": ["endpoint", "body"]},
        }, _quoroom_post, timeout_sec=20),
    ]
