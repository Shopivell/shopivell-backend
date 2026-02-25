# ad_creative_agent.py - AI Agent for Ad Creative Generation
"""
This agent takes creative angles and generates:
1. Detailed image prompts for AI image generation
2. Ad angles (descriptions) for the ad content

Uses OpenRouter to route to Claude or GPT-4o.
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Import OpenAI client (used for OpenRouter's OpenAI-compatible API)
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


class AdCreativeAgent:
    """AI Agent for generating ad creatives with high-quality structured image prompts.

    Uses OpenRouter to route to Claude (primary) or GPT-4o (fallback).
    """

    def __init__(self):
        self.client = None
        self.primary_model = "anthropic/claude-sonnet-4"
        self.fallback_model = "openai/gpt-4o"

        openrouter_key = os.getenv("OPENROUTER_API_KEY")

        if OPENAI_AVAILABLE and openrouter_key:
            self.client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=openrouter_key,
                default_headers={
                    "HTTP-Referer": "https://shopivell.com",
                    "X-Title": "Shopivell Ad Generator",
                }
            )
            logger.info("[AdCreativeAgent] Initialized with OpenRouter")
        else:
            logger.warning("[AdCreativeAgent] No OpenRouter API key or OpenAI package not available!")

        # STRUCTURED prompt template that generates high-quality image prompts
        # This format produces prompts like a professional creative director would write
        self.prompt_template = """You are an expert advertising creative director who writes EXCEPTIONAL image generation prompts for AI tools like Gemini and DALL-E.

IMPORTANT: Be IMAGINATIVE and create REAL-WORLD SCENARIOS showing the product/service IN USE. Don't just show products - show PEOPLE experiencing the benefits in realistic situations. Think about WHO uses this service and WHAT they're doing when they use it.

CRITICAL: YOU ARE CREATING A COMPLETE MARKETING AD IMAGE WITH TEXT BAKED IN.
The final image must include ALL text elements rendered directly in the image:
- HEADLINE at the top (dark banner/header area)
- BULLET POINTS on the left side (with bullet markers)
- CTA BUTTON (colored button with action text)

COMPOSITION RULES FOR MARKETING ADS WITH TEXT:
1. TOP HEADER AREA: Dark semi-transparent banner at top 15-20% with large white headline text
2. LEFT SIDE BULLETS: 3 benefit bullet points with bullet markers (•) on the left side of the image
3. CTA BUTTON: Bright colored button (use brand color) with white text for the call-to-action, positioned on right side
4. DEVICE SHOWCASE: For SaaS/digital products - person HOLDING or POINTING TO a device showing the product interface
5. SUBJECT POSITIONING: Main subjects positioned center-right to leave room for bullet text on left

Your prompts MUST follow this EXACT structure:
1. SCENE SETUP: "Professional marketing advertisement image for a [industry] company: [business name]."
2. TEXT OVERLAY - HEADLINE: "TEXT OVERLAY: At the top of the image, include a dark semi-transparent header banner with large bold white text reading: '[HEADLINE TEXT]'"
3. TEXT OVERLAY - BULLETS: "On the left side of the image, display 3 bullet points in white text: • [Benefit 1] • [Benefit 2] • [Benefit 3]"
4. TEXT OVERLAY - CTA: "Include a [brand color] colored button on the right side with white text reading: '[CTA TEXT]'"
5. SCENARIO: Create a REALISTIC scene showing the product/service being USED by real people
6. PEOPLE & ACTION: Include people actively using/benefiting from the service with positive expressions
7. DEVICE DISPLAY (for digital products): Show the product interface on a device being held/pointed to by the person
8. COLOR THEME: "IMPORTANT COLOR THEME: Use [brand color] as accent color - on CTA button, device screen elements, clothing accents."
9. MOOD: "Mood: [specific mood words]."
10. TECHNICAL: "High-quality commercial photography, marketing advertisement style, professional lighting, 8K quality."
11. COMPLIANCE: "AVOID: [things to avoid]. Ensure all text is crisp and readable."

EXAMPLE for SaaS/digital service (Business Email Provider):
"Professional marketing advertisement image for a business email service company: WEBZIM. TEXT OVERLAY: At the top of the image, include a dark semi-transparent header banner with large bold white text reading: 'Professional Email From US$25/Year'. On the left side of the image, display 3 bullet points in white text: • Personalized emails (info@yourdomain) • Plans from US$25/year • Reliable storage and spam protection. Include a bright green #7CB342 colored button on the right side with white text reading: 'CREATE BUSINESS EMAIL'. SCENE: A friendly female business owner in a cafe setting wearing a black apron over a grey shirt, warmly smiling while holding a tablet and pointing to the screen. The tablet displays a professional email inbox interface with the WEBZIM logo at top, showing multiple business email conversations with contact avatars. A male colleague stands behind her slightly blurred, also smiling. The background shows a warm, inviting cafe interior with soft bokeh lighting. Subject positioned center-right. IMPORTANT COLOR THEME: Use #7CB342 bright green as accent color - on the CTA button, tablet screen interface elements, and subtle lighting accents. Mood: professional, approachable, successful, modern. High-quality commercial photography, marketing advertisement style, warm natural lighting, 8K quality. AVOID: cluttered interfaces, corporate sterile environments, stock photo poses. Ensure all text overlays are crisp, readable, and professionally designed."

EXAMPLE for fintech/payments company (Zimswitch):
"Professional marketing advertisement image for a financial technology company: Zimswitch. TEXT OVERLAY: At the top of the image, include a dark semi-transparent header banner with large bold white text reading: 'Seamless Payroll Processing'. On the left side of the image, display 3 bullet points in white text: • Bulk salary payments • Secure transactions • Nationwide coverage. Include a blue #0066CC colored button on the right side with white text reading: 'GET STARTED'. SCENE: A confident HR manager in a modern office, smiling while holding a tablet displaying a payroll dashboard with the Zimswitch logo and multiple employee salary transactions. She points at a successful transaction on screen. A Zimswitch-branded ATM is visible through the office window. Subject positioned center-right. IMPORTANT COLOR THEME: Use #0066CC blue as accent color - on the CTA button, the tablet screen UI, the ATM branding, and ambient office lighting. Mood: efficient, relieved, professional, empowering. High-quality commercial photography, marketing advertisement style, warm professional lighting, 8K quality. AVOID: stressed expressions, cluttered desks, outdated technology. Ensure all text overlays are crisp and readable."

EXAMPLE for fashion retail (Edgars):
"Professional marketing advertisement image for a fashion retail company: Edgars. TEXT OVERLAY: At the top of the image, include a dark semi-transparent header banner with large bold white text reading: 'Style That Defines You'. On the left side of the image, display 3 bullet points in white text: • Trendy fashion for all • Affordable prices • Quality brands you trust. Include a red #E31837 colored button on the right side with white text reading: 'SHOP NOW'. SCENE: A stylish young professional woman walking confidently out of a modern Edgars store entrance with the illuminated 'EDGARS' storefront sign visible above. She's carrying Edgars-branded shopping bags, wearing a chic outfit, checking her phone with a satisfied smile while her friend admires her new look. Subject positioned center-right. IMPORTANT COLOR THEME: Use #E31837 red as accent color - on the CTA button, Edgars signage, shopping bags, her accessories. Mood: aspirational, confident, social, successful. High-quality commercial photography, marketing advertisement style, golden hour lighting, 8K quality. AVOID: empty stores, bored expressions, cheap-looking items. Ensure all text overlays are crisp and readable."

EXAMPLE for security company (SecureSights):
"Professional marketing advertisement image for a security company: SecureSights. TEXT OVERLAY: At the top of the image, include a dark semi-transparent header banner with large bold white text reading: 'Peace of Mind, Always'. On the left side of the image, display 3 bullet points in white text: • 24/7 monitoring • Smart home integration • Instant alerts. Include a navy blue #1E3A5F colored button on the right side with white text reading: 'PROTECT YOUR HOME'. SCENE: A relaxed father on a couch with his daughter, both smiling while he holds and points to a tablet showing the SecureSights home security app with all-clear status and the SecureSights logo visible. Through the window, a peaceful evening neighborhood is visible. A SecureSights-branded security camera in the corner of the room. Subject positioned center-right. IMPORTANT COLOR THEME: Use #1E3A5F navy blue as accent color - on CTA button, tablet screen UI, the security camera, cushion accents. Mood: peaceful, protected, family-focused, reassuring. High-quality commercial photography, marketing advertisement style, cozy evening lighting, 8K quality. AVOID: fear-based imagery, weapons, dark threatening scenes. Ensure all text overlays are crisp and readable."

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

IMAGE_PROMPT: [Write a COMPLETE marketing ad prompt following my exact format above. MUST INCLUDE:
1. TEXT OVERLAY instructions with the HEADLINE text at the top in a dark banner
2. BULLET POINTS (3 benefits) on the left side using the key_benefits provided
3. CTA BUTTON with the call_to_action text in brand color
4. SCENE description with people using the product/service
5. Brand color theme and mood
6. Technical specs
The prompt must generate a COMPLETE AD IMAGE with all text baked in, not just a photo. If a Logo URL is provided above, ADD: "LOGO: Include the company logo from [logo_url] positioned subtly in the bottom-right corner."]

AD_ANGLE: [Write a compelling 1-2 sentence ad description that captures the essence of this creative angle.]

HEADLINE: [Write a short, punchy headline (5-8 words max) - NO EMOJIS, clean and professional. This MUST match the headline text you include in the IMAGE_PROMPT.]
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
        brand_color: str = "",
        visual_profile: Dict[str, Any] = None
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

        # Build visual profile instruction (uniforms, vehicles, equipment from actual website images)
        visual_profile_instruction = ""
        if visual_profile:
            parts = []
            if visual_profile.get("uniform_description"):
                parts.append(f"ACTUAL UNIFORMS FROM WEBSITE: {visual_profile['uniform_description']}")
            if visual_profile.get("vehicle_description"):
                parts.append(f"ACTUAL VEHICLES FROM WEBSITE: {visual_profile['vehicle_description']}")
            if visual_profile.get("equipment_description"):
                parts.append(f"ACTUAL EQUIPMENT FROM WEBSITE: {visual_profile['equipment_description']}")
            if parts:
                visual_profile_instruction = " | CRITICAL - USE THESE EXACT VISUAL DETAILS SEEN ON THE COMPANY WEBSITE (do not invent different uniforms/vehicles): " + " | ".join(parts)

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
            "visual_direction": (visual_direction or "Modern, clean, professional advertising style") + color_instruction + visual_profile_instruction,
            "logo_url": logo_url or "Not provided"
        }

        # Build prompt from template
        prompt_text = self.prompt_template.format(**creative_data)

        # Try primary model (Claude) via OpenRouter, then fallback (GPT-4o)
        if self.client:
            for model in [self.primary_model, self.fallback_model]:
                try:
                    return await self._generate_with_openrouter(prompt_text, model, product_name, visual_direction, angle_value_proposition)
                except Exception as e:
                    print(f"[AdCreativeAgent] {model} error: {e}")

        # Return fallback values if all fails
        return {
            "image_prompt": self._generate_fallback_prompt(product_name, visual_direction),
            "ad_angle": f"Discover {product_name} - Quality you can trust",
            "headline": f"Discover {product_name}"
        }

    async def _generate_with_openrouter(self, prompt_text: str, model_name: str, product_name: str, visual_direction: str, angle_value_proposition: str) -> Dict[str, str]:
        """Generate creative using OpenRouter (routes to Claude, GPT-4o, etc.)"""
        max_tokens = 800

        print(f"[AdCreativeAgent] Using OpenRouter ({model_name}, max_tokens={max_tokens})...")

        response = self.client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "user", "content": prompt_text}
            ],
            temperature=0.7,
            max_tokens=max_tokens
        )

        response_text = response.choices[0].message.content

        # Log token usage
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0
        print(f"[AdCreativeAgent] {model_name} tokens used - Input: {input_tokens}, Output: {output_tokens}, Total: {input_tokens + output_tokens}")

        # Track usage for billing
        try:
            from modules.openrouter.context import ai_context
            from modules.openrouter.ai_usage_service import track_usage
            ctx = ai_context.get()
            track_usage(
                model=model_name,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                agent_name=ctx.agent_name if ctx else "ad_creative",
                store_id=ctx.store_id if ctx else None,
                user_id=ctx.user_id if ctx else None,
                campaign_id=ctx.campaign_id if ctx else None,
                endpoint="chat/completions"
            )
        except Exception as e:
            logger.warning(f"[AdCreativeAgent] Usage tracking failed: {e}")

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

        print(f"[AdCreativeAgent] {model_name} generation successful (used {input_tokens + output_tokens} tokens)")
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
