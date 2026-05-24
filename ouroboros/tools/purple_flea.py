"""Purple Flea API — Bootstrap vốn từ $0 cho Ouroboros."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List

import requests as _requests

from ouroboros.tools.registry import ToolEntry, ToolContext

log = logging.getLogger(__name__)

BASE_FAUCET = "https://faucet.purpleflea.com/v1"
BASE_CASINO = "https://casino.purpleflea.com/v1"
REFERRAL_CODE = "STARTER"


def _api_key_path(ctx: ToolContext) -> str:
    return str(ctx.drive_root / "memory" / "purple_flea_key.txt")


def _load_api_key(ctx: ToolContext) -> str:
    path = _api_key_path(ctx)
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _save_api_key(ctx: ToolContext, key: str) -> None:
    path = _api_key_path(ctx)
    with open(path, "w") as f:
        f.write(key.strip())


def _post(url: str, data: dict = None, api_key: str = "") -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    r = _requests.post(url, json=data or {}, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


def _get(url: str, api_key: str = "") -> dict:
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    r = _requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


def handle_pf_register(ctx: ToolContext, agent_name: str = "") -> str:
    """Register Ouroboros on Purple Flea, get free $1 from faucet."""
    name = agent_name or f"ouroboros-{uuid.uuid4().hex[:6]}"
    try:
        result = _post(f"{BASE_FAUCET}/register", {"name": name, "ref": REFERRAL_CODE})
        api_key = result.get("api_key", "")
        if api_key:
            _save_api_key(ctx, api_key)
            claim = _post(f"{BASE_FAUCET}/claim", {}, api_key=api_key)
            return json.dumps({
                "status": "registered",
                "agent_name": name,
                "api_key_prefix": api_key[:12] + "...",
                "faucet_claimed": claim.get("amount", 0),
                "balance": claim.get("balance", 0),
                "referral_code": REFERRAL_CODE,
            })
        return json.dumps({"status": "error", "message": str(result)})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def handle_pf_balance(ctx: ToolContext) -> str:
    """Check Purple Flea casino balance."""
    api_key = _load_api_key(ctx)
    if not api_key:
        return json.dumps({"status": "error", "message": "Chua register. Goi pf_register truoc."})
    try:
        result = _get(f"{BASE_CASINO}/balance", api_key=api_key)
        return json.dumps({"status": "ok", "balance_usd": result.get("balance", 0)})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def handle_pf_coinflip(ctx: ToolContext, amount: float = 0.5, side: str = "heads") -> str:
    """Coinflip 50/50. Win = 1.96x. House edge 0.5% only."""
    api_key = _load_api_key(ctx)
    if not api_key:
        return json.dumps({"status": "error", "message": "Chua register."})
    try:
        result = _post(f"{BASE_CASINO}/flip", {"amount": amount, "side": side}, api_key=api_key)
        return json.dumps({
            "status": "ok",
            "result": result.get("result"),
            "won": result.get("won"),
            "payout": result.get("payout"),
            "new_balance": result.get("balance"),
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def handle_pf_martingale(ctx: ToolContext, start_bet: float = 0.1, target: float = 5.0) -> str:
    """Auto Martingale: double bet on loss, reset on win. Stop when target or broke."""
    api_key = _load_api_key(ctx)
    if not api_key:
        return json.dumps({"status": "error", "message": "Chua register."})
    try:
        bal_info = _get(f"{BASE_CASINO}/balance", api_key=api_key)
        bal = bal_info.get("balance", 0)
        if bal < start_bet:
            return json.dumps({"status": "error", "message": f"Balance ${bal:.2f} khong du bet"})

        bet = start_bet
        rounds = 0
        wins = 0
        losses = 0

        while bal > start_bet and bal < target and rounds < 100:
            if bet > bal:
                bet = bal
            result = _post(f"{BASE_CASINO}/flip", {"amount": bet, "side": "heads"}, api_key=api_key)
            won = result.get("won", False)
            payout = result.get("payout", 0)
            bal = result.get("balance", bal - bet + (payout if won else 0))
            rounds += 1
            if won:
                wins += 1
                bet = start_bet
            else:
                losses += 1
                bet = min(bet * 2, bal)

        return json.dumps({
            "status": "ok",
            "rounds": rounds,
            "wins": wins,
            "losses": losses,
            "final_balance": round(bal, 4),
            "target_reached": bal >= target,
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def handle_pf_create_agent(ctx: ToolContext, agent_label: str = "") -> str:
    """Create sub-agent for referral commission (10-20%)."""
    name = agent_label or f"sub-{uuid.uuid4().hex[:6]}"
    try:
        result = _post(f"{BASE_FAUCET}/register", {"name": name, "ref": REFERRAL_CODE})
        sub_key = result.get("api_key", "")
        claim = _post(f"{BASE_FAUCET}/claim", {}, api_key=sub_key)
        return json.dumps({
            "status": "created",
            "name": name,
            "faucet_claimed": claim.get("amount", 0),
            "referral_code": REFERRAL_CODE,
            "note": "Sub-agent hoat dong -> ban nhan 10-20% hoa hong",
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def handle_pf_status(ctx: ToolContext) -> str:
    """Full account overview: balance, registration, strategy."""
    api_key = _load_api_key(ctx)
    registered = bool(api_key)
    bal = 0
    if registered:
        try:
            bal_info = _get(f"{BASE_CASINO}/balance", api_key=api_key)
            bal = bal_info.get("balance", 0)
        except Exception:
            pass
    return json.dumps({
        "status": "ok",
        "registered": registered,
        "balance_usd": bal,
        "referral_code": REFERRAL_CODE,
        "strategy": "pf_register -> pf_martingale(start_bet=0.1, target=5.0) -> sub-agents via pf_create_agent",
    })


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("pf_register", {
            "name": "pf_register",
            "description": "Register on Purple Flea -> get free $1 faucet. Returns API key + balance.",
            "parameters": {"type": "object", "properties": {
                "agent_name": {"type": "string", "description": "Optional agent name"},
            }, "required": []},
        }, handle_pf_register),
        ToolEntry("pf_balance", {
            "name": "pf_balance",
            "description": "Check Purple Flea casino balance in USD.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, handle_pf_balance),
        ToolEntry("pf_coinflip", {
            "name": "pf_coinflip",
            "description": "Bet on coinflip 50/50. Win = 1.96x. House edge 0.5%.",
            "parameters": {"type": "object", "properties": {
                "amount": {"type": "number", "description": "Bet amount USD (default: 0.5)"},
                "side": {"type": "string", "description": "heads or tails (default: heads)"},
            }, "required": []},
        }, handle_pf_coinflip),
        ToolEntry("pf_martingale", {
            "name": "pf_martingale",
            "description": "Auto Martingale on coinflip: double bet on loss, reset on win. Stop at target or when broke.",
            "parameters": {"type": "object", "properties": {
                "start_bet": {"type": "number", "description": "Initial bet (default: 0.1)"},
                "target": {"type": "number", "description": "Target balance to stop (default: 5.0)"},
            }, "required": []},
        }, handle_pf_martingale),
        ToolEntry("pf_create_agent", {
            "name": "pf_create_agent",
            "description": "Create sub-agent -> get 10-20% referral commission on their activity.",
            "parameters": {"type": "object", "properties": {
                "agent_label": {"type": "string", "description": "Optional label"},
            }, "required": []},
        }, handle_pf_create_agent),
        ToolEntry("pf_status", {
            "name": "pf_status",
            "description": "Full account overview: balance, registration, referral code, strategy tips.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, handle_pf_status),
    ]
