"""
OpenRouter API Integration Module for Shopivell

This module provides a unified interface to OpenRouter's API for:
- Image generation (google/gemini-3-pro-image-preview)
- AI reasoning/agents (openai/gpt-5.1)

Usage:
    from modules.openrouter import OpenRouterClient, ChatOpenRouter

    # For direct API calls
    client = OpenRouterClient()
    result = await client.chat_completion(messages=[...])

    # For LangChain integration
    from modules.openrouter.langchain_adapter import ChatOpenRouter
    llm = ChatOpenRouter(model="openai/gpt-5.1")
"""

from .service import (
    OpenRouterClient,
    OPENROUTER_API_KEY,
    OPENROUTER_IMAGE_MODEL,
    OPENROUTER_REASONING_MODEL,
    LUXURY_CREATIVE_GUIDELINES,
    FACEBOOK_AD_TYPES,
    openrouter_client
)

from .langchain_adapter import ChatOpenRouter

__all__ = [
    "OpenRouterClient",
    "ChatOpenRouter",
    "OPENROUTER_API_KEY",
    "OPENROUTER_IMAGE_MODEL",
    "OPENROUTER_REASONING_MODEL",
    "LUXURY_CREATIVE_GUIDELINES",
    "FACEBOOK_AD_TYPES",
    "openrouter_client"
]
