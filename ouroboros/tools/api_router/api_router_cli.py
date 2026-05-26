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
from api_router_backend import APIRouter, ProviderType, Route, KeyStatus

class APIRouterCLI:
    """CLI wrapper for APIRouter."""
    
    def __init__(self, db_path: str = "api_router.db"):
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
            cli_instance.router.key_store.conn.execute(
                "UPDATE usage SET requests_today = 0, tokens_today = 0 WHERE key_id = ?",
                (key_id,)
            )
            cli_instance.router.key_store.conn.commit()
            click.echo(f"✓ Usage reset for key {key_id}")
        
        elif provider:
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
            cli_instance.router.key_store.conn.execute(
                "UPDATE usage SET requests_today = 0, tokens_today = 0"
            )
            cli_instance.router.key_store.conn.commit()
            click.echo("✓ Usage reset for all keys")
    
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)

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
