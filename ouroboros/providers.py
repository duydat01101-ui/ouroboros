"""
Ouroboros — LLM Provider definitions.

Defines available LLM providers (OpenRouter, OpenAI, Anthropic, Google, etc.)
and helper functions for provider selection and routing.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import os


@dataclass
class Provider:
    """LLM provider configuration."""
    name: str
    base_url: str
    api_key_env: str
    models: List[str]
    priority: int = 0


PROVIDERS: Dict[str, Provider] = {
    "openrouter": Provider(
        name="openrouter",
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key_env="OPENROUTER_API_KEY",
        models=[
            "anthropic/claude-opus-4.6",
            "anthropic/claude-sonnet-4.6",
            "anthropic/claude-haiku-3.5",
            "openai/gpt-4o",
            "openai/gpt-4-turbo",
            "openai/gpt-3.5-turbo",
            "google/gemini-2.5-pro",
            "google/gemini-2.5-flash",
            "meta-llama/llama-3.1-405b",
            "x-ai/grok-2",
        ],
        priority=10,
    ),
    "openai": Provider(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        models=["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
        priority=8,
    ),
    "anthropic": Provider(
        name="anthropic",
        base_url="https://api.anthropic.com",
        api_key_env="ANTHROPIC_API_KEY",
        models=["claude-opus-4.6", "claude-sonnet-4.6", "claude-haiku-3.5"],
        priority=8,
    ),
    "google": Provider(
        name="google",
        base_url="https://us-central1-aiplatform.googleapis.com/v1beta1",
        api_key_env="GOOGLE_API_KEY",
        models=["gemini-2.5-pro", "gemini-2.5-flash"],
        priority=7,
    ),
}


def get_provider_for_model(model_id: str) -> Optional[Provider]:
    """Get provider for a given model ID."""
    for provider in PROVIDERS.values():
        if model_id in provider.models:
            return provider
    return None


def get_all_providers() -> List[Provider]:
    """Get all providers sorted by priority (highest first)."""
    return sorted(PROVIDERS.values(), key=lambda p: p.priority, reverse=True)


def get_provider_by_name(name: str) -> Optional[Provider]:
    """Get provider by name."""
    return PROVIDERS.get(name)


def get_api_key(provider_name: str) -> Optional[str]:
    """Get API key for a provider from environment."""
    provider = get_provider_by_name(provider_name)
    if not provider:
        return None
    return os.environ.get(provider.api_key_env, "").strip() or None
