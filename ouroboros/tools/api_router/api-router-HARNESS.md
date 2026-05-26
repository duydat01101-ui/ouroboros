# API Router Harness — Installation & Integration Guide

**Version:** 0.1.0  
**Status:** Production-ready  
**Last updated:** 2026-05-26

## What is API Router?

API Router is a CLI harness that provides unified management of API keys across multiple LLM providers. It enables Ouroboros to:

- Store and manage multiple API keys per provider
- Route requests intelligently based on task complexity
- Handle automatic failover when keys fail
- Track usage and enforce rate limits
- Define named routing strategies

## Installation

### Prerequisites

- Python 3.10+
- SQLite3 (usually included)
- Click (for CLI)

### Setup

1. **Copy files to Ouroboros tools directory:**

```bash
cp api_router_backend.py /app/ouroboros/tools/api_router/
cp api_router_cli.py /app/ouroboros/tools/api_router/
cp __init__.py /app/ouroboros/tools/api_router/
cp test_api_router.py /app/ouroboros/tools/api_router/tests/
```

2. **Install dependencies:**

```bash
pip install click
```

3. **Verify installation:**

```bash
python -m ouroboros.tools.api_router.api_router_cli --help
```

## Quick Start

### 1. Add API Keys

```bash
# Add OpenAI key
python -m ouroboros.tools.api_router.api_router_cli key add \
  --provider openai --key sk-... --model gpt-4

# Add Anthropic key
python -m ouroboros.tools.api_router.api_router_cli key add \
  --provider anthropic --key sk-ant-... --model claude-3-opus

# Add OpenRouter key (fallback)
python -m ouroboros.tools.api_router.api_router_cli key add \
  --provider openrouter --key sk-or-... --model openai/gpt-4
```

### 2. Create Routes

```bash
# Fast tasks (< 1000 tokens) — use cheap provider
python -m ouroboros.tools.api_router.api_router_cli route create \
  --name fast-task --provider openai --model gpt-4 \
  --min-tokens 0 --max-tokens 1000 --fallback openrouter

# Complex tasks (> 5000 tokens) — use powerful provider
python -m ouroboros.tools.api_router.api_router_cli route create \
  --name complex-task --provider anthropic --model claude-3-opus \
  --min-tokens 5000 --max-tokens 999999 --fallback openai
```

### 3. Use in Code

```python
from ouroboros.tools.api_router import APIRouter

# Initialize router
router = APIRouter(db_path="/data/api_router.db")

# Add keys programmatically
router.add_key(ProviderType.OPENAI, "sk-...", "gpt-4")

# Select route
router.select_route("fast-task")

# Get best key for current context
key = router.get_best_key(estimated_tokens=500)

# Use the key with your LLM client
response = call_llm(key.key, key.model, prompt)

# Record usage
router.record_usage(key.id, tokens_used=response.usage.total_tokens)

# Handle errors
if error:
    next_key = router.on_error(key.id, "rate_limit", "Too many requests")
    if next_key:
        # Retry with next key
        response = call_llm(next_key.key, next_key.model, prompt)
```

## Integration with Ouroboros

### Step 1: Update llm.py

Modify `ouroboros/llm.py` to use API Router:

```python
from ouroboros.tools.api_router import APIRouter, ProviderType

class LLMClient:
    def __init__(self):
        self.router = APIRouter(db_path="/data/api_router.db")
    
    def call(self, prompt, estimated_tokens=1000):
        # Get best key from router
        key = self.router.get_best_key(estimated_tokens)
        if not key:
            raise Exception("No available API keys")
        
        # Call LLM
        try:
            response = self._call_provider(key, prompt)
            self.router.record_usage(key.id, response.usage.total_tokens)
            return response
        except Exception as e:
            # Try failover
            next_key = self.router.on_error(key.id, "error", str(e))
            if next_key:
                return self.call(prompt, estimated_tokens)
            raise
    
    def _call_provider(self, key, prompt):
        # Implementation depends on provider
        if key.provider == ProviderType.OPENAI:
            return self._call_openai(key, prompt)
        elif key.provider == ProviderType.ANTHROPIC:
            return self._call_anthropic(key, prompt)
        # ... etc
```

### Step 2: Initialize Router on Startup

In `ouroboros/agent.py` or startup code:

```python
from ouroboros.tools.api_router import APIRouter

def initialize_router():
    router = APIRouter(db_path="/data/api_router.db")
    
    # Load keys from environment or config
    # This is optional — keys can be added via CLI
    
    return router
```

### Step 3: Add Router Tool to Ouroboros

Create `ouroboros/tools/api_router_tool.py`:

```python
import click
from ouroboros.tools.api_router import APIRouter

@click.group()
def api_router():
    """API Router management."""
    pass

# Import all commands from api_router_cli
from ouroboros.tools.api_router.api_router_cli import cli as router_cli

# Register with Ouroboros tool system
def get_tools():
    return {
        "api_router": router_cli
    }
```

## Configuration

### Database Location

By default, API Router uses `api_router.db` in the current directory. To use a custom location:

```python
router = APIRouter(db_path="/data/api_router.db")
```

### Rate Limits

Default rate limits per key:
- RPM (Requests Per Minute): 3500
- TPM (Tokens Per Minute): 90000

To customize, modify `KeyStore._create_table()` in `api_router_backend.py`.

### Failover Strategy

By default, failover is enabled. To disable:

```python
router.failover_manager.disable()
```

To manually trigger failover:

```python
next_key = router.failover_manager.trigger_failover(ProviderType.OPENAI)
```

## Monitoring

### Check Router Health

```bash
python -m ouroboros.tools.api_router.api_router_cli health
```

### View Usage Statistics

```bash
# Overall usage
python -m ouroboros.tools.api_router.api_router_cli usage show

# Usage by provider
python -m ouroboros.tools.api_router.api_router_cli usage show --provider openai

# Usage by key
python -m ouroboros.tools.api_router.api_router_cli usage show --key-id 1
```

### Debug Failover Events

```bash
python -m ouroboros.tools.api_router.api_router_cli debug failover-log
```

### Dump All Data

```bash
python -m ouroboros.tools.api_router.api_router_cli debug dump > router_state.json
```

## Testing

Run the test suite:

```bash
pytest ouroboros/tools/api_router/test_api_router.py -v
```

Test coverage:
- KeyStore operations (add, list, update, error handling)
- RoutingEngine (route selection, context-aware key selection)
- FailoverManager (automatic failover, fallback chains)
- RateLimiter (rate limit checking, usage tracking)
- APIRouter (orchestration, full workflow)

## Troubleshooting

### "No available API keys"

**Cause:** No active keys in the router.

**Solution:**
```bash
python -m ouroboros.tools.api_router.api_router_cli key list
python -m ouroboros.tools.api_router.api_router_cli key add --provider openai --key sk-... --model gpt-4
```

### "Rate limit exceeded"

**Cause:** Key has exceeded RPM or TPM limits.

**Solution:**
```bash
# Check usage
python -m ouroboros.tools.api_router.api_router_cli usage show --key-id 1

# Reset counters (if needed)
python -m ouroboros.tools.api_router.api_router_cli usage reset --key-id 1

# Or wait for hourly reset (automatic)
```

### "Key marked as ERROR"

**Cause:** Key has failed 5+ times.

**Solution:**
```bash
# Check key status
python -m ouroboros.tools.api_router.api_router_cli key status

# Remove the key
python -m ouroboros.tools.api_router.api_router_cli key remove --key-id 1

# Add a new key
python -m ouroboros.tools.api_router.api_router_cli key add --provider openai --key sk-... --model gpt-4
```

### "Route not found"

**Cause:** Route name doesn't exist.

**Solution:**
```bash
# List all routes
python -m ouroboros.tools.api_router.api_router_cli debug routes

# Create the route
python -m ouroboros.tools.api_router.api_router_cli route create --name my-route --provider openai --model gpt-4
```

## Performance Notes

- **Database:** SQLite with WAL mode for concurrent access
- **Caching:** Key status cached in memory
- **Usage reset:** Hourly automatic reset (configurable)
- **Failover:** O(n) lookup where n = number of keys per provider

For high-volume usage (>1000 requests/hour), consider:
- Using multiple keys per provider
- Distributing load across providers
- Monitoring failover events

## Security

- API keys stored as SHA256 hashes (never plaintext)
- Keys marked INACTIVE instead of deleted (audit trail)
- All operations logged in failover_log
- Database file should be protected (chmod 600)

## Future Enhancements

- [ ] Cost tracking per provider
- [ ] Automatic key rotation
- [ ] Webhook notifications on failover
- [ ] Web dashboard for monitoring
- [ ] Prometheus metrics export
- [ ] Multi-region failover
- [ ] Key expiration management

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review test cases in `test_api_router.py`
3. Check failover log: `api-router debug failover-log`
4. Dump state: `api-router debug dump`
