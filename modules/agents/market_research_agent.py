"""Compatibility shim.

Market research moved to modules.market_research.service.MarketResearchService.
This re-export keeps any legacy `from modules.agents.market_research_agent import
MarketResearchAgent` imports working.
"""

from modules.market_research.service import MarketResearchService as MarketResearchAgent  # noqa: F401

__all__ = ["MarketResearchAgent"]
