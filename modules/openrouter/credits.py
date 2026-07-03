# modules/openrouter/credits.py
"""AI credit economics: message credits, cost-plus markup, tier-based model routing.

A "credit" is the unit a store owner buys and spends. Each answered bot message
consumes credits = ceil(real_provider_cost_usd * MARKUP_MULTIPLIER / CREDIT_USD_VALUE),
floored at MIN_CREDITS_PER_MESSAGE. This keeps pricing cost-plus while showing
whole-number credits, and naturally makes Claude messages cost more credits than
GPT-4o-mini messages (because they cost us more to serve).

All values below are tunable — adjust to match your retail pricing & target margin.
"""

import math

# --- Economics (tune these) --------------------------------------------------

# What we charge over raw provider cost. 3.0 = 3x cost (~67% gross margin on AI).
MARKUP_MULTIPLIER = 3.0

# USD value of one credit (internal billable value = cost x markup, per credit).
# At 0.002: a ~$0.0006 GPT-4o-mini msg (x3 = $0.0018) ≈ 1 credit; a ~$0.012 Claude
# Sonnet msg (x3 = $0.036) ≈ 18 credits (less with prompt-cache hits).
CREDIT_USD_VALUE = 0.002

# Every answered message costs at least this many credits.
MIN_CREDITS_PER_MESSAGE = 1

# Monthly free credits granted per subscription tier (reset each calendar month).
TIER_MONTHLY_CREDITS = {
    "free": 50,
    "premium": 3_000,
    "business": 30_000,
}

# --- Tier-based model routing ------------------------------------------------

# Free stores get the cheap/fast model; paid stores get Claude for quality.
TIER_PRIMARY_MODEL = {
    "free": "gpt-4o-mini",
    "premium": "claude-sonnet-4-6",
    "business": "claude-sonnet-4-6",
}
FALLBACK_MODEL = "gpt-4o-mini"


def monthly_allowance(package: str) -> int:
    """Free credits granted to this tier each month."""
    return TIER_MONTHLY_CREDITS.get(package, TIER_MONTHLY_CREDITS["free"])


def pick_model(package: str) -> str:
    """Primary model for this tier (used by the WhatsApp bot)."""
    return TIER_PRIMARY_MODEL.get(package, FALLBACK_MODEL)


def credits_for_cost(cost_usd: float) -> int:
    """Convert a real provider cost (USD) into credits consumed (cost-plus, min 1)."""
    if cost_usd <= 0:
        return MIN_CREDITS_PER_MESSAGE
    billable = cost_usd * MARKUP_MULTIPLIER
    return max(MIN_CREDITS_PER_MESSAGE, math.ceil(billable / CREDIT_USD_VALUE))
