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

# Import OpenAI for direct fallback
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


class AdCreativeAgent:
    """AI Agent for generating ad creatives with high-quality structured image prompts"""

    def __init__(self):
        # Use OpenRouter with gpt-4o model
        self.llm = ChatOpenRouter(
            model="anthropic/claude-3.5-sonnet" if OPENROUTER_AVAILABLE else "gpt-4o-mini",
            temperature=0.7
        )
        logger.info(f"[AdCreativeAgent] Initialized with {'OpenRouter' if OPENROUTER_AVAILABLE else 'OpenAI'}")

        # STRUCTURED prompt that generates high-quality image prompts
        # This format produces prompts like a professional creative director would write
        self.prompt = ChatPromptTemplate.from_template("""You are an expert advertising creative director who writes EXCEPTIONAL image generation prompts for AI tools like Gemini and DALL-E.

Your prompts MUST follow this EXACT structure:
1. SCENE SETUP: "Professional advertisement image for a [industry] company: [business name]."
2. TARGET AUDIENCE: "Target audience: [audience]. Create a scene showing [industry-specific visuals] that appeals to this audience."
3. VISUAL DESCRIPTION: Describe EXACTLY what should be in the image - specific products, settings, compositions
4. COLOR THEME: "IMPORTANT COLOR THEME: Use [brand color] as accent color throughout - on products, lighting, backgrounds."
5. MOOD: "Mood: [specific mood words]."
6. TECHNICAL: "High-quality commercial photography, clean composition, professional lighting, 8K quality."
7. COMPLIANCE: "AVOID: [things to avoid]. No AI-generated human faces, no text in image."

EXAMPLE for fashion retail:
"Professional advertisement image for a fashion retail company: Edgars. Target audience: Young Professionals. Create a scene showing stylish business casual clothing displayed on modern wooden hangers against a clean white backdrop, with a sleek leather briefcase and polished shoes arranged nearby. IMPORTANT COLOR THEME: Use #E31837 red as accent color throughout - on clothing items, shopping bags, and subtle lighting accents. Mood: aspirational, sophisticated, confident. High-quality commercial photography, clean composition, professional studio lighting, 8K quality. AVOID: cluttered backgrounds, competitor logos, price tags. No AI-generated human faces, no text in image."

EXAMPLE for security company:
"Professional advertisement image for a security company: SecureSights. Target audience: Homeowners. Create a scene showing a modern smart home security panel mounted on a clean white wall, with a hand reaching to touch the screen showing a green 'secured' status. A stylish front door with a smart lock visible in background. IMPORTANT COLOR THEME: Use #1E3A5F navy blue as accent color on LED indicators, UI elements, and ambient lighting. Mood: professional, trustworthy, reassuring. High-quality commercial photography, clean modern interior, professional lighting, 8K quality. AVOID: weapons, armed guards, threatening imagery. No AI-generated human faces, no text in image."

---

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

IMAGE_PROMPT: [Write a STRUCTURED 4-6 sentence prompt following my exact format above. Include: scene setup with business name, target audience context, SPECIFIC product/item descriptions, color theme with hex code, mood, technical specs, and what to AVOID. Make it SPECIFIC to this business type - not generic.]

AD_ANGLE: [Write a compelling 1-2 sentence ad description that captures the essence of this creative angle.]

HEADLINE: [Write a short, punchy headline (5-8 words max) - NO EMOJIS, clean and professional]
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
            print(f"[AdCreativeAgent] OpenRouter error: {e}")
            # Try OpenAI as fallback
            if OPENAI_AVAILABLE:
                try:
                    return await self._generate_with_openai_fallback(creative_data, product_name, visual_direction, angle_value_proposition)
                except Exception as openai_error:
                    print(f"[AdCreativeAgent] OpenAI fallback error: {openai_error}")

            # Return fallback values
            return {
                "image_prompt": self._generate_fallback_prompt(product_name, visual_direction),
                "ad_angle": f"Discover {product_name} - Quality you can trust",
                "headline": f"Discover {product_name}"
            }

    async def _generate_with_openai_fallback(self, creative_data: Dict, product_name: str, visual_direction: str, angle_value_proposition: str) -> Dict[str, str]:
        """Fallback to OpenAI when OpenRouter fails"""
        print("[AdCreativeAgent] Trying OpenAI fallback...")
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise ValueError("OpenAI API key not configured")

        client = OpenAI(api_key=openai_key)

        # Build the prompt text
        prompt_text = self.prompt.format(**creative_data)

        # LOG THE EXACT PROMPT BEING SENT
        print("\n" + "=" * 60)
        print("[AdCreativeAgent] PROMPT SENT TO LLM:")
        print("=" * 60)
        print(prompt_text)
        print("=" * 60 + "\n")

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": prompt_text}
            ],
            temperature=0.7,
            max_tokens=1500
        )

        response_text = response.choices[0].message.content

        # LOG THE RESPONSE FROM LLM
        print("\n" + "-" * 60)
        print("[AdCreativeAgent] RAW RESPONSE FROM LLM:")
        print("-" * 60)
        print(response_text)
        print("-" * 60 + "\n")

        # Parse response
        result = self._parse_creative_response(response_text)

        # Ensure we have valid values
        if not result["image_prompt"]:
            result["image_prompt"] = self._generate_fallback_prompt(product_name, visual_direction)
        if not result["ad_angle"]:
            result["ad_angle"] = f"Discover {product_name} - {angle_value_proposition or 'Your perfect choice'}"
        if not result["headline"]:
            result["headline"] = f"Discover {product_name}"

        print("[AdCreativeAgent] OpenAI fallback successful")
        return result

    def _generate_fallback_prompt(self, product_name: str, visual_direction: str) -> str:
        """Generate a structured fallback image prompt"""
        if visual_direction:
            return f"Professional advertisement image for {product_name}. {visual_direction}. IMPORTANT COLOR THEME: Use brand-appropriate accent colors throughout the composition. Mood: professional, inviting, aspirational. High-quality commercial photography, clean composition, professional studio lighting, 8K quality. AVOID: cluttered backgrounds, competitor logos, low quality elements. No AI-generated human faces, no text in image."
        return f"Professional advertisement image for {product_name}. Create a scene showing the product/service in an aspirational setting with clean, modern styling. IMPORTANT COLOR THEME: Use brand-appropriate accent colors on key elements and lighting. Mood: professional, trustworthy, inviting. High-quality commercial photography, clean composition, professional studio lighting, 8K quality. AVOID: cluttered backgrounds, competitor logos. No AI-generated human faces, no text in image."

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
