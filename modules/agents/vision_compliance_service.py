"""
Vision Compliance Service - OpenAI Vision-based image compliance checking.

This service analyzes AI-generated images for advertising compliance issues
including nudity, violence, brand risk, prohibited text, and more.
"""

import os
import json
import base64
import httpx
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime


# Vision Compliance Result Models
class VisionComplianceIssue(BaseModel):
    """Individual compliance issue detected in an image"""
    category: str  # nudity, violence, brand_risk, text_content, political, etc.
    severity: str  # warning, violation, critical
    description: str
    location: Optional[str] = None  # top-left, center, bottom-right, etc.


class VisionComplianceResult(BaseModel):
    """Result of vision compliance check"""
    is_compliant: bool
    risk_level: str  # low, medium, high, critical
    issues: List[VisionComplianceIssue] = []
    detected_text: List[str] = []
    detected_logos: List[str] = []
    suggestions: List[str] = []
    confidence: float = 0.0
    analysis_time_ms: int = 0


class BrandSafetyResult(BaseModel):
    """Result of brand safety check"""
    is_safe: bool
    detected_logos: List[str] = []
    detected_text: List[str] = []
    competitor_detected: bool = False
    trademark_risk: bool = False
    issues: List[str] = []


class VisionComplianceService:
    """
    OpenAI Vision-based image compliance checking for advertising content.

    Checks for:
    - Nudity/sexual content
    - Violence/weapons
    - Brand risk (competitor logos, trademarks)
    - Prohibited text in images
    - Political/controversial content
    - Misleading claims
    - Age-restricted content (alcohol, tobacco, gambling)
    """

    COMPLIANCE_CATEGORIES = [
        "nudity",           # Explicit/suggestive content
        "violence",         # Graphic violence, weapons
        "brand_risk",       # Competitor logos, trademark violations
        "text_content",     # Prohibited words in image text
        "political",        # Political content
        "misleading",       # Fake testimonials, unrealistic claims
        "alcohol_tobacco",  # Age-restricted products
        "gambling",         # Gambling imagery
        "hate_speech",      # Discriminatory content
        "celebrity",        # Celebrity likenesses without permission
    ]

    # Meta Ads prohibited content keywords (for text detection)
    PROHIBITED_KEYWORDS = [
        # Weapons & violence
        "gun", "rifle", "weapon", "ammunition", "explosive",
        # Adult content
        "nude", "naked", "xxx", "porn", "adult only",
        # Drugs
        "cocaine", "heroin", "meth", "drug dealer",
        # Misleading
        "guaranteed results", "get rich quick", "miracle cure",
        # Political
        "vote for", "election", "political party",
    ]

    def __init__(self):
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        self.base_url = "https://api.openai.com/v1"
        self.openrouter_url = "https://openrouter.ai/api/v1"

        # Prefer OpenRouter if available (may be more cost-effective)
        self.use_openrouter = bool(self.openrouter_api_key) and not self.openai_api_key

    async def analyze_image(
        self,
        image_base64: str,
        industry: Optional[str] = None,
        brand_name: Optional[str] = None,
        competitor_brands: Optional[List[str]] = None
    ) -> VisionComplianceResult:
        """
        Analyze an image for advertising compliance issues using GPT-4o Vision.

        Args:
            image_base64: Base64-encoded image data
            industry: Optional industry context (e.g., "security", "food", "health")
            brand_name: The advertiser's brand name
            competitor_brands: List of competitor brand names to check for

        Returns:
            VisionComplianceResult with compliance status and any issues found
        """
        start_time = datetime.now()

        # Build the compliance check prompt
        prompt = self._build_compliance_prompt(industry, brand_name, competitor_brands)

        try:
            # Call vision API
            response = await self._call_vision_api(image_base64, prompt)

            # Parse response
            result = self._parse_compliance_response(response)

            # Calculate analysis time
            result.analysis_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            return result

        except Exception as e:
            # Return safe default on error (flag for manual review)
            return VisionComplianceResult(
                is_compliant=False,
                risk_level="medium",
                issues=[VisionComplianceIssue(
                    category="error",
                    severity="warning",
                    description=f"Vision analysis failed: {str(e)}. Manual review recommended."
                )],
                suggestions=["Manual review required due to analysis error"],
                confidence=0.0,
                analysis_time_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )

    async def check_brand_safety(
        self,
        image_base64: str,
        brand_name: str,
        competitor_brands: List[str]
    ) -> BrandSafetyResult:
        """
        Check image specifically for brand safety issues.

        Detects:
        - Competitor logos
        - Trademarked content
        - Inappropriate brand associations
        """
        prompt = f"""Analyze this image for brand safety. The advertiser's brand is "{brand_name}".

Check for the presence of these competitor brands: {', '.join(competitor_brands)}

Identify:
1. Any visible logos or brand names
2. Any text that mentions brands
3. Any trademark symbols or registered marks
4. Any content that could create negative brand association

Return JSON:
{{
    "is_safe": boolean,
    "detected_logos": ["list of brand logos visible"],
    "detected_text": ["list of brand names in text"],
    "competitor_detected": boolean,
    "trademark_risk": boolean,
    "issues": ["list of specific brand safety concerns"]
}}"""

        try:
            response = await self._call_vision_api(image_base64, prompt)
            data = self._extract_json_from_response(response)

            return BrandSafetyResult(
                is_safe=data.get("is_safe", True),
                detected_logos=data.get("detected_logos", []),
                detected_text=data.get("detected_text", []),
                competitor_detected=data.get("competitor_detected", False),
                trademark_risk=data.get("trademark_risk", False),
                issues=data.get("issues", [])
            )
        except Exception as e:
            return BrandSafetyResult(
                is_safe=False,
                issues=[f"Brand safety check failed: {str(e)}"]
            )

    async def extract_text_from_image(self, image_base64: str) -> List[str]:
        """
        Extract all visible text from an image using OCR via Vision API.

        Returns list of text strings found in the image.
        """
        prompt = """Extract ALL visible text from this image.

Return a JSON array of strings containing each piece of text found:
["text 1", "text 2", "text 3"]

Include:
- Headlines and titles
- Body text
- Buttons and CTAs
- Watermarks
- Small print
- Any other readable text"""

        try:
            response = await self._call_vision_api(image_base64, prompt)
            data = self._extract_json_from_response(response)

            if isinstance(data, list):
                return data
            return []
        except:
            return []

    def _build_compliance_prompt(
        self,
        industry: Optional[str] = None,
        brand_name: Optional[str] = None,
        competitor_brands: Optional[List[str]] = None
    ) -> str:
        """Build the comprehensive compliance check prompt."""

        industry_context = f"\nIndustry context: {industry}" if industry else ""
        brand_context = f"\nAdvertiser brand: {brand_name}" if brand_name else ""
        competitor_context = f"\nCompetitor brands to detect: {', '.join(competitor_brands)}" if competitor_brands else ""

        return f"""Analyze this advertising image for compliance with Meta Ads policies. Be thorough and strict.
{industry_context}{brand_context}{competitor_context}

CHECK FOR THESE CATEGORIES:

1. NUDITY/SEXUAL CONTENT (Critical)
   - Any exposed intimate body parts
   - Suggestive poses or expressions
   - Underwear/lingerie as main focus
   - Sexual innuendo

2. VIOLENCE/WEAPONS (Critical)
   - Guns, knives, or weapons of any kind
   - Blood, gore, or injury
   - Threatening imagery
   - Combat or fighting scenes

3. BRAND RISK (High)
   - Competitor logos or branding
   - Trademarked imagery
   - Celebrity likenesses without obvious consent
   - Content that could damage brand reputation

4. TEXT CONTENT (Medium-High)
   - Read ALL text in the image
   - Flag prohibited words: drugs, weapons, hate speech
   - Check for misleading claims: "guaranteed", "miracle", "get rich"
   - Political messaging

5. MISLEADING CONTENT (High)
   - Fake before/after images
   - Unrealistic body transformations
   - False testimonials
   - Exaggerated claims

6. RESTRICTED CATEGORIES (Medium)
   - Alcohol imagery (age-restricted)
   - Tobacco/vaping products
   - Gambling elements
   - Political content

7. HATE/DISCRIMINATION (Critical)
   - Discriminatory imagery
   - Hate symbols
   - Offensive stereotypes

Return your analysis as valid JSON:
{{
    "is_compliant": boolean,
    "risk_level": "low" | "medium" | "high" | "critical",
    "issues": [
        {{
            "category": "category_name",
            "severity": "warning" | "violation" | "critical",
            "description": "detailed description of the issue",
            "location": "where in image (e.g., 'center', 'top-left')"
        }}
    ],
    "detected_text": ["all", "text", "found", "in", "image"],
    "detected_logos": ["any", "brand", "logos", "detected"],
    "suggestions": ["how to fix each issue"],
    "confidence": 0.0 to 1.0
}}

Be conservative - when in doubt, flag it. False positives are better than false negatives."""

    async def _call_vision_api(self, image_base64: str, prompt: str) -> str:
        """Call the OpenAI or OpenRouter Vision API."""

        # Ensure proper base64 format
        if not image_base64.startswith("data:"):
            # Add data URI prefix if not present
            image_base64 = f"data:image/jpeg;base64,{image_base64}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_base64,
                            "detail": "high"  # Use high detail for compliance checking
                        }
                    }
                ]
            }
        ]

        if self.use_openrouter:
            # Use OpenRouter
            headers = {
                "Authorization": f"Bearer {self.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://shopivell.com",
                "X-Title": "Shopivell Vision Compliance"
            }
            url = f"{self.openrouter_url}/chat/completions"
            model = "openai/gpt-4o"  # GPT-4o via OpenRouter
        else:
            # Use OpenAI directly
            headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }
            url = f"{self.base_url}/chat/completions"
            model = "gpt-4o-mini"

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 2000,
            "temperature": 0.1  # Low temperature for consistent compliance checking
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()

            data = response.json()
            return data["choices"][0]["message"]["content"]

    def _parse_compliance_response(self, response: str) -> VisionComplianceResult:
        """Parse the Vision API response into a VisionComplianceResult."""

        data = self._extract_json_from_response(response)

        # Parse issues
        issues = []
        for issue_data in data.get("issues", []):
            issues.append(VisionComplianceIssue(
                category=issue_data.get("category", "unknown"),
                severity=issue_data.get("severity", "warning"),
                description=issue_data.get("description", ""),
                location=issue_data.get("location")
            ))

        return VisionComplianceResult(
            is_compliant=data.get("is_compliant", True),
            risk_level=data.get("risk_level", "low"),
            issues=issues,
            detected_text=data.get("detected_text", []),
            detected_logos=data.get("detected_logos", []),
            suggestions=data.get("suggestions", []),
            confidence=data.get("confidence", 0.8)
        )

    def _extract_json_from_response(self, response: str) -> Dict[str, Any]:
        """Extract JSON from a response that may contain markdown code blocks."""

        # Try to parse directly first
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try to extract from markdown code block
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            if end > start:
                try:
                    return json.loads(response[start:end].strip())
                except:
                    pass

        # Try to find JSON object in response
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except:
            pass

        # Return safe default
        return {
            "is_compliant": False,
            "risk_level": "medium",
            "issues": [{
                "category": "parse_error",
                "severity": "warning",
                "description": "Could not parse compliance response. Manual review recommended."
            }],
            "suggestions": ["Manual review required"],
            "confidence": 0.0
        }


# Singleton instance for easy import
vision_compliance_service = VisionComplianceService()
