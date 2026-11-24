from modules.website_builder.template_catalog import CATALOG, _project, _has_untouched_legacy_markup
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
    assert tags == ["header", "section", "section", "footer"]
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
