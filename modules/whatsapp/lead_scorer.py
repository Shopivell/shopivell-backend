"""
Enhanced Lead Scoring Service for AI Sales Bot

Provides intelligent lead scoring based on:
- Conversation engagement signals
- Industry-specific buying indicators
- Intent detection
- Customer behavior patterns
"""

import logging
import re
import json
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field

from openai import OpenAI
import os

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class LeadStatus(str, Enum):
    """Lead status based on score"""
    COLD = "cold"           # 0-20: Just browsing
    COOL = "cool"           # 21-40: General questions
    WARM = "warm"           # 41-60: Interest in specific items
    HOT = "hot"             # 61-80: Serious interest, comparing
    VERY_HOT = "very_hot"   # 81-100: Ready to buy (HOT LEAD)


# --- Structured output models ---

class AIScoreOutput(BaseModel):
    """Structured AI scoring response"""
    ai_score: float = Field(..., ge=0, le=100, description="AI-assessed lead score 0-100")
    confidence: float = Field(..., ge=0, le=1, description="Confidence in assessment")
    reasoning: str = Field(..., description="Brief explanation")
    buying_intent: str = Field(default="low", description="low/medium/high/very_high")
    urgency: str = Field(default="none", description="none/low/medium/high")
    suggested_response_tone: str = Field(default="helpful", description="helpful/persuasive/urgent/closing")


class LeadScoreResult(BaseModel):
    """Complete lead scoring result"""
    score: float = Field(..., ge=0, le=100)
    status: str
    interests: List[str] = Field(default_factory=list)
    engagement_level: str = "low"
    primary_intent: Optional[str] = None
    objections: List[str] = Field(default_factory=list)
    recommended_action: str = ""
    signals: List[Dict[str, Any]] = Field(default_factory=list)
    score_change: float = 0.0
    is_hot_lead: bool = False
    message_count: int = 0
    scoring_method: str = "rule_based"
    ai_analysis: Optional[Dict[str, Any]] = None


@dataclass
class ScoringSignal:
    """Represents a scoring signal with weight"""
    pattern: str
    weight: int
    category: str
    description: str


class EnhancedLeadScorer:
    """
    Enhanced lead scoring with industry-specific criteria.

    Score Ranges:
    - 0-20: Cold (Just browsing)
    - 21-40: Cool (General questions)
    - 41-60: Warm (Interest in specific items)
    - 61-80: Hot (Serious interest, comparing)
    - 81-100: Very Hot (Ready to buy - HOT LEAD)
    """

    # Universal positive signals
    POSITIVE_SIGNALS = [
        ScoringSignal(r"\b(price|pricing|cost|how much|quote)\b", 15, "pricing", "Asked about pricing"),
        ScoringSignal(r"\b(buy|purchase|order|get|want)\b", 20, "intent", "Expressed buying intent"),
        ScoringSignal(r"\b(available|in stock|have|do you have)\b", 10, "availability", "Asked about availability"),
        ScoringSignal(r"\b(today|tomorrow|this week|soon|urgent|asap)\b", 15, "timeline", "Mentioned timeline"),
        ScoringSignal(r"\b(delivery|shipping|ship|deliver)\b", 10, "logistics", "Asked about delivery"),
        ScoringSignal(r"\b(payment|pay|card|cash|transfer)\b", 15, "payment", "Asked about payment"),
        ScoringSignal(r"\b(compare|vs|versus|difference|better)\b", 12, "comparison", "Comparing options"),
        ScoringSignal(r"\b(discount|deal|offer|promotion|sale)\b", 10, "deals", "Asked about discounts"),
        ScoringSignal(r"\b(warranty|guarantee|return|refund)\b", 8, "trust", "Asked about guarantees"),
        ScoringSignal(r"\b(schedule|appointment|book|reserve)\b", 18, "scheduling", "Wants to schedule"),
        ScoringSignal(r"\b(callback|call me|contact me|reach me)\b", 20, "contact", "Requested callback"),
        ScoringSignal(r"\b(bulk|wholesale|large order|multiple)\b", 15, "volume", "Bulk order interest"),
        ScoringSignal(r"\b(recommend|suggest|which one|best)\b", 8, "guidance", "Seeking recommendation"),
        ScoringSignal(r"\b(invoice|receipt|documentation)\b", 12, "business", "Business customer signals"),
    ]

    # Universal negative signals
    NEGATIVE_SIGNALS = [
        ScoringSignal(r"\b(just looking|browsing|curious)\b", -15, "intent", "Just browsing"),
        ScoringSignal(r"\b(too expensive|can't afford|budget)\b", -10, "objection", "Price objection"),
        ScoringSignal(r"\b(not interested|no thanks|maybe later)\b", -20, "rejection", "Not interested"),
        ScoringSignal(r"\b(competitor|other company|elsewhere)\b", -5, "competition", "Mentioned competitor"),
        ScoringSignal(r"\b(spam|stop|unsubscribe)\b", -25, "rejection", "Opt-out request"),
    ]

    # Industry-specific signals
    INDUSTRY_SIGNALS = {
        "security": [
            ScoringSignal(r"\b(site survey|assessment|audit)\b", 18, "interest", "Site survey request"),
            ScoringSignal(r"\b(install|installation|setup)\b", 15, "service", "Installation interest"),
            ScoringSignal(r"\b(cctv|camera|surveillance|alarm)\b", 12, "product", "Security product interest"),
            ScoringSignal(r"\b(monitoring|24.7|patrol)\b", 10, "service", "Monitoring interest"),
            ScoringSignal(r"\b(break-in|theft|crime|robbery)\b", 15, "urgency", "Security concern"),
            ScoringSignal(r"\b(quote|proposal|estimate)\b", 18, "intent", "Quote request"),
        ],
        "ecommerce": [
            ScoringSignal(r"\b(add to cart|cart|basket)\b", 20, "intent", "Cart activity"),
            ScoringSignal(r"\b(checkout|pay now|complete order)\b", 25, "intent", "Checkout intent"),
            ScoringSignal(r"\b(track|tracking|where is|status)\b", 5, "support", "Order tracking"),
            ScoringSignal(r"\b(size|color|variant|option)\b", 10, "product", "Product details"),
            ScoringSignal(r"\b(gift|present|occasion)\b", 12, "occasion", "Gift purchase"),
        ],
        "services": [
            ScoringSignal(r"\b(consultation|consult|meet|meeting)\b", 18, "scheduling", "Consultation request"),
            ScoringSignal(r"\b(quote|estimate|proposal)\b", 18, "intent", "Quote request"),
            ScoringSignal(r"\b(project|work|job|task)\b", 10, "interest", "Project discussion"),
            ScoringSignal(r"\b(contract|agreement|terms)\b", 15, "business", "Contract discussion"),
            ScoringSignal(r"\b(portfolio|examples|previous work)\b", 8, "research", "Research phase"),
        ],
        "restaurant": [
            ScoringSignal(r"\b(table|reservation|book|reserve)\b", 20, "booking", "Reservation request"),
            ScoringSignal(r"\b(menu|special|dish|food)\b", 10, "menu", "Menu inquiry"),
            ScoringSignal(r"\b(party|event|celebration|group)\b", 15, "event", "Event booking"),
            ScoringSignal(r"\b(takeaway|delivery|order food)\b", 18, "order", "Food order"),
            ScoringSignal(r"\b(allergy|dietary|vegetarian|vegan)\b", 8, "dietary", "Dietary needs"),
        ],
        "real_estate": [
            ScoringSignal(r"\b(view|viewing|visit|tour)\b", 20, "viewing", "Property viewing request"),
            ScoringSignal(r"\b(mortgage|finance|loan|afford)\b", 15, "finance", "Financing discussion"),
            ScoringSignal(r"\b(bedrooms?|bathrooms?|sqft|size)\b", 10, "property", "Property details"),
            ScoringSignal(r"\b(neighborhood|area|location|schools)\b", 8, "research", "Location research"),
            ScoringSignal(r"\b(offer|bid|negotiate)\b", 25, "intent", "Making an offer"),
        ],
    }

    def __init__(self, store_type: str = "general"):
        """
        Initialize the lead scorer with store type for industry-specific signals.

        Args:
            store_type: Type of store (security, ecommerce, services, restaurant, real_estate, general)
        """
        self.store_type = store_type.lower()
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns for performance"""
        self._compiled_positive = [
            (re.compile(s.pattern, re.IGNORECASE), s)
            for s in self.POSITIVE_SIGNALS
        ]
        self._compiled_negative = [
            (re.compile(s.pattern, re.IGNORECASE), s)
            for s in self.NEGATIVE_SIGNALS
        ]

        # Add industry-specific signals
        industry_signals = self.INDUSTRY_SIGNALS.get(self.store_type, [])
        self._compiled_industry = [
            (re.compile(s.pattern, re.IGNORECASE), s)
            for s in industry_signals
        ]

    def _detect_signals(self, text: str) -> Tuple[List[Dict], int]:
        """
        Detect scoring signals in text.

        Returns:
            Tuple of (list of detected signals, total score adjustment)
        """
        detected = []
        score_adjustment = 0

        # Check positive signals
        for pattern, signal in self._compiled_positive:
            if pattern.search(text):
                detected.append({
                    "category": signal.category,
                    "description": signal.description,
                    "weight": signal.weight,
                    "type": "positive"
                })
                score_adjustment += signal.weight

        # Check negative signals
        for pattern, signal in self._compiled_negative:
            if pattern.search(text):
                detected.append({
                    "category": signal.category,
                    "description": signal.description,
                    "weight": signal.weight,
                    "type": "negative"
                })
                score_adjustment += signal.weight

        # Check industry-specific signals
        for pattern, signal in self._compiled_industry:
            if pattern.search(text):
                detected.append({
                    "category": signal.category,
                    "description": signal.description,
                    "weight": signal.weight,
                    "type": "industry"
                })
                score_adjustment += signal.weight

        return detected, score_adjustment

    def _get_status_from_score(self, score: float) -> LeadStatus:
        """Determine lead status from score"""
        if score <= 20:
            return LeadStatus.COLD
        elif score <= 40:
            return LeadStatus.COOL
        elif score <= 60:
            return LeadStatus.WARM
        elif score <= 80:
            return LeadStatus.HOT
        else:
            return LeadStatus.VERY_HOT

    def _analyze_conversation_context(
        self,
        conversation_history: List[Dict[str, str]],
        last_message: str
    ) -> Dict[str, Any]:
        """
        Analyze conversation context for additional scoring factors.
        """
        context = {
            "message_count": len(conversation_history),
            "user_message_count": sum(1 for m in conversation_history if m.get("role") == "user"),
            "avg_message_length": 0,
            "has_quick_responses": False,
            "engagement_level": "low"
        }

        # Calculate average message length (longer = more engaged)
        user_messages = [m.get("content", "") for m in conversation_history if m.get("role") == "user"]
        if user_messages:
            context["avg_message_length"] = sum(len(m) for m in user_messages) / len(user_messages)

        # Determine engagement level
        if context["user_message_count"] >= 5:
            context["engagement_level"] = "high"
        elif context["user_message_count"] >= 3:
            context["engagement_level"] = "medium"

        return context

    def _extract_interests(self, conversation_history: List[Dict[str, str]]) -> List[str]:
        """Extract topics/interests from conversation"""
        interests = set()

        # Common interest patterns
        interest_patterns = [
            (r"\b(product|item|service):\s*([^\.,]+)", 2),
            (r"\babout\s+(the\s+)?(\w+(?:\s+\w+)?)\b", 2),
            (r"\binterested\s+in\s+(\w+(?:\s+\w+)?)\b", 1),
            (r"\blooking\s+for\s+(\w+(?:\s+\w+)?)\b", 1),
        ]

        for msg in conversation_history:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                for pattern, group in interest_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    for match in matches:
                        if isinstance(match, tuple):
                            interests.add(match[group - 1].strip().lower())
                        else:
                            interests.add(match.strip().lower())

        # Filter out common words
        stopwords = {"the", "a", "an", "it", "this", "that", "your", "my"}
        return [i for i in interests if i and i not in stopwords][:5]

    def _detect_objections(self, text: str) -> List[str]:
        """Detect objections in text"""
        objections = []

        objection_patterns = [
            (r"\b(too expensive|too costly|can't afford)\b", "Price objection"),
            (r"\b(not sure|uncertain|hesitant)\b", "Uncertainty"),
            (r"\b(need to think|consider|discuss)\b", "Needs consideration"),
            (r"\b(not now|later|another time)\b", "Timing objection"),
            (r"\b(already have|using another)\b", "Existing solution"),
        ]

        for pattern, objection in objection_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                objections.append(objection)

        return objections

    def _get_recommended_action(
        self,
        score: float,
        status: LeadStatus,
        signals: List[Dict],
        objections: List[str]
    ) -> str:
        """Get recommended action based on scoring analysis"""

        if status == LeadStatus.VERY_HOT:
            return "HOT LEAD: Prioritize immediate follow-up. Customer is ready to buy."

        if status == LeadStatus.HOT:
            if objections:
                return f"Address objections: {', '.join(objections)}. Close to conversion."
            return "High intent lead. Provide detailed quote or schedule call."

        if status == LeadStatus.WARM:
            # Check for specific interests
            interest_signals = [s for s in signals if s["category"] in ["pricing", "availability", "product"]]
            if interest_signals:
                return "Engaged lead. Share product details and promotions to move to next stage."
            return "Interested lead. Continue nurturing with relevant content."

        if status == LeadStatus.COOL:
            return "General inquiry. Provide helpful information and capture contact details."

        return "New lead. Build rapport and identify needs."

    def score_lead(
        self,
        conversation_history: List[Dict[str, str]],
        last_message: str,
        current_score: float = 0
    ) -> Dict[str, Any]:
        """
        Score a lead based on conversation history and last message.

        Args:
            conversation_history: List of messages with 'role' and 'content'
            last_message: The most recent message from the user
            current_score: The current lead score (0-100)

        Returns:
            Dict with:
                - score: Updated score (0-100)
                - status: Lead status (cold, cool, warm, hot, very_hot)
                - interests: Detected interests/topics
                - engagement_level: low, medium, high
                - primary_intent: Primary detected intent
                - objections: List of detected objections
                - recommended_action: Suggested next action
                - signals: List of detected scoring signals
                - score_change: Change from previous score
        """
        # Detect signals in last message
        signals, score_adjustment = self._detect_signals(last_message)

        # Also check recent conversation for context
        recent_messages = conversation_history[-5:] if len(conversation_history) > 5 else conversation_history
        for msg in recent_messages:
            if msg.get("role") == "user":
                _, msg_adjustment = self._detect_signals(msg.get("content", ""))
                score_adjustment += msg_adjustment * 0.3  # Weight historical messages less

        # Analyze conversation context
        context = self._analyze_conversation_context(conversation_history, last_message)

        # Engagement bonus
        engagement_bonus = 0
        if context["engagement_level"] == "high":
            engagement_bonus = 10
        elif context["engagement_level"] == "medium":
            engagement_bonus = 5

        # Message length bonus (shows engagement)
        if context["avg_message_length"] > 100:
            engagement_bonus += 5

        # Calculate new score
        new_score = current_score + score_adjustment + engagement_bonus

        # Clamp score to 0-100
        new_score = max(0, min(100, new_score))

        # Get status
        status = self._get_status_from_score(new_score)

        # Extract interests
        interests = self._extract_interests(conversation_history + [{"role": "user", "content": last_message}])

        # Detect objections
        objections = self._detect_objections(last_message)

        # Determine primary intent
        primary_intent = None
        if signals:
            # Get highest weighted signal
            intent_signals = [s for s in signals if s["type"] == "positive"]
            if intent_signals:
                primary_intent = max(intent_signals, key=lambda x: x["weight"])["category"]

        # Get recommended action
        recommended_action = self._get_recommended_action(new_score, status, signals, objections)

        result = LeadScoreResult(
            score=round(new_score, 1),
            status=status.value,
            interests=interests,
            engagement_level=context["engagement_level"],
            primary_intent=primary_intent,
            objections=objections,
            recommended_action=recommended_action,
            signals=signals,
            score_change=round(new_score - current_score, 1),
            is_hot_lead=status == LeadStatus.VERY_HOT,
            message_count=context["message_count"]
        )
        return result.model_dump()

    async def score_with_ai(
        self,
        conversation_history: List[Dict[str, str]],
        last_message: str,
        current_score: float,
        store_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Enhanced scoring using AI for complex conversations.
        Falls back to rule-based scoring if AI fails.
        """
        # First get rule-based score
        rule_based = self.score_lead(conversation_history, last_message, current_score)

        try:
            # Format conversation for AI
            conv_text = "\n".join([
                f"{msg['role'].upper()}: {msg['content']}"
                for msg in conversation_history[-10:]
            ])

            prompt = f"""Analyze this sales conversation and provide a lead score (0-100).

CONVERSATION:
{conv_text}

LATEST MESSAGE: {last_message}

CURRENT SCORE: {current_score}

RULE-BASED ANALYSIS:
- Score: {rule_based['score']}
- Signals detected: {rule_based['signals']}
- Objections: {rule_based['objections']}

Provide your assessment as JSON:
{{
    "ai_score": <0-100>,
    "confidence": <0-1>,
    "reasoning": "<brief explanation>",
    "buying_intent": "<low/medium/high/very_high>",
    "urgency": "<none/low/medium/high>",
    "suggested_response_tone": "<helpful/persuasive/urgent/closing>"
}}"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a lead scoring expert. Analyze conversations and assess buying intent. Return ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=300,
                response_format={"type": "json_object"}
            )

            response_text = response.choices[0].message.content.strip()

            # Validate with Pydantic first
            try:
                validated = AIScoreOutput.model_validate_json(response_text)
                ai_analysis = validated.model_dump()
            except Exception:
                # Fallback to plain JSON parse
                ai_analysis = json.loads(response_text)
                ai_analysis.setdefault("ai_score", rule_based["score"])
                ai_analysis.setdefault("confidence", 0.5)

            # Blend AI and rule-based scores (weighted by AI confidence)
            confidence = ai_analysis.get("confidence", 0.5)
            ai_weight = 0.4 * confidence  # Scale AI weight by confidence
            rule_weight = 1.0 - ai_weight
            blended_score = (rule_based["score"] * rule_weight) + (ai_analysis["ai_score"] * ai_weight)

            rule_based.update({
                "score": round(blended_score, 1),
                "ai_analysis": ai_analysis,
                "scoring_method": "hybrid"
            })

        except Exception as e:
            logger.warning(f"AI scoring failed, using rule-based only: {e}")
            rule_based["scoring_method"] = "rule_based"

        return rule_based


# Utility functions for external use
def get_lead_status_label(score: float) -> str:
    """Get human-readable label for lead score"""
    if score <= 20:
        return "Cold - Just Browsing"
    elif score <= 40:
        return "Cool - General Questions"
    elif score <= 60:
        return "Warm - Specific Interest"
    elif score <= 80:
        return "Hot - Serious Buyer"
    else:
        return "Very Hot - Ready to Buy!"


def should_notify_hot_lead(score: float, threshold: float = 80) -> bool:
    """Check if score triggers hot lead notification"""
    return score >= threshold
