# ad_creative_agent.py - AI Agent for Ad Creative Generation
"""
This agent takes creative angles and generates:
1. Detailed image prompts for AI image generation
2. Ad angles (descriptions) for the ad content

Uses OpenRouter API via ChatOpenRouter adapter for AI generation.
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Import OpenRouter adapter (with fallback to ChatOpenAI)
try:
    from modules.openrouter.langchain_adapter import ChatOpenRouter
    OPENROUTER_AVAILABLE = True
except ImportError:
    from langchain_openai import ChatOpenAI as ChatOpenRouter
    OPENROUTER_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


class AdCreativeAgent:
    """AI Agent for generating ad creatives with image prompts and ad angles"""

    def __init__(self):
        # Use OpenRouter with gpt-4o model
        self.llm = ChatOpenRouter(
            model="openai/gpt-4o" if OPENROUTER_AVAILABLE else "gpt-4o-mini",
            temperature=0.7
        )
        logger.info(f"[AdCreativeAgent] Initialized with {'OpenRouter' if OPENROUTER_AVAILABLE else 'OpenAI'}")

        # Prompt for generating image prompt and ad angle
        self.prompt = ChatPromptTemplate.from_template("""
You are an expert ad creative director. Based on the product information and creative angle, generate:
1. A detailed IMAGE PROMPT for AI image generation
2. An AD ANGLE (compelling description/copy for the ad)

PRODUCT INFORMATION:
Product Name: {product_name}
Product Description: {product_description}
Target Audience: {target_audience}
Key Benefits: {key_benefits}
Call to Action: {call_to_action}

CREATIVE ANGLE:
Angle Name: {angle_name}
Value Proposition: {angle_value_proposition}
Emotion Target: {angle_emotion}
Visual Direction: {visual_direction}

Generate output in this EXACT format:

IMAGE_PROMPT: [Write a detailed, vivid image prompt for AI image generation. Include specific details about composition, colors, mood, lighting, style, and visual elements. The prompt should be 2-3 sentences that will produce a professional advertising image. Do NOT include any text in the image description.]

AD_ANGLE: [Write a compelling 1-2 sentence ad description that captures the essence of this creative angle. This will be the primary text shown with the ad.]

HEADLINE: [Write a short, punchy headline (5-8 words max)]
""")

    def _parse_creative_response(self, response_text: str) -> Dict[str, str]:
        """Parse the AI response into structured creative data"""
        result = {
            "image_prompt": "",
            "ad_angle": "",
            "headline": ""
        }

        lines = response_text.strip().split('\n')
        current_key = None
        current_value = []

        for line in lines:
            line = line.strip()
            if line.upper().startswith('IMAGE_PROMPT:'):
                if current_key and current_value:
                    result[current_key] = ' '.join(current_value).strip()
                current_key = "image_prompt"
                current_value = [line.split(':', 1)[1].strip() if ':' in line else '']
            elif line.upper().startswith('AD_ANGLE:'):
                if current_key and current_value:
                    result[current_key] = ' '.join(current_value).strip()
                current_key = "ad_angle"
                current_value = [line.split(':', 1)[1].strip() if ':' in line else '']
            elif line.upper().startswith('HEADLINE:'):
                if current_key and current_value:
                    result[current_key] = ' '.join(current_value).strip()
                current_key = "headline"
                current_value = [line.split(':', 1)[1].strip() if ':' in line else '']
            elif current_key and line:
                current_value.append(line)

        # Don't forget the last value
        if current_key and current_value:
            result[current_key] = ' '.join(current_value).strip()

        return result

    async def generate_ad_creative(
        self,
        product_name: str,
        product_description: str,
        target_audience: str = "General audience",
        key_benefits: List[str] = None,
        call_to_action: str = "Learn More",
        angle_name: str = "Default",
        angle_value_proposition: str = "",
        angle_emotion: str = "Interest",
        visual_direction: str = ""
    ) -> Dict[str, str]:
        """
        Generate ad creative with image prompt and ad angle.

        Returns:
            Dict with 'image_prompt', 'ad_angle', and 'headline'
        """
        try:
            # Prepare data
            creative_data = {
                "product_name": product_name,
                "product_description": product_description,
                "target_audience": target_audience,
                "key_benefits": ", ".join(key_benefits) if key_benefits else "Quality, Value, Convenience",
                "call_to_action": call_to_action,
                "angle_name": angle_name,
                "angle_value_proposition": angle_value_proposition or f"Experience the best of {product_name}",
                "angle_emotion": angle_emotion,
                "visual_direction": visual_direction or "Modern, clean, professional advertising style"
            }

            # Run the LLM chain
            chain = self.prompt | self.llm | StrOutputParser()
            response_text = await chain.ainvoke(creative_data)

            # Parse response
            result = self._parse_creative_response(response_text)

            # Ensure we have valid values
            if not result["image_prompt"]:
                result["image_prompt"] = self._generate_fallback_prompt(product_name, visual_direction)
            if not result["ad_angle"]:
                result["ad_angle"] = f"Discover {product_name} - {angle_value_proposition or 'Your perfect choice'}"
            if not result["headline"]:
                result["headline"] = f"Discover {product_name}"

            return result

        except Exception as e:
            print(f"[AdCreativeAgent] Error generating creative: {e}")
            # Return fallback values
            return {
                "image_prompt": self._generate_fallback_prompt(product_name, visual_direction),
                "ad_angle": f"Discover {product_name} - Quality you can trust",
                "headline": f"Discover {product_name}"
            }

    def _generate_fallback_prompt(self, product_name: str, visual_direction: str) -> str:
        """Generate a fallback image prompt"""
        if visual_direction:
            return f"Professional advertisement for {product_name}. {visual_direction}. High-quality, commercial photography style with clean composition and modern aesthetic."
        return f"Professional advertisement for {product_name}. Clean, modern design with high-quality product photography. Bright, welcoming colors with professional lighting. Commercial advertising style."

    async def generate_multiple_creatives(
        self,
        product_name: str,
        product_description: str,
        creative_angles: List[Dict[str, Any]],
        call_to_action: str = "Learn More"
    ) -> List[Dict[str, Any]]:
        """
        Generate ad creatives for multiple creative angles.

        Args:
            product_name: Name of the product/business
            product_description: Description of the product
            creative_angles: List of creative angle dicts with angle_name, value_proposition, emotion_target, visual_direction
            call_to_action: CTA text

        Returns:
            List of creative dicts with image_prompt, ad_angle, headline, and original angle data
        """
        creatives = []

        for angle in creative_angles:
            creative = await self.generate_ad_creative(
                product_name=product_name,
                product_description=product_description,
                target_audience=angle.get("target_audience", "General audience"),
                key_benefits=angle.get("key_benefits", []),
                call_to_action=call_to_action,
                angle_name=angle.get("angle_name", "Default"),
                angle_value_proposition=angle.get("value_proposition", ""),
                angle_emotion=angle.get("emotion_target", "Interest"),
                visual_direction=angle.get("visual_direction", "")
            )

            creatives.append({
                **creative,
                "angle_name": angle.get("angle_name", "Default"),
                "angle_data": angle
            })

        return creatives


# Convenience function for direct use
async def generate_ad_creative(
    product_name: str,
    product_description: str,
    visual_direction: str = "",
    call_to_action: str = "Learn More"
) -> Dict[str, str]:
    """
    Quick function to generate a single ad creative.

    Returns:
        Dict with 'image_prompt', 'ad_angle', and 'headline'
    """
    agent = AdCreativeAgent()
    return await agent.generate_ad_creative(
        product_name=product_name,
        product_description=product_description,
        visual_direction=visual_direction,
        call_to_action=call_to_action
    )
