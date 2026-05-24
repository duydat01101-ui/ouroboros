"""Development tools — sandbox, package mgmt, debug, test gen, CI/CD."""

import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

SANDBOX_DIR = pathlib.Path("/tmp/ouroboros_sandbox/")


# ─── Sandbox — safe code execution ─────────────────────────────────────

def _sandbox_exec(ctx: ToolContext, code: str, language: str = "python") -> str:
    """Run code in isolated temp dir with timeout. Supports python/node/shell."""
    safe_dir = SANDBOX_DIR / f"run_{int(time.time())}"
    safe_dir.mkdir(parents=True, exist_ok=True)
    result = {"stdout": "", "stderr": "", "exit_code": -1, "error": ""}
    try:
        if language == "python":
            script = safe_dir / "script.py"
            script.write_text(code)
            r = subprocess.run(
                [sys.executable, str(script)],
                cwd=safe_dir, capture_output=True, text=True, timeout=30
            )
        elif language == "node":
            script = safe_dir / "script.mjs"
            script.write_text(code)
            r = subprocess.run(
                ["node", str(script)],
                cwd=safe_dir, capture_output=True, text=True, timeout=30
            )
        elif language == "shell":
            r = subprocess.run(
                code, shell=True, cwd=safe_dir,
                capture_output=True, text=True, timeout=30
            )
        else:
            return f"Unsupported language: {language}. Use python/node/shell."
        result["stdout"] = r.stdout[:5000]
        result["stderr"] = r.stderr[:2000]
        result["exit_code"] = r.returncode
    except subprocess.TimeoutExpired:
        result["error"] = "Timed out after 30s"
    except Exception as e:
        result["error"] = str(e)
    shutil.rmtree(safe_dir, ignore_errors=True)
    return json.dumps(result, indent=2)


def _sandbox_test_file(ctx: ToolContext, relative_path: str) -> str:
    """Copy a file from repo to sandbox and run its tests."""
    source = pathlib.Path(ctx.repo_dir) / relative_path
    if not source.exists():
        return f"File not found: {relative_path}"
    safe_dir = SANDBOX_DIR / f"test_{int(time.time())}"
    safe_dir.mkdir(parents=True, exist_ok=True)
    try:
        dest = safe_dir / source.name
        shutil.copy2(source, dest)
        if relative_path.endswith(".py"):
            r = subprocess.run(
                [sys.executable, "-m", "pytest", str(dest), "-v", "--tb=short"],
                cwd=safe_dir, capture_output=True, text=True, timeout=30
            )
        elif relative_path.endswith(".js") or relative_path.endswith(".mjs"):
            r = subprocess.run(
                ["node", "--test", str(dest)],
                cwd=safe_dir, capture_output=True, text=True, timeout=30
            )
        else:
            r = subprocess.run(
                [sys.executable, str(dest)],
                cwd=safe_dir, capture_output=True, text=True, timeout=30
            )
        result = {
            "stdout": r.stdout[:3000],
            "stderr": r.stderr[:2000],
            "exit_code": r.returncode,
            "passed": r.returncode == 0
        }
    except subprocess.TimeoutExpired:
        result = {"error": "Timed out after 30s", "passed": False}
    except Exception as e:
        result = {"error": str(e), "passed": False}
    shutil.rmtree(safe_dir, ignore_errors=True)
    return json.dumps(result, indent=2)


# ─── Package manager ───────────────────────────────────────────────────

def _pkg_install(ctx: ToolContext, packages: str, manager: str = "auto") -> str:
    """Install packages using pip or npm."""
    repo_dir = pathlib.Path(ctx.repo_dir)
    try:
        if manager == "auto":
            if (repo_dir / "requirements.txt").exists() or (repo_dir / "setup.py").exists():
                manager = "pip"
            elif (repo_dir / "package.json").exists():
                manager = "npm"
            else:
                manager = "pip"
        if manager == "pip":
            req = repo_dir / "requirements.txt"
            if req.exists() and not packages:
                r = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req)],
                                   capture_output=True, text=True, timeout=120)
            elif packages:
                r = subprocess.run([sys.executable, "-m", "pip", "install"] + packages.split(),
                                   capture_output=True, text=True, timeout=120)
            else:
                return "No packages specified and no requirements.txt found"
        elif manager == "npm":
            cmd = ["npm", "install"]
            if packages:
                cmd.extend(packages.split())
            r = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, timeout=120)
        else:
            return f"Unsupported manager: {manager}"
        return json.dumps({
            "stdout": r.stdout[:2000],
            "stderr": r.stderr[:1000],
            "exit_code": r.returncode,
            "success": r.returncode == 0
        }, indent=2)
    except subprocess.TimeoutExpired:
        return '{"error": "Timed out after 120s", "success": false}'
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, indent=2)


def _pkg_check(ctx: ToolContext) -> str:
    """Check what packages are installed vs what's required."""
    repo_dir = pathlib.Path(ctx.repo_dir)
    results = {}
    req_file = repo_dir / "requirements.txt"
    if req_file.exists():
        required = set()
        installed = set()
        for line in req_file.read_text().splitlines():
            pkg = line.strip().split("==")[0].split(">=")[0].split("<")[0].strip()
            if pkg and not pkg.startswith("#"):
                required.add(pkg.lower())
        r = subprocess.run([sys.executable, "-m", "pip", "list", "--format=freeze"],
                           capture_output=True, text=True, timeout=30)
        for line in r.stdout.splitlines():
            installed.add(line.split("==")[0].strip().lower())
        missing = required - installed
        results["pip"] = {"required": len(required), "installed": len(installed),
                          "missing": list(missing)[:20]}
    pkg_file = repo_dir / "package.json"
    if pkg_file.exists():
        import json as _json
        data = _json.loads(pkg_file.read_text())
        deps = list((data.get("dependencies") or {}).keys())
        if os.path.exists(str(repo_dir / "node_modules")):
            installed_npm = set(os.listdir(str(repo_dir / "node_modules")))
            missing_npm = [d for d in deps if d not in installed_npm]
        else:
            missing_npm = deps
        results["npm"] = {"required": len(deps), "missing": missing_npm[:20]}
    return json.dumps(results, indent=2)


# ─── Auto-debug ────────────────────────────────────────────────────────

def _auto_debug(ctx: ToolContext, error_text: str, file_path: str = "") -> str:
    """Analyze error and suggest/produce fix. Optionally reads file context."""
    context = {}
    if file_path:
        full = pathlib.Path(ctx.repo_dir) / file_path
        if full.exists():
            context["file"] = full.read_text()[:5000]
            context["file_path"] = file_path
    context["error"] = error_text
    return json.dumps({
        "analysis": "Error context captured. Agent should analyze and fix using claude_code_edit.",
        "next_step": f"Read {file_path or 'affected file'} with repo_read, then apply fix with claude_code_edit.",
        "context": context
    }, indent=2)


def _sys_health(ctx: ToolContext) -> str:
    """Report system health — disk, memory, processes."""
    import shutil
    info = {}
    total, used, free = shutil.disk_usage("/")
    info["disk"] = {"total_gb": round(total / (2**30), 1),
                    "used_gb": round(used / (2**30), 1),
                    "free_gb": round(free / (2**30), 1),
                    "free_pct": round(free / total * 100, 1)}
    try:
        r = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=10)
        info["memory"] = r.stdout
    except Exception:
        pass
    try:
        r = subprocess.run(["ps", "-eo", "pid,cmd,%mem,%cpu", "--sort=-%mem", "--headers"],
                           capture_output=True, text=True, timeout=10)
        lines = r.stdout.splitlines()[:10]
        info["top_processes"] = lines
    except Exception:
        pass
    return json.dumps(info, indent=2)


# ─── Auto-test generator ───────────────────────────────────────────────

GENERATE_TEST_PROMPT = """You are a test-writing specialist. Given this source file, generate comprehensive tests.
Return ONLY valid code — no explanations, no markdown formatting.

Rules:
- If .py file: use pytest style
- If .js/.mjs file: use node --test or jest style
- Cover: normal cases, edge cases, error cases
- Use the same imports/patterns as the source file
- Tests must be self-contained (create mocks if needed)
- Keep tests under 100 lines

Source file:
{code}
"""


def _generate_tests(ctx: ToolContext, file_path: str) -> str:
    """Generate test file for given source file. Uses LLM to write tests."""
    full = pathlib.Path(ctx.repo_dir) / file_path
    if not full.exists():
        return f"File not found: {file_path}"
    code = full.read_text()
    prompt = GENERATE_TEST_PROMPT.format(code=code[:8000])
    return json.dumps({
        "file": file_path,
        "prompt": prompt,
        "note": "Agent should generate tests using claude_code_edit with this prompt.",
        "suggested_test_path": file_path.replace(".py", "_test.py").replace("/", "/test_")
    }, indent=2)


def _run_tests(ctx: ToolContext, path: str = "tests/") -> str:
    """Run pytest on given path, return results."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", path, "-q", "--tb=line", "--no-header"],
            cwd=ctx.repo_dir, capture_output=True, text=True, timeout=60
        )
        return json.dumps({
            "exit_code": r.returncode,
            "passed": r.returncode == 0,
            "stdout": r.stdout[:3000],
            "stderr": r.stderr[:1000],
            "summary": "All tests passed" if r.returncode == 0 else f"{r.stdout.strip().split(chr(10))[-1] if r.stdout.strip() else 'Failed'}"
        }, indent=2)
    except subprocess.TimeoutExpired:
        return '{"error": "Timed out after 60s", "passed": false}'
    except Exception as e:
        return json.dumps({"error": str(e), "passed": False}, indent=2)


# ─── CI/CD pipeline ────────────────────────────────────────────────────

CI_STAGES = ["lint", "typecheck", "test", "build"]


def _run_ci(ctx: ToolContext, stages: str = "") -> str:
    """Run CI pipeline: lint → typecheck → test. Stages: comma-separated or all."""
    selected = [s.strip() for s in stages.split(",")] if stages else CI_STAGES
    results = {}
    all_pass = True
    repo_dir = ctx.repo_dir

    for stage in selected:
        if stage not in CI_STAGES:
            results[stage] = {"status": "skipped", "reason": f"Unknown stage: {stage}"}
            continue
        try:
            if stage == "lint":
                r = subprocess.run(
                    [sys.executable, "-m", "ruff", "check", "ouroboros/", "supervisor/"],
                    cwd=repo_dir, capture_output=True, text=True, timeout=30
                )
            elif stage == "typecheck":
                r = subprocess.run(
                    [sys.executable, "-m", "mypy", "ouroboros/", "--ignore-missing-imports"],
                    cwd=repo_dir, capture_output=True, text=True, timeout=60
                )
            elif stage == "test":
                r = subprocess.run(
                    [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line", "--no-header"],
                    cwd=repo_dir, capture_output=True, text=True, timeout=60
                )
            elif stage == "build":
                r = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-e", "."],
                    cwd=repo_dir, capture_output=True, text=True, timeout=120
                )
            passed = r.returncode == 0
            if not passed:
                all_pass = False
            results[stage] = {
                "status": "passed" if passed else "failed",
                "stdout": r.stdout[:1000],
                "stderr": r.stderr[:500]
            }
        except subprocess.TimeoutExpired:
            results[stage] = {"status": "timeout"}
            all_pass = False
        except Exception as e:
            results[stage] = {"status": "error", "error": str(e)}
            all_pass = False

    return json.dumps({
        "stages": results,
        "all_passed": all_pass,
        "summary": "All stages passed ✓" if all_pass else "Some stages failed ✗"
    }, indent=2)


def _lint_code(ctx: ToolContext, path: str = "ouroboros/") -> str:
    """Run ruff linter on given path."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "ruff", "check", path],
            cwd=ctx.repo_dir, capture_output=True, text=True, timeout=30
        )
        return json.dumps({
            "exit_code": r.returncode,
            "clean": r.returncode == 0,
            "output": r.stdout[:2000] + r.stderr[:1000],
            "summary": "Lint passed" if r.returncode == 0 else "Lint found issues"
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


# ─── Registry ──────────────────────────────────────────────────────────

def get_tools() -> list[ToolEntry]:
    return [
        ToolEntry("sandbox_exec", {
            "name": "sandbox_exec",
            "description": "Run code safely in isolated temp dir. Supports python/node/shell. 30s timeout. Use for testing code before deploying.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Code to execute"},
                    "language": {"type": "string", "description": "python, node, or shell (default python)"},
                },
                "required": ["code"]
            }
        }, _sandbox_exec),

        ToolEntry("sandbox_test_file", {
            "name": "sandbox_test_file",
            "description": "Copy a repo file to sandbox and run its tests in isolation. Safe for testing before deploy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string", "description": "Path relative to repo root, e.g. ouroboros/tools/git.py"},
                },
                "required": ["relative_path"]
            }
        }, _sandbox_test_file),

        ToolEntry("pkg_install", {
            "name": "pkg_install",
            "description": "Install Python (pip) or Node (npm) packages. Detects requirements.txt or package.json automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "packages": {"type": "string", "description": "Space-separated package names (optional, reads requirements.txt if empty)"},
                    "manager": {"type": "string", "description": "pip, npm, or auto (default auto)"},
                },
            }
        }, _pkg_install),

        ToolEntry("pkg_check", {
            "name": "pkg_check",
            "description": "Check installed vs required packages. Reports missing dependencies.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }, _pkg_check),

        ToolEntry("auto_debug", {
            "name": "auto_debug",
            "description": "Capture error context for debugging. Pass error text and optional file path. Agent will analyze and fix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "error_text": {"type": "string", "description": "Error message or stack trace"},
                    "file_path": {"type": "string", "description": "Path to affected file (optional)"},
                },
                "required": ["error_text"]
            }
        }, _auto_debug),

        ToolEntry("sys_health", {
            "name": "sys_health",
            "description": "Report system health: disk usage, memory, top processes.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }, _sys_health),

        ToolEntry("generate_tests", {
            "name": "generate_tests",
            "description": "Generate test file for a given source file. Provides prompt for claude_code_edit to write tests.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to source file relative to repo root"},
                },
                "required": ["file_path"]
            }
        }, _generate_tests),

        ToolEntry("run_tests", {
            "name": "run_tests",
            "description": "Run pytest on given path. Returns results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Test path (default tests/)"},
                },
            }
        }, _run_tests),

        ToolEntry("run_ci", {
            "name": "run_ci",
            "description": "Run CI pipeline: lint → typecheck → test. Stages: comma-separated or all (default). Returns each stage result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "stages": {"type": "string", "description": "Comma-separated stages: lint,typecheck,test,build (optional, default all)"},
                },
            }
        }, _run_ci),

        ToolEntry("lint_code", {
            "name": "lint_code",
            "description": "Run ruff linter on given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to lint (default ouroboros/)"},
                },
            }
        }, _lint_code),
    ]
