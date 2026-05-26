"""
API Router harness — Multi-provider LLM key management for Ouroboros.

Exports:
- APIRouter: Main orchestrator
- ProviderType: Enum of supported providers
- KeyStatus: Enum of key statuses
- Route: Named routing configuration
- APIKey: API key data class
"""

from .api_router_backend import (
    APIRouter,
    ProviderType,
    KeyStatus,
    Route,
    APIKey,
    KeyStore,
    RoutingEngine,
    FailoverManager,
    RateLimiter,
)

__version__ = "0.1.0"
__all__ = [
    "APIRouter",
    "ProviderType",
    "KeyStatus",
    "Route",
    "APIKey",
    "KeyStore",
    "RoutingEngine",
    "FailoverManager",
    "RateLimiter",
]
