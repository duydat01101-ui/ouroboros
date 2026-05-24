# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ouroboros is a self-developing AI agent that rewrites its own code, improves itself, and maintains persistent identity across restarts. It runs in Docker, uses a data volume (`/data/`) for persistence, communicates via Telegram, and pushes changes to its own GitHub fork. Governed by a philosophical constitution (BIBLE.md) with 18 sections.

## Folder Structure Convention (từ lớn → nhỏ)

```
Ouroboros/
├── launcher.py              # Entry point (root, duy nhất)
├── BIBLE.md / VERSION       # Identity + phiên bản
│
├── ouroboros/               # [LỚN] Core agent — code chính
├── supervisor/              # Process management
├── prompts/                 # Identity files (SYSTEM.md, CONSCIOUSNESS.md)
│
├── infra/                   # Build/deploy (Docker, Makefile)
├── tests/                   # Test suites (unit + e2e)
├── docs/                    # Tài liệu website
├── improvements-log/        # Evolution records
└── data/                    # [NHỎ] Runtime data (gitignored, volume-only)
```

Quy tắc sắp xếp:
- **Thư mục lớn → nhỏ**: core code > management > config > infra > docs > data
- **Trong mỗi thư mục**: file quan trọng nhất lên đầu, ít quan trọng xuống cuối
- **Không để file rác ở root**: `_*.py`, `temp*`, debug scripts phải nằm trong thư mục riêng hoặc xóa
- **infra/** chứa mọi thứ về build/deploy: Dockerfile, docker-compose.yml, Makefile
- **data/** chỉ chứa runtime data (trong .gitignore nếu cần)

## Commands

```bash
cd infra && make test        # Run smoke tests
cd infra && make test-v      # Verbose test output
cd infra && make health      # Code complexity metrics
cd infra && make clean       # Clean caches
cd infra && make test-e2e    # E2E tests in Docker (requires API keys)

# Single test
python3 -m pytest tests/test_smoke.py::test_name -v

# Docker (from repo root)
docker compose -f infra/docker-compose.yml up -d
```

## Linting

Ruff configured in `pyproject.toml`: line-length 120, Python 3.10+, rules E/F/W/I, E501 ignored.

## Architecture

Three-layer design:

**Layer 1 — Supervisor** (`supervisor/`): Process management, Telegram client, task queue, worker lifecycle, persistent state on data volume, git operations, event dispatch.

**Layer 2 — Agent Core** (`ouroboros/`): Per-worker agent instance. `agent.py` orchestrates message→context→tools. `loop.py` is the core LLM tool execution loop. `llm.py` is the sole OpenRouter API client. `context.py` assembles LLM context. `memory.py` manages scratchpad, identity, user context, and chat history. `consciousness.py` runs background thinking between tasks.

**Layer 3 — Tools** (`ouroboros/tools/`): Plugin registry with auto-discovery. Each module exports `get_tools()` returning `List[ToolEntry]`. `registry.py` is the SSOT — it collects all tools via `pkgutil.iter_modules()`. ~33 tools total. Every tool receives a `ToolContext` dataclass with repo dir, Drive root, task ID, event queue, browser state.

**Entry points**: `launcher.py` → `supervisor/workers.py` → `ouroboros/agent.py` → `ouroboros/loop.py`.

**Persistence**: All state lives on the data volume at `/data/` (JSON state files, JSONL event logs, Markdown memory files). No database. Atomic writes with file locks.

## Key Conventions

- **SSOT pattern**: state.py owns state, llm.py owns API calls, registry.py owns tools. No duplicate definitions.
- **Minimalism (Bible section 8)**: Modules should fit in LLM context (~1000 lines). Methods >150 lines signal decomposition needed.
- **Versioning (Bible section 15)**: `VERSION` file == git tags == README changelog. Philosophy changes = MAJOR bump.
- **Tool auto-discovery**: Add a new tool by creating `ouroboros/tools/new_tool.py` with a `get_tools()` function. No registration code needed.
- **BIBLE.md is the protected core** (Bible section 17): Cannot be deleted, gutted, or replaced wholesale. Changes require user approval and MAJOR version bump.
- **Self-improvements require user approval** unless `/no-approve` mode is active (Bible section 7).
- **Folder convention** (Bible section 18): Always follow the "từ lớn → nhỏ" hierarchy. Do not create files at root unless they are entry points or identity files. New tools go in `ouroboros/tools/`. New services go in `supervisor/`. Build config goes in `infra/`.

## Required Environment Variables

`OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `GITHUB_TOKEN`, `GITHUB_USER`, `GITHUB_REPO`, `ANTHROPIC_API_KEY`

## Key Files

| File | Role |
|------|------|
| `BIBLE.md` | Constitution (18 sections, Philosophy v4.0) |
| `prompts/SYSTEM.md` | Main system prompt |
| `prompts/CONSCIOUSNESS.md` | Background consciousness prompt |
| `ouroboros/loop.py` | Core LLM tool execution loop (largest module) |
| `ouroboros/agent.py` | Per-worker orchestrator |
| `ouroboros/tools/registry.py` | Tool plugin system (SSOT) |
| `supervisor/state.py` | Persistent state management |
| `supervisor/workers.py` | Worker process lifecycle |
| `launcher.py` | Main entry point (Docker VPS) |
| `tests/e2e/harness.py` | E2E test harness (Docker-sandboxed, real LLM) |
| `infra/docker-compose.yml` | Docker orchestration |
| `infra/Makefile` | Dev commands |
