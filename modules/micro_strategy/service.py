"""
Micro-Strategy service: Lexi isolated variable testing + Pixel auto-switch.

Core logic for:
- Creating micro-strategies with 4 phases (HEADLINE, IMAGE, AUDIENCE, OFFER)
- Generating 5 variations per phase using existing AI agents
- Publishing variations to Meta Ads as separate ad sets
- Syncing performance metrics and detecting phase winners
- Automatically progressing through phases
- Pixel readiness tracking and Traffic -> Lead Gen auto-switch
"""
import os
import json
import logging
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import uuid as uuid_mod

from .models import (
    MicroStrategy, MicroStrategyPhase, PhaseVariation, PixelReadinessTracker,
    StrategyStatus, PhaseType, PhaseStatus, WinnerMetric, SwitchStatus,
)
from modules.marketing.models import MetaAdAccount, MetaAdInsight
from modules.marketing.router import (
    create_meta_campaign,
    create_meta_adset,
    create_meta_adcreative,
    create_meta_ad,
)
from modules.agents.ad_copy_agent import AdCopyAgent
from modules.agents.media_generator_agent import MediaGeneratorAgent
from modules.agents.creative_strategist_agent import CreativeStrategistAgent

load_dotenv()
logger = logging.getLogger(__name__)

FB_GRAPH_URL = "https://graph.facebook.com/v24.0"


class MicroStrategyService:
    """Business logic for Lexi Micro-Strategy and Pixel Auto-Switch."""

    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────────────────────
    # Strategy CRUD
    # ─────────────────────────────────────────────────────────

    def create_strategy(
        self,
        ad_account_id,
        store_id,
        name: str,
        source_url: str,
        destination_url: Optional[str] = None,
        winner_metric: str = "LOWEST_CPA",
        daily_budget_cents: int = 1000,
        max_spend_per_phase_cents: int = 5000,
        min_days_per_phase: int = 3,
        max_days_per_phase: int = 7,
        variations_per_phase: int = 5,
        product_context: Optional[dict] = None,
    ) -> MicroStrategy:
        """Create a new micro-strategy with 4 pre-defined phases."""
        strategy = MicroStrategy(
            ad_account_id=ad_account_id,
            store_id=store_id,
            name=name,
            source_url=source_url,
            destination_url=destination_url or source_url,
            winner_metric=winner_metric,
            daily_budget_cents=daily_budget_cents,
            max_spend_per_phase_cents=max_spend_per_phase_cents,
            min_days_per_phase=min_days_per_phase,
            max_days_per_phase=max_days_per_phase,
            variations_per_phase=variations_per_phase,
            product_context=product_context or {},
        )
        self.db.add(strategy)
        self.db.flush()

        # Create 4 phases
        budget_per_var = daily_budget_cents // variations_per_phase
        for i, phase_type in enumerate(
            [PhaseType.HEADLINE, PhaseType.IMAGE, PhaseType.AUDIENCE, PhaseType.OFFER], 1
        ):
            phase = MicroStrategyPhase(
                strategy_id=strategy.id,
                phase_number=i,
                phase_type=phase_type.value,
                status=PhaseStatus.PENDING.value,
                budget_per_variation_cents=budget_per_var,
            )
            self.db.add(phase)

        self.db.commit()
        self.db.refresh(strategy)
        return strategy

    def get_strategy(self, strategy_id) -> Optional[MicroStrategy]:
        return self.db.query(MicroStrategy).filter(MicroStrategy.id == strategy_id).first()

    def list_strategies(self, store_id) -> List[MicroStrategy]:
        return (
            self.db.query(MicroStrategy)
            .filter(MicroStrategy.store_id == store_id)
            .order_by(MicroStrategy.created_at.desc())
            .all()
        )

    def delete_strategy(self, strategy_id):
        strategy = self.get_strategy(strategy_id)
        if strategy:
            self.db.delete(strategy)
            self.db.commit()

    # ─────────────────────────────────────────────────────────
    # Start / Pause / Resume
    # ─────────────────────────────────────────────────────────

    async def start_strategy(self, strategy_id):
        """
        Start a strategy: generate Phase 1 variations, publish to Meta, activate.
        """
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")

        if strategy.status not in (StrategyStatus.DRAFT.value, StrategyStatus.PAUSED.value):
            raise ValueError(f"Cannot start strategy in {strategy.status} status")

        # Scrape product context if not already set
        if not strategy.product_context or not strategy.product_context.get("company_name"):
            await self._scrape_product_context(strategy)

        strategy.status = StrategyStatus.RUNNING.value
        self.db.commit()

        # Start Phase 1 (headlines)
        phase_1 = next((p for p in strategy.phases if p.phase_number == 1), None)
        if phase_1 and phase_1.status == PhaseStatus.PENDING.value:
            await self.generate_phase_variations(strategy.id, phase_1.id)
            await self.publish_phase_to_meta(strategy.id, phase_1.id)
            # Activate all ad sets
            await self._set_phase_ads_status(strategy, phase_1, "ACTIVE")

        return strategy

    async def pause_strategy(self, strategy_id):
        """Pause all active Meta ads for this strategy."""
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")

        strategy.status = StrategyStatus.PAUSED.value
        self.db.commit()

        # Pause all running phases
        for phase in strategy.phases:
            if phase.status == PhaseStatus.RUNNING.value:
                await self._set_phase_ads_status(strategy, phase, "PAUSED")

        return strategy

    async def resume_strategy(self, strategy_id):
        """Resume paused strategy."""
        strategy = self.get_strategy(strategy_id)
        if not strategy or strategy.status != StrategyStatus.PAUSED.value:
            raise ValueError("Strategy not found or not paused")

        strategy.status = StrategyStatus.RUNNING.value
        self.db.commit()

        # Re-activate current running phase
        for phase in strategy.phases:
            if phase.status == PhaseStatus.RUNNING.value:
                await self._set_phase_ads_status(strategy, phase, "ACTIVE")

        return strategy

    # ─────────────────────────────────────────────────────────
    # Variation Generation (AI Agents)
    # ─────────────────────────────────────────────────────────

    async def generate_phase_variations(self, strategy_id, phase_id):
        """Generate 5 variations for a phase using the appropriate AI agent."""
        phase = self.db.query(MicroStrategyPhase).filter(MicroStrategyPhase.id == phase_id).first()
        strategy = self.get_strategy(strategy_id)
        if not phase or not strategy:
            raise ValueError("Phase or strategy not found")

        phase.status = PhaseStatus.GENERATING.value
        self.db.commit()

        try:
            if phase.phase_type == PhaseType.HEADLINE.value:
                variations = await self._generate_headline_variations(strategy)
            elif phase.phase_type == PhaseType.IMAGE.value:
                variations = await self._generate_image_variations(strategy)
            elif phase.phase_type == PhaseType.AUDIENCE.value:
                variations = await self._generate_audience_variations(strategy)
            elif phase.phase_type == PhaseType.OFFER.value:
                variations = await self._generate_offer_variations(strategy)
            else:
                raise ValueError(f"Unknown phase type: {phase.phase_type}")

            # Create PhaseVariation records
            strategy_code = f"AV{str(strategy.id)[:3].upper()}"
            for i, var_data in enumerate(variations[: strategy.variations_per_phase], 1):
                tag = var_data.get("tag", f"VAR{i}").upper().replace(" ", "-")
                var_name = f"{strategy_code}_{phase.phase_type}_V{i}_{tag}"

                variation = PhaseVariation(
                    phase_id=phase.id,
                    variation_number=i,
                    variation_name=var_name,
                    variable_type=phase.phase_type,
                    variable_value=var_data["value"],
                    variable_metadata=var_data.get("metadata", {}),
                )
                self.db.add(variation)

            phase.status = PhaseStatus.PUBLISHING.value
            self.db.commit()
            logger.info(f"Generated {len(variations)} variations for phase {phase.phase_type}")

        except Exception as e:
            logger.error(f"Failed to generate variations for phase {phase.phase_type}: {e}")
            phase.status = PhaseStatus.FAILED.value
            phase.error_message = str(e)
            self.db.commit()
            raise

    async def _generate_headline_variations(self, strategy: MicroStrategy) -> list:
        """Use AdCopyAgent to generate 5 headline variations."""
        agent = AdCopyAgent()
        ctx = strategy.product_context or {}

        try:
            result = await agent.generate_ad_copy_from_research(
                research_data={
                    "extracted_data": {
                        "company_info": {
                            "name": ctx.get("company_name", ""),
                            "industry": ctx.get("industry", ""),
                        },
                        "products_services": ctx.get("products_services", []),
                        "key_terms": ctx.get("key_terms", []),
                    },
                    "research_summary": {
                        "company_name": ctx.get("company_name", ""),
                        "primary_products": ctx.get("primary_products", ""),
                        "target_audience": ctx.get("target_audience", "General consumers"),
                        "unique_selling_points": ctx.get("unique_selling_points", []),
                    },
                },
                platform="facebook",
                brand_voice=ctx.get("brand_voice", "professional yet approachable"),
            )

            # Extract headlines from the result
            headlines = []
            emotions = ["urgency", "curiosity", "social_proof", "aspiration", "value"]

            # Parse headlines from the agent output
            raw_headlines = result.get("headlines", [])
            if isinstance(raw_headlines, list):
                for idx, h in enumerate(raw_headlines[:5]):
                    text = h.get("text", h) if isinstance(h, dict) else str(h)
                    emotion = h.get("type", emotions[idx % len(emotions)]) if isinstance(h, dict) else emotions[idx % len(emotions)]
                    headlines.append({
                        "value": text,
                        "tag": emotion.upper().replace("/", "-").replace(" ", "-"),
                        "metadata": {
                            "emotion": emotion,
                            "length": len(text),
                            "has_number": any(c.isdigit() for c in text),
                            "has_emoji": any(ord(c) > 127 for c in text),
                        },
                    })

            # Pad to 5 if needed using hooks
            hooks = result.get("hooks", {})
            for hook_type in ["pattern_interrupt", "question", "social_proof"]:
                if len(headlines) >= 5:
                    break
                hook_text = hooks.get(hook_type, "")
                if hook_text:
                    headlines.append({
                        "value": hook_text,
                        "tag": hook_type.upper().replace("_", "-"),
                        "metadata": {"emotion": hook_type, "length": len(hook_text)},
                    })

            # Final padding with generic variations
            while len(headlines) < 5:
                idx = len(headlines) + 1
                headlines.append({
                    "value": f"Headline Variation {idx}",
                    "tag": f"VAR{idx}",
                    "metadata": {"emotion": "generic"},
                })

            return headlines[:5]

        except Exception as e:
            logger.error(f"Headline generation failed: {e}")
            # Return fallback variations
            return [
                {"value": f"Headline Variation {i}", "tag": f"VAR{i}", "metadata": {"emotion": "generic"}}
                for i in range(1, 6)
            ]

    async def _generate_image_variations(self, strategy: MicroStrategy) -> list:
        """Use MediaGeneratorAgent to generate 5 image variations with different styles."""
        agent = MediaGeneratorAgent()
        ctx = strategy.product_context or {}
        company = ctx.get("company_name", "Brand")
        product = ctx.get("primary_products", "product")
        winning_headline = strategy.winning_headline or "Your perfect solution"

        styles = [
            ("lifestyle", f"Photorealistic lifestyle scene showing someone using {product} by {company}. Natural lighting, warm tones, real-world setting. Text overlay: '{winning_headline}'"),
            ("product_hero", f"Clean, professional product shot of {product} by {company} on minimal white background. Studio lighting, sharp detail. Text overlay: '{winning_headline}'"),
            ("testimonial", f"Social proof style ad showing happy customer with {product} by {company}. Candid, authentic feel. Include quote bubble. Text overlay: '{winning_headline}'"),
            ("infographic", f"Bold infographic-style ad for {product} by {company}. Key benefits displayed with icons and stats. Clean modern design. Headline: '{winning_headline}'"),
            ("emotional", f"Cinematic, emotional scene related to {product} by {company}. Dramatic lighting, aspirational mood. Text overlay: '{winning_headline}'"),
        ]

        variations = []
        for style_name, prompt in styles:
            try:
                result = await agent.generate_image(
                    prompt=prompt,
                    style="professional",
                    aspect_ratio="1:1",
                )
                image_url = result.get("url") or result.get("cloudinary_url") or result.get("image_url", "")
                variations.append({
                    "value": image_url,
                    "tag": style_name.upper(),
                    "metadata": {
                        "style": style_name,
                        "prompt": prompt,
                        "has_people": style_name in ("lifestyle", "testimonial"),
                        "has_text_overlay": True,
                    },
                })
            except Exception as e:
                logger.error(f"Image generation failed for style {style_name}: {e}")
                variations.append({
                    "value": "",
                    "tag": style_name.upper(),
                    "metadata": {"style": style_name, "error": str(e)},
                })

        return variations

    async def _generate_audience_variations(self, strategy: MicroStrategy) -> list:
        """Use CreativeStrategistAgent to generate 5 audience segment variations."""
        agent = CreativeStrategistAgent()
        ctx = strategy.product_context or {}

        try:
            result = await agent.generate_meta_audience(
                website_data={
                    "extracted_data": {
                        "company_info": {
                            "name": ctx.get("company_name", ""),
                            "industry": ctx.get("industry", ""),
                        },
                        "products_services": ctx.get("products_services", []),
                    },
                    "research_summary": {
                        "company_name": ctx.get("company_name", ""),
                        "primary_products": ctx.get("primary_products", ""),
                        "target_audience": ctx.get("target_audience", "General consumers"),
                    },
                },
                company_name=ctx.get("company_name"),
            )

            segments = result.get("audience_segments", [])
            interest_tags = result.get("interest_tags", {})
            demographics = result.get("demographics", {})

            variations = []
            for idx, segment in enumerate(segments[:5]):
                seg_name = segment.get("name", f"Segment {idx + 1}")
                # Build targeting spec for this segment
                targeting = {
                    "age_min": demographics.get("age_range", {}).get("min", 18),
                    "age_max": demographics.get("age_range", {}).get("max", 65),
                    "geo_locations": demographics.get("locations", [{"name": "United States"}]),
                    "interests": segment.get("interests", interest_tags.get("core_interests", [])[:5]),
                    "behaviors": segment.get("behaviors", []),
                    "segment_description": segment.get("description", ""),
                }

                variations.append({
                    "value": json.dumps(targeting),
                    "tag": seg_name.upper().replace(" ", "-")[:20],
                    "metadata": {
                        "segment_name": seg_name,
                        "description": segment.get("description", ""),
                        "priority": segment.get("priority", "medium"),
                        "size_estimate": segment.get("size_estimate", "unknown"),
                    },
                })

            # Pad to 5
            while len(variations) < 5:
                idx = len(variations) + 1
                variations.append({
                    "value": json.dumps({"age_min": 18, "age_max": 65, "interests": []}),
                    "tag": f"SEGMENT-{idx}",
                    "metadata": {"segment_name": f"Segment {idx}"},
                })

            return variations[:5]

        except Exception as e:
            logger.error(f"Audience generation failed: {e}")
            return [
                {
                    "value": json.dumps({"age_min": 18, "age_max": 65, "interests": []}),
                    "tag": f"SEGMENT-{i}",
                    "metadata": {"segment_name": f"Segment {i}"},
                }
                for i in range(1, 6)
            ]

    async def _generate_offer_variations(self, strategy: MicroStrategy) -> list:
        """Generate 5 offer/incentive variations via LLM."""
        ctx = strategy.product_context or {}
        company = ctx.get("company_name", "Our store")
        product = ctx.get("primary_products", "products")

        # Pre-defined offer templates
        offer_templates = [
            {
                "value": f"Get 20% off your first order of {product}!",
                "tag": "20PCT-OFF",
                "metadata": {"offer_type": "percentage", "offer_value": 20, "urgency": "none"},
            },
            {
                "value": f"Free shipping on all {product} orders today only!",
                "tag": "FREE-SHIP",
                "metadata": {"offer_type": "free_shipping", "offer_value": 0, "urgency": "limited_time"},
            },
            {
                "value": f"Buy 2 get 1 free on selected {product}!",
                "tag": "BOGO",
                "metadata": {"offer_type": "bogo", "offer_value": 33, "urgency": "none"},
            },
            {
                "value": f"Limited stock: Only 50 left! Order {product} now before they're gone.",
                "tag": "SCARCITY",
                "metadata": {"offer_type": "scarcity", "offer_value": 0, "urgency": "scarcity"},
            },
            {
                "value": f"Order {product} now and get a free bonus gift worth $25!",
                "tag": "BONUS",
                "metadata": {"offer_type": "bonus", "offer_value": 25, "urgency": "none"},
            },
        ]

        # Try to enhance with LLM
        try:
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model="openai/gpt-4o",
                openai_api_key=os.getenv("OPENROUTER_API_KEY"),
                openai_api_base="https://openrouter.ai/api/v1",
                temperature=0.8,
            )

            prompt = f"""Generate 5 unique offer/incentive variations for:
Company: {company}
Product: {product}

Each offer should use a DIFFERENT incentive type:
1. Percentage discount (e.g., 20% off)
2. Free shipping
3. Buy-one-get-one / bundle deal
4. Scarcity / urgency (limited time or stock)
5. Free bonus / gift with purchase

Return as JSON array:
[{{"text": "offer copy", "type": "percentage|free_shipping|bogo|scarcity|bonus", "value": 20, "urgency": "none|limited_time|scarcity"}}]

Only return the JSON array, no markdown."""

            response = await llm.ainvoke(prompt)
            content = response.content.strip()

            # Parse JSON from response
            if content.startswith("["):
                offers = json.loads(content)
                for idx, offer in enumerate(offers[:5]):
                    offer_templates[idx] = {
                        "value": offer.get("text", offer_templates[idx]["value"]),
                        "tag": offer.get("type", "VAR").upper().replace("_", "-")[:15],
                        "metadata": {
                            "offer_type": offer.get("type", "unknown"),
                            "offer_value": offer.get("value", 0),
                            "urgency": offer.get("urgency", "none"),
                        },
                    }
        except Exception as e:
            logger.warning(f"LLM offer generation failed, using templates: {e}")

        return offer_templates

    # ─────────────────────────────────────────────────────────
    # Publish to Meta
    # ─────────────────────────────────────────────────────────

    async def publish_phase_to_meta(self, strategy_id, phase_id):
        """
        Create Meta ads for each variation in a phase.
        One campaign shared across all phases, 5 ad sets per phase.
        """
        phase = self.db.query(MicroStrategyPhase).filter(MicroStrategyPhase.id == phase_id).first()
        strategy = self.get_strategy(strategy_id)
        if not phase or not strategy:
            raise ValueError("Phase or strategy not found")

        ad_account = self.db.query(MetaAdAccount).filter(
            MetaAdAccount.id == strategy.ad_account_id
        ).first()
        if not ad_account:
            raise ValueError("Ad account not found")

        # Create or reuse the Meta campaign
        if not strategy.meta_campaign_id:
            campaign_data = {
                "name": f"[LEXI] {strategy.name}",
                "objective": "OUTCOME_TRAFFIC",
                "status": "PAUSED",
                "special_ad_categories": "[]",
                "daily_budget": str(strategy.daily_budget_cents),
            }
            try:
                meta_result = create_meta_campaign(
                    ad_account.ad_account_id, ad_account.access_token, campaign_data
                )
                strategy.meta_campaign_id = meta_result.get("id", "")
                self.db.commit()
            except Exception as e:
                logger.error(f"Failed to create Meta campaign: {e}")
                phase.status = PhaseStatus.FAILED.value
                phase.error_message = f"Meta campaign creation failed: {e}"
                self.db.commit()
                raise

        # Create ad sets for each variation
        variations = (
            self.db.query(PhaseVariation)
            .filter(PhaseVariation.phase_id == phase.id)
            .order_by(PhaseVariation.variation_number)
            .all()
        )

        budget_per_var = strategy.daily_budget_cents // max(len(variations), 1)

        for var in variations:
            try:
                targeting = self._build_targeting(strategy, phase, var)
                headline = self._get_headline(strategy, phase, var)
                description = self._get_description(strategy, phase, var)
                image_url = self._get_image_url(strategy, phase, var)
                destination = strategy.destination_url or strategy.source_url or ""

                # Create ad set
                adset_data = {
                    "name": var.variation_name,
                    "campaign_id": strategy.meta_campaign_id,
                    "optimization_goal": "LINK_CLICKS",
                    "billing_event": "IMPRESSIONS",
                    "daily_budget": str(budget_per_var),
                    "targeting": json.dumps(targeting),
                    "status": "PAUSED",
                }
                adset_result = create_meta_adset(
                    ad_account.ad_account_id, ad_account.access_token, adset_data
                )
                var.meta_adset_id = adset_result.get("id", "")

                # Create ad creative
                creative_data = {
                    "name": f"Creative - {var.variation_name}",
                    "object_story_spec": json.dumps({
                        "page_id": ad_account.business_id or "",
                        "link_data": {
                            "message": description,
                            "link": destination,
                            "name": headline,
                            "picture": image_url,
                            "call_to_action": {"type": "LEARN_MORE"},
                        },
                    }),
                }
                creative_result = create_meta_adcreative(
                    ad_account.ad_account_id, ad_account.access_token, creative_data
                )
                var.meta_creative_id = creative_result.get("id", "")

                # Create ad
                ad_data = {
                    "name": var.variation_name,
                    "adset_id": var.meta_adset_id,
                    "creative": json.dumps({"creative_id": var.meta_creative_id}),
                    "status": "PAUSED",
                }
                ad_result = create_meta_ad(
                    ad_account.ad_account_id, ad_account.access_token, ad_data
                )
                var.meta_ad_id = ad_result.get("id", "")

                logger.info(f"Published variation {var.variation_name} to Meta")

            except Exception as e:
                logger.error(f"Failed to publish variation {var.variation_name}: {e}")
                var.is_active = False

        phase.status = PhaseStatus.RUNNING.value
        phase.started_at = datetime.utcnow()
        strategy.current_phase_number = phase.phase_number
        self.db.commit()

    def _build_targeting(self, strategy, phase, variation) -> dict:
        """Build Meta targeting spec based on phase type."""
        # For AUDIENCE phase, use the variation's targeting
        if phase.phase_type == PhaseType.AUDIENCE.value:
            try:
                targeting = json.loads(variation.variable_value)
                return {
                    "age_min": targeting.get("age_min", 18),
                    "age_max": targeting.get("age_max", 65),
                    "geo_locations": targeting.get("geo_locations", {"countries": ["US"]}),
                    "flexible_spec": [{"interests": targeting.get("interests", [])}],
                }
            except (json.JSONDecodeError, TypeError):
                pass

        # For other phases, use winning audience or default
        if strategy.winning_audience:
            aud = strategy.winning_audience
            return {
                "age_min": aud.get("age_min", 18),
                "age_max": aud.get("age_max", 65),
                "geo_locations": aud.get("geo_locations", {"countries": ["US"]}),
                "flexible_spec": [{"interests": aud.get("interests", [])}],
            }

        # Default broad targeting
        return {
            "age_min": 18,
            "age_max": 65,
            "geo_locations": {"countries": ["US"]},
        }

    def _get_headline(self, strategy, phase, variation) -> str:
        """Get the headline for an ad based on phase type."""
        if phase.phase_type == PhaseType.HEADLINE.value:
            return variation.variable_value
        return strategy.winning_headline or "Discover something amazing"

    def _get_description(self, strategy, phase, variation) -> str:
        """Get the description/primary text for an ad."""
        if phase.phase_type == PhaseType.OFFER.value:
            return variation.variable_value
        ctx = strategy.product_context or {}
        return ctx.get("primary_products", "Check out our latest products")

    def _get_image_url(self, strategy, phase, variation) -> str:
        """Get the image URL for an ad."""
        if phase.phase_type == PhaseType.IMAGE.value:
            return variation.variable_value
        return strategy.winning_image_url or ""

    # ─────────────────────────────────────────────────────────
    # Metrics Sync & Winner Detection
    # ─────────────────────────────────────────────────────────

    async def sync_phase_metrics(self, phase_id):
        """Sync performance metrics from Meta Insights for all variations in a phase."""
        phase = self.db.query(MicroStrategyPhase).filter(MicroStrategyPhase.id == phase_id).first()
        if not phase:
            return

        strategy = self.get_strategy(phase.strategy_id)
        ad_account = self.db.query(MetaAdAccount).filter(
            MetaAdAccount.id == strategy.ad_account_id
        ).first()
        if not ad_account:
            return

        total_spend = 0
        for var in phase.variations:
            if not var.meta_ad_id:
                continue

            try:
                # Query Meta Insights API for this ad
                url = f"{FB_GRAPH_URL}/{var.meta_ad_id}/insights"
                params = {
                    "access_token": ad_account.access_token,
                    "fields": "impressions,clicks,spend,actions,ctr,cpc,cpm",
                    "date_preset": "maximum",
                }
                response = requests.get(url, params=params, timeout=30)
                data = response.json()

                if "data" in data and len(data["data"]) > 0:
                    insights = data["data"][0]
                    var.impressions = int(insights.get("impressions", 0))
                    var.clicks = int(insights.get("clicks", 0))
                    var.spend_cents = int(float(insights.get("spend", 0)) * 100)
                    var.ctr = float(insights.get("ctr", 0))
                    var.cpc = float(insights.get("cpc", 0))

                    # Extract conversions from actions
                    actions = insights.get("actions", [])
                    for action in actions:
                        if action.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase"):
                            var.conversions = int(action.get("value", 0))
                            break

                    # Calculate CPA and ROAS
                    spend = float(insights.get("spend", 0))
                    if var.conversions > 0:
                        var.cpa = spend / var.conversions
                    else:
                        var.cpa = 0.0
                    var.roas = 0.0  # Requires revenue data

                    total_spend += var.spend_cents

            except Exception as e:
                logger.error(f"Failed to sync metrics for ad {var.meta_ad_id}: {e}")

        phase.total_spend_cents = total_spend
        self.db.commit()

    def evaluate_phase_winner(self, phase_id) -> Optional[PhaseVariation]:
        """
        Determine the winner of a phase.

        Winner conditions:
        1. At least min_days have elapsed
        2. Total spend >= max_spend_per_phase OR max_days elapsed
        3. Variations have meaningful data (impressions > 100)
        """
        phase = self.db.query(MicroStrategyPhase).filter(MicroStrategyPhase.id == phase_id).first()
        if not phase or not phase.started_at:
            return None

        strategy = self.get_strategy(phase.strategy_id)
        days_running = (datetime.utcnow() - phase.started_at).days
        total_spend = sum(v.spend_cents for v in phase.variations)

        # Not enough time
        if days_running < strategy.min_days_per_phase:
            return None

        # Check if ready to evaluate
        ready = (
            total_spend >= strategy.max_spend_per_phase_cents
            or days_running >= strategy.max_days_per_phase
        )
        if not ready:
            return None

        # Filter viable variations
        viable = [v for v in phase.variations if v.impressions >= 100 and v.is_active]
        if len(viable) < 2:
            if days_running < strategy.max_days_per_phase:
                return None
            viable = [v for v in phase.variations if v.impressions > 0 and v.is_active]

        if not viable:
            return None

        # Pick winner by metric
        metric = strategy.winner_metric
        if metric == WinnerMetric.LOWEST_CPA.value:
            with_conv = [v for v in viable if v.conversions > 0]
            if with_conv:
                winner = min(with_conv, key=lambda v: v.cpa)
            else:
                winner = max(viable, key=lambda v: v.ctr)
        elif metric == WinnerMetric.HIGHEST_CTR.value:
            winner = max(viable, key=lambda v: v.ctr)
        elif metric == WinnerMetric.LOWEST_CPC.value:
            winner = min(viable, key=lambda v: v.cpc if v.cpc > 0 else float("inf"))
        elif metric == WinnerMetric.HIGHEST_ROAS.value:
            winner = max(viable, key=lambda v: v.roas)
        else:
            winner = max(viable, key=lambda v: v.ctr)

        return winner

    async def declare_winner(self, strategy_id, phase_id, variation_id=None):
        """Manually declare a winner for a phase (or auto-detect if no variation_id)."""
        phase = self.db.query(MicroStrategyPhase).filter(MicroStrategyPhase.id == phase_id).first()
        strategy = self.get_strategy(strategy_id)
        if not phase or not strategy:
            raise ValueError("Phase or strategy not found")

        if variation_id:
            winner = self.db.query(PhaseVariation).filter(
                PhaseVariation.id == variation_id,
                PhaseVariation.phase_id == phase_id,
            ).first()
            if not winner:
                raise ValueError("Variation not found in this phase")
        else:
            winner = self.evaluate_phase_winner(phase_id)
            if not winner:
                raise ValueError("No winner can be determined yet")

        await self._complete_phase_with_winner(strategy, phase, winner)
        return winner

    # ─────────────────────────────────────────────────────────
    # Phase Progression (called by scheduler)
    # ─────────────────────────────────────────────────────────

    async def progress_phase(self, strategy_id):
        """
        Check current phase and advance if winner detected.
        Called by scheduler every 15 minutes.
        """
        strategy = self.get_strategy(strategy_id)
        if not strategy or strategy.status != StrategyStatus.RUNNING.value:
            return

        current_phase = next(
            (p for p in strategy.phases if p.status == PhaseStatus.RUNNING.value),
            None,
        )
        if not current_phase:
            return

        # Step 1: Sync metrics
        await self.sync_phase_metrics(current_phase.id)

        # Step 2: Try to evaluate winner
        winner = self.evaluate_phase_winner(current_phase.id)
        if not winner:
            return

        # Step 3: Complete phase and advance
        await self._complete_phase_with_winner(strategy, current_phase, winner)

    async def _complete_phase_with_winner(self, strategy, phase, winner):
        """Mark phase complete, store winner, advance to next phase."""
        # Mark winner
        winner.is_winner = True
        phase.winner_variation_id = winner.id
        phase.winner_value = winner.variable_value
        phase.winner_metadata = {
            "ctr": winner.ctr,
            "cpa": winner.cpa,
            "cpc": winner.cpc,
            "roas": winner.roas,
            "impressions": winner.impressions,
            "clicks": winner.clicks,
            "spend_cents": winner.spend_cents,
            "conversions": winner.conversions,
        }
        phase.status = PhaseStatus.COMPLETED.value
        phase.completed_at = datetime.utcnow()

        # Store winner on strategy
        if phase.phase_type == PhaseType.HEADLINE.value:
            strategy.winning_headline = winner.variable_value
        elif phase.phase_type == PhaseType.IMAGE.value:
            strategy.winning_image_url = winner.variable_value
        elif phase.phase_type == PhaseType.AUDIENCE.value:
            try:
                strategy.winning_audience = json.loads(winner.variable_value)
            except (json.JSONDecodeError, TypeError):
                strategy.winning_audience = {"raw": winner.variable_value}
        elif phase.phase_type == PhaseType.OFFER.value:
            strategy.winning_offer = winner.variable_value

        # Update learnings
        learnings = strategy.learnings or {}
        learnings[phase.phase_type.lower()] = winner.variable_metadata or {}
        strategy.learnings = learnings

        # Pause losing variations on Meta
        ad_account = self.db.query(MetaAdAccount).filter(
            MetaAdAccount.id == strategy.ad_account_id
        ).first()

        for var in phase.variations:
            if not var.is_winner and var.meta_adset_id and ad_account:
                try:
                    self._update_meta_entity_status(
                        ad_account, var.meta_adset_id, "adset", "PAUSED"
                    )
                except Exception as e:
                    logger.error(f"Failed to pause loser {var.variation_name}: {e}")

        self.db.commit()

        # Advance to next phase
        next_phase = next(
            (p for p in strategy.phases if p.phase_number == phase.phase_number + 1),
            None,
        )
        if next_phase and next_phase.status == PhaseStatus.PENDING.value:
            try:
                await self.generate_phase_variations(strategy.id, next_phase.id)
                await self.publish_phase_to_meta(strategy.id, next_phase.id)
                await self._set_phase_ads_status(strategy, next_phase, "ACTIVE")
            except Exception as e:
                logger.error(f"Failed to start next phase: {e}")
                next_phase.status = PhaseStatus.FAILED.value
                next_phase.error_message = str(e)
                self.db.commit()
        elif not next_phase:
            # All 4 phases done
            strategy.status = StrategyStatus.COMPLETED.value
            self.db.commit()
            logger.info(f"Strategy {strategy.name} completed with all winning combos!")

    # ─────────────────────────────────────────────────────────
    # Meta Helpers
    # ─────────────────────────────────────────────────────────

    async def _set_phase_ads_status(self, strategy, phase, status: str):
        """Set status (ACTIVE/PAUSED) for all ad sets in a phase."""
        ad_account = self.db.query(MetaAdAccount).filter(
            MetaAdAccount.id == strategy.ad_account_id
        ).first()
        if not ad_account:
            return

        for var in phase.variations:
            if var.meta_adset_id:
                try:
                    self._update_meta_entity_status(
                        ad_account, var.meta_adset_id, "adset", status
                    )
                except Exception as e:
                    logger.error(f"Failed to set {var.variation_name} to {status}: {e}")

    def _update_meta_entity_status(self, ad_account, entity_id, entity_type, status):
        """Update status of a Meta entity (campaign/adset/ad)."""
        url = f"{FB_GRAPH_URL}/{entity_id}"
        response = requests.post(
            url,
            data={"status": status, "access_token": ad_account.access_token},
            timeout=30,
        )
        if response.status_code != 200:
            logger.error(f"Meta API error updating {entity_type} {entity_id}: {response.text}")

    async def _scrape_product_context(self, strategy: MicroStrategy):
        """Scrape source URL to build product context."""
        try:
            from modules.agents.market_research_agent import MarketResearchAgent

            agent = MarketResearchAgent()
            result = await agent.research_website(strategy.source_url)

            extracted = result.get("extracted_data", {})
            summary = result.get("research_summary", {})

            strategy.product_context = {
                "company_name": extracted.get("company_info", {}).get("name", ""),
                "industry": extracted.get("company_info", {}).get("industry", ""),
                "primary_products": summary.get("primary_products", ""),
                "products_services": extracted.get("products_services", []),
                "target_audience": summary.get("target_audience", ""),
                "unique_selling_points": summary.get("unique_selling_points", []),
                "key_terms": extracted.get("key_terms", []),
                "brand_voice": "professional yet approachable",
            }
            self.db.commit()
        except Exception as e:
            logger.error(f"Failed to scrape product context: {e}")

    # ─────────────────────────────────────────────────────────
    # Pixel Readiness / Traffic -> Lead Gen Auto-Switch
    # ─────────────────────────────────────────────────────────

    def create_pixel_tracker(
        self,
        ad_account_id,
        store_id,
        pixel_id: str,
        pixel_name: str = None,
        micro_strategy_id=None,
        required_events: int = 50,
        required_days: int = 7,
        event_window_days: int = 7,
    ) -> PixelReadinessTracker:
        """Create a pixel readiness tracker."""
        tracker = PixelReadinessTracker(
            ad_account_id=ad_account_id,
            store_id=store_id,
            pixel_id=pixel_id,
            pixel_name=pixel_name,
            micro_strategy_id=micro_strategy_id,
            required_events=required_events,
            required_days=required_days,
            event_window_days=event_window_days,
            switch_status=SwitchStatus.TRAFFIC_PHASE.value,
        )
        self.db.add(tracker)
        self.db.commit()
        self.db.refresh(tracker)
        return tracker

    def get_pixel_tracker(self, tracker_id) -> Optional[PixelReadinessTracker]:
        return self.db.query(PixelReadinessTracker).filter(
            PixelReadinessTracker.id == tracker_id
        ).first()

    def list_pixel_trackers(self, store_id) -> List[PixelReadinessTracker]:
        return (
            self.db.query(PixelReadinessTracker)
            .filter(PixelReadinessTracker.store_id == store_id)
            .order_by(PixelReadinessTracker.created_at.desc())
            .all()
        )

    async def start_traffic_campaign(self, tracker_id):
        """Create a TRAFFIC campaign to warm up the pixel."""
        tracker = self.get_pixel_tracker(tracker_id)
        if not tracker:
            raise ValueError("Tracker not found")

        ad_account = self.db.query(MetaAdAccount).filter(
            MetaAdAccount.id == tracker.ad_account_id
        ).first()
        if not ad_account:
            raise ValueError("Ad account not found")

        campaign_data = {
            "name": f"[PIXEL-WARMUP] Traffic - {tracker.pixel_id[:8]}",
            "objective": "OUTCOME_TRAFFIC",
            "status": "ACTIVE",
            "special_ad_categories": "[]",
            "daily_budget": "1000",
        }

        try:
            result = create_meta_campaign(
                ad_account.ad_account_id, ad_account.access_token, campaign_data
            )
            tracker.traffic_campaign_id = result.get("id", "")
            tracker.traffic_started_at = datetime.utcnow()
            tracker.switch_status = SwitchStatus.MONITORING.value
            self.db.commit()
        except Exception as e:
            logger.error(f"Failed to create traffic campaign: {e}")
            raise

        return tracker

    async def check_pixel_readiness(self, tracker_id) -> bool:
        """
        Query Meta for pixel event stats.
        Returns True if ready to switch to Lead Gen.
        """
        tracker = self.get_pixel_tracker(tracker_id)
        if not tracker or tracker.switch_status != SwitchStatus.MONITORING.value:
            return False

        ad_account = self.db.query(MetaAdAccount).filter(
            MetaAdAccount.id == tracker.ad_account_id
        ).first()
        if not ad_account:
            return False

        # Query pixel stats from Meta
        try:
            stats = self._fetch_pixel_stats(
                tracker.pixel_id,
                ad_account.access_token,
                tracker.event_window_days,
            )

            tracker.page_view_count = stats.get("PageView", 0)
            tracker.view_content_count = stats.get("ViewContent", 0)
            tracker.lead_count = stats.get("Lead", 0)
            tracker.add_to_cart_count = stats.get("AddToCart", 0)
            tracker.purchase_count = stats.get("Purchase", 0)
            tracker.total_optimization_events = (
                tracker.view_content_count
                + tracker.lead_count
                + tracker.add_to_cart_count
                + tracker.purchase_count
            )

            # Check threshold
            days_running = 0
            if tracker.traffic_started_at:
                days_running = (datetime.utcnow() - tracker.traffic_started_at).days

            ready = (
                tracker.total_optimization_events >= tracker.required_events
                and days_running >= tracker.required_days
            )

            if ready:
                tracker.switch_status = SwitchStatus.READY_TO_SWITCH.value

            self.db.commit()
            return ready

        except Exception as e:
            logger.error(f"Failed to check pixel readiness: {e}")
            return False

    async def execute_objective_switch(self, tracker_id):
        """
        Switch from Traffic to Lead Gen:
        1. Pause traffic campaign
        2. Create custom audience from pixel data
        3. Create OUTCOME_LEADS campaign
        """
        tracker = self.get_pixel_tracker(tracker_id)
        if not tracker:
            raise ValueError("Tracker not found")

        ad_account = self.db.query(MetaAdAccount).filter(
            MetaAdAccount.id == tracker.ad_account_id
        ).first()
        if not ad_account:
            raise ValueError("Ad account not found")

        # 1. Pause traffic campaign
        if tracker.traffic_campaign_id:
            try:
                self._update_meta_entity_status(
                    ad_account, tracker.traffic_campaign_id, "campaign", "PAUSED"
                )
            except Exception as e:
                logger.error(f"Failed to pause traffic campaign: {e}")

        # 2. Create custom audience from pixel
        audience_data = None
        try:
            audience_data = self._create_custom_audience(
                ad_account, tracker.pixel_id
            )
            tracker.audience_snapshot = audience_data
        except Exception as e:
            logger.error(f"Failed to create custom audience: {e}")

        # 3. Create Lead Gen campaign
        leadgen_data = {
            "name": f"[AUTO-SWITCH] Lead Gen - {tracker.pixel_id[:8]}",
            "objective": "OUTCOME_LEADS",
            "status": "ACTIVE",
            "special_ad_categories": "[]",
            "daily_budget": "1000",
        }

        try:
            result = create_meta_campaign(
                ad_account.ad_account_id, ad_account.access_token, leadgen_data
            )
            tracker.leadgen_campaign_id = result.get("id", "")
            tracker.switch_triggered_at = datetime.utcnow()
            tracker.leadgen_started_at = datetime.utcnow()
            tracker.current_objective = "OUTCOME_LEADS"
            tracker.switch_status = SwitchStatus.LEAD_GEN_PHASE.value
            self.db.commit()

            # Create ad sets using winning creatives from linked micro-strategy
            if tracker.micro_strategy_id:
                strategy = self.get_strategy(tracker.micro_strategy_id)
                if strategy:
                    await self._create_leadgen_adsets(
                        tracker, ad_account, strategy, audience_data
                    )

        except Exception as e:
            logger.error(f"Failed to create Lead Gen campaign: {e}")
            raise

        return tracker

    def _fetch_pixel_stats(self, pixel_id: str, access_token: str, days: int) -> dict:
        """Query Meta Graph API for pixel event counts."""
        url = f"{FB_GRAPH_URL}/{pixel_id}/stats"
        params = {
            "access_token": access_token,
            "aggregation": "event",
            "start_time": int((datetime.utcnow() - timedelta(days=days)).timestamp()),
            "end_time": int(datetime.utcnow().timestamp()),
        }
        response = requests.get(url, params=params, timeout=30)
        data = response.json().get("data", [])
        stats = {}
        for entry in data:
            event = entry.get("event", "") or entry.get("name", "")
            count = entry.get("count", 0) or entry.get("value", 0)
            stats[event] = count
        return stats

    def _create_custom_audience(self, ad_account, pixel_id: str) -> dict:
        """Create a custom audience from pixel data via Meta API."""
        url = f"{FB_GRAPH_URL}/act_{ad_account.ad_account_id}/customaudiences"
        payload = {
            "name": f"Pixel Audience - {pixel_id[:8]}",
            "subtype": "WEBSITE",
            "rule": json.dumps({
                "inclusions": {
                    "operator": "or",
                    "rules": [
                        {
                            "event_sources": [{"id": pixel_id, "type": "pixel"}],
                            "retention_seconds": 30 * 86400,  # 30 days
                            "filter": {"operator": "and", "filters": [
                                {"field": "event", "operator": "eq", "value": "PageView"}
                            ]},
                        }
                    ],
                }
            }),
            "access_token": ad_account.access_token,
        }
        response = requests.post(url, data=payload, timeout=30)
        return response.json()

    async def _create_leadgen_adsets(self, tracker, ad_account, strategy, audience_data):
        """Create ad sets for the Lead Gen campaign using winning creatives."""
        targeting = strategy.winning_audience or {"age_min": 18, "age_max": 65}
        headline = strategy.winning_headline or "Learn More"
        image_url = strategy.winning_image_url or ""
        destination = strategy.destination_url or strategy.source_url or ""

        # If we have a custom audience, include it
        if audience_data and audience_data.get("id"):
            targeting["custom_audiences"] = [{"id": audience_data["id"]}]

        adset_data = {
            "name": f"[LEAD-GEN] {strategy.name}",
            "campaign_id": tracker.leadgen_campaign_id,
            "optimization_goal": "LEAD_GENERATION",
            "billing_event": "IMPRESSIONS",
            "daily_budget": "1000",
            "targeting": json.dumps(targeting),
            "status": "ACTIVE",
        }

        try:
            adset_result = create_meta_adset(
                ad_account.ad_account_id, ad_account.access_token, adset_data
            )

            creative_data = {
                "name": f"[LEAD-GEN] Creative - {strategy.name}",
                "object_story_spec": json.dumps({
                    "page_id": ad_account.business_id or "",
                    "link_data": {
                        "message": strategy.winning_offer or "Learn more about us",
                        "link": destination,
                        "name": headline,
                        "picture": image_url,
                        "call_to_action": {"type": "SIGN_UP"},
                    },
                }),
            }
            creative_result = create_meta_adcreative(
                ad_account.ad_account_id, ad_account.access_token, creative_data
            )

            ad_data = {
                "name": f"[LEAD-GEN] Ad - {strategy.name}",
                "adset_id": adset_result.get("id", ""),
                "creative": json.dumps({"creative_id": creative_result.get("id", "")}),
                "status": "ACTIVE",
            }
            create_meta_ad(
                ad_account.ad_account_id, ad_account.access_token, ad_data
            )

            logger.info(f"Created Lead Gen ad set for strategy {strategy.name}")

        except Exception as e:
            logger.error(f"Failed to create Lead Gen ad sets: {e}")


# ─────────────────────────────────────────────────────────────
# Scheduler Integration
# ─────────────────────────────────────────────────────────────


async def run_micro_strategy_cycle():
    """
    Called by the scheduler every 15 minutes.
    Checks all running strategies and monitoring pixel trackers.
    """
    from database import SessionLocal

    db = SessionLocal()
    service = MicroStrategyService(db)

    results = {"strategies_checked": 0, "trackers_checked": 0, "errors": []}

    try:
        # Check all RUNNING strategies
        strategies = (
            db.query(MicroStrategy)
            .filter(MicroStrategy.status == StrategyStatus.RUNNING.value)
            .all()
        )
        for strategy in strategies:
            try:
                await service.progress_phase(strategy.id)
                results["strategies_checked"] += 1
            except Exception as e:
                logger.error(f"Strategy {strategy.id} progress error: {e}")
                results["errors"].append(str(e))

        # Check all MONITORING pixel trackers
        trackers = (
            db.query(PixelReadinessTracker)
            .filter(PixelReadinessTracker.switch_status == SwitchStatus.MONITORING.value)
            .all()
        )
        for tracker in trackers:
            try:
                ready = await service.check_pixel_readiness(tracker.id)
                if ready:
                    await service.execute_objective_switch(tracker.id)
                results["trackers_checked"] += 1
            except Exception as e:
                logger.error(f"Pixel tracker {tracker.id} check error: {e}")
                results["errors"].append(str(e))

    except Exception as e:
        logger.error(f"Micro-strategy cycle error: {e}")
        results["errors"].append(str(e))
    finally:
        db.close()

    return results
