"""Seeded, editable SiteForge starter templates stored as GrapesJS project JSON."""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from .models import WebsiteTemplate, WebsiteTemplatePage


def _style(**values: str) -> str:
    return ";".join(f"{key.replace('_', '-')}: {value}" for key, value in values.items())


def _el(tag: str, text: str | None = None, *, styles: dict[str, str] | None = None,
        children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    component: dict[str, Any] = {"tagName": tag, "attributes": {}}
    if styles:
        component["attributes"]["style"] = _style(**styles)
    component["components"] = children if children is not None else ([{"type": "textnode", "content": text}] if text else [])
    return component


def _project(name: str, colors: tuple[str, str, str], page: str) -> dict[str, Any]:
    primary, accent, surface = colors
    title = {
        "Home": "Your story starts here",
        "About": "Built around what matters",
        "Contact": "Let’s talk",
        "Services": "What we do",
        "Projects": "Selected work",
        "Menu": "Made fresh, served with care",
        "Sermons": "Messages for every season",
        "Shop": "Find something you’ll love",
    }.get(page, page)
    subtitle = {
        "Home": "A warm, clear introduction to your business. Replace this copy with your own story.",
        "About": "Tell visitors who you are, what you believe in, and how you serve your community.",
        "Contact": "Questions, ideas, or ready to get started? We’d love to hear from you.",
        "Services": "Explore practical ways our team can help you reach your goals.",
        "Projects": "A few examples of the work we’re proud to share.",
        "Menu": "Explore seasonal favourites made with care and quality ingredients.",
        "Sermons": "Watch or listen to recent teaching and encouragement.",
        "Shop": "Discover carefully selected products from our latest collection.",
    }.get(page, "Add a short introduction for your visitors.")
    nav_items = ["Home", "About", "Contact", "Services"]
    header = _el("header", styles={"background": surface, "padding": "24px 6%", "display": "flex", "justify_content": "space-between", "align_items": "center"}, children=[
        _el("strong", "YOUR BRAND", styles={"color": primary, "font_size": "22px", "letter_spacing": "-0.03em"}),
        _el("nav", children=[_el("span", "   ".join(nav_items), styles={"color": primary, "font_size": "14px"})]),
    ])
    hero = _el("section", styles={"background": primary, "color": "#ffffff", "padding": "96px 8%", "min_height": "430px", "display": "flex", "flex_direction": "column", "justify_content": "center"}, children=[
        _el("p", name.upper(), styles={"color": accent, "font_size": "13px", "letter_spacing": "0.14em", "font_weight": "700"}),
        _el("h1", title, styles={"font_size": "clamp(38px, 6vw, 72px)", "line_height": "1.04", "max_width": "820px", "margin": "18px 0"}),
        _el("p", subtitle, styles={"font_size": "19px", "line_height": "1.7", "max_width": "620px", "color": "#e5e7eb"}),
        _el("a", "Get in touch  →", styles={"display": "inline-block", "margin_top": "28px", "padding": "14px 22px", "background": accent, "color": "#111827", "font_weight": "700", "text_decoration": "none", "width": "fit-content", "border_radius": "8px"}),
    ])
    cards = _el("section", styles={"padding": "64px 8%", "background": "#ffffff"}, children=[
        _el("h2", "Made for your next chapter", styles={"color": primary, "font_size": "32px", "margin_bottom": "24px"}),
        _el("div", styles={"display": "grid", "grid_template_columns": "repeat(auto-fit, minmax(210px, 1fr))", "gap": "18px"}, children=[
            _el("article", styles={"padding": "24px", "border": "1px solid #e5e7eb", "border_radius": "12px"}, children=[
                _el("h3", label, styles={"color": primary, "font_size": "19px"}),
                _el("p", "Add a useful detail about this offer, product, or part of your story.", styles={"color": "#6b7280", "line_height": "1.6"}),
            ]) for label in ["Thoughtful service", "Made with care", "Here to help"]
        ]),
    ])
    footer = _el("footer", "YOUR BRAND  ·  hello@example.com  ·  +263 00 000 0000", styles={"background": "#111827", "color": "#ffffff", "padding": "32px 8%", "text_align": "center"})
    return {"assets": [], "styles": [], "pages": [{"name": page, "component": {"type": "wrapper", "components": [header, hero, cards, footer]}}]}


CATALOG: list[dict[str, Any]] = [
    {"name": "Business Landing", "slug": "business-landing", "category": "Business", "description": "A confident, flexible site for service businesses and growing companies.", "colors": ("#172554", "#38bdf8", "#f8fafc"), "pages": ["Home", "About", "Services", "Contact"]},
    {"name": "Personal Portfolio", "slug": "personal-portfolio", "category": "Portfolio", "description": "A clean portfolio for creatives, consultants, and independent professionals.", "colors": ("#18181b", "#a3e635", "#fafafa"), "pages": ["Home", "About", "Projects", "Contact"]},
    {"name": "Restaurant & Café", "slug": "restaurant-cafe", "category": "Food & Drink", "description": "A welcoming menu-first website for restaurants, cafés, and caterers.", "colors": ("#431407", "#fb923c", "#fff7ed"), "pages": ["Home", "About", "Menu", "Contact"]},
    {"name": "Church & Ministry", "slug": "church-ministry", "category": "Community", "description": "A calm, welcoming home for a church, ministry, or community organisation.", "colors": ("#312e81", "#c4b5fd", "#f5f3ff"), "pages": ["Home", "About", "Sermons", "Contact"]},
    {"name": "Online Store", "slug": "online-store", "category": "E-commerce", "description": "A product-focused storefront with clear categories and shopping calls to action.", "colors": ("#064e3b", "#34d399", "#ecfdf5"), "pages": ["Home", "About", "Shop", "Contact"]},
]


def ensure_starter_templates(db: Session) -> None:
    """Create missing built-in templates without overwriting administrator edits."""
    added = False
    for item in CATALOG:
        if db.query(WebsiteTemplate.id).filter(WebsiteTemplate.slug == item["slug"]).first():
            continue
        primary, accent, surface = item["colors"]
        template = WebsiteTemplate(
            name=item["name"], slug=item["slug"], description=item["description"],
            category=item["category"], is_published=True,
            thumbnail_url=None, preview_url=None,
        )
        db.add(template)
        db.flush()
        colors = (primary, accent, surface)
        for order, page_name in enumerate(item["pages"]):
            db.add(WebsiteTemplatePage(
                template_id=template.id,
                page_name=page_name,
                route_path="/" if page_name == "Home" else f"/{page_name.lower()}",
                sort_order=order,
                grapesjs_project_json=_project(item["name"], colors, page_name),
            ))
        added = True
    if added:
        db.commit()
