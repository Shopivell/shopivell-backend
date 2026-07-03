# modules/website_builder/generation_service.py
"""Service for AI-powered website generation"""

import json
import logging
import re
from typing import Dict, List, Optional, Any
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from modules.openrouter.service import openrouter_client
from modules.stores.models import Store
from modules.products.models import Product
from modules.whatsapp.models import FAQ

from .models import Website, WebsiteGeneration, WebsiteStatus, GenerationStatus
from .prompts import PROMPTS, INTEGRATION_SNIPPETS, CHAT_REFINEMENT_PROMPT

logger = logging.getLogger(__name__)

# Default theme
DEFAULT_THEME = {
    "primary_color": "#3B82F6",
    "secondary_color": "#1F2937",
    "accent_color": "#10B981",
    "font_family": "Inter, sans-serif"
}


class WebsiteGenerationService:
    """Service for generating websites using AI"""

    def __init__(self):
        self.client = openrouter_client

    def _get_store_data(self, db: Session, store_id: UUID) -> Dict[str, Any]:
        """Fetch and format store data for AI context"""
        store = db.query(Store).filter(Store.id == store_id).first()
        if not store:
            raise ValueError(f"Store not found: {store_id}")

        return {
            "name": store.store_name,
            "description": store.store_description or store.store_voice or "",
            "category": store.store_category or "General",
            "phone": store.store_phone or "",
            "email": store.store_email or "",
            "address": store.store_address or "",
            "city": store.store_city or "",
            "country": store.store_country or "",
            "operating_hours": store.operating_hours or {},
            "currency": store.currency or "USD",
            "logo_url": store.logo_url or "",
            "color_theme": store.color_theme or DEFAULT_THEME["primary_color"],
            "tone": store.store_tone or "professional",
            "voice": store.store_voice or "",
        }

    def _get_products_data(self, db: Session, store_id: UUID, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch and format products for AI context"""
        products = db.query(Product).filter(
            Product.store_id == store_id,
            Product.status == "Active"
        ).limit(limit).all()

        return [
            {
                "id": str(p.id),
                "title": p.title,
                "description": p.description or "",
                "price": p.price,
                "category": p.category or "Uncategorized",
                "image_url": p.image_url or f"https://picsum.photos/seed/{p.id}/400/400",
                "available": p.available > 0,
            }
            for p in products
        ]

    def _get_faqs_data(self, db: Session, store_id: UUID) -> List[Dict[str, Any]]:
        """Fetch and format FAQs for AI context"""
        faqs = db.query(FAQ).filter(
            FAQ.store_id == store_id,
            FAQ.is_active == True
        ).order_by(FAQ.display_order).all()

        return [
            {
                "question": f.question,
                "answer": f.answer,
                "category": f.category or "general",
            }
            for f in faqs
        ]

    def _build_generation_context(
        self,
        store_data: Dict[str, Any],
        products: List[Dict[str, Any]],
        faqs: List[Dict[str, Any]],
        user_prompt: str
    ) -> str:
        """Build the full context string for AI generation"""
        context = f"""
STORE INFORMATION:
- Name: {store_data['name']}
- Description: {store_data['description']}
- Category: {store_data['category']}
- Phone: {store_data['phone']}
- Email: {store_data['email']}
- Address: {store_data['address']}, {store_data['city']}, {store_data['country']}
- Currency: {store_data['currency']}
- Brand Tone: {store_data['tone']}

BRANDING:
- Primary Color: {store_data['color_theme']}
- Logo URL: {store_data['logo_url']}

PRODUCTS ({len(products)} items):
"""
        for p in products[:10]:  # Limit to first 10 for context
            context += f"""
- {p['title']}
  Price: {store_data['currency']} {p['price']}
  Description: {p['description'][:100]}...
  Image: {p['image_url']}
"""

        if faqs:
            context += f"\nFAQs ({len(faqs)} items):\n"
            for faq in faqs[:5]:  # Limit FAQs
                context += f"Q: {faq['question']}\nA: {faq['answer'][:150]}...\n\n"

        context += f"\nUSER'S REQUEST:\n{user_prompt}"

        return context

    def _extract_html(self, response: Dict[str, Any]) -> str:
        """Extract HTML from AI response"""
        try:
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")

            # Try to extract HTML from code blocks if present
            html_match = re.search(r'```html?\s*([\s\S]*?)\s*```', content, re.IGNORECASE)
            if html_match:
                return html_match.group(1).strip()

            # If content starts with <!DOCTYPE or <html, return as-is
            if content.strip().startswith('<!DOCTYPE') or content.strip().startswith('<html'):
                return content.strip()

            # Otherwise return the content (might be just HTML without doctype)
            return content.strip()

        except Exception as e:
            logger.error(f"Error extracting HTML: {e}")
            return ""

    def _apply_theme_colors(self, html: str, theme: Dict[str, Any]) -> str:
        """Replace color placeholders with actual theme colors"""
        html = html.replace("{PRIMARY_COLOR}", theme.get("primary_color", DEFAULT_THEME["primary_color"]))
        html = html.replace("{SECONDARY_COLOR}", theme.get("secondary_color", DEFAULT_THEME["secondary_color"]))
        html = html.replace("{ACCENT_COLOR}", theme.get("accent_color", DEFAULT_THEME["accent_color"]))
        return html

    def _inject_integrations(self, html: str, integrations: Dict[str, Any]) -> str:
        """Inject integration scripts into HTML"""
        integration_scripts = []

        for integration_name, config in integrations.items():
            if config and integration_name in INTEGRATION_SNIPPETS:
                snippet = INTEGRATION_SNIPPETS[integration_name]

                # Replace config placeholders
                if integration_name == "stripe" and isinstance(config, dict):
                    snippet = snippet.replace("{STRIPE_PUBLIC_KEY}", config.get("public_key", ""))
                elif integration_name == "google_analytics" and isinstance(config, dict):
                    snippet = snippet.replace("{GA_TRACKING_ID}", config.get("tracking_id", ""))
                elif integration_name == "paynow" and isinstance(config, dict):
                    snippet = snippet.replace("{PAYNOW_INTEGRATION_ID}", config.get("integration_id", ""))
                    snippet = snippet.replace("{PAYNOW_INTEGRATION_KEY}", config.get("integration_key", ""))

                integration_scripts.append(snippet)

        if integration_scripts:
            # Inject before </head> or at end of <head>
            scripts_html = "\n".join(integration_scripts)
            if "</head>" in html:
                html = html.replace("</head>", f"{scripts_html}\n</head>")
            else:
                html = f"{scripts_html}\n{html}"

        return html

    async def generate_page(
        self,
        screen_type: str,
        context: str,
        theme: Dict[str, Any]
    ) -> str:
        """Generate a single page using AI"""
        if screen_type not in PROMPTS:
            logger.warning(f"Unknown screen type: {screen_type}, using homepage")
            screen_type = "homepage"

        system_prompt = PROMPTS[screen_type]

        try:
            response = await self.client.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": context}
                ],
                model="anthropic/claude-sonnet-4.6",
                temperature=0.7,
                max_tokens=8000
            )

            html = self._extract_html(response)
            html = self._apply_theme_colors(html, theme)

            return html

        except Exception as e:
            logger.error(f"Error generating {screen_type}: {e}")
            raise

    def _compile_website(self, pages: Dict[str, str], theme: Dict[str, Any]) -> str:
        """Compile all pages into a single preview HTML with navigation"""
        # For preview, we'll show the homepage
        homepage = pages.get("homepage", "")

        if not homepage:
            # Create a simple placeholder
            return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Website Preview</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 flex items-center justify-center min-h-screen">
    <div class="text-center">
        <h1 class="text-2xl font-bold text-gray-800">No pages generated yet</h1>
        <p class="text-gray-600 mt-2">Select screens and generate your website</p>
    </div>
</body>
</html>
"""

        return homepage

    async def generate_website(
        self,
        db: Session,
        website: Website,
        generation: WebsiteGeneration,
        prompt: str,
        screens: List[str]
    ) -> None:
        """
        Generate a complete website.
        Updates the generation and website records as it progresses.
        """
        try:
            # Update status to processing
            generation.status = GenerationStatus.PROCESSING
            generation.started_at = datetime.utcnow()
            generation.progress = 0
            db.commit()

            # Fetch store data
            generation.current_step = "Fetching store data..."
            generation.progress = 10
            db.commit()

            store_data = self._get_store_data(db, website.store_id)
            products = self._get_products_data(db, website.store_id)
            faqs = self._get_faqs_data(db, website.store_id)

            # Build theme from store data
            theme = {
                "primary_color": store_data.get("color_theme", DEFAULT_THEME["primary_color"]),
                "secondary_color": DEFAULT_THEME["secondary_color"],
                "accent_color": DEFAULT_THEME["accent_color"],
                "font_family": DEFAULT_THEME["font_family"],
                "logo_url": store_data.get("logo_url", ""),
            }

            # Build context
            context = self._build_generation_context(store_data, products, faqs, prompt)

            # Generate each page
            pages = {}
            total_screens = len(screens)

            for idx, screen in enumerate(screens):
                generation.current_step = f"Generating {screen} page..."
                generation.progress = 10 + (80 * (idx / total_screens))
                db.commit()

                logger.info(f"Generating {screen} for website {website.id}")

                page_html = await self.generate_page(screen, context, theme)
                pages[screen] = page_html

            # Compile preview
            generation.current_step = "Compiling website..."
            generation.progress = 90
            db.commit()

            preview_html = self._compile_website(pages, theme)

            # Apply integrations if any
            if website.integrations:
                preview_html = self._inject_integrations(preview_html, website.integrations)

            # Update website
            website.pages = pages
            website.theme = theme
            website.preview_html = preview_html
            website.status = WebsiteStatus.READY
            website.updated_at = datetime.utcnow()

            # Update generation
            generation.status = GenerationStatus.COMPLETED
            generation.progress = 100
            generation.current_step = "Complete!"
            generation.generated_pages = pages
            generation.completed_at = datetime.utcnow()

            db.commit()

            logger.info(f"Website generation completed for {website.id}")

        except Exception as e:
            logger.error(f"Website generation failed: {e}")

            generation.status = GenerationStatus.FAILED
            generation.error_message = str(e)
            generation.completed_at = datetime.utcnow()

            website.status = WebsiteStatus.FAILED

            db.commit()
            raise

    async def refine_website(
        self,
        db: Session,
        website: Website,
        user_message: str
    ) -> Dict[str, Any]:
        """Refine the website based on user feedback via chat"""
        try:
            prompt = CHAT_REFINEMENT_PROMPT.format(
                current_html=website.preview_html[:10000],  # Limit context
                user_message=user_message
            )

            response = await self.client.chat_completion(
                messages=[
                    {"role": "system", "content": "You are a web designer helping refine a website. Output only HTML."},
                    {"role": "user", "content": prompt}
                ],
                model="anthropic/claude-sonnet-4.6",
                temperature=0.5,
                max_tokens=8000
            )

            updated_html = self._extract_html(response)

            if updated_html and len(updated_html) > 100:
                # Apply theme and integrations
                updated_html = self._apply_theme_colors(updated_html, website.theme or {})
                if website.integrations:
                    updated_html = self._inject_integrations(updated_html, website.integrations)

                # Update website
                website.preview_html = updated_html
                website.updated_at = datetime.utcnow()
                db.commit()

                return {
                    "message": "I've made the changes you requested. Check the preview to see the updates!",
                    "updated_html": updated_html
                }
            else:
                return {
                    "message": "I understood your request, but I couldn't generate the updated HTML. Could you try rephrasing your request?",
                    "updated_html": None
                }

        except Exception as e:
            logger.error(f"Error refining website: {e}")
            return {
                "message": f"Sorry, I encountered an error: {str(e)}. Please try again.",
                "updated_html": None
            }


# Singleton instance
website_generation_service = WebsiteGenerationService()
