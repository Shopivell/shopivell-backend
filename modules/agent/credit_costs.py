# modules/agent/credit_costs.py
"""The one place that says what each AI action costs, in wallet tokens.

Every charge (agent confirm cards, ad images, the ad pipeline, Brand DNA) reads its price
from here, so prices change in one edit and the UI/API can list them. The numbers are the
same ones that used to be hardcoded at each call site; changing a number here is a pricing
decision, not a code change.

Agent chat turns are the exception: they are metered by the real LLM tokens used.
"""

# action key -> tokens charged per use
ACTION_COSTS = {
    "ad_image": 12000,         # one generated brand ad image
    "ad_pipeline": 6000,       # scrape + research + angles + copy variations (several LLM calls)
    "brand_dna": 1500,         # Brand DNA generation for a store
    "create_campaign": 500,    # create a draft campaign
    "scrape_url": 0,           # plain lookups and page fetches are not AI usage, so they are never blocked
    "list_stores": 0,
    "list_campaigns": 0,
    "navigate": 0,
}

# agent tool name -> action key (a tool is a thin wrapper over an action)
TOOL_ACTIONS = {
    "show_ad_variations": "ad_pipeline",
    "generate_image": "ad_image",
    "create_campaign": "create_campaign",
    "scrape_url": "scrape_url",
    "list_stores": "list_stores",
    "list_campaigns": "list_campaigns",
    "navigate": "navigate",
}

# What an unlisted tool costs the agent's confirm flow.
DEFAULT_TOOL_COST = 250


def cost_of(action: str, default: int = 0) -> int:
    """Tokens for one use of `action`."""
    return int(ACTION_COSTS.get(action, default))


def tool_costs() -> dict:
    """Agent tool name -> tokens, derived from the action table."""
    return {tool: cost_of(action) for tool, action in TOOL_ACTIONS.items()}
