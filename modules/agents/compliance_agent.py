# compliance_agent.py - AI Agent for Meta Ads Policy Compliance
"""
Uses Claude Haiku for context-aware compliance checking.
Claude excels at understanding nuanced context and applying complex rules.
"""

import os
import re
import json
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Import OpenRouter adapter
try:
    from modules.openrouter.langchain_adapter import ChatOpenRouter
    OPENROUTER_AVAILABLE = True
except ImportError:
    from langchain_openai import ChatOpenAI as ChatOpenRouter
    OPENROUTER_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


# --- Structured output model for compliance checks ---

class ComplianceIssue(BaseModel):
    category: str = ""
    description: str = ""
    severity: str = "medium"  # low, medium, high

class ComplianceCheckOutput(BaseModel):
    is_compliant: bool = False
    risk_level: str = "medium"  # low, medium, high, critical
    risk_score: int = Field(default=50, ge=0, le=100)  # Numeric risk 0-100
    issues: List[ComplianceIssue] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    safe_prompt: Optional[str] = None
    reasoning: str = ""


class ComplianceAgent:
    """
    AI Agent for checking Meta Ads policy compliance.

    Uses Claude Haiku for:
    - Context-aware policy analysis
    - Nuanced understanding (not just keyword matching)
    - Intelligent suggestions for safe alternatives
    """

    # Meta Advertising Policies - Prohibited Content
    META_PROHIBITED_CONTENT = {
        "weapons_violence": {
            "description": "Weapons, ammunition, explosives, or content promoting violence",
            "examples": ["guns", "firearms", "knives as weapons", "ammunition", "explosives",
                        "violence", "blood", "gore", "fighting", "assault"],
            "safe_alternatives": {
                "armed guard": "security monitoring system",
                "weapon": "protection technology",
                "gun": "surveillance equipment",
                "military personnel": "security professional",
                "combat": "protection services",
                "attack": "threat detection"
            }
        },
        "adult_content": {
            "description": "Nudity, sexual content, or adult products",
            "examples": ["nude", "naked", "sexual", "explicit", "adult content",
                        "provocative poses", "suggestive imagery"],
            "safe_alternatives": {}
        },
        "discriminatory_content": {
            "description": "Content that discriminates based on personal attributes",
            "examples": ["racist", "discrimination", "hate speech", "religious attacks",
                        "ethnic targeting", "disability mockery"],
            "safe_alternatives": {}
        },
        "drugs_tobacco": {
            "description": "Illegal drugs, tobacco products, or drug paraphernalia",
            "examples": ["drugs", "narcotics", "marijuana", "cocaine", "smoking",
                        "cigarettes", "vaping", "drug use"],
            "safe_alternatives": {}
        },
        "misleading_content": {
            "description": "False claims, fake news, or deceptive practices",
            "examples": ["guaranteed results", "miracle cure", "get rich quick",
                        "fake news", "misleading claims", "before/after transformation"],
            "safe_alternatives": {
                "guaranteed": "proven results",
                "miracle": "effective",
                "cure": "support",
                "instant results": "see improvements"
            }
        },
        "political_controversial": {
            "description": "Political content or highly controversial topics",
            "examples": ["political", "election", "voting", "controversial",
                        "extremist", "propaganda"],
            "safe_alternatives": {}
        }
    }

    # Meta Advertising Policies - Restricted Content (requires extra review)
    META_RESTRICTED_CONTENT = {
        "alcohol": {
            "description": "Alcohol products - restricted by age and location",
            "requires": "Age-gating, location restrictions"
        },
        "financial_services": {
            "description": "Financial products, crypto, loans",
            "requires": "Proper disclaimers, licensing info"
        },
        "health_wellness": {
            "description": "Health claims, supplements, weight loss",
            "requires": "No before/after, no miracle claims"
        },
        "gambling": {
            "description": "Gambling, betting, casinos",
            "requires": "Licensing, age restrictions, location limits"
        },
        "dating": {
            "description": "Dating services",
            "requires": "No explicit content, age restrictions"
        }
    }

    # AI-Generated Content Rules
    AI_CONTENT_RULES = {
        "faces_people": {
            "rule": "AI-generated realistic faces may require disclosure",
            "recommendation": "Use product-focused imagery instead of AI people",
            "keywords": ["person", "people", "man", "woman", "face", "portrait",
                        "human", "model", "customer", "user"]
        },
        "celebrities": {
            "rule": "Cannot use celebrity likeness without permission",
            "keywords": ["celebrity", "famous", "star", "actor", "singer", "politician"]
        },
        "brands": {
            "rule": "Cannot use other brand logos/trademarks",
            "keywords": ["logo", "trademark", "brand name", "competitor"]
        }
    }

    def __init__(self):
        """Initialize the compliance agent with Claude Haiku."""
        # Use Claude Haiku for compliance - great at context, cheap
        self.model = "anthropic/claude-3-haiku" if OPENROUTER_AVAILABLE else "claude-3-haiku-20240307"

        self.llm = ChatOpenRouter(
            model=self.model,
            temperature=0.1  # Low temperature for consistent rule application
        )

        logger.info(f"[ComplianceAgent] Initialized with model: {self.model}")

    def quick_keyword_check(self, prompt: str) -> Dict[str, Any]:
        """
        Fast initial check using word-boundary regex matching.
        Uses \\b word boundaries to avoid false positives (e.g., "arm" in "charm").

        Returns:
            Dict with preliminary compliance status and risk score
        """
        prompt_lower = prompt.lower()
        issues = []
        blocked_words = []
        suggestions = []

        # Check prohibited content categories with word boundaries
        for category, data in self.META_PROHIBITED_CONTENT.items():
            for example in data["examples"]:
                # Use word boundary regex to avoid false positives
                pattern = r'\b' + re.escape(example) + r'\b'
                if re.search(pattern, prompt_lower):
                    issues.append(f"[{category}] Contains: '{example}'")
                    blocked_words.append(example)

                    # Find safe alternative if available
                    for unsafe, safe in data.get("safe_alternatives", {}).items():
                        if re.search(r'\b' + re.escape(unsafe) + r'\b', prompt_lower):
                            suggestions.append(f"Replace '{unsafe}' with '{safe}'")

        # Check AI content rules with word boundaries
        has_people = False
        for rule_name, rule_data in self.AI_CONTENT_RULES.items():
            for keyword in rule_data["keywords"]:
                if re.search(r'\b' + re.escape(keyword) + r'\b', prompt_lower):
                    if rule_name == "faces_people":
                        has_people = True
                        suggestions.append(rule_data["recommendation"])
                    else:
                        issues.append(f"[{rule_name}] Contains: '{keyword}' - {rule_data['rule']}")

        # Check restricted content (warning, not blocking)
        warnings = []
        for category, data in self.META_RESTRICTED_CONTENT.items():
            if re.search(r'\b' + re.escape(category) + r'\b', prompt_lower):
                warnings.append(f"[{category}] {data['description']} - {data['requires']}")

        # Calculate risk score (0-100)
        risk_score = min(len(issues) * 25 + len(warnings) * 10, 100)

        return {
            "passed_quick_check": len(issues) == 0,
            "issues": issues,
            "blocked_words": blocked_words,
            "suggestions": list(set(suggestions)),
            "warnings": warnings,
            "has_people_reference": has_people,
            "needs_ai_review": len(issues) > 0 or has_people,
            "risk_score": risk_score
        }

    async def deep_compliance_check(self, prompt: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Deep compliance check using Claude Haiku.
        Understands context and nuance beyond simple keywords.

        Args:
            prompt: The image generation prompt to check
            context: Optional context (industry, product type, target audience)

        Returns:
            Comprehensive compliance analysis
        """
        context_str = ""
        if context:
            context_str = f"""
CONTEXT:
- Industry: {context.get('industry', 'Unknown')}
- Product/Service: {context.get('product', 'Unknown')}
- Target Audience: {context.get('audience', 'General')}
- Ad Platform: Meta (Facebook/Instagram)
"""

        system_prompt = f"""You are a Meta Advertising Policy Compliance Expert.
Analyze the image generation prompt for Meta (Facebook/Instagram) ad policy violations.

{context_str}

META PROHIBITED CONTENT:
1. Weapons, violence, blood, gore
2. Adult/sexual content, nudity
3. Discriminatory content, hate speech
4. Illegal drugs, tobacco
5. Misleading claims, fake news
6. Political/controversial content

META RESTRICTED CONTENT (needs extra care):
- Alcohol (age-gating required)
- Financial services (disclaimers needed)
- Health/wellness (no miracle claims)
- Gambling (licensing required)

AI-GENERATED CONTENT RULES:
- AI-generated realistic faces may need disclosure
- Cannot use celebrity likeness
- Cannot use competitor brand logos
- Recommend product-focused over people-focused

IMPORTANT CONTEXT:
- "Security company" does NOT mean weapons are allowed
- "Protection services" should show technology, not armed people
- Focus on professional, trustworthy imagery

Respond with JSON only:
{{
    "is_compliant": true/false,
    "risk_level": "low/medium/high/critical",
    "risk_score": 0-100,
    "issues": [
        {{"category": "category_name", "description": "what's wrong", "severity": "low/medium/high"}}
    ],
    "suggestions": ["list of specific suggestions to fix issues"],
    "safe_prompt": "rewritten prompt that is compliant (if original is not). Make it context-aware and grammatically correct.",
    "reasoning": "brief explanation of your analysis"
}}"""

        from langchain_core.messages import SystemMessage, HumanMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Check this ad image prompt for compliance:\n\n{prompt}")
        ]

        try:
            from modules.openrouter.context import set_ai_context
            json_llm = self.llm.bind(response_format={"type": "json_object"})

            from langchain_core.output_parsers import StrOutputParser
            chain_messages = [messages[0], messages[1]]

            with set_ai_context(agent_name="compliance"):
                response = await json_llm.ainvoke(chain_messages)
            response_text = response.content.strip()

            # Clean JSON if wrapped in markdown
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]

            # Try Pydantic validation first
            try:
                validated = ComplianceCheckOutput.model_validate_json(response_text.strip())
                result = validated.model_dump()
            except Exception:
                # Fallback to plain JSON parse
                result = json.loads(response_text.strip())
                # Ensure required fields
                result.setdefault("is_compliant", False)
                result.setdefault("risk_level", "medium")
                result.setdefault("risk_score", 50)
                result.setdefault("issues", [])
                result.setdefault("suggestions", [])
                result.setdefault("safe_prompt", None)
                result.setdefault("reasoning", "")

            result["model_used"] = self.model
            result["check_type"] = "deep_ai_analysis"

            # Log to AI Decision Trail
            self._log_compliance_check(prompt, context, result)

            return result

        except json.JSONDecodeError as e:
            logger.error(f"[ComplianceAgent] Failed to parse AI response: {e}")
            result = {
                "is_compliant": False,
                "risk_level": "medium",
                "risk_score": 50,
                "issues": [{"category": "parse_error", "description": "Could not parse AI response", "severity": "medium"}],
                "suggestions": ["Manual review recommended"],
                "safe_prompt": None,
                "reasoning": "AI response could not be parsed",
                "model_used": self.model,
                "check_type": "deep_ai_analysis",
                "error": str(e)
            }
            self._log_compliance_check(prompt, context, result)
            return result
        except Exception as e:
            logger.error(f"[ComplianceAgent] AI check failed: {e}")
            result = {
                "is_compliant": False,
                "risk_level": "unknown",
                "risk_score": 75,
                "issues": [{"category": "error", "description": str(e), "severity": "high"}],
                "suggestions": ["Manual review required"],
                "safe_prompt": None,
                "reasoning": f"AI check failed: {str(e)}",
                "model_used": self.model,
                "check_type": "deep_ai_analysis",
                "error": str(e)
            }
            self._log_compliance_check(prompt, context, result)
            return result

    async def check_compliance(
        self,
        prompt: str,
        context: Optional[Dict] = None,
        deep_check: bool = True
    ) -> Dict[str, Any]:
        """
        Tiered compliance check — skips deep check when quick check passes cleanly.

        Tiers:
        1. Quick keyword check (free, instant) → if clean with no people refs, auto-approve
        2. If borderline or has people refs → deep AI check
        3. If critical (3+ blocked words) → block immediately, skip deep check

        Args:
            prompt: The image generation prompt
            context: Optional context about the ad
            deep_check: Whether to run AI analysis (costs ~$0.0003)

        Returns:
            Complete compliance report with risk_score (0-100)
        """
        # Step 1: Quick keyword check (free, instant)
        quick_result = self.quick_keyword_check(prompt)

        # Tier 3: Critical issues → block immediately, no deep check needed
        if len(quick_result["blocked_words"]) > 3:
            result = {
                "is_compliant": False,
                "risk_level": "critical",
                "risk_score": 95,
                "quick_check": quick_result,
                "deep_check": None,
                "final_verdict": "BLOCKED - Multiple policy violations detected",
                "suggestions": quick_result["suggestions"],
                "safe_prompt": None,
                "original_prompt": prompt,
                "deep_check_skipped": True,
                "skip_reason": "critical_violation"
            }
            self._log_compliance_check(prompt, context, result)
            return result

        # Tier 1: Clean quick check with no people refs → auto-approve, skip deep check
        if quick_result["passed_quick_check"] and not quick_result["has_people_reference"]:
            result = {
                "is_compliant": True,
                "risk_level": "low",
                "risk_score": quick_result.get("risk_score", 0),
                "quick_check": quick_result,
                "deep_check": None,
                "final_verdict": "APPROVED - Prompt is Meta compliant",
                "suggestions": quick_result.get("suggestions", []),
                "safe_prompt": None,
                "original_prompt": prompt,
                "deep_check_skipped": True,
                "skip_reason": "clean_quick_check"
            }
            self._log_compliance_check(prompt, context, result)
            return result

        # Tier 2: Borderline or has people refs → deep AI check
        deep_result = None
        if deep_check:
            deep_result = await self.deep_compliance_check(prompt, context)

        # Combine results
        if deep_result:
            is_compliant = deep_result.get("is_compliant", False)
            risk_level = deep_result.get("risk_level", "medium")
            risk_score = deep_result.get("risk_score", 50)
            safe_prompt = deep_result.get("safe_prompt")
        else:
            is_compliant = quick_result["passed_quick_check"] and not quick_result["has_people_reference"]
            risk_level = "low" if is_compliant else "medium"
            risk_score = quick_result.get("risk_score", 50)
            safe_prompt = None

        # Determine final verdict
        if is_compliant:
            verdict = "APPROVED - Prompt is Meta compliant"
        elif risk_level == "critical":
            verdict = "BLOCKED - Critical policy violations"
        elif risk_level == "high":
            verdict = "REJECTED - High risk content detected"
        else:
            verdict = "NEEDS_REVIEW - Some concerns found"

        return {
            "is_compliant": is_compliant,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "quick_check": quick_result,
            "deep_check": deep_result,
            "final_verdict": verdict,
            "suggestions": (quick_result.get("suggestions", []) +
                          (deep_result.get("suggestions", []) if deep_result else [])),
            "safe_prompt": safe_prompt,
            "original_prompt": prompt,
            "deep_check_skipped": False
        }

    def _log_compliance_check(self, prompt: str, context: Optional[Dict], result: Dict) -> None:
        """Persist compliance check to AI Decision Log for audit trail."""
        try:
            from .meta_learner import log_ai_decision
            log_ai_decision(
                decision_type="compliance_check",
                agent_name="compliance",
                input_context={
                    "prompt_preview": prompt[:200],
                    "industry": context.get("industry") if context else None,
                    "product": context.get("product") if context else None,
                },
                decision={
                    "is_compliant": result.get("is_compliant"),
                    "risk_level": result.get("risk_level"),
                    "risk_score": result.get("risk_score"),
                    "issues_count": len(result.get("issues", [])),
                    "has_safe_prompt": bool(result.get("safe_prompt")),
                },
                reasoning=result.get("reasoning", ""),
                confidence=1.0 - (result.get("risk_score", 50) / 100),
                model_used=result.get("model_used")
            )
        except Exception as e:
            logger.warning(f"[ComplianceAgent] Failed to log compliance check: {e}")

    def clean_prompt(self, prompt: str, deep_check_result: Optional[Dict] = None) -> str:
        """
        Clean a prompt by replacing unsafe terms with safe alternatives.

        Uses the LLM's safe_prompt from deep check if available (context-aware),
        falls back to word-boundary regex replacement.

        Args:
            prompt: The original prompt
            deep_check_result: Optional result from deep_compliance_check containing safe_prompt

        Returns:
            Cleaned prompt with safe alternatives
        """
        # Prefer the LLM's context-aware safe_prompt if available
        if deep_check_result and deep_check_result.get("safe_prompt"):
            logger.info("[ComplianceAgent] Using LLM-generated safe prompt (context-aware)")
            return deep_check_result["safe_prompt"]

        # Fallback: word-boundary regex replacement
        cleaned = prompt

        for category, data in self.META_PROHIBITED_CONTENT.items():
            for unsafe, safe in data.get("safe_alternatives", {}).items():
                # Use word boundaries and case-insensitive matching
                pattern = re.compile(r'\b' + re.escape(unsafe) + r'\b', re.IGNORECASE)
                if pattern.search(cleaned):
                    cleaned = pattern.sub(safe, cleaned)
                    logger.info(f"[ComplianceAgent] Replaced '{unsafe}' with '{safe}'")

        # Verify the cleaned prompt doesn't still have issues
        quick_check = self.quick_keyword_check(cleaned)
        if not quick_check["passed_quick_check"]:
            logger.warning(f"[ComplianceAgent] Cleaned prompt still has {len(quick_check['issues'])} issues")

        return cleaned

    def get_industry_guidelines(self, industry: str) -> Dict[str, Any]:
        """
        Get specific compliance guidelines for an industry.

        Args:
            industry: Industry type (security, food, retail, etc.)

        Returns:
            Industry-specific dos and don'ts
        """
        guidelines = {
            "security": {
                "do": [
                    "Show modern technology and monitoring systems",
                    "Use abstract shield/lock icons",
                    "Display professional buildings and environments",
                    "Emphasize trust, reliability, peace of mind",
                    "Use blue, dark grey, white color schemes"
                ],
                "dont": [
                    "Show weapons of any kind",
                    "Show armed personnel",
                    "Use military imagery",
                    "Show violence or threatening scenarios",
                    "Generate AI faces of security guards"
                ],
                "safe_imagery": [
                    "Security cameras (mounted, not handheld)",
                    "Access control panels",
                    "Monitoring dashboards",
                    "Modern office buildings",
                    "Smart home devices",
                    "Abstract protection icons"
                ]
            },
            "food": {
                "do": [
                    "Show appetizing, well-lit food",
                    "Use warm, inviting colors",
                    "Display fresh ingredients",
                    "Show clean, professional kitchen/restaurant settings"
                ],
                "dont": [
                    "Make health claims without evidence",
                    "Show raw meat in unsafe conditions",
                    "Use before/after weight loss imagery"
                ],
                "safe_imagery": [
                    "Plated dishes",
                    "Fresh ingredients",
                    "Restaurant interiors",
                    "Kitchen equipment",
                    "Table settings"
                ]
            },
            "health_fitness": {
                "do": [
                    "Show equipment and facilities",
                    "Use energetic, motivating imagery",
                    "Display healthy lifestyle elements"
                ],
                "dont": [
                    "Show before/after body transformations",
                    "Make miracle cure claims",
                    "Promise specific weight loss results",
                    "Show unrealistic body standards"
                ],
                "safe_imagery": [
                    "Gym equipment",
                    "Yoga mats and props",
                    "Healthy food",
                    "Fitness facilities",
                    "Workout gear"
                ]
            },
            "beauty": {
                "do": [
                    "Show products clearly",
                    "Use soft, flattering lighting",
                    "Display ingredients and textures"
                ],
                "dont": [
                    "Make anti-aging miracle claims",
                    "Show before/after transformations",
                    "Promise unrealistic results"
                ],
                "safe_imagery": [
                    "Product bottles and packaging",
                    "Ingredients and botanicals",
                    "Spa settings",
                    "Textures and swatches"
                ]
            },
            "default": {
                "do": [
                    "Focus on products, not people",
                    "Use professional, clean imagery",
                    "Keep messaging honest and clear"
                ],
                "dont": [
                    "Use AI-generated faces without disclosure",
                    "Make false or exaggerated claims",
                    "Include any prohibited content"
                ],
                "safe_imagery": [
                    "Product shots",
                    "Abstract graphics",
                    "Professional environments",
                    "Lifestyle settings without people"
                ]
            }
        }

        return guidelines.get(industry.lower(), guidelines["default"])


# Convenience functions for direct use
async def check_ad_compliance(
    prompt: str,
    industry: Optional[str] = None,
    deep_check: bool = True
) -> Dict[str, Any]:
    """
    Quick function to check ad compliance.

    Args:
        prompt: Image generation prompt
        industry: Optional industry for context
        deep_check: Whether to use AI analysis

    Returns:
        Compliance report
    """
    agent = ComplianceAgent()
    context = {"industry": industry} if industry else None
    return await agent.check_compliance(prompt, context, deep_check)


def quick_compliance_check(prompt: str) -> Dict[str, Any]:
    """
    Synchronous quick check (keyword only, no AI).
    Free and instant.
    """
    agent = ComplianceAgent()
    return agent.quick_keyword_check(prompt)


def get_safe_prompt(prompt: str) -> str:
    """
    Clean a prompt by replacing unsafe terms.
    """
    agent = ComplianceAgent()
    return agent.clean_prompt(prompt)


# ==================== FEEDBACK LOOP FUNCTIONS ====================

async def compliance_feedback_loop(
    prompt: str,
    industry: str,
    visual_director_callback,
    max_iterations: int = 3
) -> Dict[str, Any]:
    """
    Feedback loop that keeps regenerating prompts until compliant.

    This implements FEEDBACK LOOP #1 in the architecture:
    1. Check compliance
    2. If not compliant, get safe_prompt and suggestions
    3. Call visual_director to regenerate with suggestions
    4. Re-check compliance
    5. Repeat until compliant or max iterations reached

    Args:
        prompt: Original image generation prompt
        industry: Industry type for context
        visual_director_callback: Async function to regenerate prompt
                                  Signature: async def callback(original, suggestions, safe_prompt) -> str
        max_iterations: Maximum number of regeneration attempts

    Returns:
        Dict with final_prompt, is_compliant, iterations, history
    """
    agent = ComplianceAgent()
    context = {"industry": industry}
    history = []
    current_prompt = prompt
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        logger.info(f"[ComplianceFeedbackLoop] Iteration {iteration}/{max_iterations}")

        # Check compliance
        result = await agent.check_compliance(current_prompt, context, deep_check=True)

        history.append({
            "iteration": iteration,
            "prompt": current_prompt,
            "is_compliant": result["is_compliant"],
            "risk_level": result.get("risk_level"),
            "issues": result.get("quick_check", {}).get("issues", [])
        })

        if result["is_compliant"]:
            logger.info(f"[ComplianceFeedbackLoop] Prompt compliant after {iteration} iteration(s)")
            return {
                "final_prompt": current_prompt,
                "is_compliant": True,
                "iterations": iteration,
                "history": history,
                "original_prompt": prompt
            }

        # Not compliant - need to regenerate
        if iteration >= max_iterations:
            break

        # Get safe prompt and suggestions
        safe_prompt = result.get("safe_prompt")
        suggestions = result.get("suggestions", [])

        logger.info(f"[ComplianceFeedbackLoop] Regenerating with {len(suggestions)} suggestions")

        # Call visual director to regenerate
        try:
            current_prompt = await visual_director_callback(
                original_prompt=current_prompt,
                suggestions=suggestions,
                safe_prompt=safe_prompt
            )
        except Exception as e:
            logger.error(f"[ComplianceFeedbackLoop] Regeneration failed: {e}")
            # Use safe_prompt as fallback
            if safe_prompt:
                current_prompt = safe_prompt
            else:
                break

    # Max iterations reached without compliance
    logger.warning(f"[ComplianceFeedbackLoop] Max iterations reached, using best available prompt")

    # Use the safe_prompt from last check if available
    final_safe = result.get("safe_prompt") if result else None

    return {
        "final_prompt": final_safe or current_prompt,
        "is_compliant": False,
        "iterations": iteration,
        "history": history,
        "original_prompt": prompt,
        "warning": "Max iterations reached - manual review recommended"
    }


async def optimizer_feedback_loop(
    ad_id: str,
    performance_data: Dict[str, Any],
    creative_strategist_callback,
    ad_copy_callback,
    visual_director_callback
) -> Dict[str, Any]:
    """
    Feedback loop for optimizing underperforming ads.

    This implements FEEDBACK LOOP #2 in the architecture:
    1. Analyze performance data
    2. Determine what needs to change (angle, copy, visual)
    3. Call appropriate agent to regenerate
    4. Return new creative for testing

    Args:
        ad_id: ID of the underperforming ad
        performance_data: Dict with CTR, CPA, ROAS, etc.
        creative_strategist_callback: Async function to generate new angles
        ad_copy_callback: Async function to regenerate copy
        visual_director_callback: Async function to regenerate visuals

    Returns:
        Dict with recommendation, new_creative, action_taken
    """
    # Analyze what's wrong
    ctr = performance_data.get("ctr", 0)
    cpa = performance_data.get("cpa", float("inf"))
    roas = performance_data.get("roas", 0)

    # Determine the issue
    if ctr < 0.5:  # Low click-through rate
        issue = "low_engagement"
        recommendation = "new_creative"
    elif cpa > performance_data.get("target_cpa", 50) * 1.5:
        issue = "high_cost"
        recommendation = "new_angle"
    elif roas < 1.0:
        issue = "low_return"
        recommendation = "adjust_copy"
    else:
        issue = "general_underperformance"
        recommendation = "new_angle"

    logger.info(f"[OptimizerFeedbackLoop] Ad {ad_id} issue: {issue}, recommendation: {recommendation}")

    result = {
        "ad_id": ad_id,
        "issue": issue,
        "recommendation": recommendation,
        "performance_data": performance_data,
        "new_creative": None,
        "action_taken": None
    }

    try:
        if recommendation == "new_angle":
            # Generate completely new creative angle
            new_angles = await creative_strategist_callback(
                exclude_current=True,
                performance_insights={
                    "issue": issue,
                    "avoid": "similar approaches to current ad"
                }
            )
            result["new_creative"] = new_angles
            result["action_taken"] = "Generated new creative angles"

        elif recommendation == "new_creative":
            # New visual direction
            new_visual = await visual_director_callback(
                style_change=True,
                insights={"issue": issue, "current_ctr": ctr}
            )
            result["new_creative"] = new_visual
            result["action_taken"] = "Generated new visual direction"

        elif recommendation == "adjust_copy":
            # Regenerate copy with different approach
            new_copy = await ad_copy_callback(
                variation=True,
                insights={"issue": issue, "current_roas": roas}
            )
            result["new_creative"] = new_copy
            result["action_taken"] = "Generated new ad copy variations"

    except Exception as e:
        logger.error(f"[OptimizerFeedbackLoop] Failed to generate new creative: {e}")
        result["error"] = str(e)

    return result
