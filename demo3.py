import requests
import json
import os
import time
import re
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse
from datetime import datetime
from apify_client import ApifyClient
import textwrap

class MarketResearchAI:
    """
    MARKET RESEARCH AI AGENT - RESEARCH BUSINESSES & CREATE AD CREATIVES
    """
    
    def __init__(self, apify_api_key: str, openrouter_api_key: str = None):
        self.apify_client = ApifyClient(apify_api_key)
        self.openrouter_api_key = openrouter_api_key
        self.openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.research_data = {}
    
    def scrape_website_only(self, website_url: str) -> Dict:
        """
        ONLY scrape website and save content - NO AI ANALYSIS
        Returns raw scraped data
        """
        print(f"🔍 WEBSITE SCRAPER (NO AI)")
        print("=" * 80)
        print(f"Target: {website_url}")
        print("=" * 80)
        
        # Validate URL
        url = self._validate_url(website_url)
        if not url:
            return self._error_response("Invalid URL", website_url)
        
        # Scrape website
        scraped_data = self._scrape_website(url)
        if not scraped_data.get("success"):
            return scraped_data
        
        # Save scraped content
        output_dir = self._save_scraped_content(scraped_data)
        
        print(f"\n💾 RAW CONTENT SAVED TO: {output_dir}/")
        print("📄 Files saved:")
        print(f"   1. pages/ - Raw HTML/markdown files")
        print(f"   2. metadata.json - Scraping metadata")
        print(f"   3. combined_content.txt - All text combined")
        
        return {
            "success": True,
            "url": url,
            "output_dir": output_dir,
            "total_pages": len(scraped_data["pages"]),
            "scraped_at": scraped_data["scraped_at"]
        }
    
    def research_and_create_ads(self, website_url: str, content_file: str = None) -> Dict:
        """
        Complete market research pipeline and create Facebook ad creatives
        """
        print(f"🔬 MARKET RESEARCH AI AGENT")
        print("=" * 80)
        print(f"Target: {website_url}")
        print("=" * 80)
        
        if not self.openrouter_api_key:
            return self._error_response("OpenRouter API key required for research", website_url)
        
        # Load or scrape content
        if content_file:
            print(f"📖 Using saved content file: {content_file}")
            with open(content_file, 'r', encoding='utf-8') as f:
                content = f.read()
            output_dir = os.path.dirname(content_file)
        else:
            # Scrape first
            print("🔍 Scraping website...")
            scrape_result = self.scrape_website_only(website_url)
            if not scrape_result.get("success"):
                return scrape_result
            
            output_dir = scrape_result["output_dir"]
            content_file = os.path.join(output_dir, "combined_content.txt")
            
            with open(content_file, 'r', encoding='utf-8') as f:
                content = f.read()
        
        print(f"\n📊 RESEARCHING BUSINESS & MARKET")
        print("-" * 40)
        
        # Step 1: Extract business fundamentals
        print("1️⃣ Extracting business fundamentals...")
        business_data = self._extract_business_fundamentals(content, website_url)
        
        # Step 2: Deep market research
        print("2️⃣ Conducting deep market research...")
        market_research = self._conduct_market_research(business_data, content)
        
        # Step 3: Analyze target audience deeply
        print("3️⃣ Analyzing target audience in-depth...")
        audience_analysis = self._analyze_target_audience(business_data, market_research)
        
        # Step 4: Research competition
        print("4️⃣ Researching competitive landscape...")
        competitive_analysis = self._analyze_competition(business_data)
        
        # Step 5: Create Facebook ad creatives
        print("5️⃣ Creating Facebook ad creatives...")
        ad_creatives = self._create_facebook_ad_creatives(
            business_data, 
            market_research, 
            audience_analysis, 
            competitive_analysis
        )
        
        # Step 6: Generate hashtags
        print("6️⃣ Generating targeted hashtags...")
        hashtags = self._generate_hashtags(business_data, audience_analysis)
        
        # Combine all research
        complete_research = {
            "business_fundamentals": business_data,
            "market_research": market_research,
            "audience_analysis": audience_analysis,
            "competitive_analysis": competitive_analysis,
            "facebook_ad_creatives": ad_creatives,
            "hashtag_strategy": hashtags,
            "metadata": {
                "researched_at": datetime.now().isoformat(),
                "session_id": self.session_id,
                "website_url": website_url,
                "content_size": len(content)
            }
        }
        
        # Save complete research
        self._save_complete_research(complete_research, output_dir)
        
        print(f"\n✅ MARKET RESEARCH COMPLETE!")
        print(f"📁 Results saved to: {output_dir}/")
        print(f"📄 1. complete_research.json - Full research data")
        print(f"📄 2. facebook_ads_ready.txt - Ready-to-use ad creatives")
        print(f"📄 3. research_summary.txt - Executive summary")
        
        return complete_research
    
    def _extract_business_fundamentals(self, content: str, website_url: str) -> Dict:
        """Extract core business information"""
        prompt = f"""As a MARKET RESEARCHER, extract fundamental business information from this website content.

URL: {website_url}

CONTENT SAMPLE:
{content[:4000]}

Extract information in this STRUCTURE:

{{
  "business_basics": {{
    "company_name": "",
    "core_business": "",
    "primary_product_service": "",
    "industry_category": "",
    "sub_category": "",
    "business_model": "",
    "revenue_model": "",
    "unique_value_proposition": "",
    "key_differentiators": []
  }},
  "problem_solution_matrix": {{
    "primary_customer_problems": [],
    "industry_pain_points": [],
    "specific_challenges_solved": [],
    "solution_mechanisms": [],
    "outcomes_delivered": []
  }},
  "audience_indicators": {{
    "target_customer_signals": [],
    "decision_maker_hints": [],
    "mentioned_roles": [],
    "implied_buyer_personas": [],
    "customer_segments_hinted": []
  }},
  "value_metrics": {{
    "mentioned_roi": "",
    "time_savings": "",
    "cost_reductions": "",
    "efficiency_gains": "",
    "quality_improvements": ""
  }},
  "content_analysis": {{
    "key_themes": [],
    "frequently_mentioned_concepts": [],
    "emotional_triggers": [],
    "language_patterns": [],
    "call_to_action_phrases": []
  }}
}}

RESEARCHER GUIDELINES:
1. Focus on WHAT problems they solve and HOW
2. Identify WHO they're talking to (implied audience)
3. Extract specific pain points mentioned
4. Note any metrics or results mentioned
5. Analyze language and emotional triggers
6. Look for hidden audience signals
7. Capture solution mechanisms in detail
8. Note industry-specific terminology

Return ONLY valid JSON."""

        response = self._call_ai(prompt, temperature=0.1)
        return self._extract_json(response)
    
    def _conduct_market_research(self, business_data: Dict, content: str) -> Dict:
        """Conduct deeper market research based on business fundamentals"""
        
        business_basics = business_data.get("business_basics", {})
        industry = business_basics.get("industry_category", "general")
        
        prompt = f"""As a SENIOR MARKET RESEARCHER, analyze this business context and provide deep market insights.

BUSINESS CONTEXT:
- Company: {business_basics.get('company_name', 'Unknown')}
- Industry: {industry}
- Core Business: {business_basics.get('core_business', 'Unknown')}
- Primary Offering: {business_basics.get('primary_product_service', 'Unknown')}

PROBLEM-SOLUTION CONTEXT:
{json.dumps(business_data.get('problem_solution_matrix', {}), indent=2)}

CONDUCT MARKET RESEARCH AND PROVIDE:

{{
  "market_landscape": {{
    "market_size_estimate": "",
    "growth_trends": [],
    "key_market_drivers": [],
    "industry_challenges": [],
    "regulatory_factors": [],
    "technology_trends": []
  }},
  "decision_maker_analysis": {{
    "primary_decision_makers": [],
    "secondary_influencers": [],
    "buying_committee_roles": [],
    "decision_criteria": [],
    "purchase_triggers": [],
    "objections_overcome": []
  }},
  "pain_point_hierarchy": {{
    "strategic_pains": [],
    "operational_pains": [],
    "financial_pains": [],
    "emotional_pains": [],
    "compliance_pains": []
  }},
  "solution_depth_analysis": {{
    "immediate_solutions": [],
    "strategic_solutions": [],
    "transformative_impacts": [],
    "competitive_solutions": [],
    "industry_best_practices": []
  }},
  "market_intelligence": {{
    "current_market_gaps": [],
    "unmet_needs": [],
    "emerging_opportunities": [],
    "competitive_threats": [],
    "partner_ecosystem": []
  }}
}}

RESEARCH METHODOLOGY:
1. Analyze industry context and trends
2. Map decision-making processes
3. Categorize pain points by severity and type
4. Evaluate solution effectiveness
5. Identify market gaps and opportunities
6. Consider buying committee dynamics

Base your analysis on REAL MARKET KNOWLEDGE for this industry.
Return ONLY valid JSON."""

        response = self._call_ai(prompt, temperature=0.2)
        return self._extract_json(response)
    
    def _analyze_target_audience(self, business_data: Dict, market_research: Dict) -> Dict:
        """Deep dive into target audience analysis"""
        
        prompt = f"""As a BUYER PERSONA EXPERT, create detailed audience profiles based on:

BUSINESS FUNDAMENTALS:
{json.dumps(business_data.get('business_basics', {}), indent=2)}

MARKET RESEARCH:
{json.dumps(market_research.get('decision_maker_analysis', {}), indent=2)}

CREATE DETAILED AUDIENCE PROFILES:

{{
  "primary_buyer_personas": [
    {{
      "persona_name": "",
      "job_title": "",
      "seniority_level": "",
      "department": "",
      "key_responsibilities": [],
      "daily_challenges": [],
      "success_metrics": [],
      "information_sources": [],
      "peer_influences": [],
      "pain_points_priority": []
    }}
  ],
  "secondary_influencers": [
    {{
      "role": "",
      "influence_level": "",
      "concerns": [],
      "information_needs": []
    }}
  ],
  "audience_psychographics": {{
    "primary_motivations": [],
    "fears_anxieties": [],
    "aspirations": [],
    "values": [],
    "communication_preferences": []
  }},
  "buying_journey": {{
    "awareness_triggers": [],
    "consideration_criteria": [],
    "evaluation_process": [],
    "decision_factors": [],
    "onboarding_expectations": []
  }},
  "content_preferences": {{
    "format_preferences": [],
    "channel_preferences": [],
    "tone_resonance": [],
    "technical_depth": "",
    "social_proof_types": []
  }}
}}

ANALYSIS GUIDELINES:
1. Create REALISTIC personas based on industry norms
2. Include specific job titles and responsibilities
3. Map complete buying journey
4. Identify emotional and psychological factors
5. Note content and communication preferences
6. Consider departmental dynamics

Create 2-3 detailed primary personas.
Return ONLY valid JSON."""

        response = self._call_ai(prompt, temperature=0.3)
        return self._extract_json(response)
    
    def _analyze_competition(self, business_data: Dict) -> Dict:
        """Analyze competitive landscape"""
        
        industry = business_data.get("business_basics", {}).get("industry_category", "general")
        core_business = business_data.get("business_basics", {}).get("core_business", "")
        
        prompt = f"""As a COMPETITIVE INTELLIGENCE ANALYST, analyze the competitive landscape for:

INDUSTRY: {industry}
CORE BUSINESS: {core_business}

PROVIDE COMPETITIVE ANALYSIS:

{{
  "direct_competitors": [
    {{
      "competitor_type": "",
      "typical_offerings": [],
      "pricing_strategies": [],
      "marketing_approaches": [],
      "strengths": [],
      "weaknesses": []
    }}
  ],
  "competitive_positioning": {{
    "market_segments_covered": [],
    "price_points": [],
    "feature_differentiation": [],
    "service_differentiation": [],
    "brand_perception": ""
  }},
  "competitive_messaging": {{
    "common_value_propositions": [],
    "frequently_used_claims": [],
    "common_cta_phrases": [],
    "typical_offerings": [],
    "guarantee_types": []
  }},
  "advertising_patterns": {{
    "common_ad_formats": [],
    "frequently_used_headlines": [],
    "visual_elements": [],
    "success_metrics_highlighted": [],
    "testimonial_usage": []
  }},
  "opportunity_analysis": {{
    "gaps_in_competitor_offers": [],
    "underserved_segments": [],
    "price_opportunities": [],
    "feature_opportunities": [],
    "messaging_opportunities": []
  }}
}}

ANALYSIS APPROACH:
1. Research typical competitors in this space
2. Analyze their positioning and messaging
3. Identify common advertising patterns
4. Find gaps and opportunities
5. Consider pricing and feature comparisons

Base analysis on MARKET REALITIES for this industry.
Return ONLY valid JSON."""

        response = self._call_ai(prompt, temperature=0.2)
        return self._extract_json(response)
    
    def _create_facebook_ad_creatives(self, business_data: Dict, market_research: Dict, 
                                    audience_analysis: Dict, competitive_analysis: Dict) -> Dict:
        """Create 5 targeted Facebook ad creatives"""
        
        # Prepare context
        business_name = business_data.get("business_basics", {}).get("company_name", "Our Solution")
        core_business = business_data.get("business_basics", {}).get("core_business", "")
        pain_points = business_data.get("problem_solution_matrix", {}).get("primary_customer_problems", [])
        
        personas = audience_analysis.get("primary_buyer_personas", [{}])
        primary_persona = personas[0] if personas else {}
        
        prompt = f"""As a FACEBOOK AD EXPERT, create 5 highly targeted ad creatives based on deep market research.

BUSINESS CONTEXT:
- Company: {business_name}
- Core Business: {core_business}
- Primary Pain Points: {', '.join(pain_points[:3])}

TARGET PERSONA:
{json.dumps(primary_persona, indent=2)}

MARKET INSIGHTS:
{json.dumps(market_research.get('pain_point_hierarchy', {}), indent=2)}

COMPETITIVE LANDSCAPE:
{json.dumps(competitive_analysis.get('competitive_messaging', {}), indent=2)}

CREATE 5 DISTINCT FACEBOOK AD CREATIVES:

{{
  "ad_campaign_strategy": {{
    "campaign_objective": "",
    "primary_audience": "",
    "secondary_audience": "",
    "key_message_themes": [],
    "emotional_appeals": []
  }},
  "ad_creatives": [
    {{
      "ad_name": "Pain-Point Agitator",
      "target_persona": "",
      "primary_goal": "",
      "headline": "",
      "primary_text": "",
      "visual_description": "",
      "call_to_action": "",
      "pain_point_targeted": "",
      "solution_highlighted": "",
      "emotional_trigger": "",
      "social_proof_element": "",
      "estimated_engagement_rate": ""
    }},
    {{
      "ad_name": "Solution Showcase",
      "target_persona": "",
      "primary_goal": "",
      "headline": "",
      "primary_text": "",
      "visual_description": "",
      "call_to_action": "",
      "pain_point_targeted": "",
      "solution_highlighted": "",
      "emotional_trigger": "",
      "social_proof_element": "",
      "estimated_engagement_rate": ""
    }},
    {{
      "ad_name": "Social Proof Hero",
      "target_persona": "",
      "primary_goal": "",
      "headline": "",
      "primary_text": "",
      "visual_description": "",
      "call_to_action": "",
      "pain_point_targeted": "",
      "solution_highlighted": "",
      "emotional_trigger": "",
      "social_proof_element": "",
      "estimated_engagement_rate": ""
    }},
    {{
      "ad_name": "ROI Calculator",
      "target_persona": "",
      "primary_goal": "",
      "headline": "",
      "primary_text": "",
      "visual_description": "",
      "call_to_action": "",
      "pain_point_targeted": "",
      "solution_highlighted": "",
      "emotional_trigger": "",
      "social_proof_element": "",
      "estimated_engagement_rate": ""
    }},
    {{
      "ad_name": "FOMO/Urgency",
      "target_persona": "",
      "primary_goal": "",
      "headline": "",
      "primary_text": "",
      "visual_description": "",
      "call_to_action": "",
      "pain_point_targeted": "",
      "solution_highlighted": "",
      "emotional_trigger": "",
      "social_proof_element": "",
      "estimated_engagement_rate": ""
    }}
  ],
  "ad_optimization_tips": [
    {{
      "testing_recommendation": "",
      "targeting_suggestion": "",
      "bid_strategy": "",
      "placement_recommendation": ""
    }}
  ],
  "performance_metrics": {{
    "expected_ctr_range": "",
    "conversion_goals": [],
    "retargeting_strategy": "",
    "lookalike_audience_suggestions": []
  }}
}}

CREATIVE GUIDELINES:
1. Each ad must target SPECIFIC pain points
2. Include emotional triggers relevant to persona
3. Use industry-appropriate language
4. Include clear CTAs
5. Suggest appropriate visuals
6. Include social proof elements
7. Reference specific benefits/results
8. Create urgency or curiosity
9. Align with buying journey stage
10. Differentiate from competitors

Make ads READY-TO-USE with complete copy.
Return ONLY valid JSON."""

        response = self._call_ai(prompt, temperature=0.4)
        return self._extract_json(response)
    
    def _generate_hashtags(self, business_data: Dict, audience_analysis: Dict) -> Dict:
        """Generate targeted hashtag strategy"""
        
        industry = business_data.get("business_basics", {}).get("industry_category", "")
        personas = audience_analysis.get("primary_buyer_personas", [{}])
        
        prompt = f"""As a SOCIAL MEDIA STRATEGIST, create a comprehensive hashtag strategy for Facebook ads.

INDUSTRY: {industry}
TARGET PERSONAS: {json.dumps(personas[:2], indent=2)}

CREATE HASHTAG STRATEGY:

{{
  "hashtag_categories": {{
    "industry_broad": [],
    "industry_specific": [],
    "pain_point_focused": [],
    "solution_oriented": [],
    "benefit_based": [],
    "role_targeted": [],
    "trending_topics": [],
    "community_hashtags": [],
    "branded_hashtags": []
  }},
  "hashtag_combinations": [
    {{
      "combination_name": "Problem-Solution Mix",
      "hashtags": [],
      "use_case": "",
      "expected_reach": ""
    }},
    {{
      "combination_name": "Industry-Professional Mix",
      "hashtags": [],
      "use_case": "",
      "expected_reach": ""
    }},
    {{
      "combination_name": "Benefit-Action Mix",
      "hashtags": [],
      "use_case": "",
      "expected_reach": ""
    }}
  ],
  "hashtag_guidelines": {{
    "optimal_number_per_post": "",
    "placement_recommendation": "",
    "seasonal_hashtags": [],
    "event_based_hashtags": [],
    "avoid_these_hashtags": []
  }},
  "performance_tips": {{
    "testing_recommendation": "",
    "engagement_strategy": "",
    "community_building": "",
    "hashtag_research_tools": []
  }}
}}

HASHTAG RESEARCH RULES:
1. Research REAL hashtags used in this industry
2. Include hashtags for decision makers
3. Mix broad and specific hashtags
4. Include pain-point hashtags
5. Consider trending industry terms
6. Suggest branded hashtag ideas
7. Provide usage guidelines

Return ONLY valid JSON with ACTUAL hashtags (no placeholders)."""

        response = self._call_ai(prompt, temperature=0.3)
        return self._extract_json(response)
    
    def _call_ai(self, prompt: str, temperature: float = 0.2) -> str:
        """Call OpenRouter API"""
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://market-research.ai",
            "X-Title": "Market Research AI Agent",
        }
        
        data = {
            "model": "google/gemini-2.0-flash-exp:free",
            "messages": [
                {
                    "role": "system",
                    "content": """You are a SENIOR MARKET RESEARCHER and AD CREATIVE EXPERT. 
                    You conduct thorough market research, analyze audiences deeply, 
                    and create highly effective advertising content. 
                    You provide detailed, actionable insights based on real market knowledge."""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": temperature,
            "max_tokens": 4000,
        }
        
        try:
            response = requests.post(self.openrouter_url, headers=headers, json=data, timeout=90)
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
        except Exception as e:
            print(f"❌ AI call error: {e}")
            return json.dumps({"error": str(e)})
    
    def _save_complete_research(self, research_data: Dict, output_dir: str):
        """Save complete research output"""
        
        # Save full research JSON
        research_file = os.path.join(output_dir, "complete_research.json")
        with open(research_file, 'w', encoding='utf-8') as f:
            json.dump(research_data, f, indent=2, ensure_ascii=False)
        
        # Create ready-to-use Facebook ads file
        ads_file = os.path.join(output_dir, "facebook_ads_ready.txt")
        with open(ads_file, 'w', encoding='utf-8') as f:
            self._format_facebook_ads(research_data, f)
        
        # Create executive summary
        summary_file = os.path.join(output_dir, "research_summary.txt")
        with open(summary_file, 'w', encoding='utf-8') as f:
            self._create_executive_summary(research_data, f)
    
    def _format_facebook_ads(self, research_data: Dict, file_handle):
        """Format Facebook ads for immediate use"""
        
        ads = research_data.get("facebook_ad_creatives", {}).get("ad_creatives", [])
        hashtags = research_data.get("hashtag_strategy", {})
        
        file_handle.write("=" * 80 + "\n")
        file_handle.write("🎯 FACEBOOK AD CREATIVES - READY TO USE\n")
        file_handle.write("=" * 80 + "\n\n")
        
        file_handle.write("📊 CAMPAIGN STRATEGY\n")
        file_handle.write("-" * 40 + "\n")
        strategy = research_data.get("facebook_ad_creatives", {}).get("ad_campaign_strategy", {})
        for key, value in strategy.items():
            if isinstance(value, list):
                file_handle.write(f"{key.replace('_', ' ').title()}: {', '.join(value)}\n")
            else:
                file_handle.write(f"{key.replace('_', ' ').title()}: {value}\n")
        
        file_handle.write("\n" + "=" * 80 + "\n")
        file_handle.write("🔄 AD CREATIVES\n")
        file_handle.write("=" * 80 + "\n\n")
        
        for i, ad in enumerate(ads, 1):
            file_handle.write(f"AD #{i}: {ad.get('ad_name', 'Unnamed Ad')}\n")
            file_handle.write("-" * 40 + "\n")
            
            file_handle.write(f"🎯 Target: {ad.get('target_persona', 'N/A')}\n")
            file_handle.write(f"🎯 Goal: {ad.get('primary_goal', 'N/A')}\n")
            file_handle.write(f"💔 Pain Point: {ad.get('pain_point_targeted', 'N/A')}\n")
            file_handle.write(f"✨ Solution: {ad.get('solution_highlighted', 'N/A')}\n")
            file_handle.write(f"😊 Emotional Trigger: {ad.get('emotional_trigger', 'N/A')}\n\n")
            
            file_handle.write("📝 AD COPY:\n")
            file_handle.write(f"HEADLINE: {ad.get('headline', '')}\n\n")
            
            # Format primary text with line breaks
            primary_text = ad.get('primary_text', '')
            wrapped_text = textwrap.fill(primary_text, width=80)
            file_handle.write(f"PRIMARY TEXT:\n{wrapped_text}\n\n")
            
            file_handle.write(f"VISUAL: {ad.get('visual_description', 'N/A')}\n")
            file_handle.write(f"CTA: {ad.get('call_to_action', 'N/A')}\n")
            file_handle.write(f"📊 Expected Engagement: {ad.get('estimated_engagement_rate', 'N/A')}\n\n")
            
            file_handle.write("🏷️ RECOMMENDED HASHTAGS:\n")
            if "hashtag_categories" in hashtags:
                # Get relevant hashtags
                categories = ["pain_point_focused", "solution_oriented", "industry_specific"]
                for category in categories:
                    if category in hashtags["hashtag_categories"]:
                        tags = hashtags["hashtag_categories"][category][:5]
                        if tags:
                            file_handle.write(f"  {category.replace('_', ' ').title()}: ")
                            file_handle.write(f"{' '.join(['#' + tag for tag in tags])}\n")
            
            file_handle.write("\n" + "=" * 80 + "\n\n")
        
        # Add hashtag strategy
        file_handle.write("=" * 80 + "\n")
        file_handle.write("🏷️ COMPLETE HASHTAG STRATEGY\n")
        file_handle.write("=" * 80 + "\n\n")
        
        if "hashtag_categories" in hashtags:
            for category, tags in hashtags["hashtag_categories"].items():
                if tags:
                    file_handle.write(f"{category.replace('_', ' ').upper()}:\n")
                    tag_groups = [tags[i:i+10] for i in range(0, len(tags), 10)]
                    for group in tag_groups:
                        file_handle.write(f"  {' '.join(['#' + tag for tag in group])}\n")
                    file_handle.write("\n")
    
    def _create_executive_summary(self, research_data: Dict, file_handle):
        """Create executive summary"""
        
        business = research_data.get("business_fundamentals", {}).get("business_basics", {})
        market = research_data.get("market_research", {})
        audience = research_data.get("audience_analysis", {})
        
        file_handle.write("=" * 80 + "\n")
        file_handle.write("📊 MARKET RESEARCH EXECUTIVE SUMMARY\n")
        file_handle.write("=" * 80 + "\n\n")
        
        file_handle.write("🏢 BUSINESS OVERVIEW\n")
        file_handle.write("-" * 40 + "\n")
        file_handle.write(f"Company: {business.get('company_name', 'N/A')}\n")
        file_handle.write(f"Industry: {business.get('industry_category', 'N/A')}\n")
        file_handle.write(f"Core Business: {business.get('core_business', 'N/A')}\n")
        file_handle.write(f"Primary Offering: {business.get('primary_product_service', 'N/A')}\n\n")
        
        file_handle.write("🎯 KEY FINDINGS\n")
        file_handle.write("-" * 40 + "\n")
        
        # Top pain points
        pains = research_data.get("business_fundamentals", {}).get("problem_solution_matrix", {}).get("primary_customer_problems", [])
        if pains:
            file_handle.write("Primary Pain Points Identified:\n")
            for i, pain in enumerate(pains[:5], 1):
                file_handle.write(f"  {i}. {pain}\n")
            file_handle.write("\n")
        
        # Target audience
        personas = audience.get("primary_buyer_personas", [])
        if personas:
            file_handle.write("Primary Target Personas:\n")
            for persona in personas[:2]:
                file_handle.write(f"  • {persona.get('persona_name', 'Persona')}: ")
                file_handle.write(f"{persona.get('job_title', '')}\n")
            file_handle.write("\n")
        
        # Market opportunities
        opportunities = research_data.get("competitive_analysis", {}).get("opportunity_analysis", {}).get("gaps_in_competitor_offers", [])
        if opportunities:
            file_handle.write("Key Market Opportunities:\n")
            for i, opportunity in enumerate(opportunities[:3], 1):
                file_handle.write(f"  {i}. {opportunity}\n")
            file_handle.write("\n")
        
        # Ad strategy
        ads = research_data.get("facebook_ad_creatives", {}).get("ad_creatives", [])
        if ads:
            file_handle.write("📱 AD CREATIVE STRATEGY\n")
            file_handle.write("-" * 40 + "\n")
            file_handle.write(f"Total Ads Created: {len(ads)}\n")
            file_handle.write("Ad Approaches:\n")
            for ad in ads:
                file_handle.write(f"  • {ad.get('ad_name')}: {ad.get('primary_goal')}\n")
        
        file_handle.write("\n" + "=" * 80 + "\n")
        file_handle.write("✅ RESEARCH COMPLETE - READY FOR IMPLEMENTATION\n")
        file_handle.write("=" * 80 + "\n")
    
    # ============================================================================
    # HELPER METHODS (Keep from original)
    # ============================================================================
    
    def _validate_url(self, url: str) -> Optional[str]:
        """Validate and format URL"""
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        try:
            parsed = urlparse(url)
            return url if parsed.netloc else None
        except:
            return None
    
    def _scrape_website(self, url: str) -> Dict:
        """Scrape website with Apify"""
        print(f"\n🔍 SCRAPING WEBSITE")
        print("-" * 40)
        print(f"URL: {url}")
        
        run_input = {
            "startUrls": [{ "url": url }],
            "crawlerType": "playwright:adaptive",
            "maxCrawlDepth": 2,
            "maxCrawlPages": 10,
            "dynamicContentWaitSecs": 10,
            "saveMarkdown": True,
            "saveHtml": True,
            "saveFiles": True,
            "htmlTransformer": "readableText",
            "removeElementsCssSelector": "nav, footer, script, style, noscript",
            "proxyConfiguration": { "useApifyProxy": True },
            "ignoreHttpsErrors": False,
            "maxScrollHeightPixels": 2000,
        }
        
        try:
            run = self.apify_client.actor("aYG0l9s7dbB7j3gbS").call(run_input=run_input)
            print(f"✅ Scraper started: {run['id']}")
            
            # Wait for completion
            print("⏳ Scraping ", end="", flush=True)
            for _ in range(15):
                time.sleep(2)
                print(".", end="", flush=True)
            print()
            
            # Collect results
            dataset_id = run["defaultDatasetId"]
            pages = []
            
            for item in self.apify_client.dataset(dataset_id).iterate_items():
                pages.append(item)
            
            print(f"✅ Found {len(pages)} pages")
            
            return {
                "success": True,
                "url": url,
                "pages": pages,
                "total_pages": len(pages),
                "scraped_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Scraping error: {e}")
            return self._error_response(str(e), url)
    
    def _save_scraped_content(self, scraped_data: Dict) -> str:
        """Save all scraped content to files"""
        output_dir = f"market_research_{self.session_id}"
        os.makedirs(output_dir, exist_ok=True)
        
        # Create pages directory
        pages_dir = os.path.join(output_dir, "pages")
        os.makedirs(pages_dir, exist_ok=True)
        
        pages = scraped_data["pages"]
        all_text = []
        
        print(f"\n💾 SAVING SCRAPED CONTENT")
        print("-" * 40)
        
        for i, page in enumerate(pages):
            page_data = {
                "url": page.get("url", ""),
                "metadata": page.get("metadata", {}),
                "scraped_at": datetime.now().isoformat()
            }
            
            # Save page metadata
            page_file = os.path.join(pages_dir, f"page_{i+1:02d}.json")
            with open(page_file, 'w', encoding='utf-8') as f:
                json.dump(page_data, f, indent=2, ensure_ascii=False)
            
            # Save markdown content if available
            if 'markdown' in page and page['markdown']:
                md_file = os.path.join(pages_dir, f"page_{i+1:02d}.md")
                with open(md_file, 'w', encoding='utf-8') as f:
                    f.write(page['markdown'])
                
                # Add to combined text
                page_text = f"\n{'='*60}\nPAGE {i+1}: {page.get('url', 'Unknown')}\n{'='*60}\n"
                
                # Add metadata
                if 'metadata' in page:
                    meta = page['metadata']
                    if 'title' in meta and meta['title']:
                        page_text += f"Title: {meta['title']}\n"
                    if 'description' in meta and meta['description']:
                        page_text += f"Description: {meta['description']}\n"
                
                page_text += "\nContent:\n" + page['markdown'][:3000] + "\n"
                all_text.append(page_text)
        
        # Save combined content
        combined_file = os.path.join(output_dir, "combined_content.txt")
        with open(combined_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(all_text))
        
        # Save metadata
        metadata = {
            "url": scraped_data["url"],
            "total_pages": len(pages),
            "scraped_at": scraped_data["scraped_at"],
            "session_id": self.session_id,
            "files": {
                "pages_directory": pages_dir,
                "combined_content": combined_file
            }
        }
        
        metadata_file = os.path.join(output_dir, "metadata.json")
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Saved {len(pages)} pages")
        print(f"✅ Combined content: {len(''.join(all_text)):,} characters")
        
        return output_dir
    
    def _extract_json(self, text: str) -> Dict:
        """Extract JSON from AI response"""
        try:
            # Try to find JSON object
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                # Clean up JSON
                json_str = re.sub(r',\s*}', '}', json_str)
                json_str = re.sub(r',\s*]', ']', json_str)
                return json.loads(json_str)
            else:
                return json.loads(text)
        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing error: {e}")
            return {"error": "Failed to parse AI response", "raw_response": text[:500]}
    
    def _error_response(self, error: str, context: str) -> Dict:
        """Create error response"""
        return {
            "success": False,
            "error": error,
            "context": context,
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat()
        }


# ============================================================================
# MAIN EXECUTION WITH NEW MODES
# ============================================================================

def main():
    print("🔬 MARKET RESEARCH AI AGENT - BUSINESS ANALYSIS & AD CREATION")
    print("=" * 80)
    print("Modes:")
    print("  1. Scrape only (save content for later)")
    print("  2. Full market research & ad creation")
    print("  3. Research saved content")
    print("=" * 80)
    
    # Get API keys
    apify_key = input("\nEnter Apify API key (required): ").strip()
    if not apify_key:
        print("❌ Apify API key required")
        return
    
    openrouter_key = input("Enter OpenRouter API key (required for research): ").strip()
    
    researcher = MarketResearchAI(apify_key, openrouter_key)
    
    while True:
        print("\n" + "=" * 80)
        print("\nSELECT MODE:")
        print("  1. Scrape website only (save content)")
        print("  2. Full market research & create Facebook ads")
        print("  3. Research saved content file")
        print("  q. Quit")
        
        mode = input("\nEnter mode (1/2/3/q): ").strip().lower()
        
        if mode == 'q':
            print("\n👋 Goodbye!")
            break
        
        if mode == '1':
            # Mode 1: Scrape only
            url = input("\nEnter website URL to scrape: ").strip()
            if not url:
                print("❌ URL required")
                continue
            
            try:
                print(f"\n🔍 Scraping: {url}")
                result = researcher.scrape_website_only(url)
                
                if result.get("success"):
                    print(f"\n✅ Success! Content saved to: {result['output_dir']}/")
                    print(f"📄 You can research it later with mode 3")
                else:
                    print(f"\n❌ Failed: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                print(f"\n❌ Error: {e}")
        
        elif mode == '2':
            # Mode 2: Full research pipeline
            if not openrouter_key:
                print("❌ OpenRouter API key required for research")
                continue
            
            url = input("\nEnter website URL to research: ").strip()
            if not url:
                print("❌ URL required")
                continue
            
            try:
                print(f"\n🔬 Starting market research for: {url}")
                result = researcher.research_and_create_ads(url)
                
                if "business_fundamentals" in result:
                    print(f"\n✅ MARKET RESEARCH COMPLETE!")
                    
                    # Quick preview
                    business = result.get("business_fundamentals", {}).get("business_basics", {})
                    ads = result.get("facebook_ad_creatives", {}).get("ad_creatives", [])
                    hashtags = result.get("hashtag_strategy", {}).get("hashtag_categories", {})
                    
                    print(f"\n📊 Quick Summary:")
                    print(f"   🏢 Company: {business.get('company_name', 'N/A')}")
                    print(f"   🎯 Ads Created: {len(ads)}")
                    
                    if "industry_specific" in hashtags:
                        print(f"   🏷️ Top Hashtags: {', '.join(['#' + tag for tag in hashtags['industry_specific'][:3]])}")
                    
                    print(f"\n📁 Results saved with READY-TO-USE Facebook ad creatives!")
                else:
                    print(f"\n⚠️ Research may have issues")
                    
            except Exception as e:
                print(f"\n❌ Error: {e}")
        
        elif mode == '3':
            # Mode 3: Research saved content
            if not openrouter_key:
                print("❌ OpenRouter API key required for research")
                continue
            
            content_file = input("\nEnter path to saved content file (combined_content.txt): ").strip()
            if not content_file or not os.path.exists(content_file):
                print(f"❌ File not found: {content_file}")
                continue
            
            website_url = input("Enter website URL (for context): ").strip()
            
            try:
                print(f"\n🔬 Researching saved content...")
                result = researcher.research_and_create_ads(website_url, content_file)
                
                if "business_fundamentals" in result:
                    print(f"\n✅ RESEARCH COMPLETE!")
                    
                    # Show ad preview
                    ads = result.get("facebook_ad_creatives", {}).get("ad_creatives", [])
                    if ads:
                        print(f"\n📱 Sample Ad Headlines:")
                        for i, ad in enumerate(ads[:2], 1):
                            print(f"  {i}. {ad.get('headline')}")
                    
                    print(f"\n🎯 Check the output folder for complete Facebook ad creatives!")
                else:
                    print(f"\n⚠️ Research may have issues")
                    
            except Exception as e:
                print(f"\n❌ Error: {e}")
        
        else:
            print("❌ Invalid mode. Please enter 1, 2, 3, or q")


if __name__ == "__main__":
    main()