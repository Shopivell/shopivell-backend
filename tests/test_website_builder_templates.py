from modules.website_builder.template_catalog import CATALOG, _project, _has_untouched_legacy_markup, _is_v1_starter_snapshot
from modules.website_builder.router import router
from modules.website_builder.chat_widget import render_chat_widget
from uuid import UUID
from datetime import datetime, timedelta
from types import SimpleNamespace


def test_starter_catalog_has_five_distinct_responsive_site_types():
    assert len(CATALOG) == 5
    assert len({item["slug"] for item in CATALOG}) == 5
    assert {item["category"] for item in CATALOG} >= {"Business", "Portfolio", "Food & Drink", "Community", "E-commerce"}
    assert all({"Home", "About", "Contact"}.issubset(set(item["pages"])) for item in CATALOG)


def test_template_page_is_valid_grapesjs_project_json():
    project = _project("Northline Studio", ("#10253f", "#4f8cff", "#f4f7fb"), "Home", "business-landing")
    assert set(project) >= {"assets", "styles", "pages"}
    assert len(project["pages"]) == 1
    root = project["pages"][0]["component"]
    assert root["type"] == "wrapper"
    tags = [child["tagName"] for child in root["components"]]
    assert tags[0] == "header" and tags[-1] == "footer"
    assert tags.count("section") >= 3
    assert "#10253f" in str(root)


def test_starter_templates_have_distinct_art_direction_and_real_navigation():
    projects = {
        item["slug"]: _project(item["name"], item["colors"], "Home", item["slug"])
        for item in CATALOG
    }
    markup = {slug: str(project["pages"][0]["component"]) for slug, project in projects.items()}
    assert len(set(markup.values())) == 5
    assert "font-family: Georgia,serif" in markup["personal-portfolio"]
    assert "Seasonal" in markup["restaurant-cafe"]
    assert "Plan your first visit" in markup["church-ministry"]
    assert "Shop the collection" in markup["online-store"]
    assert "href" in markup["business-landing"]


def test_legacy_seed_upgrade_skips_admin_modified_templates():
    created = datetime.now() - timedelta(days=2)
    page = SimpleNamespace(grapesjs_project_json={"content": "YOUR BRAND / Made for your next chapter"})
    untouched = SimpleNamespace(pages=[page], created_at=created, updated_at=created, created_by=None)
    edited = SimpleNamespace(pages=[page], created_at=created, updated_at=created + timedelta(seconds=15), created_by=None)
    assert _has_untouched_legacy_markup(untouched)
    assert not _has_untouched_legacy_markup(edited)


def test_v1_catalog_rollout_is_migrated_only_once():
    rollout = datetime(2026, 11, 24, 16, 11, 59)
    snapshot = SimpleNamespace(created_by=None, slug="online-store", updated_at=rollout)
    edited = SimpleNamespace(created_by="admin-user", slug="online-store", updated_at=rollout)
    assert _is_v1_starter_snapshot(snapshot)
    assert not _is_v1_starter_snapshot(edited)


def _walk_components(node):
    yield node
    for child in node.get("components", []):
        yield from _walk_components(child)


def test_every_starter_page_has_professional_about_and_complete_footer():
    for template in CATALOG:
        for page in template["pages"]:
            root = _project(template["name"], template["colors"], page, template["slug"])["pages"][0]["component"]
            components = list(_walk_components(root))
            assert any(component.get("tagName") == "footer" for component in components), (template["slug"], page)
            if page == "About":
                assert any(component.get("tagName") == "h2" and component.get("components") for component in components)
                assert any(component.get("tagName") == "p" and len(str(component.get("components"))) > 100 for component in components)


def test_online_store_has_editable_product_catalog_with_prices_and_actions():
    project = _project("Everyday Goods", CATALOG[-1]["colors"], "Shop", "online-store")
    components = list(_walk_components(project["pages"][0]["component"]))
    cards = [component for component in components if component.get("tagName") == "article"]
    text = str(project)
    assert len(cards) >= 6
    assert all(price in text for price in ("$42", "$28", "$36", "$32", "$86", "$24"))
    assert "View item" in text


def test_website_builder_routes_cover_owner_and_public_chat_flows():
    paths = {route.path for route in router.routes}
    assert "/api/website-builder/websites/{website_id}/pages" in paths
    assert "/api/website-builder/websites/{website_id}/media" in paths
    assert "/api/website-builder/websites/{website_id}/inbox" in paths
    assert "/api/website-builder/public/sites/{website_id}/messages" in paths
    assert "/api/website-builder/public/sites/{website_id}/messages/{conversation_id}" in paths
    assert "/api/website-builder/templates/admin" in paths


def test_published_site_chat_widget_escapes_store_name_and_loads_conversation_history():
    widget = render_chat_widget(UUID("00000000-0000-0000-0000-000000000001"), "<script>bad</script>")
    assert "&lt;script&gt;bad&lt;/script&gt;" in widget
    assert "messages/'+encodeURIComponent(conversationId)" in widget
    assert "messages',{" in widget

