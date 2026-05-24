"""Graph of Thoughts planning engine.

Decomposes complex tasks into DAG of sub-tasks,
executes them respecting dependencies, supports retry.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ouroboros.utils import estimate_tokens

log = logging.getLogger(__name__)


@dataclass
class PlanNode:
    id: str
    description: str
    agent: str  # "reason" (LLM-only), "tool:name" (call tool), "subtask" (recursive)
    args: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending"  # pending | running | done | failed | skipped
    result: str = ""
    max_retries: int = 2
    retries: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "agent": self.agent,
            "dependencies": self.dependencies,
            "status": self.status,
            "result_preview": self.result[:120] if self.result else "",
            "retries": self.retries,
        }


class PlanGraph:
    """DAG of PlanNodes. Supports topological execution."""

    def __init__(self, task: str):
        self.task = task
        self.nodes: Dict[str, PlanNode] = {}
        self._errors: List[str] = []

    def add_node(self, node: PlanNode) -> None:
        self.nodes[node.id] = node

    def get_node(self, node_id: str) -> Optional[PlanNode]:
        return self.nodes.get(node_id)

    def next_ready(self) -> List[str]:
        """Return node IDs whose dependencies are all done and status is pending."""
        ready = []
        for nid, node in self.nodes.items():
            if node.status != "pending":
                continue
            deps_met = all(
                self.nodes.get(d) and self.nodes[d].status == "done"
                for d in node.dependencies
            )
            if deps_met:
                ready.append(nid)
        return ready

    @property
    def is_complete(self) -> bool:
        return all(n.status in ("done", "skipped") for n in self.nodes.values())

    @property
    def failed_nodes(self) -> List[str]:
        return [nid for nid, n in self.nodes.items() if n.status == "failed"]

    def mark_done(self, node_id: str, result: str) -> None:
        node = self.nodes.get(node_id)
        if node:
            node.status = "done"
            node.result = result

    def mark_failed(self, node_id: str, error: str) -> None:
        node = self.nodes.get(node_id)
        if not node:
            return
        node.retries += 1
        if node.retries >= node.max_retries:
            node.status = "failed"
            node.result = error
            self._errors.append(f"[{node_id}] {error}")
        else:
            node.status = "pending"  # will retry

    def summary(self) -> str:
        lines = [f"Plan: {self.task}", f"Nodes: {len(self.nodes)}"]
        for nid, n in self.nodes.items():
            lines.append(f"  [{n.status}] {nid}: {n.description}")
        if self._errors:
            lines.append("Errors:")
            for e in self._errors[-5:]:
                lines.append(f"  {e}")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps({
            "task": self.task,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "errors": self._errors,
            "complete": self.is_complete,
        }, indent=2)


def decompose_task(task: str, tools_summary: str, llm_client=None) -> PlanGraph:
    """Use LLM to decompose a task into a DAG of PlanNodes.

    Args:
        task: The user's request / task description
        tools_summary: Available tools description for the LLM
        llm_client: LLMClient instance (creates one if None)

    Returns:
        PlanGraph with nodes in dependency order
    """
    prompt = f"""You are a planning agent. Decompose this task into a DAG of sub-tasks.

Task: {task}

Available tools:
{tools_summary}

Rules:
- Break the task into 2-8 steps (nodes)
- Each node has: id, description, agent, args, dependencies
- agent is "tool:tool_name" to call a tool, or "reason" for LLM reasoning
- First node has empty dependencies []
- Later nodes depend on earlier outputs via dependencies list
- Each node's args should include the key parameters needed

Respond ONLY with valid JSON:
{{
  "nodes": [
    {{
      "id": "step_1",
      "description": "what to do in this step",
      "agent": "tool:tool_name or reason",
      "args": {{key: value}},
      "dependencies": []
    }}
  ]
}}"""

    from ouroboros.llm import LLMClient

    client = llm_client or LLMClient()
    try:
        model = os.environ.get("OUROBOROS_MODEL_LIGHT") or os.environ.get("DEFAULT_LIGHT_MODEL", "openai/gpt-4o-mini")
        resp_msg, _usage = client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            reasoning_effort="low",
            max_tokens=2048,
            temperature=0.3,
        )
        raw = resp_msg.get("content", "")
        # Extract JSON from response
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        data = json.loads(raw)
    except Exception as e:
        log.warning(f"LLM plan decomposition failed: {e}, falling back to linear plan")
        graph = PlanGraph(task)
        graph.add_node(PlanNode(
            id="step_1",
            description=f"Execute task: {task[:200]}",
            agent="reason",
            args={"task": task},
            dependencies=[],
        ))
        return graph

    graph = PlanGraph(task)
    for n in data.get("nodes", []):
        graph.add_node(PlanNode(
            id=n.get("id", f"step_{len(graph.nodes)+1}"),
            description=n.get("description", ""),
            agent=n.get("agent", "reason"),
            args=n.get("args", {}),
            dependencies=n.get("dependencies", []),
        ))
    if not graph.nodes:
        graph.add_node(PlanNode(id="step_1", description=f"Do: {task[:200]}", agent="reason", args={}))
    return graph
