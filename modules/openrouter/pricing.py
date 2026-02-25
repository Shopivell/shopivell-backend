# modules/openrouter/pricing.py
"""
OpenRouter model pricing for cost calculation.
Prices in USD per token. See: https://openrouter.ai/models
"""


# model_id -> {"input": price_per_token, "output": price_per_token}
MODEL_PRICING = {
    # OpenAI
    "openai/gpt-4o": {
        "input": 2.50 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "openai/gpt-4o-mini": {
        "input": 0.15 / 1_000_000,
        "output": 0.60 / 1_000_000,
    },

    # Anthropic
    "anthropic/claude-sonnet-4": {
        "input": 3.00 / 1_000_000,
        "output": 15.00 / 1_000_000,
    },
    "anthropic/claude-3.5-sonnet": {
        "input": 3.00 / 1_000_000,
        "output": 15.00 / 1_000_000,
    },
    "anthropic/claude-3-haiku": {
        "input": 0.25 / 1_000_000,
        "output": 1.25 / 1_000_000,
    },

    # Google
    "google/gemini-2.0-flash-exp": {
        "input": 0.0 / 1_000_000,
        "output": 0.0 / 1_000_000,
    },
    "google/gemini-3-pro-image-preview": {
        "input": 1.25 / 1_000_000,
        "output": 5.00 / 1_000_000,
    },
}

# Fallback for unknown models
DEFAULT_PRICING = {
    "input": 3.00 / 1_000_000,
    "output": 10.00 / 1_000_000,
}


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate USD cost for a model call."""
    pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
    cost = (prompt_tokens * pricing["input"]) + (completion_tokens * pricing["output"])
    return round(cost, 8)
