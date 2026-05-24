"""Graph of Thoughts planning tool.

Lets Ouroboros decompose complex tasks into a DAG of sub-tasks,
execute them in dependency order, and return results.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolEntry, ToolContext
from ouroboros.planning import decompose_task, PlanGraph, PlanNode
from ouroboros.llm import LLMClient

log = logging.getLogger(__name__)

# Set by loop.py via override_handler to inject the ToolRegistry
_registry: Any = None


def _set_registry(reg: Any) -> None:
    global _registry
    _registry = reg


def _execute_node(graph: PlanGraph, node: PlanNode, ctx: ToolContext) -> str:
    """Execute a single plan node, returning the result string."""
    if node.agent == "reason" or node.agent.startswith("tool:"):
        tool_name = node.agent.replace("tool:", "") if node.agent.startswith("tool:") else ""
        if tool_name and _registry is not None:
            result = _registry.execute(tool_name, node.args)
        elif tool_name and _registry is None:
            result = f"(no registry — cannot call {tool_name})"
        else:
            # Pure reasoning: call LLM to think about this step
            plan_ctx = (
                f"Task: {graph.task}\n"
                f"Current step: {node.id} — {node.description}\n"
                f"Previous results:\n"
            )
            for dep_id in node.dependencies:
                dep_node = graph.get_node(dep_id)
                if dep_node and dep_node.result:
                    plan_ctx += f"  [{dep_id}] {dep_node.result[:500]}\n"
            if not node.args.get("task"):
                plan_ctx += f"\nArgs: {json.dumps(node.args, indent=2)}"
            else:
                plan_ctx += f"\n{node.args.get('task', '')}"

            try:
                client = LLMClient()
                model = os.environ.get("OUROBOROS_MODEL_LIGHT") or os.environ.get("DEFAULT_LIGHT_MODEL", "openai/gpt-4o-mini")
                resp_msg, _usage = client.chat(
                    messages=[{"role": "user", "content": plan_ctx}],
                    model=model,
                    reasoning_effort="low",
                    max_tokens=1024,
                )
                result = resp_msg.get("content", "(no response)")
            except Exception as e:
                result = f"(reasoning error: {e})"
        return result


def handle_plan_task(ctx: ToolContext, task: str = "", steps: str = "") -> str:
    """Decompose a complex task into a plan and execute it step by step.

    Either provide 'task' for LLM-based plan generation,
    or 'steps' as a JSON array of step objects for manual plans.
    """
    if not task and not steps:
        return "⚠️ Provide either 'task' (auto-plan) or 'steps' (manual plan)."

    if steps:
        try:
            steps_data = json.loads(steps) if isinstance(steps, str) else steps
            graph = PlanGraph(steps_data.get("task", "Manual plan"))
            for s in steps_data.get("nodes", steps_data if isinstance(steps_data, list) else []):
                graph.add_node(PlanNode(
                    id=s.get("id", f"step_{len(graph.nodes)+1}"),
                    description=s.get("description", ""),
                    agent=s.get("agent", "reason"),
                    args=s.get("args", {}),
                    dependencies=s.get("dependencies", []),
                ))
        except (json.JSONDecodeError, KeyError) as e:
            return f"⚠️ Invalid steps JSON: {e}"
    else:
        # Auto-decompose via LLM
        tools_avail = _registry.available_tools() if _registry else []
        tools_summary = "\n".join(f"- {t}" for t in sorted(tools_avail))
        try:
            graph = decompose_task(task, tools_summary)
        except Exception as e:
            return f"⚠️ Plan generation failed: {e}"

    if not graph.nodes:
        return "⚠️ No plan steps generated."

    # Execute nodes in dependency order
    output: Dict[str, Any] = {
        "task": graph.task,
        "steps_total": len(graph.nodes),
        "steps": [],
        "errors": [],
    }

    max_rounds = 50
    rounds = 0
    while not graph.is_complete and rounds < max_rounds:
        rounds += 1
        ready = graph.next_ready()
        if not ready and not graph.is_complete:
            failed = graph.failed_nodes
            if failed:
                for nid in failed:
                    output["errors"].append(f"Step {nid} failed after retries")
            break

        for nid in ready:
            node = graph.get_node(nid)
            if not node:
                continue
            node.status = "running"
            try:
                result = _execute_node(graph, node, ctx)
                graph.mark_done(nid, result)
                output["steps"].append({
                    "id": nid,
                    "description": node.description,
                    "status": "done",
                    "result_preview": result[:200],
                })
            except Exception as e:
                graph.mark_failed(nid, str(e))
                output["steps"].append({
                    "id": nid,
                    "description": node.description,
                    "status": "failed",
                    "error": str(e),
                })

    failed = graph.failed_nodes
    for nid in failed:
        fn = graph.get_node(nid)
        output["errors"].append(f"[{nid}] {fn.result[:300] if fn else ''}")

    output["complete"] = graph.is_complete
    output["rounds"] = rounds

    return json.dumps(output, indent=2, ensure_ascii=False)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("plan_task", {
            "name": "plan_task",
            "description": "Decompose a complex task into a DAG of sub-tasks and execute them in dependency order. Uses Graph of Thoughts for multi-step reasoning. Provide 'task' for auto-planning (LLM generates plan) or 'steps' for a manual plan.",
            "parameters": {"type": "object", "properties": {
                "task": {"type": "string",
                         "description": "Complex task to auto-decompose into sub-steps"},
                "steps": {"type": "string",
                          "description": "JSON manual plan - array of {id, description, agent, args, dependencies} or object with {task, nodes}"},
            }, "required": []},
        }, handle_plan_task),
    ]
