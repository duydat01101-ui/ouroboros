"""
Tests for API Router harness.
"""

import pytest
import tempfile
import os
from api_router_backend import (
    APIRouter, ProviderType, KeyStatus, Route, APIKey, KeyStore
)

@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)

@pytest.fixture
def router(temp_db):
    """Create APIRouter instance with temp database."""
    return APIRouter(temp_db)

class TestKeyStore:
    """Test KeyStore operations."""
    
    def test_add_key(self, router):
        """Test adding a key."""
        key_id = router.add_key(ProviderType.OPENAI, "sk-test-123", "gpt-4")
        assert key_id > 0
        
        keys = router.key_store.get_keys()
        assert len(keys) == 1
        assert keys[0].provider == ProviderType.OPENAI
        assert keys[0].model == "gpt-4"
        assert keys[0].status == KeyStatus.ACTIVE
    
    def test_get_keys_by_provider(self, router):
        """Test filtering keys by provider."""
        router.add_key(ProviderType.OPENAI, "sk-openai-1", "gpt-4")
        router.add_key(ProviderType.OPENAI, "sk-openai-2", "gpt-3.5")
        router.add_key(ProviderType.ANTHROPIC, "sk-anthropic-1", "claude-3")
        
        openai_keys = router.key_store.get_keys(ProviderType.OPENAI)
        assert len(openai_keys) == 2
        
        anthropic_keys = router.key_store.get_keys(ProviderType.ANTHROPIC)
        assert len(anthropic_keys) == 1
    
    def test_update_key_status(self, router):
        """Test updating key status."""
        key_id = router.add_key(ProviderType.OPENAI, "sk-test", "gpt-4")
        
        router.key_store.update_key_status(key_id, KeyStatus.INACTIVE)
        
        keys = router.key_store.get_keys()
        assert keys[0].status == KeyStatus.INACTIVE
    
    def test_mark_key_error(self, router):
        """Test marking key errors."""
        key_id = router.add_key(ProviderType.OPENAI, "sk-test", "gpt-4")
        
        for _ in range(6):
            router.key_store.mark_key_error(key_id, "rate_limit", "Too many requests")
        
        keys = router.key_store.get_keys()
        assert keys[0].error_count == 6
        assert keys[0].status == KeyStatus.ERROR

class TestRoutingEngine:
    """Test RoutingEngine operations."""
    
    def test_select_route(self, router):
        """Test selecting a route."""
        route = Route(
            name="test-route",
            provider=ProviderType.OPENAI,
            model="gpt-4"
        )
        router.add_route(route)
        
        assert router.select_route("test-route")
        assert router.routing_engine.current_route == "test-route"
    
    def test_get_best_key_simple_task(self, router):
        """Test getting best key for simple task."""
        router.add_key(ProviderType.OPENAI, "sk-openai", "gpt-4")
        router.add_key(ProviderType.ANTHROPIC, "sk-anthropic", "claude-3")
        
        # Simple task (< 1000 tokens) should prefer OpenAI
        key = router.get_best_key(estimated_tokens=500)
        assert key is not None
        assert key.provider == ProviderType.OPENAI
    
    def test_get_best_key_complex_task(self, router):
        """Test getting best key for complex task."""
        router.add_key(ProviderType.OPENAI, "sk-openai", "gpt-4")
        router.add_key(ProviderType.ANTHROPIC, "sk-anthropic", "claude-3")
        
        # Complex task (> 5000 tokens) should prefer Anthropic
        key = router.get_best_key(estimated_tokens=10000)
        assert key is not None
        assert key.provider == ProviderType.ANTHROPIC
    
    def test_get_best_key_with_route(self, router):
        """Test getting best key with selected route."""
        router.add_key(ProviderType.OPENAI, "sk-openai", "gpt-4")
        router.add_key(ProviderType.ANTHROPIC, "sk-anthropic", "claude-3")
        
        route = Route(
            name="anthropic-route",
            provider=ProviderType.ANTHROPIC,
            model="claude-3",
            min_tokens=0,
            max_tokens=999999
        )
        router.add_route(route)
        router.select_route("anthropic-route")
        
        # Should use route's provider regardless of token count
        key = router.get_best_key(estimated_tokens=500)
        assert key is not None
        assert key.provider == ProviderType.ANTHROPIC

class TestFailoverManager:
    """Test FailoverManager operations."""
    
    def test_failover_enabled(self, router):
        """Test failover is enabled by default."""
        assert router.failover_manager.enabled
    
    def test_on_key_error(self, router):
        """Test handling key error."""
        key1_id = router.add_key(ProviderType.OPENAI, "sk-openai-1", "gpt-4")
        key2_id = router.add_key(ProviderType.OPENAI, "sk-openai-2", "gpt-3.5")
        
        # First key fails
        next_key = router.on_error(key1_id, "rate_limit", "Too many requests")
        
        # Should return second key
        assert next_key is not None
        assert next_key.id == key2_id
    
    def test_failover_with_fallback_providers(self, router):
        """Test failover with fallback providers."""
        key1_id = router.add_key(ProviderType.OPENAI, "sk-openai", "gpt-4")
        key2_id = router.add_key(ProviderType.ANTHROPIC, "sk-anthropic", "claude-3")
        
        route = Route(
            name="test-route",
            provider=ProviderType.OPENAI,
            model="gpt-4",
            fallback_providers=[ProviderType.ANTHROPIC]
        )
        router.add_route(route)
        router.select_route("test-route")
        
        # Mark OpenAI key as error
        for _ in range(6):
            router.key_store.mark_key_error(key1_id, "error", "Failed")
        
        # Should failover to Anthropic
        next_key = router.on_error(key1_id, "error", "Failed")
        assert next_key is not None
        assert next_key.provider == ProviderType.ANTHROPIC

class TestRateLimiter:
    """Test RateLimiter operations."""
    
    def test_can_use_key_active(self, router):
        """Test checking if active key can be used."""
        key_id = router.add_key(ProviderType.OPENAI, "sk-test", "gpt-4")
        
        can_use, reason = router.rate_limiter.can_use_key(key_id)
        assert can_use
        assert reason == "OK"
    
    def test_can_use_key_inactive(self, router):
        """Test checking if inactive key can be used."""
        key_id = router.add_key(ProviderType.OPENAI, "sk-test", "gpt-4")
        router.key_store.update_key_status(key_id, KeyStatus.INACTIVE)
        
        can_use, reason = router.rate_limiter.can_use_key(key_id)
        assert not can_use
        assert "status" in reason.lower()
    
    def test_record_usage(self, router):
        """Test recording usage."""
        key_id = router.add_key(ProviderType.OPENAI, "sk-test", "gpt-4")
        
        router.record_usage(key_id, tokens_used=1000)
        
        usage = router.key_store.get_usage(key_id)
        assert usage.requests_today == 1
        assert usage.tokens_today == 1000

class TestAPIRouter:
    """Test APIRouter orchestration."""
    
    def test_get_status(self, router):
        """Test getting router status."""
        router.add_key(ProviderType.OPENAI, "sk-openai", "gpt-4")
        router.add_key(ProviderType.ANTHROPIC, "sk-anthropic", "claude-3")
        
        status = router.get_status()
        
        assert status["total_keys"] == 2
        assert status["active_keys"] == 2
        assert status["error_keys"] == 0
        assert status["failover_enabled"]
        assert "openai" in status["keys_by_provider"]
        assert "anthropic" in status["keys_by_provider"]
    
    def test_full_workflow(self, router):
        """Test complete workflow."""
        # Add keys
        key1 = router.add_key(ProviderType.OPENAI, "sk-openai", "gpt-4")
        key2 = router.add_key(ProviderType.ANTHROPIC, "sk-anthropic", "claude-3")
        
        # Create route
        route = Route(
            name="fast-task",
            provider=ProviderType.OPENAI,
            model="gpt-4",
            min_tokens=0,
            max_tokens=1000,
            fallback_providers=[ProviderType.ANTHROPIC]
        )
        router.add_route(route)
        
        # Select route
        assert router.select_route("fast-task")
        
        # Get best key
        key = router.get_best_key(estimated_tokens=500)
        assert key is not None
        assert key.provider == ProviderType.OPENAI
        
        # Record usage
        router.record_usage(key.id, tokens_used=500)
        
        # Check status
        status = router.get_status()
        assert status["total_keys"] == 2
        assert status["active_keys"] == 2
        
        # Simulate error and failover
        next_key = router.on_error(key.id, "rate_limit", "Too many requests")
        assert next_key is not None

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
