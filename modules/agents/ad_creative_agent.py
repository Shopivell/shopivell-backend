# ad_creative_agent.py - AI Agent for Ad Creative Generation
"""
This agent takes creative angles and generates:
1. Detailed image prompts for AI image generation
2. Ad angles (descriptions) for the ad content

Uses Claude (Anthropic API) for best quality prompts, with OpenAI fallback.
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Import Anthropic (Claude) - primary choice for prompt generation
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# Import OpenAI for fallback
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


class AdCreativeAgent:
    """AI Agent for generating ad creatives with high-quality structured image prompts.

    Uses Claude (Anthropic) for best quality prompts, with OpenAI (GPT-4o) fallback.
    """

    def __init__(self):
        # Initialize Claude client if available
        self.anthropic_client = None
        self.openai_client = None

        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")

        if ANTHROPIC_AVAILABLE and anthropic_key:
            self.anthropic_client = anthropic.Anthropic(api_key=anthropic_key)
            logger.info("[AdCreativeAgent] Initialized with Claude (Anthropic API)")

        if OPENAI_AVAILABLE and openai_key:
            self.openai_client = OpenAI(api_key=openai_key)
            if not self.anthropic_client:
                logger.info("[AdCreativeAgent] Initialized with OpenAI (fallback)")

        if not self.anthropic_client and not self.openai_client:
            logger.warning("[AdCreativeAgent] No API clients available!")

        # STRUCTURED prompt template that generates high-quality image prompts
        # This format produces prompts like a professional creative director would write
        self.prompt_template = """You are an expert advertising creative director who writes EXCEPTIONAL image generation prompts for AI tools like Gemini and DALL-E.

IMPORTANT: Be IMAGINATIVE and create REAL-WORLD SCENARIOS showing the product/service IN USE. Don't just show products - show PEOPLE experiencing the benefits in realistic situations. Think about WHO uses this service and WHAT they're doing when they use it.

Your prompts MUST follow this EXACT structure:
1. SCENE SETUP: "Professional advertisement image for a [industry] company: [business name]."
2. SCENARIO: Create a REALISTIC scene showing the product/service being USED by real people in a believable situation
3. PEOPLE & ACTION: Include people actively using/benefiting from the service - show their expressions, body language, the environment
4. BRAND VISIBILITY: Include the brand name naturally in the scene - on ATMs, storefronts, cards, screens, uniforms, signage, packaging, or products where it would realistically appear
5. COLOR THEME: "IMPORTANT COLOR THEME: Use [brand color] as accent color throughout - on screens, clothing accents, lighting, environment."
6. MOOD: "Mood: [specific mood words]."
7. TECHNICAL: "High-quality commercial photography, cinematic composition, professional lighting, 8K quality."
8. COMPLIANCE: "AVOID: [things to avoid]."

EXAMPLE for fintech/payments company (Zimswitch):
"Professional advertisement image for a financial technology company: Zimswitch. Target audience: HR Managers & Business Owners. Create a scene showing a confident HR manager in a modern office, smiling while viewing a laptop screen displaying a payroll dashboard with multiple employee salary transactions being processed. A Zimswitch-branded ATM is visible through the office window in the building lobby. In the background, happy employees can be seen through glass walls. The Zimswitch logo appears on the payment interface screen. IMPORTANT COLOR THEME: Use #0066CC blue as accent color throughout - on the laptop screen UI, the ATM branding, the manager's blazer accent, and ambient office lighting. Mood: efficient, relieved, professional, empowering. High-quality commercial photography, cinematic office composition, warm professional lighting, 8K quality. AVOID: stressed expressions, cluttered desks, outdated technology."

EXAMPLE for fashion retail (Edgars):
"Professional advertisement image for a fashion retail company: Edgars. Target audience: Young Professionals. Create a scene showing a stylish young professional woman walking confidently out of a modern Edgars store entrance with the illuminated 'EDGARS' storefront sign visible above. She's carrying Edgars-branded shopping bags, wearing a chic outfit. She's checking her phone with a satisfied smile while her friend admires her new look. IMPORTANT COLOR THEME: Use #E31837 red as accent color throughout - on the Edgars signage, shopping bags, her accessories, store lighting glow. Mood: aspirational, confident, social, successful. High-quality commercial photography, street-style composition, golden hour lighting, 8K quality. AVOID: empty stores, bored expressions, cheap-looking items."

EXAMPLE for security company (SecureSights):
"Professional advertisement image for a security company: SecureSights. Target audience: Homeowners. Create a scene showing a relaxed father on a couch with his daughter, both smiling while he checks the SecureSights home security app on his tablet showing all-clear status with the SecureSights logo visible on the app interface. Through the window, you can see a peaceful evening neighborhood. A SecureSights-branded security camera is visible in the corner of the room. IMPORTANT COLOR THEME: Use #1E3A5F navy blue as accent color on tablet screen UI, the SecureSights camera, cushion accents, and evening ambient lighting. Mood: peaceful, protected, family-focused, reassuring. High-quality commercial photography, warm home interior, cozy evening lighting, 8K quality. AVOID: fear-based imagery, weapons, dark threatening scenes."

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
Logo URL: {logo_url}

Generate output in this EXACT format:

IMAGE_PROMPT: [Write a STRUCTURED 4-6 sentence prompt following my exact format above. Be IMAGINATIVE - create a REAL-WORLD SCENARIO showing people USING the product/service. Include: scene setup, realistic scenario with people in action, BRAND NAME visible naturally in the scene (on ATMs, storefronts, cards, screens, signage, products), their expressions and environment, color theme with hex code, mood, technical specs, and what to AVOID. Make it SPECIFIC to this business type - show the actual USE CASE with brand visibility. If a Logo URL is provided above, ADD this instruction at the end: "LOGO: Include the company logo from [logo_url] positioned subtly in the bottom-right corner."]

AD_ANGLE: [Write a compelling 1-2 sentence ad description that captures the essence of this creative angle.]

HEADLINE: [Write a short, punchy headline (5-8 words max) - NO EMOJIS, clean and professional]
"""

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
        visual_direction: str = "",
        logo_url: str = "",
        brand_color: str = ""
    ) -> Dict[str, str]:
        """
        Generate ad creative with image prompt and ad angle.
        Uses Claude (Anthropic) first, falls back to OpenAI (GPT-4o).

        Args:
            logo_url: URL to the company logo - will be included in prompt for Gemini to incorporate
            brand_color: Hex color code for brand color (e.g., "#0066CC") - extracted from website CSS

        Returns:
            Dict with 'image_prompt', 'ad_angle', and 'headline'
        """
        # Build brand color instruction
        color_instruction = ""
        if brand_color:
            color_instruction = f" IMPORTANT: The brand's primary color is {brand_color} - use this EXACT color as the accent color throughout the image."

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
            "visual_direction": (visual_direction or "Modern, clean, professional advertising style") + color_instruction,
            "logo_url": logo_url or "Not provided"
        }

        # Build prompt from template
        prompt_text = self.prompt_template.format(**creative_data)

        # Try Claude first (best for creative prompts)
        if self.anthropic_client:
            try:
                return await self._generate_with_claude(prompt_text, product_name, visual_direction, angle_value_proposition)
            except Exception as e:
                print(f"[AdCreativeAgent] Claude error: {e}")

        # Fall back to OpenAI
        if self.openai_client:
            try:
                return await self._generate_with_openai(prompt_text, product_name, visual_direction, angle_value_proposition)
            except Exception as e:
                print(f"[AdCreativeAgent] OpenAI error: {e}")

        # Return fallback values if all fails
        return {
            "image_prompt": self._generate_fallback_prompt(product_name, visual_direction),
            "ad_angle": f"Discover {product_name} - Quality you can trust",
            "headline": f"Discover {product_name}"
        }

    async def _generate_with_claude(self, prompt_text: str, product_name: str, visual_direction: str, angle_value_proposition: str) -> Dict[str, str]:
        """Generate creative using Claude (Anthropic API)"""
        model_name = "claude-sonnet-4-20250514"
        max_tokens = 800  # Reduced from 1500 to save costs

        print(f"[AdCreativeAgent] Using Claude ({model_name}, max_tokens={max_tokens})...")

        message = self.anthropic_client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": prompt_text}
            ]
        )

        response_text = message.content[0].text

        # Log token usage
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        print(f"[AdCreativeAgent] Claude tokens used - Input: {input_tokens}, Output: {output_tokens}, Total: {input_tokens + output_tokens}")

        # Parse response
        result = self._parse_creative_response(response_text)

        # Ensure valid values
        if not result["image_prompt"]:
            result["image_prompt"] = self._generate_fallback_prompt(product_name, visual_direction)
        if not result["ad_angle"]:
            result["ad_angle"] = f"Discover {product_name} - {angle_value_proposition or 'Your perfect choice'}"
        if not result["headline"]:
            result["headline"] = f"Discover {product_name}"

        # Add AI model info to result
        result["ai_model"] = model_name
        result["tokens_used"] = input_tokens + output_tokens

        print(f"[AdCreativeAgent] Claude generation successful (used {input_tokens + output_tokens} tokens)")
        return result

    async def _generate_with_openai(self, prompt_text: str, product_name: str, visual_direction: str, angle_value_proposition: str) -> Dict[str, str]:
        """Generate creative using OpenAI (GPT-4o) as fallback"""
        model_name = "gpt-4o"
        max_tokens = 800  # Reduced from 1500 to save costs

        print(f"[AdCreativeAgent] Using OpenAI ({model_name}, max_tokens={max_tokens}) as fallback...")

        response = self.openai_client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "user", "content": prompt_text}
            ],
            temperature=0.7,
            max_tokens=max_tokens
        )

        response_text = response.choices[0].message.content

        # Log token usage
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        print(f"[AdCreativeAgent] OpenAI tokens used - Input: {input_tokens}, Output: {output_tokens}, Total: {input_tokens + output_tokens}")

        # Parse response
        result = self._parse_creative_response(response_text)

        # Ensure valid values
        if not result["image_prompt"]:
            result["image_prompt"] = self._generate_fallback_prompt(product_name, visual_direction)
        if not result["ad_angle"]:
            result["ad_angle"] = f"Discover {product_name} - {angle_value_proposition or 'Your perfect choice'}"
        if not result["headline"]:
            result["headline"] = f"Discover {product_name}"

        # Add AI model info to result
        result["ai_model"] = model_name
        result["tokens_used"] = input_tokens + output_tokens

        print(f"[AdCreativeAgent] OpenAI generation successful (used {input_tokens + output_tokens} tokens)")
        return result

    def _generate_fallback_prompt(self, product_name: str, visual_direction: str) -> str:
        """Generate a structured fallback image prompt"""
        if visual_direction:
            return f"Professional advertisement image for {product_name}. {visual_direction}. IMPORTANT COLOR THEME: Use brand-appropriate accent colors throughout the composition. Mood: professional, inviting, aspirational. High-quality commercial photography, clean composition, professional studio lighting, 8K quality. AVOID: cluttered backgrounds, competitor logos, low quality elements. No text in image."
        return f"Professional advertisement image for {product_name}. Create a scene showing the product/service in an aspirational setting with clean, modern styling. IMPORTANT COLOR THEME: Use brand-appropriate accent colors on key elements and lighting. Mood: professional, trustworthy, inviting. High-quality commercial photography, clean composition, professional studio lighting, 8K quality. AVOID: cluttered backgrounds, competitor logos. No text in image."

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
