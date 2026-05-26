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


"""
RoutingEngine and FailoverManager for API Router.
"""

from typing import Optional, List, Tuple

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
        self.failover_chain: List[Tuple[int, ProviderType]] = []  # (key_id, provider)
    
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


"""
CLI interface for API Router harness.

Usage:
  api-router key add --provider openai --key sk-... --model gpt-4
  api-router key list
  api-router route select --name fast-task
  api-router failover enable
  api-router usage show --provider openai
"""

import click
import json
from typing import Optional
from datetime import datetime
from pathlib import Path

class APIRouterCLI:
    """CLI wrapper for APIRouter."""
    
    def __init__(self, db_path: str = "api_router.db"):
        # Import here to avoid circular dependency
        self.router = APIRouter(db_path)
        self.ProviderType = ProviderType
        self.Route = Route
        self.KeyStatus = KeyStatus
    
    def format_key(self, key) -> dict:
        """Format APIKey for display."""
        return {
            "id": key.id,
            "provider": key.provider.value,
            "model": key.model,
            "status": key.status.value,
            "error_count": key.error_count,
            "created_at": key.created_at,
            "last_used": key.last_used
        }
    
    def format_usage(self, usage) -> dict:
        """Format Usage for display."""
        return {
            "key_id": usage.key_id,
            "requests_today": usage.requests_today,
            "tokens_today": usage.tokens_today,
            "requests_hour": usage.requests_hour,
            "tokens_hour": usage.tokens_hour,
            "last_reset_hour": usage.last_reset_hour
        }

# Create CLI instance
cli_instance = APIRouterCLI()

@click.group()
def cli():
    """API Router — Multi-provider LLM key management."""
    pass

@cli.group()
def key():
    """Manage API keys."""
    pass

@key.command()
@click.option('--provider', type=click.Choice(['openai', 'anthropic', 'google', 'openrouter']), required=True)
@click.option('--key', required=True, prompt='API Key', hide_input=True)
@click.option('--model', required=True, help='Model name (e.g., gpt-4, claude-3-opus)')
def add(provider, key, model):
    """Add a new API key."""
    try:
        provider_enum = cli_instance.ProviderType(provider)
        key_id = cli_instance.router.add_key(provider_enum, key, model)
        click.echo(f"✓ Key added (ID: {key_id})")
        click.echo(f"  Provider: {provider}")
        click.echo(f"  Model: {model}")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@key.command()
@click.option('--provider', type=click.Choice(['openai', 'anthropic', 'google', 'openrouter']), default=None)
def list(provider):
    """List all API keys."""
    try:
        if provider:
            provider_enum = cli_instance.ProviderType(provider)
            keys = cli_instance.router.key_store.get_keys(provider_enum)
        else:
            keys = cli_instance.router.key_store.get_keys()
        
        if not keys:
            click.echo("No keys found.")
            return
        
        click.echo(f"\n{'ID':<4} {'Provider':<12} {'Model':<20} {'Status':<10} {'Errors':<6}")
        click.echo("-" * 60)
        
        for key in keys:
            click.echo(
                f"{key.id:<4} {key.provider.value:<12} {key.model:<20} "
                f"{key.status.value:<10} {key.error_count:<6}"
            )
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@key.command()
@click.option('--key-id', type=int, required=True)
def remove(key_id):
    """Remove an API key."""
    try:
        # Mark as inactive instead of deleting
        cli_instance.router.key_store.update_key_status(
            key_id, 
            cli_instance.KeyStatus.INACTIVE
        )
        click.echo(f"✓ Key {key_id} marked as inactive")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@key.command()
@click.option('--provider', type=click.Choice(['openai', 'anthropic', 'google', 'openrouter']), default=None)
def status(provider):
    """Show key status."""
    try:
        status_data = cli_instance.router.get_status()
        
        click.echo("\n=== API Router Status ===")
        click.echo(f"Total keys: {status_data['total_keys']}")
        click.echo(f"Active keys: {status_data['active_keys']}")
        click.echo(f"Error keys: {status_data['error_keys']}")
        click.echo(f"Failover enabled: {status_data['failover_enabled']}")
        click.echo(f"Current route: {status_data['current_route'] or 'None'}")
        
        click.echo("\nKeys by provider:")
        for prov, keys_list in status_data['keys_by_provider'].items():
            click.echo(f"  {prov}: {len(keys_list)} keys")
            for k in keys_list:
                click.echo(f"    - ID {k['id']}: {k['model']} ({k['status']})")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@key.command()
@click.option('--key-id', type=int, required=True)
def test(key_id):
    """Test a key (validate format and basic connectivity)."""
    try:
        keys = cli_instance.router.key_store.get_keys()
        key = next((k for k in keys if k.id == key_id), None)
        
        if not key:
            click.echo(f"✗ Key {key_id} not found")
            return
        
        # Check rate limits
        can_use, reason = cli_instance.router.rate_limiter.can_use_key(key_id)
        
        if can_use:
            click.echo(f"✓ Key {key_id} is valid and ready to use")
            click.echo(f"  Provider: {key.provider.value}")
            click.echo(f"  Model: {key.model}")
            click.echo(f"  Status: {key.status.value}")
        else:
            click.echo(f"✗ Key {key_id} cannot be used: {reason}")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)


"""
Route and Failover commands for API Router CLI.
"""

import click

@cli.group()
def route():
    """Manage routing configurations."""
    pass

@route.command()
@click.option('--name', required=True, help='Route name')
@click.option('--provider', type=click.Choice(['openai', 'anthropic', 'google', 'openrouter']), required=True)
@click.option('--model', required=True, help='Model name')
@click.option('--priority', type=int, default=1)
@click.option('--min-tokens', type=int, default=0)
@click.option('--max-tokens', type=int, default=999999)
@click.option('--fallback', multiple=True, help='Fallback providers')
def create(name, provider, model, priority, min_tokens, max_tokens, fallback):
    """Create a new route."""
    try:
        provider_enum = cli_instance.ProviderType(provider)
        fallback_providers = [cli_instance.ProviderType(p) for p in fallback]
        
        route = cli_instance.Route(
            name=name,
            provider=provider_enum,
            model=model,
            priority=priority,
            fallback_providers=fallback_providers,
            min_tokens=min_tokens,
            max_tokens=max_tokens
        )
        
        cli_instance.router.add_route(route)
        click.echo(f"✓ Route '{name}' created")
        click.echo(f"  Provider: {provider}")
        click.echo(f"  Model: {model}")
        click.echo(f"  Token range: {min_tokens}-{max_tokens}")
        if fallback:
            click.echo(f"  Fallback: {', '.join(fallback)}")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@route.command()
@click.option('--name', required=True)
def select(name):
    """Select a route for next request."""
    try:
        if cli_instance.router.select_route(name):
            click.echo(f"✓ Route '{name}' selected")
        else:
            click.echo(f"✗ Route '{name}' not found")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@route.command()
def info():
    """Show current route info."""
    try:
        current = cli_instance.router.routing_engine.current_route
        
        if not current:
            click.echo("No route selected")
            return
        
        route = cli_instance.router.key_store.get_route(current)
        if not route:
            click.echo(f"Route '{current}' not found")
            return
        
        click.echo(f"\n=== Route: {route.name} ===")
        click.echo(f"Provider: {route.provider.value}")
        click.echo(f"Model: {route.model}")
        click.echo(f"Priority: {route.priority}")
        click.echo(f"Token range: {route.min_tokens}-{route.max_tokens}")
        if route.fallback_providers:
            click.echo(f"Fallback: {', '.join(p.value for p in route.fallback_providers)}")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@route.command()
@click.option('--name', required=True)
@click.option('--tokens', type=int, default=1000, help='Estimated tokens for test')
def test(name, tokens):
    """Test a route (get best key for route)."""
    try:
        if not cli_instance.router.select_route(name):
            click.echo(f"✗ Route '{name}' not found")
            return
        
        key = cli_instance.router.get_best_key(tokens)
        
        if key:
            click.echo(f"✓ Route '{name}' test passed")
            click.echo(f"  Selected key: ID {key.id}")
            click.echo(f"  Provider: {key.provider.value}")
            click.echo(f"  Model: {key.model}")
            
            # Check rate limits
            can_use, reason = cli_instance.router.rate_limiter.can_use_key(key.id)
            click.echo(f"  Rate limit check: {reason}")
        else:
            click.echo(f"✗ No available key for route '{name}'")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@cli.group()
def failover():
    """Manage failover settings."""
    pass

@failover.command()
def enable():
    """Enable automatic failover."""
    try:
        cli_instance.router.failover_manager.enable()
        click.echo("✓ Automatic failover enabled")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@failover.command()
def disable():
    """Disable automatic failover."""
    try:
        cli_instance.router.failover_manager.disable()
        click.echo("✓ Automatic failover disabled")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@failover.command()
def status():
    """Show failover status."""
    try:
        enabled = cli_instance.router.failover_manager.enabled
        status_str = "enabled" if enabled else "disabled"
        click.echo(f"Automatic failover: {status_str}")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@failover.command()
@click.option('--provider', type=click.Choice(['openai', 'anthropic', 'google', 'openrouter']), required=True)
def trigger(provider):
    """Manually trigger failover for a provider."""
    try:
        provider_enum = cli_instance.ProviderType(provider)
        next_key = cli_instance.router.failover_manager.trigger_failover(provider_enum)
        
        if next_key:
            click.echo(f"✓ Failover triggered for {provider}")
            click.echo(f"  Next key: ID {next_key.id}")
            click.echo(f"  Model: {next_key.model}")
        else:
            click.echo(f"✗ No fallback key available for {provider}")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@cli.group()
def usage():
    """View usage statistics."""
    pass

@usage.command()
@click.option('--provider', type=click.Choice(['openai', 'anthropic', 'google', 'openrouter']), default=None)
@click.option('--key-id', type=int, default=None)
def show(provider, key_id):
    """Show usage statistics."""
    try:
        if key_id:
            # Show usage for specific key
            usage_data = cli_instance.router.key_store.get_usage(key_id)
            if not usage_data:
                click.echo(f"✗ Key {key_id} not found")
                return
            
            click.echo(f"\n=== Usage for Key {key_id} ===")
            click.echo(f"Requests today: {usage_data.requests_today}")
            click.echo(f"Tokens today: {usage_data.tokens_today}")
            click.echo(f"Requests this hour: {usage_data.requests_hour}")
            click.echo(f"Tokens this hour: {usage_data.tokens_hour}")
        
        elif provider:
            # Show usage for all keys of a provider
            provider_enum = cli_instance.ProviderType(provider)
            keys = cli_instance.router.key_store.get_keys(provider_enum)
            
            click.echo(f"\n=== Usage for {provider} ===")
            click.echo(f"{'Key ID':<8} {'Model':<20} {'Req/Day':<10} {'Tokens/Day':<12}")
            click.echo("-" * 50)
            
            for key in keys:
                usage_data = cli_instance.router.key_store.get_usage(key.id)
                if usage_data:
                    click.echo(
                        f"{key.id:<8} {key.model:<20} "
                        f"{usage_data.requests_today:<10} {usage_data.tokens_today:<12}"
                    )
        
        else:
            # Show overall usage
            keys = cli_instance.router.key_store.get_keys()
            total_requests = 0
            total_tokens = 0
            
            for key in keys:
                usage_data = cli_instance.router.key_store.get_usage(key.id)
                if usage_data:
                    total_requests += usage_data.requests_today
                    total_tokens += usage_data.tokens_today
            
            click.echo(f"\n=== Overall Usage ===")
            click.echo(f"Total requests today: {total_requests}")
            click.echo(f"Total tokens today: {total_tokens}")
    
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@usage.command()
@click.option('--provider', type=click.Choice(['openai', 'anthropic', 'google', 'openrouter']), default=None)
@click.option('--key-id', type=int, default=None)
def reset(provider, key_id):
    """Reset usage counters."""
    try:
        if key_id:
            # Reset specific key
            cli_instance.router.key_store.conn.execute(
                "UPDATE usage SET requests_today = 0, tokens_today = 0 WHERE key_id = ?",
                (key_id,)
            )
            cli_instance.router.key_store.conn.commit()
            click.echo(f"✓ Usage reset for key {key_id}")
        
        elif provider:
            # Reset all keys for provider
            provider_enum = cli_instance.ProviderType(provider)
            keys = cli_instance.router.key_store.get_keys(provider_enum)
            
            for key in keys:
                cli_instance.router.key_store.conn.execute(
                    "UPDATE usage SET requests_today = 0, tokens_today = 0 WHERE key_id = ?",
                    (key.id,)
                )
            
            cli_instance.router.key_store.conn.commit()
            click.echo(f"✓ Usage reset for all {provider} keys")
        
        else:
            # Reset all
            cli_instance.router.key_store.conn.execute(
                "UPDATE usage SET requests_today = 0, tokens_today = 0"
            )
            cli_instance.router.key_store.conn.commit()
            click.echo("✓ Usage reset for all keys")
    
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)


"""
Debug commands and main entry point for API Router CLI.
"""

import click
import json

@cli.group()
def debug():
    """Debug and diagnostic commands."""
    pass

@debug.command()
def dump():
    """Dump all keys and routes as JSON."""
    try:
        keys = cli_instance.router.key_store.get_keys()
        
        keys_data = []
        for key in keys:
            usage = cli_instance.router.key_store.get_usage(key.id)
            keys_data.append({
                "id": key.id,
                "provider": key.provider.value,
                "model": key.model,
                "status": key.status.value,
                "error_count": key.error_count,
                "created_at": key.created_at,
                "last_used": key.last_used,
                "usage": {
                    "requests_today": usage.requests_today if usage else 0,
                    "tokens_today": usage.tokens_today if usage else 0,
                    "requests_hour": usage.requests_hour if usage else 0,
                    "tokens_hour": usage.tokens_hour if usage else 0
                }
            })
        
        status = cli_instance.router.get_status()
        
        output = {
            "status": status,
            "keys": keys_data,
            "current_route": cli_instance.router.routing_engine.current_route
        }
        
        click.echo(json.dumps(output, indent=2))
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@debug.command()
@click.option('--key-id', type=int, required=True)
def key_info(key_id):
    """Show detailed info for a key."""
    try:
        keys = cli_instance.router.key_store.get_keys()
        key = next((k for k in keys if k.id == key_id), None)
        
        if not key:
            click.echo(f"✗ Key {key_id} not found")
            return
        
        usage = cli_instance.router.key_store.get_usage(key_id)
        
        click.echo(f"\n=== Key {key_id} Details ===")
        click.echo(f"Provider: {key.provider.value}")
        click.echo(f"Model: {key.model}")
        click.echo(f"Status: {key.status.value}")
        click.echo(f"Error count: {key.error_count}")
        click.echo(f"Created: {key.created_at}")
        click.echo(f"Last used: {key.last_used or 'Never'}")
        click.echo(f"\nRate limits:")
        click.echo(f"  RPM: {key.rate_limit_rpm}")
        click.echo(f"  TPM: {key.rate_limit_tpm}")
        
        if usage:
            click.echo(f"\nUsage today:")
            click.echo(f"  Requests: {usage.requests_today}")
            click.echo(f"  Tokens: {usage.tokens_today}")
            click.echo(f"Usage this hour:")
            click.echo(f"  Requests: {usage.requests_hour}")
            click.echo(f"  Tokens: {usage.tokens_hour}")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@debug.command()
def routes():
    """List all routes."""
    try:
        # Get all routes from database
        rows = cli_instance.router.key_store.conn.execute(
            "SELECT * FROM routes"
        ).fetchall()
        
        if not rows:
            click.echo("No routes defined.")
            return
        
        click.echo(f"\n{'Name':<20} {'Provider':<12} {'Model':<20} {'Priority':<8}")
        click.echo("-" * 60)
        
        for row in rows:
            click.echo(
                f"{row['name']:<20} {row['provider']:<12} "
                f"{row['model']:<20} {row['priority']:<8}"
            )
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@debug.command()
def failover_log():
    """Show recent failover events."""
    try:
        rows = cli_instance.router.key_store.conn.execute(
            """SELECT fl.*, k.provider, k.model 
            FROM failover_log fl
            JOIN keys k ON fl.key_id = k.id
            ORDER BY fl.timestamp DESC
            LIMIT 20"""
        ).fetchall()
        
        if not rows:
            click.echo("No failover events.")
            return
        
        click.echo(f"\n{'Time':<20} {'Key ID':<8} {'Provider':<12} {'Error':<20}")
        click.echo("-" * 60)
        
        for row in rows:
            click.echo(
                f"{row['timestamp']:<20} {row['key_id']:<8} "
                f"{row['provider']:<12} {row['error_type']:<20}"
            )
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

@cli.command()
def version():
    """Show version."""
    click.echo("API Router v0.1.0")

@cli.command()
def health():
    """Health check."""
    try:
        status = cli_instance.router.get_status()
        
        if status['active_keys'] > 0:
            click.echo("✓ API Router is healthy")
            click.echo(f"  Active keys: {status['active_keys']}")
            click.echo(f"  Failover: {'enabled' if status['failover_enabled'] else 'disabled'}")
        else:
            click.echo("✗ API Router has no active keys")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

if __name__ == '__main__':
    cli()
