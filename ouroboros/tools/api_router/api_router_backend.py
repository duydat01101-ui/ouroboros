"""
API Router Backend — Multi-provider LLM key management for Ouroboros.

Handles:
- Key storage and validation
- Context-aware routing
- Automatic failover
- Rate limiting and usage tracking
"""

import sqlite3
import json
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Tuple
from enum import Enum
import hashlib

class ProviderType(str, Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OPENROUTER = "openrouter"

class KeyStatus(str, Enum):
    """Status of an API key."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    EXHAUSTED = "exhausted"

@dataclass
class APIKey:
    """Represents a single API key."""
    id: int
    provider: ProviderType
    key_hash: str  # SHA256 hash of actual key (never store plaintext)
    model: str  # e.g., "gpt-4", "claude-3-opus"
    status: KeyStatus = KeyStatus.ACTIVE
    rate_limit_rpm: int = 3500  # requests per minute
    rate_limit_tpm: int = 90000  # tokens per minute
    created_at: str = None
    last_used: str = None
    error_count: int = 0
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()

@dataclass
class Route:
    """Named routing configuration."""
    name: str
    provider: ProviderType
    model: str
    priority: int = 1
    fallback_providers: List[ProviderType] = None
    min_tokens: int = 0  # minimum tokens for this route
    max_tokens: int = 999999  # maximum tokens for this route
    
    def __post_init__(self):
        if self.fallback_providers is None:
            self.fallback_providers = []

@dataclass
class Usage:
    """Usage statistics for a key."""
    key_id: int
    requests_today: int = 0
    tokens_today: int = 0
    requests_hour: int = 0
    tokens_hour: int = 0
    last_reset_hour: str = None
    
    def __post_init__(self):
        if self.last_reset_hour is None:
            self.last_reset_hour = datetime.utcnow().isoformat()

class KeyStore:
    """SQLite-backed storage for API keys and routes."""
    
    def __init__(self, db_path: str = "api_router.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
    
    def _init_schema(self):
        """Create tables if they don't exist."""
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            model TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            rate_limit_rpm INTEGER DEFAULT 3500,
            rate_limit_tpm INTEGER DEFAULT 90000,
            created_at TEXT NOT NULL,
            last_used TEXT,
            error_count INTEGER DEFAULT 0
        )
        """)
        
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            priority INTEGER DEFAULT 1,
            fallback_providers TEXT,
            min_tokens INTEGER DEFAULT 0,
            max_tokens INTEGER DEFAULT 999999
        )
        """)
        
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_id INTEGER NOT NULL UNIQUE,
            requests_today INTEGER DEFAULT 0,
            tokens_today INTEGER DEFAULT 0,
            requests_hour INTEGER DEFAULT 0,
            tokens_hour INTEGER DEFAULT 0,
            last_reset_hour TEXT NOT NULL,
            FOREIGN KEY (key_id) REFERENCES keys(id)
        )
        """)
        
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS failover_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_id INTEGER NOT NULL,
            error_type TEXT NOT NULL,
            error_message TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (key_id) REFERENCES keys(id)
        )
        """)
        
        self.conn.commit()
    
    def add_key(self, provider: ProviderType, key: str, model: str) -> int:
        """Add a new API key (stores hash, not plaintext)."""
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        now = datetime.utcnow().isoformat()
        
        cursor = self.conn.execute(
            """INSERT INTO keys 
            (provider, key_hash, model, created_at, status)
            VALUES (?, ?, ?, ?, ?)""",
            (provider.value, key_hash, model, now, KeyStatus.ACTIVE.value)
        )
        self.conn.commit()
        
        key_id = cursor.lastrowid
        # Initialize usage tracking
        self.conn.execute(
            """INSERT INTO usage (key_id, last_reset_hour)
            VALUES (?, ?)""",
            (key_id, now)
        )
        self.conn.commit()
        
        return key_id
    
    def get_keys(self, provider: Optional[ProviderType] = None) -> List[APIKey]:
        """Get all keys, optionally filtered by provider."""
        if provider:
            rows = self.conn.execute(
                "SELECT * FROM keys WHERE provider = ? ORDER BY priority DESC",
                (provider.value,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM keys").fetchall()
        
        return [self._row_to_apikey(row) for row in rows]
    
    def _row_to_apikey(self, row) -> APIKey:
        """Convert database row to APIKey object."""
        return APIKey(
            id=row['id'],
            provider=ProviderType(row['provider']),
            key_hash=row['key_hash'],
            model=row['model'],
            status=KeyStatus(row['status']),
            rate_limit_rpm=row['rate_limit_rpm'],
            rate_limit_tpm=row['rate_limit_tpm'],
            created_at=row['created_at'],
            last_used=row['last_used'],
            error_count=row['error_count']
        )
    
    def update_key_status(self, key_id: int, status: KeyStatus):
        """Update key status."""
        self.conn.execute(
            "UPDATE keys SET status = ? WHERE id = ?",
            (status.value, key_id)
        )
        self.conn.commit()
    
    def mark_key_error(self, key_id: int, error_type: str, error_msg: str = ""):
        """Log an error for a key and increment error count."""
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            """INSERT INTO failover_log (key_id, error_type, error_message, timestamp)
            VALUES (?, ?, ?, ?)""",
            (key_id, error_type, error_msg, now)
        )
        
        # Increment error count
        self.conn.execute(
            "UPDATE keys SET error_count = error_count + 1 WHERE id = ?",
            (key_id,)
        )
        
        # If error count > 5, mark as error
        row = self.conn.execute(
            "SELECT error_count FROM keys WHERE id = ?",
            (key_id,)
        ).fetchone()
        
        if row['error_count'] > 5:
            self.update_key_status(key_id, KeyStatus.ERROR)
        
        self.conn.commit()
    
    def add_route(self, route: Route):
        """Add or update a route."""
        fallback_json = json.dumps([p.value for p in route.fallback_providers])
        
        self.conn.execute(
            """INSERT OR REPLACE INTO routes 
            (name, provider, model, priority, fallback_providers, min_tokens, max_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (route.name, route.provider.value, route.model, route.priority,
             fallback_json, route.min_tokens, route.max_tokens)
        )
        self.conn.commit()
    
    def get_route(self, name: str) -> Optional[Route]:
        """Get a route by name."""
        row = self.conn.execute(
            "SELECT * FROM routes WHERE name = ?",
            (name,)
        ).fetchone()
        
        if not row:
            return None
        
        fallback = json.loads(row['fallback_providers']) if row['fallback_providers'] else []
        return Route(
            name=row['name'],
            provider=ProviderType(row['provider']),
            model=row['model'],
            priority=row['priority'],
            fallback_providers=[ProviderType(p) for p in fallback],
            min_tokens=row['min_tokens'],
            max_tokens=row['max_tokens']
        )
    
    def get_usage(self, key_id: int) -> Optional[Usage]:
        """Get usage stats for a key."""
        row = self.conn.execute(
            "SELECT * FROM usage WHERE key_id = ?",
            (key_id,)
        ).fetchone()
        
        if not row:
            return None
        
        return Usage(
            key_id=row['key_id'],
            requests_today=row['requests_today'],
            tokens_today=row['tokens_today'],
            requests_hour=row['requests_hour'],
            tokens_hour=row['tokens_hour'],
            last_reset_hour=row['last_reset_hour']
        )
    
    def update_usage(self, key_id: int, tokens_used: int = 0):
        """Update usage stats for a key."""
        now = datetime.utcnow()
        usage = self.get_usage(key_id)
        
        if not usage:
            return
        
        # Check if hour has passed
        last_hour = datetime.fromisoformat(usage.last_reset_hour)
        if (now - last_hour).total_seconds() > 3600:
            # Reset hourly counters
            self.conn.execute(
                """UPDATE usage 
                SET requests_hour = 1, tokens_hour = ?, last_reset_hour = ?
                WHERE key_id = ?""",
                (tokens_used, now.isoformat(), key_id)
            )
        else:
            # Increment counters
            self.conn.execute(
                """UPDATE usage 
                SET requests_today = requests_today + 1,
                    tokens_today = tokens_today + ?,
                    requests_hour = requests_hour + 1,
                    tokens_hour = tokens_hour + ?
                WHERE key_id = ?""",
                (tokens_used, tokens_used, key_id)
            )
        
        # Update last_used timestamp
        self.conn.execute(
            "UPDATE keys SET last_used = ? WHERE id = ?",
            (now.isoformat(), key_id)
        )
        
        self.conn.commit()
    
    def close(self):
        """Close database connection."""
        self.conn.close()


class RoutingEngine:
    """Selects the best provider/key based on context."""
    
    def __init__(self, key_store: KeyStore):
        self.key_store = key_store
        self.current_route: Optional[str] = None
    
    def select_route(self, name: str) -> bool:
        """Select a named route."""
        route = self.key_store.get_route(name)
        if not route:
            return False
        self.current_route = name
        return True
    
    def get_best_key(self, 
                     estimated_tokens: int = 1000,
                     preferred_provider: Optional[ProviderType] = None) -> Optional[APIKey]:
        """
        Select the best key based on:
        1. Current route (if set)
        2. Estimated token count
        3. Provider preference
        4. Key availability and rate limits
        """
        
        # If route is set, use it
        if self.current_route:
            route = self.key_store.get_route(self.current_route)
            if route and route.min_tokens <= estimated_tokens <= route.max_tokens:
                return self._get_best_key_for_provider(route.provider)
        
        # If preferred provider given, use it
        if preferred_provider:
            return self._get_best_key_for_provider(preferred_provider)
        
        # Context-aware selection based on token count
        if estimated_tokens < 1000:
            # Simple task — use fast, cheap provider
            for provider in [ProviderType.OPENAI, ProviderType.OPENROUTER]:
                key = self._get_best_key_for_provider(provider)
                if key:
                    return key
        elif estimated_tokens > 5000:
            # Complex task — use powerful provider
            for provider in [ProviderType.ANTHROPIC, ProviderType.OPENAI]:
                key = self._get_best_key_for_provider(provider)
                if key:
                    return key
        else:
            # Medium task — balanced provider
            for provider in [ProviderType.OPENAI, ProviderType.ANTHROPIC]:
                key = self._get_best_key_for_provider(provider)
                if key:
                    return key
        
        # Fallback: any active key
        keys = self.key_store.get_keys()
        for key in keys:
            if key.status == KeyStatus.ACTIVE:
                return key
        
        return None
    
    def _get_best_key_for_provider(self, provider: ProviderType) -> Optional[APIKey]:
        """Get the best active key for a provider."""
        keys = self.key_store.get_keys(provider)
        
        for key in keys:
            if key.status == KeyStatus.ACTIVE:
                # Check rate limits
                usage = self.key_store.get_usage(key.id)
                if usage:
                    if (usage.requests_hour < key.rate_limit_rpm and
                        usage.tokens_hour < key.rate_limit_tpm):
                        return key
        
        return None

class FailoverManager:
    """Handles automatic failover when a key fails."""
    
    def __init__(self, key_store: KeyStore, routing_engine: RoutingEngine):
        self.key_store = key_store
        self.routing_engine = routing_engine
        self.enabled = True
        self.failover_chain: List[Tuple[int, ProviderType]] = []
    
    def enable(self):
        """Enable automatic failover."""
        self.enabled = True
    
    def disable(self):
        """Disable automatic failover."""
        self.enabled = False
    
    def on_key_error(self, key_id: int, error_type: str, error_msg: str = "") -> Optional[APIKey]:
        """
        Handle a key error. Returns next key to try, or None if no fallback available.
        """
        if not self.enabled:
            return None
        
        # Log the error
        self.key_store.mark_key_error(key_id, error_type, error_msg)
        
        # Get the failed key's provider
        keys = self.key_store.get_keys()
        failed_key = next((k for k in keys if k.id == key_id), None)
        
        if not failed_key:
            return None
        
        # Try next key for same provider
        next_key = self._get_next_key_for_provider(failed_key.provider, exclude_id=key_id)
        if next_key:
            return next_key
        
        # Try fallback providers
        if self.routing_engine.current_route:
            route = self.key_store.get_route(self.routing_engine.current_route)
            if route:
                for fallback_provider in route.fallback_providers:
                    next_key = self._get_next_key_for_provider(fallback_provider)
                    if next_key:
                        return next_key
        
        # No fallback available
        return None
    
    def _get_next_key_for_provider(self, 
                                   provider: ProviderType,
                                   exclude_id: Optional[int] = None) -> Optional[APIKey]:
        """Get next available key for a provider."""
        keys = self.key_store.get_keys(provider)
        
        for key in keys:
            if exclude_id and key.id == exclude_id:
                continue
            
            if key.status in [KeyStatus.ACTIVE, KeyStatus.INACTIVE]:
                usage = self.key_store.get_usage(key.id)
                if usage:
                    if (usage.requests_hour < key.rate_limit_rpm and
                        usage.tokens_hour < key.rate_limit_tpm):
                        return key
        
        return None
    
    def trigger_failover(self, provider: ProviderType) -> Optional[APIKey]:
        """Manually trigger failover for a provider."""
        return self._get_next_key_for_provider(provider)

class RateLimiter:
    """Tracks and enforces rate limits."""
    
    def __init__(self, key_store: KeyStore):
        self.key_store = key_store
    
    def can_use_key(self, key_id: int) -> Tuple[bool, str]:
        """Check if a key can be used (rate limits not exceeded)."""
        key = None
        keys = self.key_store.get_keys()
        for k in keys:
            if k.id == key_id:
                key = k
                break
        
        if not key:
            return False, "Key not found"
        
        if key.status != KeyStatus.ACTIVE:
            return False, f"Key status is {key.status}"
        
        usage = self.key_store.get_usage(key_id)
        if not usage:
            return False, "Usage not found"
        
        if usage.requests_hour >= key.rate_limit_rpm:
            return False, f"RPM limit exceeded ({usage.requests_hour}/{key.rate_limit_rpm})"
        
        if usage.tokens_hour >= key.rate_limit_tpm:
            return False, f"TPM limit exceeded ({usage.tokens_hour}/{key.rate_limit_tpm})"
        
        return True, "OK"
    
    def record_usage(self, key_id: int, tokens_used: int = 0):
        """Record usage for a key."""
        self.key_store.update_usage(key_id, tokens_used)

class APIRouter:
    """Main API Router orchestrator."""
    
    def __init__(self, db_path: str = "api_router.db"):
        self.key_store = KeyStore(db_path)
        self.routing_engine = RoutingEngine(self.key_store)
        self.failover_manager = FailoverManager(self.key_store, self.routing_engine)
        self.rate_limiter = RateLimiter(self.key_store)
    
    def add_key(self, provider: ProviderType, key: str, model: str) -> int:
        """Add a new API key."""
        return self.key_store.add_key(provider, key, model)
    
    def add_route(self, route: Route):
        """Add a new route."""
        self.key_store.add_route(route)
    
    def select_route(self, name: str) -> bool:
        """Select a route."""
        return self.routing_engine.select_route(name)
    
    def get_best_key(self, estimated_tokens: int = 1000) -> Optional[APIKey]:
        """Get the best key for current context."""
        return self.routing_engine.get_best_key(estimated_tokens)
    
    def record_usage(self, key_id: int, tokens_used: int = 0):
        """Record usage for a key."""
        self.rate_limiter.record_usage(key_id, tokens_used)
    
    def on_error(self, key_id: int, error_type: str, error_msg: str = "") -> Optional[APIKey]:
        """Handle a key error and get next key to try."""
        return self.failover_manager.on_key_error(key_id, error_type, error_msg)
    
    def get_status(self) -> dict:
        """Get overall router status."""
        keys = self.key_store.get_keys()
        active_keys = [k for k in keys if k.status == KeyStatus.ACTIVE]
        error_keys = [k for k in keys if k.status == KeyStatus.ERROR]
        
        return {
            "total_keys": len(keys),
            "active_keys": len(active_keys),
            "error_keys": len(error_keys),
            "failover_enabled": self.failover_manager.enabled,
            "current_route": self.routing_engine.current_route,
            "keys_by_provider": self._group_keys_by_provider(keys)
        }
    
    def _group_keys_by_provider(self, keys: List[APIKey]) -> dict:
        """Group keys by provider."""
        grouped = {}
        for key in keys:
            if key.provider not in grouped:
                grouped[key.provider.value] = []
            grouped[key.provider.value].append({
                "id": key.id,
                "model": key.model,
                "status": key.status.value,
                "error_count": key.error_count
            })
        return grouped
    
    def close(self):
        """Close database connection."""
        self.key_store.close()
