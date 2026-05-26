# API Router — Multi-Provider LLM Key Management

**Version:** 0.1.0  
**Category:** Infrastructure / LLM Management  
**Purpose:** Manage multiple LLM API keys, route requests intelligently, and handle failover automatically.

## Overview

API Router is a CLI harness that provides unified management of API keys across multiple LLM providers (OpenAI, Anthropic, Google, OpenRouter). It enables:

- **Multi-key management** — Store and manage multiple API keys per provider
- **Context-aware routing** — Select the best key based on task complexity (token count)
- **Automatic failover** — Switch to backup keys when one fails
- **Rate limit tracking** — Monitor usage and enforce rate limits
- **Named routes** — Define routing strategies for different task types

## Commands

### Key Management

#### `api-router key add`
Add a new API key to the router.

```bash
api-router key add --provider openai --key sk-... --model gpt-4
```

**Options:**
- `--provider` (required): Provider name (openai, anthropic, google, openrouter)
- `--key` (required): API key (will be prompted if not provided)
- `--model` (required): Model name (e.g., gpt-4, claude-3-opus)

**Output:** Key ID and confirmation

---

#### `api-router key list`
List all stored API keys.

```bash
api-router key list [--provider openai]
```

**Options:**
- `--provider` (optional): Filter by provider

**Output:** Table with ID, Provider, Model, Status, Error count

---

#### `api-router key remove`
Mark a key as inactive (soft delete).

```bash
api-router key remove --key-id 1
```

**Options:**
- `--key-id` (required): Key ID to remove

---

#### `api-router key status`
Show overall key status and health.

```bash
api-router key status
```

**Output:** Total keys, active keys, error keys, failover status, keys by provider

---

#### `api-router key test`
Test if a key is valid and ready to use.

```bash
api-router key test --key-id 1
```

**Options:**
- `--key-id` (required): Key ID to test

**Output:** Validation result and rate limit status

---

### Route Management

#### `api-router route create`
Create a named routing configuration.

```bash
api-router route create --name fast-task --provider openai --model gpt-4 \
  --min-tokens 0 --max-tokens 1000 --fallback anthropic
```

**Options:**
- `--name` (required): Route name
- `--provider` (required): Primary provider
- `--model` (required): Model name
- `--priority` (optional): Priority (default: 1)
- `--min-tokens` (optional): Minimum tokens for this route (default: 0)
- `--max-tokens` (optional): Maximum tokens for this route (default: 999999)
- `--fallback` (optional, multiple): Fallback providers

---

#### `api-router route select`
Select a route for the next request.

```bash
api-router route select --name fast-task
```

**Options:**
- `--name` (required): Route name

---

#### `api-router route info`
Show details of the currently selected route.

```bash
api-router route info
```

**Output:** Route name, provider, model, token range, fallback providers

---

#### `api-router route test`
Test a route (get the best key for that route).

```bash
api-router route test --name fast-task --tokens 500
```

**Options:**
- `--name` (required): Route name
- `--tokens` (optional): Estimated tokens for test (default: 1000)

**Output:** Selected key ID, provider, model, rate limit status

---

### Failover Management

#### `api-router failover enable`
Enable automatic failover.

```bash
api-router failover enable
```

---

#### `api-router failover disable`
Disable automatic failover.

```bash
api-router failover disable
```

---

#### `api-router failover status`
Show failover status.

```bash
api-router failover status
```

**Output:** Enabled/disabled status

---

#### `api-router failover trigger`
Manually trigger failover for a provider.

```bash
api-router failover trigger --provider openai
```

**Options:**
- `--provider` (required): Provider to failover

**Output:** Next available key or error message

---

### Usage Tracking

#### `api-router usage show`
Show usage statistics.

```bash
api-router usage show [--provider openai] [--key-id 1]
```

**Options:**
- `--provider` (optional): Show usage for all keys of a provider
- `--key-id` (optional): Show usage for a specific key
- (no options): Show overall usage

**Output:** Requests/tokens today and this hour

---

#### `api-router usage reset`
Reset usage counters.

```bash
api-router usage reset [--provider openai] [--key-id 1]
```

**Options:**
- `--provider` (optional): Reset for all keys of a provider
- `--key-id` (optional): Reset for a specific key
- (no options): Reset all counters

---

### Debug Commands

#### `api-router debug dump`
Dump all keys and routes as JSON.

```bash
api-router debug dump
```

**Output:** JSON with all keys, routes, and status

---

#### `api-router debug key-info`
Show detailed info for a key.

```bash
api-router debug key-info --key-id 1
```

**Options:**
- `--key-id` (required): Key ID

**Output:** Provider, model, status, error count, rate limits, usage

---

#### `api-router debug routes`
List all defined routes.

```bash
api-router debug routes
```

**Output:** Table with route names, providers, models, priorities

---

#### `api-router debug failover-log`
Show recent failover events.

```bash
api-router debug failover-log
```

**Output:** Last 20 failover events with timestamps and error types

---

### System Commands

#### `api-router version`
Show version.

```bash
api-router version
```

---

#### `api-router health`
Health check.

```bash
api-router health
```

**Output:** Health status and active key count

---

## Usage Examples

### Setup: Add keys for multiple providers

```bash
api-router key add --provider openai --key sk-... --model gpt-4
api-router key add --provider anthropic --key sk-ant-... --model claude-3-opus
api-router key add --provider openrouter --key sk-or-... --model openai/gpt-4
```

### Create routes for different task types

```bash
# Fast tasks (< 1000 tokens) — use cheap provider
api-router route create --name fast-task --provider openai --model gpt-4 \
  --min-tokens 0 --max-tokens 1000 --fallback openrouter

# Complex tasks (> 5000 tokens) — use powerful provider
api-router route create --name complex-task --provider anthropic --model claude-3-opus \
  --min-tokens 5000 --max-tokens 999999 --fallback openai
```

### Select and test a route

```bash
api-router route select --name fast-task
api-router route test --name fast-task --tokens 500
```

### Monitor usage

```bash
api-router usage show
api-router usage show --provider openai
api-router usage show --key-id 1
```

### Debug failover

```bash
api-router debug failover-log
api-router failover trigger --provider openai
```

## Integration with Ouroboros

The API Router is designed to integrate with Ouroboros' LLM layer:

1. **Initialization:** Create APIRouter instance with database path
2. **Key selection:** Call `get_best_key(estimated_tokens)` to get the best key
3. **Usage tracking:** Call `record_usage(key_id, tokens_used)` after each request
4. **Error handling:** Call `on_error(key_id, error_type, error_msg)` on failures
5. **Status:** Call `get_status()` to monitor health

## Database

API Router uses SQLite with the following tables:

- `keys` — Stored API keys (hashed)
- `routes` — Named routing configurations
- `usage` — Usage statistics per key
- `failover_log` — Failover event history

Database location: `api_router.db` (configurable)

## Security

- API keys are stored as SHA256 hashes (never plaintext)
- Keys are marked as INACTIVE instead of deleted (audit trail)
- Error counts trigger automatic key deactivation after 5 errors
- All operations are logged in failover_log

## Performance

- SQLite with WAL mode for concurrent access
- In-memory caching of key status
- Hourly usage counter reset (automatic)
- Efficient rate limit checking

## Future Enhancements

- [ ] Cost tracking per provider
- [ ] Automatic key rotation
- [ ] Webhook notifications on failover
- [ ] Web dashboard for monitoring
- [ ] Integration with Prometheus metrics
