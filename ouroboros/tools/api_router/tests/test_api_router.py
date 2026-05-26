"""
Simple smoke tests for API Router harness.
"""

import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

def test_imports():
    """Test that all modules can be imported."""
    try:
        from api_router_backend import (
            APIRouter, ProviderType, KeyStatus, Route, APIKey
        )
        assert APIRouter is not None
        assert ProviderType is not None
        assert KeyStatus is not None
        assert Route is not None
        assert APIKey is not None
    except ImportError as e:
        pytest.fail(f"Failed to import: {e}")

def test_provider_type_enum():
    """Test ProviderType enum values."""
    from api_router_backend import ProviderType
    
    assert hasattr(ProviderType, 'OPENAI')
    assert hasattr(ProviderType, 'ANTHROPIC')
    assert hasattr(ProviderType, 'GOOGLE')
    assert hasattr(ProviderType, 'OPENROUTER')

def test_key_status_enum():
    """Test KeyStatus enum values."""
    from api_router_backend import KeyStatus
    
    assert hasattr(KeyStatus, 'ACTIVE')
    assert hasattr(KeyStatus, 'INACTIVE')
    assert hasattr(KeyStatus, 'ERROR')

def test_route_creation():
    """Test creating a Route."""
    from api_router_backend import Route, ProviderType
    
    route = Route(
        name="test-route",
        provider=ProviderType.OPENAI,
        model="gpt-4"
    )
    
    assert route.name == "test-route"
    assert route.provider == ProviderType.OPENAI
    assert route.model == "gpt-4"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
