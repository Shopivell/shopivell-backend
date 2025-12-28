"""
Multi-Tenant AI Sales Bot Engine

A RAG-based sales assistant that:
- Uses store-specific knowledge base (products, FAQs, policies)
- Follows strict NO HALLUCINATION policy
- Tracks conversations with memory
- Scores leads intelligently
- Triggers notifications for hot leads and handoffs
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy.orm import Session
from sqlalchemy import text
from openai import OpenAI

from database import SessionLocal
from .models import (
    StoreBotConfig, WhatsAppConversation, WhatsAppConversationMessage,
    WhatsAppLead, CompanyKnowledge
)
from .knowledge_service import KnowledgeService
from .lead_scorer import EnhancedLeadScorer, should_notify_hot_lead
from .crm_service import CRMService, TaskType, TaskPriority

load_dotenv()

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class MultiTenantSalesBot:
    """
    Multi-tenant AI Sales Bot with RAG-based knowledge retrieval.

    Critical Rules (NO HALLUCINATION POLICY):
    1. ONLY use information from the CONTEXT provided (Products + Store info)
    2. If context doesn't have the answer: DO NOT RESPOND
       - Stay silent (return None)
       - Create notification alert for store owner
       - Create CRM task for human follow-up
    3. NEVER invent product names, prices, features, or packages
    4. All knowledge MUST come from Products catalogue
    """

    def __init__(
        self,
        store_id: UUID,
        db: Session,
        config: Optional[StoreBotConfig] = None
    ):
        self.store_id = store_id
        self.db = db
        self.config = config or self._get_or_create_config()
        self.knowledge_service = KnowledgeService(store_id)
        self.crm_service = CRMService(store_id, db)
        self.lead_scorer = EnhancedLeadScorer(
            store_type=self._get_store_type()
        )

        # LLM settings from config
        self.temperature = self.config.temperature if self.config else 0.7
        self.max_tokens = int(self.config.max_response_tokens) if self.config else 500
        self.similarity_threshold = self.config.similarity_threshold if self.config else 0.4

    def _get_or_create_config(self) -> StoreBotConfig:
        """Get or create bot configuration for the store"""
        config = self.db.query(StoreBotConfig).filter(
            StoreBotConfig.store_id == self.store_id
        ).first()

        if not config:
            config = StoreBotConfig(store_id=self.store_id)
            self.db.add(config)
            self.db.commit()
            self.db.refresh(config)

        return config

    def _get_store_type(self) -> str:
        """Get store type for industry-specific scoring"""
        try:
            from modules.stores.models import Store
            store = self.db.query(Store).filter(Store.id == self.store_id).first()
            if store and hasattr(store, 'business_type'):
                return store.business_type or "general"
        except:
            pass
        return "general"

    def _get_store_info(self) -> Dict[str, Any]:
        """Get store information for context"""
        try:
            from modules.stores.models import Store
            store = self.db.query(Store).filter(Store.id == self.store_id).first()
            if store:
                return {
                    "name": getattr(store, 'name', 'Store'),
                    "business_type": getattr(store, 'business_type', 'general'),
                    "description": getattr(store, 'description', ''),
                    "phone": getattr(store, 'phone', ''),
                    "email": getattr(store, 'email', ''),
                    "address": getattr(store, 'address', ''),
                    "voice": getattr(store, 'store_voice', 'professional'),
                    "tone": getattr(store, 'store_tone', 'friendly')
                }
        except Exception as e:
            logger.warning(f"Could not get store info: {e}")

        return {
            "name": "Store",
            "business_type": "general",
            "description": "",
            "voice": "professional",
            "tone": "friendly"
        }

    def _build_system_prompt(self, store_info: Dict[str, Any]) -> str:
        """Build dynamic system prompt based on store configuration"""
        bot_name = self.config.bot_name if self.config else "Sales Assistant"
        personality = self.config.bot_personality if self.config and self.config.bot_personality else ""

        store_name = store_info.get("name", "Store")
        store_voice = store_info.get("voice", "professional")
        store_tone = store_info.get("tone", "friendly")

        prompt = f"""You are {bot_name}, a sales assistant for {store_name}.

PERSONALITY: {personality if personality else f"You are {store_tone} and {store_voice}."}

CRITICAL RULES - FOLLOW EXACTLY:
1. ONLY answer using the CONTEXT provided below
2. If the CONTEXT does not contain the answer: respond with exactly "NO_KNOWLEDGE_MATCH"
3. NEVER make up product names, prices, features, or any information
4. NEVER guess or approximate - if you don't have the exact info, say "NO_KNOWLEDGE_MATCH"
5. Be concise - keep responses under 3 sentences when possible
6. When discussing products/services, ONLY mention what's in the CONTEXT

RESPONSE STYLE:
- Be {store_tone} and {store_voice}
- Use conversational language suitable for WhatsApp
- Don't use markdown or special formatting
- Keep responses brief and to the point

If asked about pricing, availability, or any specific detail not in the CONTEXT:
- Respond with "NO_KNOWLEDGE_MATCH" (the system will handle this appropriately)

Remember: It's better to say you don't have the information than to make something up."""

        return prompt

    def _retrieve_context(self, query: str) -> Tuple[Optional[str], float, List[Dict]]:
        """
        Retrieve relevant context from knowledge base.
        Returns: (context_text, confidence_score, sources)
        """
        try:
            result = self.knowledge_service.get_context_for_query(
                db=self.db,
                query=query,
                config=self.config
            )

            if result["fallback_triggered"] or not result["context"]:
                return None, 0, []

            return result["context"], result["confidence"], result["sources"]

        except Exception as e:
            logger.error(f"Error retrieving context: {e}")
            return None, 0, []

    def _check_handoff_keywords(self, message: str) -> bool:
        """Check if message contains handoff trigger keywords"""
        if not self.config or not self.config.handoff_keywords:
            default_keywords = ["speak to human", "talk to someone", "customer service", "manager"]
            keywords = default_keywords
        else:
            keywords = self.config.handoff_keywords

        message_lower = message.lower()
        return any(keyword.lower() in message_lower for keyword in keywords)

    def _get_conversation_history(
        self,
        conversation: WhatsAppConversation,
        limit: int = 10
    ) -> List[Dict[str, str]]:
        """Get recent conversation history"""
        messages = self.db.query(WhatsAppConversationMessage).filter(
            WhatsAppConversationMessage.conversation_id == conversation.id
        ).order_by(
            WhatsAppConversationMessage.created_at.desc()
        ).limit(limit).all()

        return [
            {"role": msg.role, "content": msg.content}
            for msg in reversed(messages)
        ]

    async def generate_response(
        self,
        user_message: str,
        phone_number: str,
        whatsapp_account_id: Optional[UUID] = None
    ) -> Optional[str]:
        """
        Generate a response for a user message.

        Returns:
            - Response text if knowledge match found
            - None if no knowledge match (triggers silent + notification)
        """
        # Get or create conversation
        conversation = self.crm_service.get_or_create_conversation(phone_number)

        # Check for handoff keywords first
        if self._check_handoff_keywords(user_message):
            await self._handle_handoff(
                conversation=conversation,
                reason="Customer requested human assistance",
                query_text=user_message
            )
            return self.config.handoff_message if self.config else "A team member will be with you shortly."

        # Get conversation history
        history = self._get_conversation_history(conversation)

        # Save user message to history
        self.crm_service.add_conversation_message(
            conversation=conversation,
            role="user",
            content=user_message
        )

        # Retrieve context from knowledge base
        context, confidence, sources = self._retrieve_context(user_message)

        # Check if we have sufficient context
        if context is None or confidence < self.similarity_threshold:
            # NO HALLUCINATION POLICY: Stay silent and notify owner
            logger.info(f"No knowledge match for query from {phone_number}: {user_message[:100]}")

            await self._handle_no_knowledge(
                conversation=conversation,
                phone_number=phone_number,
                query_text=user_message
            )

            # Increment fallback count
            conversation.fallback_count += 1
            self.db.commit()

            # Check if too many fallbacks - trigger handoff
            max_fallbacks = int(self.config.max_fallbacks_before_handoff) if self.config else 3
            if conversation.fallback_count >= max_fallbacks:
                await self._handle_handoff(
                    conversation=conversation,
                    reason=f"Bot couldn't answer {conversation.fallback_count} queries in a row",
                    query_text=user_message
                )

            # Return None - bot stays silent
            return None

        # Build prompt with context
        store_info = self._get_store_info()
        system_prompt = self._build_system_prompt(store_info)

        # Build messages for LLM
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"CONTEXT:\n{context}"}
        ]

        # Add conversation history
        for msg in history[-6:]:  # Last 6 messages for context
            messages.append({"role": msg["role"], "content": msg["content"]})

        # Add current message
        messages.append({"role": "user", "content": user_message})

        try:
            # Generate response
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )

            bot_response = response.choices[0].message.content.strip()

            # Check if LLM indicated no knowledge match
            if "NO_KNOWLEDGE_MATCH" in bot_response.upper():
                logger.info(f"LLM indicated no knowledge match for: {user_message[:100]}")

                await self._handle_no_knowledge(
                    conversation=conversation,
                    phone_number=phone_number,
                    query_text=user_message
                )
                return None

            # Save bot response to history
            self.crm_service.add_conversation_message(
                conversation=conversation,
                role="assistant",
                content=bot_response,
                confidence_score=confidence,
                fallback_triggered=False
            )

            # Update lead score
            await self._update_lead_score(
                phone_number=phone_number,
                whatsapp_account_id=whatsapp_account_id,
                conversation=conversation,
                history=history,
                last_message=user_message
            )

            logger.info(f"Generated response for {phone_number} with confidence {confidence:.2f}")
            return bot_response

        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return None

    async def _handle_no_knowledge(
        self,
        conversation: WhatsAppConversation,
        phone_number: str,
        query_text: str
    ):
        """Handle case when bot has no knowledge to answer"""
        # Record fallback in message history
        self.crm_service.add_conversation_message(
            conversation=conversation,
            role="system",
            content=f"[NO_KNOWLEDGE_MATCH] Query: {query_text}",
            fallback_triggered=True,
            confidence_score=0
        )

        # Notify store owner
        await self.crm_service.notify_unanswered_query(
            phone_number=phone_number,
            query_text=query_text,
            conversation_id=conversation.id,
            config=self.config
        )

    async def _handle_handoff(
        self,
        conversation: WhatsAppConversation,
        reason: str,
        query_text: Optional[str] = None
    ):
        """Handle handoff to human agent"""
        # Update conversation status
        self.crm_service.request_handoff(conversation, reason)

        # Send notification
        await self.crm_service.notify_handoff(
            conversation=conversation,
            reason=reason,
            query_text=query_text,
            config=self.config
        )

    async def _update_lead_score(
        self,
        phone_number: str,
        whatsapp_account_id: Optional[UUID],
        conversation: WhatsAppConversation,
        history: List[Dict[str, str]],
        last_message: str
    ):
        """Update lead score based on conversation"""
        if not whatsapp_account_id:
            return

        # Get or create lead
        lead = self.crm_service.get_or_create_lead(phone_number, whatsapp_account_id)

        # Score the lead
        scoring_result = self.lead_scorer.score_lead(
            conversation_history=history,
            last_message=last_message,
            current_score=lead.lead_score or 0
        )

        # Update lead
        self.crm_service.update_lead_score(
            lead=lead,
            new_score=scoring_result["score"],
            scoring_reason=scoring_result.get("recommended_action")
        )

        # Update interests
        if scoring_result.get("interests"):
            self.crm_service.update_lead_interests(lead, scoring_result["interests"])

        # Check for hot lead
        hot_lead_threshold = self.config.hot_lead_threshold if self.config else 80
        if scoring_result["score"] >= hot_lead_threshold:
            await self.crm_service.notify_hot_lead(
                lead=lead,
                score=scoring_result["score"],
                config=self.config,
                conversation_id=conversation.id
            )

        logger.info(f"Updated lead score for {phone_number}: {scoring_result['score']}")

    def get_greeting_message(self) -> str:
        """Get the greeting message for new conversations"""
        if self.config and self.config.greeting_message:
            return self.config.greeting_message
        return "Hello! Welcome to our store. How can I help you today?"


# Backwards compatibility - simple wrapper for existing code
class SalesBot:
    """
    Legacy SalesBot wrapper for backwards compatibility.
    Use MultiTenantSalesBot for new implementations.
    """

    def __init__(self, store_id: UUID = None, max_tokens: int = 300):
        self.store_id = store_id
        self.max_tokens = max_tokens
        self._bot = None

    def _get_bot(self, db: Session) -> MultiTenantSalesBot:
        """Get or create bot instance"""
        if not self._bot:
            if not self.store_id:
                raise ValueError("store_id is required")
            self._bot = MultiTenantSalesBot(
                store_id=self.store_id,
                db=db
            )
        return self._bot

    async def generate_response(
        self,
        user_message: str,
        phone_number: str,
        db: Session
    ) -> Optional[str]:
        """Generate response using the multi-tenant bot"""
        bot = self._get_bot(db)
        return await bot.generate_response(user_message, phone_number)


# Lead scorer for backwards compatibility
class LeadScorer:
    """
    Legacy LeadScorer wrapper.
    Use EnhancedLeadScorer for new implementations.
    """

    def __init__(self, store_type: str = "general"):
        self.scorer = EnhancedLeadScorer(store_type)

    def score_lead(
        self,
        conversation_history: str,
        last_message: str,
        current_score: float = 0
    ) -> dict:
        """Score a lead based on conversation"""
        # Convert string history to list format
        history = []
        if conversation_history:
            lines = conversation_history.strip().split('\n')
            for line in lines:
                if line.startswith("User:"):
                    history.append({"role": "user", "content": line[5:].strip()})
                elif line.startswith("Assistant:"):
                    history.append({"role": "assistant", "content": line[10:].strip()})

        return self.scorer.score_lead(history, last_message, current_score)
