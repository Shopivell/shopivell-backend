"""Seeded, editable, responsive Shopivell website templates."""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from .models import WebsiteTemplate, WebsiteTemplatePage


def _style(**values: str) -> str:
    return ";".join(f"{key.replace('_', '-')}: {value}" for key, value in values.items())


def _el(
    tag: str,
    text: str | None = None,
    *,
    styles: dict[str, str] | None = None,
    children: list[dict[str, Any]] | None = None,
    attrs: dict[str, str] | None = None,
) -> dict[str, Any]:
    attributes = dict(attrs or {})
    if styles:
        attributes["style"] = _style(**styles)
    component: dict[str, Any] = {"tagName": tag, "attributes": attributes}
    component["components"] = children if children is not None else ([{"type": "textnode", "content": text}] if text else [])
    return component


def _button(label: str, href: str, *, background: str, color: str = "#ffffff") -> dict[str, Any]:
    return _el("a", label, attrs={"href": href}, styles={
        "display": "inline-block", "padding": "14px 22px", "background": background,
        "color": color, "border_radius": "999px", "font_weight": "700",
        "text_decoration": "none", "margin_top": "14px",
    })


def _text(text: str, *, color: str = "#52606d", size: str = "16px", **styles: str) -> dict[str, Any]:
    return _el("p", text, styles={"color": color, "font_size": size, "line_height": "1.75", **styles})


def _section(children: list[dict[str, Any]], *, background: str, color: str = "#17212b", padding: str = "72px 8%", **styles: str) -> dict[str, Any]:
    return _el("section", styles={"background": background, "color": color, "padding": padding, **styles}, children=children)


def _header(name: str, *, background: str, color: str, accent: str, links: list[str]) -> dict[str, Any]:
    nav = _el("nav", styles={"display": "flex", "gap": "22px", "align_items": "center", "flex_wrap": "wrap"}, children=[
        _el("a", label, attrs={"href": "#" + label.lower().replace(" ", "-")}, styles={"color": color, "font_size": "14px", "text_decoration": "none"})
        for label in links
    ])
    return _el("header", styles={"background": background, "color": color, "padding": "20px 7%", "display": "flex", "justify_content": "space-between", "align_items": "center", "gap": "18px", "flex_wrap": "wrap", "border_bottom": f"1px solid {accent}33"}, children=[
        _el("strong", name, styles={"font_size": "21px", "letter_spacing": "-0.04em", "color": color}), nav,
    ])


def _footer(name: str, *, background: str, color: str, accent: str, note: str) -> dict[str, Any]:
    return _el("footer", styles={"background": background, "color": color, "padding": "32px 8%", "display": "flex", "justify_content": "space-between", "align_items": "center", "gap": "14px", "flex_wrap": "wrap", "border_top": f"1px solid {accent}55"}, children=[
        _el("strong", name, styles={"font_size": "17px"}),
        _el("span", note, styles={"font_size": "13px", "opacity": "0.8"}),
    ])


def _business(page: str, name: str) -> dict[str, Any]:
    ink, blue, paper = "#10253f", "#4f8cff", "#f4f7fb"
    heading, intro = {
        "Home": ("Make your next move\nwith confidence.", "Clear thinking, thoughtful service, and a team invested in your progress."),
        "About": ("Good work starts\nwith listening.", "Meet the people and principles behind the work. We keep the process clear and the details considered."),
        "Services": ("Practical help.\nMeasurable progress.", "Flexible support shaped around your priorities, your people, and the way you work."),
        "Contact": ("Let’s talk about\nwhat comes next.", "Tell us where you want to go. We’ll help you map out a practical first step."),
    }.get(page, (page, "Thoughtful support for your next chapter."))
    header = _header(name, background="#ffffff", color=ink, accent=blue, links=["Home", "About", "Services", "Contact"])
    hero = _section([
        _el("p", "INDEPENDENT THINKING · HUMAN SERVICE", styles={"color": blue, "font_size": "11px", "letter_spacing": ".18em", "font_weight": "800"}),
        _el("h1", heading, styles={"color": ink, "font_size": "clamp(42px, 6vw, 76px)", "line_height": "1.02", "letter_spacing": "-.055em", "white_space": "pre-line", "max_width": "780px", "margin": "18px 0"}),
        _text(intro, color="#52657a", size="18px", max_width="560px"),
        _button("Book an introduction  →", "/contact", background=ink),
        _el("div", styles={"margin_top": "46px", "display": "grid", "grid_template_columns": "repeat(auto-fit,minmax(150px,1fr))", "gap": "12px"}, children=[
            _el("div", styles={"background": "#ffffff", "padding": "20px", "border_radius": "14px", "box_shadow": "0 14px 40px #10253f12"}, children=[_el("strong", label, styles={"display": "block", "font_size": "23px", "color": ink}), _el("span", caption, styles={"font_size": "13px", "color": "#63758a"})])
            for label, caption in [("01", "Listen first"), ("02", "Plan together"), ("03", "Deliver with care")]
        ]),
    ], background=paper, padding="78px 9%")
    services = _section([
        _el("p", "HOW WE HELP", styles={"color": blue, "font_size": "11px", "letter_spacing": ".18em", "font_weight": "800"}),
        _el("h2", "A thoughtful partner\nfor the work ahead.", styles={"color": ink, "font_size": "clamp(30px,4vw,48px)", "line_height": "1.1", "white_space": "pre-line", "letter_spacing": "-.04em", "max_width": "650px"}),
        _el("div", styles={"display": "grid", "grid_template_columns": "repeat(auto-fit,minmax(220px,1fr))", "gap": "16px", "margin_top": "28px"}, children=[
            _el("article", styles={"border": "1px solid #e4eaf1", "border_radius": "16px", "padding": "24px", "background": "#ffffff"}, children=[
                _el("span", number, styles={"color": blue, "font_size": "12px", "font_weight": "800"}),
                _el("h3", title, styles={"color": ink, "font_size": "19px", "margin": "12px 0 6px"}),
                _text(copy, size="14px"),
            ]) for number, title, copy in [("01", "Strategy", "Find the clearest path from your challenge to a useful outcome."), ("02", "Expert delivery", "Bring the right skills together and keep the work moving."), ("03", "Ongoing support", "Build a dependable relationship beyond the first milestone.")]
        ]),
    ], background="#ffffff")
    return {"type": "wrapper", "components": [header, hero, services, _footer(name, background=ink, color="#ffffff", accent=blue, note="Thoughtful work. Built on trust.")]}


def _portfolio(page: str, name: str) -> dict[str, Any]:
    ink, lime, paper = "#171b18", "#c6f36b", "#f1f0e9"
    heading, intro = {
        "Home": ("Ideas made\nvisible.", "Independent designer and creative partner working across identity, digital, and the spaces in between."),
        "About": ("Curiosity is\nhow it begins.", "A little about the practice, the people, and the point of view behind each project."),
        "Projects": ("Selected work,\nmade with care.", "A selection of collaborations, identities, and digital experiences."),
        "Contact": ("Have a good\nproblem to solve?", "For collaborations, commissions, or a conversation about what you are building."),
    }.get(page, (page, "A small independent creative practice."))
    header = _header(name, background=ink, color="#ffffff", accent=lime, links=["Work", "About", "Contact"])
    hero = _section([
        _el("p", "INDEPENDENT CREATIVE PRACTICE · EST. 2018", styles={"color": lime, "font_size": "11px", "letter_spacing": ".18em", "font_weight": "700"}),
        _el("h1", heading, styles={"font_family": "Georgia,serif", "color": "#ffffff", "font_size": "clamp(58px,10vw,126px)", "line_height": ".9", "letter_spacing": "-.07em", "white_space": "pre-line", "margin": "24px 0"}),
        _text(intro, color="#c4c7c0", size="17px", max_width="520px"),
        _button("Explore selected work  ↘", "/projects", background=lime, color=ink),
        _el("div", styles={"height": "190px", "margin_top": "48px", "border_radius": "4px", "background": "linear-gradient(120deg,#718178 0%,#c5be9c 40%,#d3a46f 41%,#6b7568 70%,#242b27 100%)", "box_shadow": "inset 0 0 90px #1118"}, children=[_el("span", "A PLACEHOLDER FOR YOUR FEATURE PROJECT", styles={"display": "block", "padding": "18px", "color": "#ffffff", "font_size": "10px", "letter_spacing": ".2em"})]),
    ], background=ink, color="#ffffff", padding="76px 9% 56px")
    work = _section([
        _el("div", styles={"display": "flex", "justify_content": "space-between", "align_items": "end", "gap": "18px", "flex_wrap": "wrap"}, children=[_el("div", children=[_el("p", "A FEW RECENT THINGS", styles={"color": "#667067", "font_size": "10px", "letter_spacing": ".18em", "font_weight": "800"}), _el("h2", "Selected projects", styles={"color": ink, "font_family": "Georgia,serif", "font_size": "42px", "margin": "8px 0"})]), _el("span", "Identity · Digital · Art direction", styles={"color": "#657067", "font_size": "13px"})]),
        _el("div", styles={"display": "grid", "grid_template_columns": "repeat(auto-fit,minmax(240px,1fr))", "gap": "18px", "margin_top": "24px"}, children=[
            _el("article", styles={"background": "#ffffff", "border_radius": "8px", "overflow": "hidden"}, children=[_el("div", styles={"height": "190px", "background": backdrop}), _el("div", styles={"padding": "18px"}, children=[_el("span", category.upper(), styles={"color": "#7b837a", "font_size": "10px", "letter_spacing": ".14em"}), _el("h3", title, styles={"color": ink, "font_size": "19px", "margin": "8px 0 0"})])])
            for backdrop, category, title in [("linear-gradient(135deg,#d2b899,#697769 52%,#25342c)", "IDENTITY · 2025", "Field Notes"), ("linear-gradient(135deg,#d8e3db,#7a9387 50%,#e4b772)", "DIGITAL · 2024", "Common Ground"), ("linear-gradient(135deg,#b8b4a7,#393d35 52%,#d1c091)", "ART DIRECTION · 2024", "Studio Objects")]
        ]),
    ], background=paper, padding="68px 8%")
    return {"type": "wrapper", "components": [header, hero, work, _footer(name, background=ink, color="#ffffff", accent=lime, note="Available for select collaborations.")]}


def _restaurant(page: str, name: str) -> dict[str, Any]:
    forest, orange, cream = "#173c32", "#c77a43", "#f7f1e7"
    heading, intro = {
        "Home": ("Gather around\nsomething good.", "Seasonal cooking, generous plates, and a table ready for you."),
        "About": ("A neighbourhood\ntable, with a story.", "Our kitchen follows the seasons and celebrates the growers, makers, and traditions around us."),
        "Menu": ("Fresh from\nour kitchen.", "A changing menu inspired by the season. Ask us about today’s specials and dietary options."),
        "Contact": ("Save a seat\nat the table.", "Find us, plan your visit, or get in touch about a gathering with friends."),
    }.get(page, (page, "Seasonal food, made with care."))
    header = _header(name, background=cream, color=forest, accent=orange, links=["Our story", "Menu", "Visit us"])
    hero = _section([
        _el("div", styles={"max_width": "680px", "margin": "0 auto", "text_align": "center"}, children=[
            _el("p", "GOOD FOOD · GOOD COMPANY", styles={"color": orange, "font_size": "11px", "letter_spacing": ".2em", "font_weight": "800"}),
            _el("h1", heading, styles={"font_family": "Georgia,serif", "font_size": "clamp(46px,7vw,86px)", "line_height": ".98", "letter_spacing": "-.05em", "white_space": "pre-line", "margin": "20px 0", "color": cream}),
            _text(intro, color="#e6ded0", size="18px"),
            _button("View the menu  ↗", "/menu", background=orange),
        ]),
        _el("div", styles={"margin_top": "44px", "height": "240px", "border_radius": "160px 160px 12px 12px", "background": "linear-gradient(110deg,#a55f38,#ddab70 35%,#657457 36%,#344f3a 64%,#1d342c)", "border": "8px solid #ffffff22"}, children=[_el("span", "YOUR FOOD · YOUR PLACE · YOUR PEOPLE", styles={"display": "block", "text_align": "center", "padding": "100px 10px 0", "color": "#ffffff", "font_size": "11px", "letter_spacing": ".2em"})]),
    ], background=forest, color=cream, padding="64px 8%")
    menu = _section([
        _el("p", "FROM THE KITCHEN", styles={"color": orange, "font_size": "11px", "letter_spacing": ".18em", "font_weight": "800"}),
        _el("h2", "A little something\nfor every appetite.", styles={"font_family": "Georgia,serif", "font_size": "clamp(32px,5vw,54px)", "white_space": "pre-line", "line_height": "1.05", "color": forest, "letter_spacing": "-.04em"}),
        _el("div", styles={"display": "grid", "grid_template_columns": "repeat(auto-fit,minmax(220px,1fr))", "gap": "14px", "margin_top": "24px"}, children=[
            _el("article", styles={"background": "#ffffff", "padding": "22px", "border": "1px solid #e9dfd0", "border_radius": "12px"}, children=[_el("span", icon, styles={"font_size": "24px"}), _el("h3", title, styles={"color": forest, "font_family": "Georgia,serif", "font_size": "20px", "margin": "10px 0 4px"}), _text(copy, size="14px")])
            for icon, title, copy in [("✳", "Seasonal plates", "Fresh ingredients and thoughtful combinations, changing through the year."), ("◌", "Something to share", "Small plates and favourites made for the middle of the table."), ("☼", "Slow mornings", "Coffee, something warm, and nowhere else you need to be.")]
        ]),
        _el("div", styles={"margin_top": "30px", "padding": "24px", "background": forest, "color": cream, "border_radius": "12px", "display": "flex", "justify_content": "space-between", "align_items": "center", "gap": "14px", "flex_wrap": "wrap"}, children=[_el("div", children=[_el("strong", "Come as you are.", styles={"font_family": "Georgia,serif", "font_size": "23px"}), _text("Walk-ins welcome · Groups by arrangement", color="#d8ded3", size="13px")]), _button("Plan your visit", "/contact", background=orange)]),
    ], background=cream, padding="64px 8%")
    return {"type": "wrapper", "components": [header, hero, menu, _footer(name, background="#102c25", color=cream, accent=orange, note="Good things are better shared.")]}


def _community(page: str, name: str) -> dict[str, Any]:
    purple, gold, pale = "#35285f", "#e4bd70", "#f6f3fb"
    heading, intro = {
        "Home": ("There’s room\nfor you here.", "A community growing in faith, friendship, and care for our neighbours."),
        "About": ("Rooted in faith.\nOpen to everyone.", "Learn about our story, what guides us, and how we put care into action."),
        "Sermons": ("Words for the\nweek ahead.", "Listen, reflect, and find encouragement in recent messages from our community."),
        "Contact": ("Come and\nmeet us.", "Whether it is your first visit or your hundredth, we would love to welcome you."),
    }.get(page, (page, "Faith, friendship, and service for everyone."))
    header = _header(name, background="#ffffff", color=purple, accent=gold, links=["Welcome", "Our story", "Messages", "Visit"])
    hero = _section([
        _el("div", styles={"max_width": "780px", "margin": "0 auto", "text_align": "center"}, children=[
            _el("span", "✳", styles={"display": "inline-block", "color": gold, "font_size": "32px"}),
            _el("p", "A COMMUNITY OF HOPE", styles={"color": gold, "font_size": "11px", "letter_spacing": ".2em", "font_weight": "800"}),
            _el("h1", heading, styles={"font_family": "Georgia,serif", "font_size": "clamp(48px,8vw,88px)", "line_height": ".98", "white_space": "pre-line", "letter_spacing": "-.04em", "margin": "20px 0", "color": "#ffffff"}),
            _text(intro, color="#e6e1f1", size="18px", max_width="560px", margin="0 auto"),
            _button("Plan your first visit  →", "/contact", background=gold, color=purple),
        ]),
        _el("div", styles={"height": "170px", "margin_top": "38px", "border_radius": "100% 100% 12px 12px", "background": "linear-gradient(135deg,#8a81a7,#d5c08a 50%,#6d7965 51%,#344a43)", "opacity": ".94"}, children=[_el("span", "A PLACE TO BELONG", styles={"display": "block", "text_align": "center", "padding": "78px 0 0", "color": "#ffffff", "font_size": "11px", "letter_spacing": ".2em"})]),
    ], background=purple, color="#ffffff", padding="60px 8% 48px")
    gathering = _section([
        _el("div", styles={"display": "grid", "grid_template_columns": "repeat(auto-fit,minmax(230px,1fr))", "gap": "30px", "align_items": "center"}, children=[
            _el("div", children=[_el("p", "YOU ARE WELCOME", styles={"color": "#806f9c", "font_size": "11px", "letter_spacing": ".18em", "font_weight": "800"}), _el("h2", "A place to grow,\nserve, and belong.", styles={"font_family": "Georgia,serif", "font_size": "clamp(34px,5vw,54px)", "line_height": "1.05", "white_space": "pre-line", "color": purple}), _text("Come as you are. Find a welcoming community, thoughtful teaching, and practical ways to care for one another."), _button("Our story", "/about", background=purple)]),
            _el("div", styles={"padding": "28px", "border_radius": "16px", "background": "#ffffff", "border": "1px solid #e8e2f0", "box_shadow": "0 20px 50px #35285f0b"}, children=[_el("p", "THIS WEEK", styles={"color": "#806f9c", "font_size": "11px", "letter_spacing": ".16em", "font_weight": "800"}), _el("h3", "Gather with us", styles={"font_family": "Georgia,serif", "font_size": "25px", "color": purple}), _text("Sunday gathering · 10:00 am", size="14px"), _text("Community groups · Throughout the week", size="14px"), _text("Everyone is welcome. We’ll help you find your way.", size="14px")]),
        ]),
    ], background=pale, padding="70px 9%")
    return {"type": "wrapper", "components": [header, hero, gathering, _footer(name, background="#281f49", color="#ffffff", accent=gold, note="Growing together, serving our neighbours.")]}


def _shop(page: str, name: str) -> dict[str, Any]:
    ink, green, sand = "#193c32", "#597a58", "#f5f3eb"
    heading, intro = {
        "Home": ("Everyday pieces,\nchosen with care.", "A considered collection of useful things, made to be loved and lived with."),
        "About": ("Less, but\nbetter chosen.", "We believe useful objects can bring a little more beauty and ease to everyday life."),
        "Shop": ("Find your\nnew favourite.", "Explore the collection, discover the details, and choose what feels right for you."),
        "Contact": ("We’re happy\nto help.", "Questions about a product or an order? Our team is here to help you choose well."),
    }.get(page, (page, "Well-made essentials for everyday living."))
    header = _header(name, background="#ffffff", color=ink, accent=green, links=["Shop all", "Our story", "Contact", "Bag (0)"])
    hero = _section([
        _el("div", styles={"display": "grid", "grid_template_columns": "repeat(auto-fit,minmax(260px,1fr))", "gap": "28px", "align_items": "center"}, children=[
            _el("div", children=[_el("p", "A MORE THOUGHTFUL EVERYDAY", styles={"color": green, "font_size": "11px", "letter_spacing": ".18em", "font_weight": "800"}), _el("h1", heading, styles={"color": ink, "font_family": "Georgia,serif", "font_size": "clamp(46px,7vw,82px)", "line_height": ".98", "white_space": "pre-line", "letter_spacing": "-.05em", "margin": "18px 0"}), _text(intro, size="17px", max_width="470px"), _button("Shop the collection  ↗", "/shop", background=ink)]),
            _el("div", styles={"min_height": "350px", "border_radius": "48% 48% 8px 8px", "background": "radial-gradient(ellipse at 50% 34%,#e1c79b 0 20%,transparent 21%),linear-gradient(135deg,#d9dfce,#91a384 48%,#e9d8b7 49%,#b8875c)", "box_shadow": "inset 0 0 0 12px #ffffff55"}, children=[_el("span", "YOUR COLLECTION", styles={"display": "block", "text_align": "center", "padding": "280px 0 0", "color": "#ffffff", "font_size": "10px", "letter_spacing": ".2em", "font_weight": "800"})]),
        ]),
    ], background=sand, padding="58px 8%")
    products = _section([
        _el("div", styles={"display": "flex", "justify_content": "space-between", "align_items": "end", "gap": "12px", "flex_wrap": "wrap"}, children=[_el("div", children=[_el("p", "THE EDIT", styles={"color": green, "font_size": "11px", "letter_spacing": ".18em", "font_weight": "800"}), _el("h2", "A few good things.", styles={"color": ink, "font_family": "Georgia,serif", "font_size": "clamp(30px,4vw,44px)", "margin": "7px 0"})]), _el("a", "View everything  →", attrs={"href": "/shop"}, styles={"color": ink, "font_size": "14px", "text_decoration": "none"})]),
        _el("div", styles={"display": "grid", "grid_template_columns": "repeat(auto-fit,minmax(190px,1fr))", "gap": "15px", "margin_top": "22px"}, children=[
            _el("article", styles={"background": sand, "border_radius": "12px", "overflow": "hidden"}, children=[_el("div", styles={"height": "190px", "background": color}), _el("div", styles={"padding": "16px"}, children=[_el("span", category, styles={"color": green, "font_size": "10px", "letter_spacing": ".14em"}), _el("h3", title, styles={"font_size": "17px", "color": ink, "margin": "7px 0"}), _el("span", "Explore details  ↗", styles={"color": green, "font_size": "12px"})])])
            for color, category, title in [("linear-gradient(145deg,#d5c09e,#7a8a6d)", "HOME", "Objects for slow mornings"), ("linear-gradient(145deg,#d8b9a3,#9d755c)", "ACCESSORIES", "Everyday carry"), ("linear-gradient(145deg,#a7b6a1,#506b59)", "LIVING", "Small comforts")]
        ]),
        _el("div", styles={"margin_top": "30px", "padding": "24px", "border_top": "1px solid #d8dccf", "border_bottom": "1px solid #d8dccf", "display": "flex", "justify_content": "space-around", "gap": "12px", "flex_wrap": "wrap"}, children=[_el("span", text, styles={"color": ink, "font_size": "13px", "font_weight": "600"}) for text in ["Thoughtfully selected", "Helpful human support", "Delivery that works for you"]]),
    ], background="#ffffff", padding="64px 8%")
    return {"type": "wrapper", "components": [header, hero, products, _footer(name, background=ink, color="#ffffff", accent=green, note="Objects for the way you live.")]}


LAYOUTS = {
    "business-landing": _business,
    "personal-portfolio": _portfolio,
    "restaurant-cafe": _restaurant,
    "church-ministry": _community,
    "online-store": _shop,
}


def _project(name: str, colors: tuple[str, str, str], page: str, slug: str | None = None) -> dict[str, Any]:
    """Return a complete GrapesJS project with a distinct visual direction per starter."""
    renderer = LAYOUTS.get(slug or "business-landing", _business)
    return {"assets": [], "styles": [], "pages": [{"name": page, "component": renderer(page, name)}]}


CATALOG: list[dict[str, Any]] = [
    {"name": "Northline Studio", "slug": "business-landing", "category": "Business", "description": "A crisp, confident website for consultancies and service businesses, with a clear message and strong calls to action.", "colors": ("#10253f", "#4f8cff", "#f4f7fb"), "pages": ["Home", "About", "Services", "Contact"]},
    {"name": "Fieldnotes Portfolio", "slug": "personal-portfolio", "category": "Portfolio", "description": "An editorial, dark canvas for creatives to introduce their practice and let selected work take centre stage.", "colors": ("#171b18", "#c6f36b", "#f1f0e9"), "pages": ["Home", "About", "Projects", "Contact"]},
    {"name": "Sunday Table", "slug": "restaurant-cafe", "category": "Food & Drink", "description": "A warm, menu-led restaurant site that makes the food, atmosphere, and visit feel inviting.", "colors": ("#173c32", "#c77a43", "#f7f1e7"), "pages": ["Home", "About", "Menu", "Contact"]},
    {"name": "Open Door Community", "slug": "church-ministry", "category": "Community", "description": "A welcoming, calm home for a church or community organisation, with clear ways to visit and connect.", "colors": ("#35285f", "#e4bd70", "#f6f3fb"), "pages": ["Home", "About", "Sermons", "Contact"]},
    {"name": "Everyday Goods", "slug": "online-store", "category": "E-commerce", "description": "A refined product-led storefront with an editorial hero, collection cards, and reassuring service details.", "colors": ("#193c32", "#597a58", "#f5f3eb"), "pages": ["Home", "About", "Shop", "Contact"]},
]


def _has_untouched_legacy_markup(template: WebsiteTemplate) -> bool:
    """Allow a one-time upgrade of the original built-ins, but preserve admin edits."""
    pages = list(template.pages or [])
    if not pages:
        return False
    # SQLAlchemy stamps updated_at when an admin changes the starter's content
    # or metadata. Original seeds set created_at and updated_at together.
    created_at = getattr(template, "created_at", None)
    updated_at = getattr(template, "updated_at", None)
    if created_at and updated_at and (updated_at - created_at).total_seconds() > 5:
        return False
    if template.created_by not in (None, "shopivell-starter"):
        return False
    serialized = str([page.grapesjs_project_json for page in pages])
    return "YOUR BRAND" in serialized and "Made for your next chapter" in serialized


def _write_catalog_pages(db: Session, template: WebsiteTemplate, item: dict[str, Any]) -> None:
    template.name = item["name"]
    template.description = item["description"]
    template.category = item["category"]
    template.is_published = True
    template.pages.clear()
    db.flush()
    for order, page_name in enumerate(item["pages"]):
        db.add(WebsiteTemplatePage(
            template_id=template.id,
            page_name=page_name,
            route_path="/" if page_name == "Home" else f"/{page_name.lower()}",
            sort_order=order,
            grapesjs_project_json=_project(item["name"], item["colors"], page_name, item["slug"]),
        ))


def ensure_starter_templates(db: Session) -> None:
    """Seed missing starters and upgrade only the untouched original starter set."""
    changed = False
    for item in CATALOG:
        template = db.query(WebsiteTemplate).filter(WebsiteTemplate.slug == item["slug"]).first()
        if template is None:
            template = WebsiteTemplate(
                name=item["name"], slug=item["slug"], description=item["description"],
                category=item["category"], is_published=True,
                thumbnail_url=None, preview_url=None, created_by="shopivell-starter",
            )
            db.add(template)
            db.flush()
            _write_catalog_pages(db, template, item)
            changed = True
        elif _has_untouched_legacy_markup(template):
            _write_catalog_pages(db, template, item)
            changed = True
    if changed:
        db.commit()
