# ad_creative_agent.py - AI Agent for Ad Creative Generation
"""
This agent takes creative angles and generates:
1. Detailed image prompts for AI image generation
2. Ad angles (descriptions) for the ad content

Uses OpenRouter to route to Claude or GPT-4o.
"""

import os
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Import OpenAI client (used for OpenRouter's OpenAI-compatible API)
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


# --- Structured output model for ad creative ---

class CreativeOutput(BaseModel):
    """Structured output from ad creative generation"""
    image_prompt: str = Field(..., description="Complete image generation prompt for clean base image (NO text baked in)")
    ad_angle: str = Field(..., description="1-2 sentence compelling creative angle description")
    headline: str = Field(..., description="Short punchy headline, 5-8 words, no emojis")
    bullet_points: List[str] = Field(default_factory=list, description="3 key benefit bullet points")
    cta_text: str = Field(default="Learn More", description="Call to action button text")


class AdCreativeAgent:
    """AI Agent for generating ad creatives with high-quality structured image prompts.

    Uses OpenRouter to route to Claude (primary) or GPT-4o (fallback).
    """

    def __init__(self):
        self.client = None
        self.primary_model = "gpt-4o"
        self.fallback_model = "gpt-4o-mini"

        openai_key = os.getenv("OPENAI_API_KEY")
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
            self.primary_model = "anthropic/claude-sonnet-4.6"
            self.fallback_model = "openai/gpt-4o"
            logger.info("[AdCreativeAgent] Initialized with OpenRouter")
        elif OPENAI_AVAILABLE and openai_key:
            self.client = OpenAI(api_key=openai_key)
            logger.info("[AdCreativeAgent] Initialized with OpenAI directly")
        else:
            logger.warning("[AdCreativeAgent] No API key available!")

        # Prompt template for CLEAN base image generation (NO text baked in)
        # Text overlay is handled separately by AdImageComposer for professional results
        self.prompt_template = """You are an expert advertising creative director who writes EXCEPTIONAL image generation prompts for AI tools like Gemini and DALL-E.

IMPORTANT: Be IMAGINATIVE and create REAL-WORLD SCENARIOS showing the product/service IN USE. Don't just show products - show PEOPLE experiencing the benefits in realistic situations. Think about WHO uses this service and WHAT they're doing when they use it.

CRITICAL: Generate a CLEAN base image with NO TEXT, NO HEADLINES, NO BUTTONS, NO BULLET POINTS.
Text will be overlaid programmatically AFTER image generation for crisp, professional results.
Instead, leave these areas clear for text overlay:
- TOP 20% of image: Keep slightly darker/simpler for headline overlay
- LEFT SIDE: Leave some visual space for bullet point overlay
- BOTTOM-RIGHT: Leave space for CTA button overlay

COMPOSITION RULES FOR CLEAN BASE IMAGES:
1. TOP AREA: Slightly darker or gradient-friendly area for headline overlay (NO text in image)
2. LEFT SIDE: Visual breathing room for bullet point overlay (NO text in image)
3. BOTTOM-RIGHT: Clear space for CTA button overlay (NO button in image)
4. DEVICE SHOWCASE: For SaaS/digital products - person HOLDING or POINTING TO a device showing the product interface
5. SUBJECT POSITIONING: Main subjects positioned center-right to leave room for text overlays on left

Your prompts MUST follow this EXACT structure (ALL 10 elements required):
1. ART STYLE: "Photorealistic commercial advertisement" or "Cinematic photorealistic ad"
2. SCENE SETUP: "Professional marketing image for a [industry] company: [business name]."
3. SUBJECT: Clearly describe the main subject (person, product, or both) — the hero of the image
4. ACTION: What the subject is DOING — a specific verb (holding, demonstrating, walking, interacting)
5. SCENARIO: A REALISTIC scene showing the product/service being USED by real people
6. LIGHTING: Be SPECIFIC — key light direction, quality, mood (e.g., "soft key light from upper-left with warm fill")
7. LENS & CAMERA: Focal length, aperture, camera position (e.g., "85mm f/2.0 from waist-height, medium shot")
8. COLOR THEME: "Use [brand color] as accent color in clothing, environment, device screens"
9. MOOD: What the VIEWER should FEEL when they see this image
10. TECHNICAL: "Photorealistic commercial photography, 8K resolution, [aspect ratio]. NO TEXT IN IMAGE. AVOID: text, words, letters, logos, watermarks, cluttered backgrounds."

EXAMPLE for SaaS/digital service (Business Email Provider):
"Photorealistic commercial advertisement. Professional marketing advertisement image for a business email service company: WEBZIM. TEXT OVERLAY: At the top of the image, include a dark semi-transparent header banner with large bold white text reading: 'Professional Email From US$25/Year'. On the left side of the image, display 3 bullet points in white text: • Personalized emails (info@yourdomain) • Plans from US$25/year • Reliable storage and spam protection. Include a bright green #7CB342 colored button on the right side with white text reading: 'CREATE BUSINESS EMAIL'. SUBJECT: A friendly female business owner as the hero, wearing a black apron over a grey shirt. ACTION: She is warmly smiling while holding a tablet in one hand and pointing to the screen with the other, actively demonstrating the email interface. SCENE: The tablet displays a professional email inbox interface with the WEBZIM logo at top, showing multiple business email conversations with contact avatars. A male colleague stands behind her slightly blurred, also smiling. The background shows a warm, inviting cafe interior with soft bokeh. Subject positioned center-right. LIGHTING: Soft natural window light from the upper-left as key, with warm ambient cafe light as fill creating gentle golden tones on subjects, subtle rim light from behind separating them from the bokeh background. LENS & CAMERA: Shot at 50mm f/2.8 from eye-level, medium shot framing subject from waist up, shallow depth of field blurring background patrons and cafe decor into creamy bokeh. IMPORTANT COLOR THEME: Use #7CB342 bright green as accent color - on the CTA button, tablet screen interface elements, and subtle lighting accents. Mood: professional, approachable, successful, modern — the viewer should feel empowered to start their own business email. Photorealistic commercial photography, marketing advertisement style, 8K resolution, 4:5 portrait format. AVOID: cluttered interfaces, corporate sterile environments, stock photo poses. Ensure all text overlays are crisp, readable, and professionally designed."

EXAMPLE for fintech/payments company (Zimswitch):
"Cinematic photorealistic advertisement. Professional marketing advertisement image for a financial technology company: Zimswitch. TEXT OVERLAY: At the top of the image, include a dark semi-transparent header banner with large bold white text reading: 'Seamless Payroll Processing'. On the left side of the image, display 3 bullet points in white text: • Bulk salary payments • Secure transactions • Nationwide coverage. Include a blue #0066CC colored button on the right side with white text reading: 'GET STARTED'. SUBJECT: A confident female HR manager as the hero in a tailored navy blazer. ACTION: She is smiling while holding a tablet in her left hand and pointing at a successful salary transaction on screen with her right index finger, actively reviewing payroll results. SCENE: The tablet displays a payroll dashboard with the Zimswitch logo and multiple employee salary transactions showing green checkmarks. A Zimswitch-branded ATM is visible through the floor-to-ceiling office window. Subject positioned center-right. LIGHTING: Cool-toned key light from a large window on the right, with warm practical fill from overhead office fixtures creating a balanced corporate ambiance, soft edge light on subject's shoulders from the window. LENS & CAMERA: Shot at 85mm f/2.0 from slightly below eye-level (empowering angle), medium-close framing from chest up, background office and ATM softly out of focus at f/2.0. IMPORTANT COLOR THEME: Use #0066CC blue as accent color - on the CTA button, the tablet screen UI, the ATM branding, and ambient office lighting. Mood: efficient, relieved, professional, empowering — the viewer should feel that payroll is finally solved. Photorealistic commercial photography, marketing advertisement style, 8K resolution, 4:5 portrait format. AVOID: stressed expressions, cluttered desks, outdated technology. Ensure all text overlays are crisp and readable."

EXAMPLE for fashion retail (Edgars):
"Cinematic photorealistic advertisement. Professional marketing advertisement image for a fashion retail company: Edgars. TEXT OVERLAY: At the top of the image, include a dark semi-transparent header banner with large bold white text reading: 'Style That Defines You'. On the left side of the image, display 3 bullet points in white text: • Trendy fashion for all • Affordable prices • Quality brands you trust. Include a red #E31837 colored button on the right side with white text reading: 'SHOP NOW'. SUBJECT: A stylish young professional woman as the hero in a chic contemporary outfit. ACTION: She is walking confidently out of a modern Edgars store entrance, carrying branded shopping bags in one hand and checking her phone with a satisfied smile, while her friend behind her admires the new look. SCENE: The illuminated 'EDGARS' storefront sign is visible above. The background shows a modern shopping district with warm evening light. Subject positioned center-right. LIGHTING: Golden hour sunlight from the left casting long warm shadows, with the illuminated storefront providing cool-toned fill from behind, creating a cinematic backlit glow on the subject's hair and shoulder. LENS & CAMERA: Shot at 70mm f/2.0 from knee-height (low angle, empowering), full-body framing with the storefront sign visible above, shallow depth of field melting the street background into smooth bokeh. IMPORTANT COLOR THEME: Use #E31837 red as accent color - on the CTA button, Edgars signage, shopping bags, her accessories. Mood: aspirational, confident, social, successful — the viewer should feel inspired to upgrade their wardrobe. Cinematic photorealistic commercial photography, marketing advertisement style, golden hour warmth, 8K resolution, 4:5 portrait format. AVOID: empty stores, bored expressions, cheap-looking items. Ensure all text overlays are crisp and readable."

EXAMPLE for security company (SecureSights):
"Photorealistic commercial advertisement. Professional marketing advertisement image for a security company: SecureSights. TEXT OVERLAY: At the top of the image, include a dark semi-transparent header banner with large bold white text reading: 'Peace of Mind, Always'. On the left side of the image, display 3 bullet points in white text: • 24/7 monitoring • Smart home integration • Instant alerts. Include a navy blue #1E3A5F colored button on the right side with white text reading: 'PROTECT YOUR HOME'. SUBJECT: A relaxed father and his young daughter as the heroes, sitting close together on a modern couch. ACTION: The father is holding a tablet and pointing to the SecureSights home security app showing all-clear status with the SecureSights logo visible, while his daughter leans in curiously to look at the screen, both smiling warmly. SCENE: Through the large window behind them, a peaceful evening neighborhood with streetlights is visible. A sleek SecureSights-branded security camera is mounted in the upper corner of the room. Subject positioned center-right. LIGHTING: Cozy warm interior lighting from a floor lamp on the left as key, with cool blue evening light filtering through the window as fill, creating an intimate domestic atmosphere with gentle shadows. LENS & CAMERA: Shot at 35mm f/2.8 from seated eye-level, medium-wide shot capturing the full couch scene with environmental context of the room and window, moderate depth of field keeping subjects sharp while softening the window view. IMPORTANT COLOR THEME: Use #1E3A5F navy blue as accent color - on CTA button, tablet screen UI, the security camera, cushion accents. Mood: peaceful, protected, family-focused, reassuring — the viewer should feel their family is safe and connected. Photorealistic commercial photography, marketing advertisement style, cozy evening warmth, 8K resolution, 4:5 portrait format. AVOID: fear-based imagery, weapons, dark threatening scenes. Ensure all text overlays are crisp and readable."

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

IMPORTANT: Return your response as valid JSON with this exact structure:
{{
  "image_prompt": "Complete image generation prompt following the 10-element format above. MUST generate a CLEAN image with NO TEXT, NO WORDS, NO LETTERS. Leave clear areas for programmatic text overlay.",
  "ad_angle": "1-2 sentence compelling creative angle description",
  "headline": "Short punchy headline, 5-8 words max, NO EMOJIS",
  "bullet_points": ["Benefit 1", "Benefit 2", "Benefit 3"],
  "cta_text": "{call_to_action}"
}}

Return ONLY valid JSON, no other text.
"""

    def _parse_creative_response(self, response_text: str) -> Dict[str, Any]:
        """Parse the AI response into structured creative data. JSON-first with prefix fallback."""
        # Try JSON parsing first (Pydantic validation)
        try:
            cleaned = response_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = CreativeOutput.model_validate_json(cleaned)
            return data.model_dump()
        except Exception:
            pass

        # Try plain JSON
        try:
            data = json.loads(cleaned)
            return {
                "image_prompt": data.get("image_prompt", ""),
                "ad_angle": data.get("ad_angle", ""),
                "headline": data.get("headline", ""),
                "bullet_points": data.get("bullet_points", []),
                "cta_text": data.get("cta_text", "Learn More")
            }
        except Exception:
            pass

        logger.warning("[AdCreativeAgent] JSON parse failed, falling back to prefix parsing")

        # Fallback: prefix-based parsing (backward compatibility)
        result = {"image_prompt": "", "ad_angle": "", "headline": "", "bullet_points": [], "cta_text": "Learn More"}
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

    async def _generate_with_openrouter(self, prompt_text: str, model_name: str, product_name: str, visual_direction: str, angle_value_proposition: str) -> Dict[str, Any]:
        """Generate creative using OpenRouter with structured JSON output."""
        max_tokens = 2000

        logger.info(f"[AdCreativeAgent] Using OpenRouter ({model_name}, max_tokens={max_tokens})")

        response = self.client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "user", "content": prompt_text}
            ],
            temperature=0.7,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
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
        """Generate a structured fallback image prompt with full visual specification"""
        base = (
            f"Photorealistic commercial advertisement. "
            f"SUBJECT: {product_name} as the hero of the image. "
        )
        if visual_direction:
            base += f"ACTION & DIRECTION: {visual_direction}. "
        else:
            base += "ACTION: The product/service shown in active use in an aspirational modern setting. "

        base += (
            "LIGHTING: Soft key light from upper-left with warm fill and gentle rim light separating subject from background. "
            "LENS & CAMERA: Shot on Canon 5D Mark IV with 85mm f/1.4 lens, medium shot from eye-level, shallow depth of field, creamy bokeh, soft focus background. "
            "IMPORTANT COLOR THEME: Use brand-appropriate accent colors throughout the composition. "
            "MOOD: Professional, inviting, aspirational — the viewer should feel drawn to explore the product. "
            "Photorealistic commercial photography, clean composition, 8K resolution, 4:5 portrait format. "
            "AVOID: cluttered backgrounds, competitor logos, low quality elements. No text in image."
        )
        return base

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
        # Run all angle generations in parallel
        async def _gen_single(angle: Dict) -> Dict[str, Any]:
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
            return {
                **creative,
                "angle_name": angle.get("angle_name", "Default"),
                "angle_data": angle
            }

        tasks = [_gen_single(angle) for angle in creative_angles]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        creatives = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[AdCreativeAgent] Parallel generation error for angle {i}: {result}")
                creatives.append({
                    "image_prompt": self._generate_fallback_prompt(product_name, ""),
                    "ad_angle": f"Discover {product_name}",
                    "headline": f"Discover {product_name}",
                    "angle_name": creative_angles[i].get("angle_name", "Default"),
                    "angle_data": creative_angles[i]
                })
            else:
                creatives.append(result)

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
