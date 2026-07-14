"""
Shared helpers for parsing LLM JSON responses.

Several copy/creative agents (ad_copy_agent, copywriter_agent,
visual_director_agent, ...) each carried a byte-for-byte identical
`_clean_json_response` method. This module is the single source of truth for
that logic so a fix lands in one place. Behavior is intentionally identical to
the previous per-agent copies.
"""

import json
from typing import Any


def clean_json_response(response: str) -> str:
    """Strip markdown code fences (```json ... ```) from an LLM response."""
    response = (response or "").strip()
    if response.startswith("```json"):
        response = response[7:]
    elif response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]
    return response.strip()


def parse_llm_json(response: str) -> Any:
    """Clean fences, then json.loads. Raises on invalid JSON (callers handle)."""
    return json.loads(clean_json_response(response))
