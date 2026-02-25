"""
OpenRouter API Service

Provides unified access to OpenRouter's API for image generation and AI reasoning.
"""

import os
import base64
import logging
import json
from typing import Optional, Dict, Any, List

import httpx

logger = logging.getLogger(__name__)

# OpenRouter Configuration
OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY",
    "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"
)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Model configurations
OPENROUTER_IMAGE_MODEL = os.getenv("OPENROUTER_IMAGE_MODEL", "google/gemini-2.0-flash-exp")
OPENROUTER_REASONING_MODEL = os.getenv("OPENROUTER_REASONING_MODEL", "openai/gpt-4o")

# Luxury Ad Creative Guidelines
LUXURY_CREATIVE_GUIDELINES = {
    "backgroundTone": "neutral backdrop emphasizing texture (cream, taupe, slate gray)",
    "surfaceType": "premium materials (brushed marble, matte wood, fine linen)",
    "accentProp": "minimal singular luxury prop (gold pen, leather strap, silk ribbon)",
    "lighting": "diffused soft light with subtle highlights",
    "composition": "asymmetrical with breathing room",
    "colorPalette": ["champagne", "ivory", "graphite", "dusty rose"],
    "textureEmphasis": "tactile close-ups showing material quality"
}

# Facebook Ad Types Configuration
FACEBOOK_AD_TYPES = {
    "facebook-ad": {
        "purpose": "High-converting Facebook ad campaigns with clear CTAs",
        "format": "Attention-grabbing headline, compelling body text, strong call-to-action",
        "characteristics": [
            "Clear value proposition",
            "Urgency elements",
            "Targeted messaging",
            "Mobile-optimized"
        ]
    },
    "facebook-carousel": {
        "purpose": "Multi-product showcase with swipeable cards",
        "format": "Series of connected cards telling a story or showcasing multiple features",
        "characteristics": [
            "Sequential storytelling",
            "Multiple product highlights",
            "Swipe prompts",
            "Consistent branding"
        ]
    },
    "facebook-lead-gen": {
        "purpose": "Capture leads directly within Facebook",
        "format": "Form-focused content with low-friction conversion",
        "characteristics": [
            "Clear value exchange",
            "Minimal form fields",
            "Trust indicators",
            "Privacy reassurance"
        ]
    },
    "facebook-video-ad": {
        "purpose": "Scroll-stopping video content for news feed",
        "format": "Short, engaging videos (15-60 seconds) with captions",
        "characteristics": [
            "Hook in first 3 seconds",
            "Visual storytelling",
            "Text overlays",
            "Silent-friendly"
        ]
    },
    "facebook-story-ad": {
        "purpose": "Full-screen vertical immersive ads",
        "format": "Vertical video or image series with interactive elements",
        "characteristics": [
            "Full-screen impact",
            "Swipe-up prompts",
            "Vertical optimization",
            "Ephemeral feel"
        ]
    },
    "facebook-event-promo": {
        "purpose": "Boost attendance and engagement for events",
        "format": "Event details with social proof and urgency",
        "characteristics": [
            "Clear date/time/location",
            "Social proof",
            "FOMO elements",
            "Easy registration"
        ]
    },
    "facebook-retargeting": {
        "purpose": "Re-engage website visitors and warm leads",
        "format": "Personalized content based on previous interactions",
        "characteristics": [
            "Dynamic product ads",
            "Personalized messaging",
            "Abandoned cart recovery",
            "Cross-sell opportunities"
        ]
    }
}


class OpenRouterClient:
    """
    Unified client for OpenRouter API supporting both chat completions
    and image generation through their compatible endpoints.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or OPENROUTER_API_KEY
        self.base_url = OPENROUTER_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://shopivell.com",
            "X-Title": "Shopivell Ad Generator",
            "Content-Type": "application/json"
        }

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Send a chat completion request to OpenRouter.
        Compatible with OpenAI-style chat format.

        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model to use (defaults to OPENROUTER_REASONING_MODEL)
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens in response
            response_format: Optional response format (e.g., {"type": "json_object"})

        Returns:
            OpenRouter API response dict
        """
        model = model or OPENROUTER_REASONING_MODEL

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        if response_format:
            payload["response_format"] = response_format

        logger.info(f"[OpenRouter] Chat completion with model: {model}")

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()
                usage = result.get('usage', {})
                logger.info(f"[OpenRouter] Response received, tokens used: {usage}")

                # Fire-and-forget usage tracking
                try:
                    from modules.openrouter.context import ai_context
                    from modules.openrouter.ai_usage_service import track_usage
                    ctx = ai_context.get()
                    track_usage(
                        model=model,
                        prompt_tokens=usage.get('prompt_tokens', 0),
                        completion_tokens=usage.get('completion_tokens', 0),
                        total_tokens=usage.get('total_tokens', 0),
                        agent_name=ctx.agent_name,
                        store_id=ctx.store_id,
                        user_id=ctx.user_id,
                        campaign_id=ctx.campaign_id,
                    )
                except Exception as e:
                    logger.warning(f"[OpenRouter] Usage tracking failed: {e}")

                return result
            except httpx.HTTPStatusError as e:
                logger.error(f"[OpenRouter] HTTP error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"[OpenRouter] Error: {str(e)}")
                raise

    def chat_completion_sync(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Synchronous version of chat_completion for non-async contexts.
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If already in async context, create new loop in thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.chat_completion(messages, model, temperature, max_tokens, response_format)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(
                    self.chat_completion(messages, model, temperature, max_tokens, response_format)
                )
        except RuntimeError:
            return asyncio.run(
                self.chat_completion(messages, model, temperature, max_tokens, response_format)
            )

    async def generate_image(
        self,
        prompt: str,
        model: str = None,
        apply_luxury_guidelines: bool = True,
        ad_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate an image using OpenRouter's multimodal capabilities.

        Args:
            prompt: Image generation prompt
            model: Model to use (defaults to OPENROUTER_IMAGE_MODEL)
            apply_luxury_guidelines: Whether to enhance prompt with luxury guidelines
            ad_type: Optional Facebook ad type to apply specific guidelines

        Returns:
            OpenRouter API response with generated image
        """
        model = model or OPENROUTER_IMAGE_MODEL

        # Enhance prompt with luxury guidelines if requested
        if apply_luxury_guidelines:
            prompt = self._apply_luxury_guidelines(prompt)

        # Apply Facebook ad type guidelines if specified
        if ad_type and ad_type in FACEBOOK_AD_TYPES:
            prompt = self._apply_ad_type_guidelines(prompt, ad_type)

        messages = [
            {
                "role": "user",
                "content": f"Generate a high-quality professional advertisement image: {prompt}"
            }
        ]

        logger.info(f"[OpenRouter] Image generation with model: {model}")

        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": 4096
                    }
                )
                response.raise_for_status()
                result = response.json()

                # Fire-and-forget usage tracking
                try:
                    usage = result.get('usage', {})
                    from modules.openrouter.context import ai_context
                    from modules.openrouter.ai_usage_service import track_usage
                    ctx = ai_context.get()
                    track_usage(
                        model=model,
                        prompt_tokens=usage.get('prompt_tokens', 0),
                        completion_tokens=usage.get('completion_tokens', 0),
                        total_tokens=usage.get('total_tokens', 0),
                        agent_name=ctx.agent_name,
                        store_id=ctx.store_id,
                        user_id=ctx.user_id,
                        campaign_id=ctx.campaign_id,
                        endpoint="images/generations",
                    )
                except Exception as e:
                    logger.warning(f"[OpenRouter] Image usage tracking failed: {e}")

                return result
            except httpx.HTTPStatusError as e:
                logger.error(f"[OpenRouter] Image generation HTTP error: {e.response.status_code}")
                raise
            except Exception as e:
                logger.error(f"[OpenRouter] Image generation error: {str(e)}")
                raise

    def _apply_luxury_guidelines(self, prompt: str) -> str:
        """Apply luxury creative guidelines to the image prompt."""
        guidelines = LUXURY_CREATIVE_GUIDELINES

        enhanced = f"""{prompt}

LUXURY AD CREATIVE GUIDELINES:
- Background: {guidelines['backgroundTone']}
- Surface: {guidelines['surfaceType']}
- Accent: {guidelines['accentProp']}
- Lighting: {guidelines['lighting']}
- Composition: {guidelines['composition']}
- Colors: {', '.join(guidelines['colorPalette'])}
- Texture: {guidelines['textureEmphasis']}

Create a sophisticated, premium advertising image with high production value."""
        return enhanced

    def _apply_ad_type_guidelines(self, prompt: str, ad_type: str) -> str:
        """Apply Facebook ad type specific guidelines to the prompt."""
        ad_config = FACEBOOK_AD_TYPES.get(ad_type, {})

        if not ad_config:
            return prompt

        enhanced = f"""{prompt}

FACEBOOK AD TYPE: {ad_type.upper()}
Purpose: {ad_config.get('purpose', '')}
Format: {ad_config.get('format', '')}
Key Characteristics:
{chr(10).join(f'- {c}' for c in ad_config.get('characteristics', []))}
"""
        return enhanced

    async def generate_ad_copy(
        self,
        product_info: Dict[str, Any],
        ad_type: str = "facebook-ad",
        tone: str = "professional"
    ) -> Dict[str, Any]:
        """
        Generate ad copy for a specific Facebook ad type.

        Args:
            product_info: Dict with product_name, description, target_audience, benefits
            ad_type: Facebook ad type from FACEBOOK_AD_TYPES
            tone: Tone of voice (professional, casual, urgent, luxury)

        Returns:
            Dict with headline, primary_text, description, cta
        """
        ad_config = FACEBOOK_AD_TYPES.get(ad_type, FACEBOOK_AD_TYPES["facebook-ad"])

        system_prompt = f"""You are an expert Facebook ad copywriter. Generate compelling ad copy for the following ad type:

AD TYPE: {ad_type}
PURPOSE: {ad_config['purpose']}
FORMAT: {ad_config['format']}
CHARACTERISTICS: {', '.join(ad_config['characteristics'])}

TONE: {tone}

Return your response as a JSON object with these fields:
- headline (max 40 characters)
- primary_text (125-500 characters)
- description (max 125 characters)
- call_to_action (e.g., "Shop Now", "Learn More", "Sign Up")
- hook (attention-grabbing opening line)
"""

        user_prompt = f"""Create ad copy for:
Product: {product_info.get('product_name', 'Unknown Product')}
Description: {product_info.get('description', '')}
Target Audience: {product_info.get('target_audience', 'General audience')}
Key Benefits: {', '.join(product_info.get('benefits', []))}
"""

        result = await self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.8,
            response_format={"type": "json_object"}
        )

        try:
            content = result['choices'][0]['message']['content']
            return json.loads(content)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[OpenRouter] Failed to parse ad copy response: {e}")
            return {
                "headline": product_info.get('product_name', 'Amazing Product'),
                "primary_text": product_info.get('description', ''),
                "description": "Discover more today.",
                "call_to_action": "Shop Now",
                "hook": "Don't miss out!"
            }

    async def analyze_content(
        self,
        content: str,
        analysis_type: str = "ad_generation"
    ) -> Dict[str, Any]:
        """
        Analyze content for ad generation purposes.

        Args:
            content: Text content to analyze (e.g., scraped website content)
            analysis_type: Type of analysis ("ad_generation", "audience", "competitor")

        Returns:
            Analysis results as a dict
        """
        system_prompts = {
            "ad_generation": """You are a marketing analyst. Analyze the provided content and extract:
- 5 compelling headlines (max 40 chars each)
- 5 ad descriptions (max 125 chars each)
- Target audience segments
- Key value propositions
- Recommended ad types from: facebook-ad, facebook-carousel, facebook-lead-gen, facebook-video-ad, facebook-story-ad

Return as JSON with keys: headlines, descriptions, audiences, value_props, recommended_ad_types""",

            "audience": """Analyze the content and identify target audience segments. Return JSON with:
- demographics (age, gender, location)
- interests
- pain_points
- desires
- buying_triggers""",

            "competitor": """Analyze the content from a competitive perspective. Return JSON with:
- unique_selling_points
- market_positioning
- pricing_strategy
- strengths
- weaknesses"""
        }

        result = await self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompts.get(analysis_type, system_prompts["ad_generation"])},
                {"role": "user", "content": f"Analyze this content:\n\n{content[:4000]}"}
            ],
            temperature=0.5,
            response_format={"type": "json_object"}
        )

        try:
            content = result['choices'][0]['message']['content']
            return json.loads(content)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[OpenRouter] Failed to parse analysis response: {e}")
            return {}


# Singleton instance for easy import
openrouter_client = OpenRouterClient()
