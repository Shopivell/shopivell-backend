# modules/openrouter/context.py
"""
Context variables for AI usage tracking.
Uses Python contextvars to propagate store_id, user_id, agent_name
through LangChain chains without modifying function signatures.

Usage:
    from modules.openrouter.context import set_ai_context

    with set_ai_context(store_id="abc-123", agent_name="market_research"):
        result = await chain.ainvoke(data)
"""

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional


@dataclass
class AIContext:
    """Context data for AI usage tracking."""
    store_id: Optional[str] = None
    user_id: Optional[str] = None
    campaign_id: Optional[str] = None
    agent_name: str = "unknown"


# Async-safe, thread-safe context variable
ai_context: contextvars.ContextVar[AIContext] = contextvars.ContextVar(
    'ai_context', default=AIContext()
)


@contextmanager
def set_ai_context(
    store_id: Optional[str] = None,
    user_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    agent_name: str = "unknown"
):
    """Context manager to set AI tracking context."""
    ctx = AIContext(
        store_id=store_id,
        user_id=user_id,
        campaign_id=campaign_id,
        agent_name=agent_name
    )
    token = ai_context.set(ctx)
    try:
        yield ctx
    finally:
        ai_context.reset(token)
