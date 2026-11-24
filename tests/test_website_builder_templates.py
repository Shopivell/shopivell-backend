from modules.website_builder.template_catalog import CATALOG, _project
from modules.website_builder.router import router


def test_starter_catalog_has_five_distinct_responsive_site_types():
    assert len(CATALOG) == 5
    assert len({item["slug"] for item in CATALOG}) == 5
    assert {item["category"] for item in CATALOG} >= {"Business", "Portfolio", "Food & Drink", "Community", "E-commerce"}
    assert all({"Home", "About", "Contact"}.issubset(set(item["pages"])) for item in CATALOG)


def test_template_page_is_valid_grapesjs_project_json():
    project = _project("Sample Business", ("#172554", "#38bdf8", "#f8fafc"), "Home")
    assert set(project) >= {"assets", "styles", "pages"}
    assert len(project["pages"]) == 1
    root = project["pages"][0]["component"]
    assert root["type"] == "wrapper"
    tags = [child["tagName"] for child in root["components"]]
    assert tags == ["header", "section", "section", "footer"]
    assert "#172554" in str(root)


def test_website_builder_routes_cover_owner_and_public_chat_flows():
    paths = {route.path for route in router.routes}
    assert "/api/website-builder/websites/{website_id}/pages" in paths
    assert "/api/website-builder/websites/{website_id}/media" in paths
    assert "/api/website-builder/websites/{website_id}/inbox" in paths
    assert "/api/website-builder/public/sites/{website_id}/messages" in paths
    assert "/api/website-builder/templates/admin" in paths
