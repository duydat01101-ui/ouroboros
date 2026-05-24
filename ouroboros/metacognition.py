"""Metacognition engine — confidence scoring, uncertainty detection,
self-evaluation, and knowledge gap identification.

Lets Ouroboros think about its own thinking (metacognition).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
import re


log = logging.getLogger(__name__)


def evaluate_response(
    task: str,
    response: str,
    context: str = "",
    llm_client: Any = None,
) -> Dict[str, Any]:
    """Evaluate a response for confidence, correctness, and completeness.

    Uses a lightweight LLM call to score the response on multiple axes.

    Returns:
        Dict with keys: confidence (1-10), reasoning, gaps, suggestions
    """
    prompt = (
        "You are a metacognitive evaluator. Assess the following response.\n\n"
        f"## Task / Question\n{task[:500]}\n\n"
        f"## Response to evaluate\n{response[:1500]}\n\n"
    )
    if context:
        prompt += f"## Relevant context\n{context[:500]}\n\n"

    prompt += (
        "Evaluate on these axes (1-10 scale):\n"
        "1. **confidence** — how certain is the response? (1=wild guess, 10=verified fact)\n"
        "2. **completeness** — does it fully answer the task? (1=totally missing, 10=exhaustive)\n"
        "3. **specificity** — are claims specific/verifiable or vague? (1=vague, 10=highly specific)\n"
        "\n"
        "Then identify:\n"
        "- **gaps**: what information is missing or assumed?\n"
        "- **suggestions**: what would improve the response?\n"
        "\n"
        "Respond ONLY with valid JSON:\n"
        '{"confidence": 8, "completeness": 7, "specificity": 6, '
        '"gaps": ["list of gaps"], "suggestions": ["improvements"], '
        '"knowledge_gaps": ["things I do not know that are relevant"]}'
    )

    from ouroboros.llm import LLMClient

    client = llm_client or LLMClient()
    try:
        model = os.environ.get("OUROBOROS_MODEL_LIGHT") or os.environ.get("DEFAULT_LIGHT_MODEL", "openai/gpt-4o-mini")
        resp_msg, _usage = client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            reasoning_effort="low",
            max_tokens=1024,
        )
        raw = resp_msg.get("content", "")
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
        else:
            data = json.loads(raw)
        return {
            "confidence": data.get("confidence", 5),
            "completeness": data.get("completeness", 5),
            "specificity": data.get("specificity", 5),
            "gaps": data.get("gaps", []),
            "suggestions": data.get("suggestions", []),
            "knowledge_gaps": data.get("knowledge_gaps", []),
        }
    except Exception as e:
        log.warning("metacognition evaluation failed: %s", e)
        return {
            "confidence": 0,
            "completeness": 0,
            "specificity": 0,
            "gaps": [f"evaluation failed: {e}"],
            "suggestions": [],
            "knowledge_gaps": [],
        }


def generate_refine_prompt(evaluation: Dict[str, Any]) -> str:
    """Generate a system prompt to refine a response based on evaluation."""
    parts = ["[SELF-EVALUATION]"]

    if evaluation.get("gaps"):
        parts.append("Identified gaps: " + "; ".join(evaluation["gaps"][:3]))
    if evaluation.get("knowledge_gaps"):
        parts.append("Missing knowledge: " + "; ".join(evaluation["knowledge_gaps"][:3]))
    if evaluation.get("suggestions"):
        parts.append("Suggestions: " + "; ".join(evaluation["suggestions"][:3]))

    conf = evaluation.get("confidence", 0)
    if conf < 4:
        parts.append("⚠️ CRITICAL: Low confidence. Consider: ask clarifying question, use tools to verify, or admit uncertainty.")
    elif conf < 7:
        parts.append("⚠️ Moderate confidence. Consider using tools to verify key claims before finalizing.")

    parts.append("Please refine your response addressing the above concerns.")
    return "\n".join(parts)


def detect_uncertainty(text: str) -> List[str]:
    """Heuristic detection of uncertainty markers in text."""
    markers = [
        (r"\bI think\b", "Uses 'I think' (hedging)"),
        (r"\bmaybe\b", "Uses 'maybe' (uncertain)"),
        (r"\bpossibly\b", "Uses 'possibly' (uncertain)"),
        (r"\bnot sure\b", "Explicitly not sure"),
        (r"\bmight be\b", "Uses 'might be' (speculative)"),
        (r"\bI believe\b", "Uses 'I believe' (opinion)"),
        (r"\bprobably\b", "Uses 'probably' (uncertain)"),
        (r"\bin my opinion\b", "States opinion, not fact"),
    ]
    findings = []
    for pattern, desc in markers:
        if re.search(pattern, text, re.IGNORECASE):
            findings.append(desc)
    return findings
