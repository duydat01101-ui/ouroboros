"""
Ouroboros — LLM Router.

Manages multiple API keys, failover, context-aware routing, and load balancing.
Supports OpenRouter, OpenAI, Anthropic, Google, and other providers.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from ouroboros.providers import Provider, get_provider_for_model, get_all_providers, get_api_key

log = logging.getLogger(__name__)


@dataclass
class KeyStats:
    """Track statistics for an API key."""
    provider_name: str
    key_index: int
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    total_calls: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    failed_calls: int = 0
    is_failed: bool = False
    failed_at: Optional[float] = None
    failure_reason: str = ""

    def mark_failed(self, reason: str = ""):
        """Mark key as failed."""
        self.is_failed = True
        self.failed_at = time.time()
        self.failure_reason = reason
        self.failed_calls += 1

    def mark_recovered(self):
        """Mark key as recovered."""
        self.is_failed = False
        self.failed_at = None
        self.failure_reason = ""

    def is_recently_failed(self, timeout_seconds: int = 300) -> bool:
        """Check if key failed recently (within timeout)."""
        if not self.is_failed or not self.failed_at:
            return False
        return time.time() - self.failed_at < timeout_seconds

    def record_call(self, tokens: int = 0, cost: float = 0.0):
        """Record a successful call."""
        self.last_used = time.time()
        self.total_calls += 1
        self.total_tokens += tokens
        self.total_cost += cost


class LLMRouter:
    """
    Routes LLM calls across multiple providers and API keys.
    
    Features:
    - Multiple API keys per provider
    - Automatic failover on key exhaustion/errors
    - Context-aware routing (model selection based on task)
    - Load balancing across keys
    - Usage tracking and cost monitoring
    """

    def __init__(self):
        self.providers = {p.name: p for p in get_all_providers()}
        self.key_stats: Dict[str, List[KeyStats]] = {}
        self._load_keys()

    def _load_keys(self):
        """Load API keys from environment and initialize stats."""
        for provider_name, provider in self.providers.items():
            keys = []
            
            # Primary key from env
            primary_key = get_api_key(provider_name)
            if primary_key:
                keys.append(primary_key)
            
            # Additional keys from env (e.g., OPENROUTER_API_KEY_2, OPENROUTER_API_KEY_3)
            for i in range(2, 11):  # Support up to 10 keys per provider
                env_var = f"{provider.api_key_env}_{i}"
                extra_key = os.environ.get(env_var, "").strip()
                if extra_key:
                    keys.append(extra_key)
            
            # Initialize stats for each key
            self.key_stats[provider_name] = [
                KeyStats(provider_name=provider_name, key_index=i)
                for i in range(len(keys))
            ]
            
            log.info(f"Loaded {len(keys)} API keys for provider '{provider_name}'")

    def get_provider_for_model(self, model_id: str) -> Optional[Provider]:
        """Get provider for a given model ID."""
        return get_provider_for_model(model_id)

    def get_available_keys(self, provider_name: str) -> List[Tuple[int, KeyStats]]:
        """
        Get available (non-failed) API keys for a provider.
        Returns list of (key_index, stats) tuples, sorted by least recently used.
        """
        if provider_name not in self.key_stats:
            return []
        
        stats_list = self.key_stats[provider_name]
        available = [
            (i, stats)
            for i, stats in enumerate(stats_list)
            if not stats.is_recently_failed()
        ]
        
        # Sort by last_used (least recently used first)
        available.sort(key=lambda x: x[1].last_used)
        return available

    def select_provider_and_key(
        self,
        model_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[Provider], Optional[int]]:
        """
        Select best provider and key for a model.
        
        Args:
            model_id: Model identifier (e.g., "anthropic/claude-sonnet-4.6")
            context: Optional context dict with task info (e.g., {"task_type": "reasoning"})
        
        Returns:
            (provider, key_index) or (None, None) if no available keys
        """
        provider = self.get_provider_for_model(model_id)
        if not provider:
            log.warning(f"No provider found for model '{model_id}'")
            return None, None
        
        available = self.get_available_keys(provider.name)
        if not available:
            log.warning(f"No available keys for provider '{provider.name}'")
            return None, None
        
        # For now, use least recently used key
        # In future: context-aware selection (e.g., prefer cheaper keys for simple tasks)
        key_index, _ = available[0]
        return provider, key_index

    def record_call(
        self,
        provider_name: str,
        key_index: int,
        tokens: int = 0,
        cost: float = 0.0,
    ):
        """Record a successful API call."""
        if provider_name not in self.key_stats:
            return
        
        stats_list = self.key_stats[provider_name]
        if 0 <= key_index < len(stats_list):
            stats_list[key_index].record_call(tokens, cost)

    def mark_key_failed(
        self,
        provider_name: str,
        key_index: int,
        reason: str = "",
    ):
        """Mark an API key as failed."""
        if provider_name not in self.key_stats:
            return
        
        stats_list = self.key_stats[provider_name]
        if 0 <= key_index < len(stats_list):
            stats_list[key_index].mark_failed(reason)
            log.warning(
                f"Marked key {key_index} for provider '{provider_name}' as failed: {reason}"
            )

    def get_stats(self, provider_name: Optional[str] = None) -> Dict[str, Any]:
        """Get usage statistics."""
        if provider_name:
            if provider_name not in self.key_stats:
                return {}
            stats_list = self.key_stats[provider_name]
            return {
                "provider": provider_name,
                "keys": [
                    {
                        "index": i,
                        "total_calls": s.total_calls,
                        "total_tokens": s.total_tokens,
                        "total_cost": s.total_cost,
                        "is_failed": s.is_failed,
                        "failure_reason": s.failure_reason,
                    }
                    for i, s in enumerate(stats_list)
                ],
            }
        
        # Return stats for all providers
        return {
            name: self.get_stats(name)
            for name in self.key_stats.keys()
        }


# Global router instance
_router: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    """Get or create the global router instance."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router


class FailoverRouter(LLMRouter):
    """
    Extended router with automatic failover and recovery logic.
    
    Handles:
    - Automatic retry with next available key
    - Fallback to alternative providers
    - Key recovery after timeout
    - Circuit breaker pattern
    """

    def __init__(self, failover_timeout: int = 300):
        super().__init__()
        self.failover_timeout = failover_timeout  # seconds before retrying failed key
        self.call_history: List[Dict[str, Any]] = []

    def try_next_key(
        self,
        provider_name: str,
        current_key_index: int,
    ) -> Optional[int]:
        """
        Get next available key for a provider (after current one failed).
        
        Returns:
            Next key index or None if no more keys available
        """
        available = self.get_available_keys(provider_name)
        
        # Filter out current key
        available = [
            (idx, stats)
            for idx, stats in available
            if idx != current_key_index
        ]
        
        if not available:
            return None
        
        return available[0][0]

    def get_fallback_provider(
        self,
        model_id: str,
        exclude_provider: Optional[str] = None,
    ) -> Optional[Provider]:
        """
        Get fallback provider for a model (if primary provider fails).
        
        For example, if OpenRouter fails, try OpenAI directly.
        """
        primary_provider = self.get_provider_for_model(model_id)
        if not primary_provider:
            return None
        
        # Try to find alternative provider with same model
        for provider in self.providers.values():
            if provider.name == exclude_provider or provider.name == primary_provider.name:
                continue
            
            if model_id in provider.models:
                available = self.get_available_keys(provider.name)
                if available:
                    return provider
        
        return None

    def reset_key_stats(self, provider_name: str, key_index: int):
        """Reset stats for a specific key (for testing/recovery)."""
        if provider_name not in self.key_stats:
            return
        
        stats_list = self.key_stats[provider_name]
        if 0 <= key_index < len(stats_list):
            stats_list[key_index] = KeyStats(
                provider_name=provider_name,
                key_index=key_index,
            )

    def recover_failed_keys(self):
        """Attempt to recover keys that failed > failover_timeout seconds ago."""
        recovered_count = 0
        
        for provider_name, stats_list in self.key_stats.items():
            for stats in stats_list:
                if stats.is_failed and stats.failed_at:
                    time_since_failure = time.time() - stats.failed_at
                    if time_since_failure > self.failover_timeout:
                        stats.mark_recovered()
                        recovered_count += 1
                        log.info(
                            f"Recovered key {stats.key_index} for provider '{provider_name}' "
                            f"after {time_since_failure:.0f}s"
                        )
        
        return recovered_count

    def get_api_key_for_call(
        self,
        model_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[int]]:
        """
        Get API key for a model call.
        
        Returns:
            (api_key, provider_name, key_index) or (None, None, None) if unavailable
        """
        # Attempt recovery of failed keys
        self.recover_failed_keys()
        
        # Select provider and key
        provider, key_index = self.select_provider_and_key(model_id, context)
        if not provider or key_index is None:
            log.error(f"No available keys for model '{model_id}'")
            return None, None, None
        
        # Get actual API key from environment
        env_var = provider.api_key_env
        if key_index > 0:
            env_var = f"{provider.api_key_env}_{key_index + 1}"
        
        api_key = os.environ.get(env_var, "").strip()
        if not api_key:
            log.error(f"API key not found in environment: {env_var}")
            return None, None, None
        
        return api_key, provider.name, key_index

    def record_call_with_context(
        self,
        model_id: str,
        provider_name: str,
        key_index: int,
        tokens: int = 0,
        cost: float = 0.0,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Record a call with full context."""
        self.record_call(provider_name, key_index, tokens, cost)
        
        # Log to history
        self.call_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "model_id": model_id,
            "provider_name": provider_name,
            "key_index": key_index,
            "tokens": tokens,
            "cost": cost,
            "context": context or {},
        })
        
        # Keep history size bounded (last 1000 calls)
        if len(self.call_history) > 1000:
            self.call_history = self.call_history[-1000:]


# Global failover router instance
_failover_router: Optional[FailoverRouter] = None


def get_failover_router() -> FailoverRouter:
    """Get or create the global failover router instance."""
    global _failover_router
    if _failover_router is None:
        _failover_router = FailoverRouter()
    return _failover_router
