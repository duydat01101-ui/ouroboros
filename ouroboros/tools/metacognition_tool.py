"""Metacognition tools — confidence scoring, uncertainty detection,
self-evaluation, and response refinement.

Lets Ouroboros evaluate its own responses before finalizing them.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolEntry, ToolContext
from ouroboros.metacognition import (
    evaluate_response,
    generate_refine_prompt,
    detect_uncertainty,
)

log = logging.getLogger(__name__)

def handle_self_evaluate(
    ctx: ToolContext,
    task: str = "",
    response: str = "",
    context: str = "",
) -> str:
    """Evaluate a response for confidence, completeness, and specificity.

    Uses LLM to score the response on multiple metacognitive axes.
    Returns a JSON with confidence (1-10), completeness (1-10),
    specificity (1-10), gaps, suggestions, and knowledge gaps.
    """
    if not task or not response:
        return '⚠️ Provide both "task" and "response" to evaluate.'

    result = evaluate_response(task=task, response=response, context=context)
    return json.dumps(result, indent=2, ensure_ascii=False)


def handle_detect_uncertainty(ctx: ToolContext, text: str = "") -> str:
    """Detect uncertainty markers in text (e.g., 'I think', 'maybe', 'probably').

    Uses heuristic pattern matching to identify hedging language.
    """
    if not text:
        return '⚠️ Provide "text" to analyse.'

    markers = detect_uncertainty(text)
    if not markers:
        return json.dumps({
            "uncertainty_detected": False,
            "markers": [],
            "note": "No uncertainty markers found. Response appears confident.",
        }, indent=2)

    return json.dumps({
        "uncertainty_detected": True,
        "marker_count": len(markers),
        "markers": markers,
        "suggestion": "Consider using self_evaluate for deeper analysis.",
    }, indent=2)


def handle_refine_response(
    ctx: ToolContext,
    task: str = "",
    response: str = "",
    context: str = "",

) -> str:
    """Evaluate a response and generate a refinement prompt to improve it.

    Returns the evaluation + refinement prompt for the LLM to use.
    """
    if not task or not response:
        return '⚠️ Provide both "task" and "response" to refine.'

    evaluation = evaluate_response(task=task, response=response, context=context)
    refine_prompt = generate_refine_prompt(evaluation)

    return json.dumps({
        "evaluation": evaluation,
        "refine_prompt": refine_prompt,
        "confidence": evaluation.get("confidence", 0),
        "should_refine": evaluation.get("confidence", 0) < 7,
    }, indent=2, ensure_ascii=False)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("self_evaluate", {
            "name": "self_evaluate",
            "description": "Evaluate your own response for confidence, completeness, and specificity. Uses LLM to score on multiple metacognitive axes. Call this BEFORE responding to high-stakes tasks.",
            "parameters": {"type": "object", "properties": {
                "task": {"type": "string", "description": "The original task/question being answered"},
                "response": {"type": "string", "description": "The response to evaluate"},
                "context": {"type": "string", "description": "Optional context for evaluation"},
            }, "required": ["task", "response"]},
        }, handle_self_evaluate),
        ToolEntry("detect_uncertainty", {
            "name": "detect_uncertainty",
            "description": "Detect uncertainty markers in text using heuristic pattern matching (e.g., 'I think', 'maybe', 'probably', 'not sure'). Quick check before self_evaluate.",
            "parameters": {"type": "object", "properties": {
                "text": {"type": "string", "description": "Text to analyse for uncertainty markers"},
            }, "required": ["text"]},
        }, handle_detect_uncertainty),
        ToolEntry("refine_response", {
            "name": "refine_response",
            "description": "Evaluate a draft response and generate a refinement prompt to improve it. Combines self_evaluate + refinement guidance in one call. Use when you want to improve a response before finalizing.",
            "parameters": {"type": "object", "properties": {
                "task": {"type": "string", "description": "The original task/question being answered"},
                "response": {"type": "string", "description": "The draft response to evaluate and refine"},
                "context": {"type": "string", "description": "Optional context for evaluation"},
            }, "required": ["task", "response"]},
        }, handle_refine_response),
    ]
