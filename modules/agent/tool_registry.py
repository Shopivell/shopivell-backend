# modules/agent/tool_registry.py
"""Every action the agent can perform in Shopivell, as one declarative catalogue.

An API tool wraps an existing REST route and calls it in-process with the SAME bearer token the user's browser
sent, so permissions, validation and side effects are identical to clicking in the UI. Nothing here duplicates
business logic. A handoff tool covers flows that must happen in the user's own browser (Meta/WhatsApp sign-in
popups): the agent checks the current status, then returns a button that opens the right screen with the steps.

Argument convention (flat, what the model sends): path placeholders ({store_id}) are filled from args; for
GET/DELETE the remaining args are the query string; for POST/PUT/PATCH they are the JSON body. A missing
store_id falls back to the current store. Validation errors from the API are returned to the model so it can
fix its call and retry.
"""
import json
import re
from urllib.parse import quote
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

API_PREFIX = "/v1/api"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class Tool:
    name: str
    group: str
    desc: str
    method: str = "GET"
    path: str = ""
    cost: Optional[int] = None          # tokens; None = 0 for reads, WRITE_COST for writes
    confirm: Optional[bool] = None      # None = confirm every write; reads run at once
    handoff: Optional[Dict[str, Any]] = None   # {"page": key, "path": "/settings?tab=...", "steps": [..]}
    root: str = API_PREFIX
    title: str = ""

    @property
    def is_write(self) -> bool:
        return self.method in WRITE_METHODS

    @property
    def needs_confirm(self) -> bool:
        if self.handoff:
            return False
        return self.is_write if self.confirm is None else self.confirm

    @property
    def token_cost(self) -> int:
        if self.cost is not None:
            return self.cost
        return WRITE_COST if self.is_write else 0

    @property
    def store_scoped(self) -> bool:
        """True when the action is about one specific store, so the agent must know which."""
        if self.handoff:
            return bool(self.handoff.get("needs_store"))
        return "store_id" in self.path_args or self.name in STORE_BODY_TOOLS

    @property
    def path_args(self) -> List[str]:
        return re.findall(r"{(\w+)}", self.path)


STORE_BODY_TOOLS = {"list_products", "list_orders", "list_customers", "list_segments", "list_collections", "whatsapp_leads",
                    "create_product", "create_order", "create_customer", "create_segment", "create_collection", "create_website",
                    "auto_lead_segments"}
WRITE_COST = 0   # plain app actions are not AI usage; AI-heavy tools carry explicit costs


def _t(name, group, desc, method="GET", path="", **kw) -> Tool:
    return Tool(name=name, group=group, desc=desc, method=method, path=path, **kw)


STORE_FIELDS = ("store_name, business_type, store_phone, store_email, store_link, store_address, store_city, "
                "store_country, currency, color_theme, logo_url, brand_description, products_or_services")

TOOLS: List[Tool] = [
    # ---------------- stores ----------------
    _t("get_store", "stores", "Full details of one store. {store_id?}", path="/stores/{store_id}"),
    _t("create_store", "stores", "Create a new store. {store_name, store_phone, business_type?, store_link?, store_email?, store_city?, "
       "store_country?, currency?}. The owner is the signed-in user.", "POST", "/stores/",
       title="Create store"),
    _t("update_store", "stores", f"Edit store settings. {{store_id?, any of: {STORE_FIELDS}}}", "PATCH", "/stores/{store_id}",
       title="Update store"),
    _t("delete_store", "stores", "Permanently delete a store. {store_id}", "DELETE", "/stores/{store_id}", title="Delete store"),
    _t("scrape_store_website", "stores", "Read a website to pre-fill store details. {url}", "POST", "/stores/scrape-website",
       confirm=False, cost=0),
    _t("get_brand_dna", "stores", "A store's Brand DNA: voice, style, buyer profiles. {store_id?}", path="/stores/{store_id}/brand-dna"),
    _t("generate_brand_dna", "stores", "Generate Brand DNA and buyer profiles for a store from its website. {store_id?}", "POST",
       "/stores/{store_id}/brand-dna", cost=1500, title="Generate Brand DNA"),

    # ---------------- products ----------------
    _t("list_products", "products", "Products of a store. {store_id?}", path="/products/"),
    _t("get_product", "products", "One product. {product_id}", path="/products/{product_id}"),
    _t("create_product", "products", "Add a product. {store_id?, title, price?, description?, sku?, quantity?, category?}", "POST",
       "/products/", title="Add product"),
    _t("update_product", "products", "Edit a product. {product_id, any product fields}", "PUT", "/products/{product_id}",
       title="Update product"),
    _t("delete_product", "products", "Delete a product. {product_id}", "DELETE", "/products/{product_id}", title="Delete product"),
    _t("list_collections", "products", "Product collections. {store_id?}", path="/products/collections/"),
    _t("create_collection", "products", "Create a collection. {store_id?, title, description?}", "POST", "/products/collections/",
       title="Create collection"),
    _t("get_inventory", "products", "Stock levels for a store. {store_id?}", path="/products/inventory/store/{store_id}/items"),
    _t("update_stock", "products", "Change stock for a product. {product_id, quantity}", "PATCH",
       "/products/inventory/items/{product_id}/quantities", title="Update stock"),

    # ---------------- orders ----------------
    _t("list_orders", "orders", "Orders. {store_id?, status?}", path="/orders/"),
    _t("get_order", "orders", "One order. {order_id}", path="/orders/{order_id}"),
    _t("create_order", "orders", "Create an order. {store_id?, customer_name, total_amount, phone?, product_name?, quantity?, customer_id?}",
       "POST", "/orders/", title="Create order"),
    _t("update_order_status", "orders", "Move an order along. {order_id, status}", "PATCH", "/orders/{order_id}/status",
       title="Update order status"),
    _t("send_invoice", "orders", "Email the invoice for an order. {order_id}", "POST", "/orders/{order_id}/send-invoice",
       title="Send invoice"),

    # ---------------- customers ----------------
    _t("list_customers", "customers", "Customers. {store_id?}", path="/customers/"),
    _t("create_customer", "customers", "Add a customer. {store_id?, first_name, last_name, email, phone?, city?}", "POST", "/customers/",
       title="Add customer"),
    _t("update_customer", "customers", "Edit a customer. {customer_id, fields}", "PUT", "/customers/{customer_id}",
       title="Update customer"),
    _t("list_segments", "customers", "Customer segments. {store_id?}", path="/customers/segments/"),
    _t("create_segment", "customers", "Create a customer segment. {store_id?, name, type custom, description?}", "POST",
       "/customers/segments/", title="Create segment"),
    _t("auto_lead_segments", "customers", "Score leads and auto-create hot/warm/cold segments. {store_id?}", "POST",
       "/customers/segments/auto-create-lead-segments", title="Auto-create lead segments"),

    # ---------------- campaigns and ads ----------------
    _t("get_campaign", "campaigns", "One campaign with its ads. {campaign_id}", path="/url-campaigns/{campaign_id}"),
    _t("pause_campaign", "campaigns", "Pause a campaign. {campaign_id}", "POST", "/url-campaigns/{campaign_id}/pause",
       title="Pause campaign"),
    _t("resume_campaign", "campaigns", "Resume a campaign. {campaign_id}", "POST", "/url-campaigns/{campaign_id}/resume",
       title="Resume campaign"),
    _t("publish_campaign", "campaigns", "Publish a draft campaign to Meta. {campaign_id}", "POST",
       "/url-campaigns/{campaign_id}/publish", cost=250, title="Publish campaign"),
    _t("delete_campaign", "campaigns", "Delete a campaign. {campaign_id}", "DELETE", "/url-campaigns/{campaign_id}",
       title="Delete campaign"),
    _t("optimize_campaign", "campaigns", "Run the optimizer on a campaign. {campaign_id}", "POST",
       "/url-campaigns/{campaign_id}/optimize", cost=250, title="Optimize campaign"),
    _t("collect_metrics", "campaigns", "Pull the latest results for a campaign. {campaign_id}", "POST",
       "/url-campaigns/{campaign_id}/collect-metrics", confirm=False, cost=0),
    _t("check_ad_fatigue", "campaigns", "Check whether a campaign's ads are wearing out. {campaign_id}", "POST",
       "/url-campaigns/{campaign_id}/check-fatigue", confirm=False, cost=0),
    _t("scale_campaign", "campaigns", "Raise a winning campaign's budget. {campaign_id, daily_budget}", "POST",
       "/openclaw/campaigns/{campaign_id}/scale", root="/v1", title="Scale campaign"),
    _t("campaign_insights", "campaigns", "Performance insights for a campaign. {campaign_id}", path="/openclaw/campaigns/{campaign_id}/insights",
       root="/v1"),
    _t("optimizer_status", "campaigns", "What the optimizer is doing for a store. {store_id?}",
       path="/openclaw/stores/{store_id}/optimizer/status", root="/v1"),
    _t("weekly_report", "campaigns", "Weekly ad performance report. {store_id?}",
       path="/openclaw/stores/{store_id}/report/weekly", root="/v1"),
    _t("ad_settings", "campaigns", "A store's ad settings (budget limits, targeting). {store_id?}",
       path="/openclaw/stores/{store_id}/ad-settings", root="/v1"),
    _t("update_ad_settings", "campaigns", "Change ad settings. {store_id?, settings fields}", "PATCH",
       "/openclaw/stores/{store_id}/ad-settings", root="/v1", title="Update ad settings"),

    _t("open_store_editor", "stores", "Open a store's edit screen on the right store. Use it for anything that needs the screen: "
       "uploading or changing the logo or banner, editing details, Brand DNA. {store_id? or store_name?, focus?: logo|details|brand_dna}",
       handoff={"page": "Store editor", "title": "Edit {store_name}", "needs_store": True,
                "path": "/settings?tab=stores&store={store_id}&open=detail&edit=1&focus={focus}",
                "steps": ["Opens {store_name} in edit mode", "{focus_step}", "Press Save when you are done"]}),

    # ---------------- WhatsApp ----------------
    _t("whatsapp_accounts", "whatsapp", "WhatsApp numbers connected to a store. {store_id?}",
       path="/whatsapp/store/{store_id}/accounts"),
    _t("whatsapp_conversations", "whatsapp", "Recent WhatsApp conversations. {store_id?}",
       path="/whatsapp/stores/{store_id}/conversations"),
    _t("whatsapp_leads", "whatsapp", "WhatsApp leads. {store_id?}", path="/whatsapp/leads"),
    _t("whatsapp_send_text", "whatsapp", "Send a WhatsApp message. {account_id, to, message}", "POST",
       "/whatsapp/accounts/{account_id}/send-text", title="Send WhatsApp message"),
    _t("whatsapp_bot_config", "whatsapp", "The store's WhatsApp assistant settings. {store_id?}",
       path="/whatsapp/stores/{store_id}/bot-config"),
    _t("update_whatsapp_bot", "whatsapp", "Change the WhatsApp assistant's settings. {store_id?, fields}", "PUT",
       "/whatsapp/stores/{store_id}/bot-config", title="Update WhatsApp assistant"),
    _t("add_faq", "whatsapp", "Teach the WhatsApp assistant an answer. {store_id?, question, answer}", "POST",
       "/whatsapp/stores/{store_id}/faqs", title="Add FAQ"),
    _t("sync_products_to_assistant", "whatsapp", "Load the store's products into the WhatsApp assistant's knowledge. {store_id?}",
       "POST", "/whatsapp/stores/{store_id}/knowledge/sync-products", title="Sync products to assistant"),
    _t("enable_whatsapp_ordering", "whatsapp", "Turn on ordering inside WhatsApp. {store_id?}", "POST",
       "/whatsapp/store/{store_id}/enable-ordering-flow", title="Enable WhatsApp ordering"),
    _t("connect_whatsapp", "whatsapp", "Connect a WhatsApp Business number. Needs the user's own Meta sign-in, so this opens the screen.",
       handoff={"page": "WhatsApp", "path": "/settings?tab=whatsapp&store={store_id}&name={store_name_q}&focus=connect", "needs_store": True, "status_tool": "whatsapp_accounts",
                "steps": ["Press Connect WhatsApp and sign in to Facebook", "Choose or create your WhatsApp Business account",
                          "Pick the phone number and verify it by code", "Come back here and I will confirm it is live"]}),

    # ---------------- social ----------------
    _t("list_facebook_pages", "social", "Facebook pages connected to the account.", path="/business/pages"),
    _t("list_instagram_accounts", "social", "Instagram accounts connected.", path="/business/instagram/accounts"),
    _t("post_to_facebook_page", "social", "Publish a post to a Facebook page. {page_id, message, image_url?}", "POST",
       "/business/pages/{page_id}/post", title="Post to Facebook page"),
    _t("connect_facebook", "social", "Connect a Facebook page. Needs the user's own Facebook sign-in, so this opens the screen.",
       handoff={"page": "Social accounts", "path": "/settings?tab=socials&store={store_id}&name={store_name_q}", "needs_store": True, "status_tool": "list_facebook_pages",
                "steps": ["Press Connect Facebook and sign in", "Allow page access", "Choose the pages to link"]}),
    _t("connect_instagram", "social", "Connect an Instagram business account. Needs the user's own sign-in, so this opens the screen.",
       handoff={"page": "Social accounts", "path": "/settings?tab=socials&store={store_id}&name={store_name_q}", "needs_store": True, "status_tool": "list_instagram_accounts",
                "steps": ["Press Connect Instagram and sign in", "Allow access to the business account"]}),
    _t("connect_ad_account", "social", "Connect the Meta ad account used to run ads. Needs the user's own sign-in, so this opens the screen.",
       handoff={"page": "Ad accounts", "path": "/settings?tab=socials&store={store_id}&name={store_name_q}", "needs_store": True, "status_tool": "ad_accounts_status",
                "steps": ["Press Connect ad account and sign in to Facebook", "Choose the ad account and Facebook page",
                          "Confirm and return here"]}),
    _t("ad_accounts_status", "social", "Ad accounts connected to a store. {store_id?}",
       path="/openclaw/stores/{store_id}/connected-accounts", root="/v1"),

    # ---------------- website ----------------
    _t("list_websites", "website", "Websites built for a store. {store_id?}", path="/website-builder/websites/store/{store_id}"),
    _t("create_website", "website", "Start a new website. {store_id?, name, description?}", "POST", "/website-builder/websites",
       title="Create website"),
    _t("generate_website", "website", "Generate the website's pages. {website_id}", "POST",
       "/website-builder/websites/{website_id}/generate", cost=3000, title="Generate website"),
    _t("deploy_website", "website", "Publish the website live. {website_id}", "POST",
       "/website-builder/websites/{website_id}/deploy", title="Deploy website"),

    # ---------------- analytics and account ----------------
    _t("product_analytics", "analytics", "Product performance overview. {store_id?}", path="/analytics/products/{store_id}/overview"),
    _t("notifications", "account", "Recent notifications. {store_id?}", path="/notifications/store/{store_id}", root="/v1"),
]

BY_NAME: Dict[str, Tool] = {t.name: t for t in TOOLS}


_VERBS = {"add": "create", "new": "create", "make": "create", "remove": "delete", "show": "list", "view": "get",
          "edit": "update", "change": "update", "modify": "update", "link": "connect"}


def resolve(name: str, extra: Optional[List[str]] = None) -> str:
    """Map a near-miss tool name from the model (add_customer, show_orders) to a real one. Returns the input
    unchanged when nothing is close, so unknown names still fail loudly."""
    import difflib
    known = set(BY_NAME) | set(extra or [])
    n = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if n in known:
        return n
    head, _, rest = n.partition("_")
    cand = f"{_VERBS.get(head, head)}_{rest}" if rest else n
    for c in (cand, cand + "s", cand.rstrip("s")):
        if c in known:
            return c
    close = difflib.get_close_matches(cand, sorted(known), n=1, cutoff=0.75)
    return close[0] if close else name


def costs() -> Dict[str, int]:
    return {t.name: t.token_cost for t in TOOLS}


GROUP_WORDS = {
    "stores": "store shop brand business website url dna profile", "products": "product item stock inventory collection price sku catalog",
    "orders": "order invoice sale delivery status", "customers": "customer client segment lead contact",
    "campaigns": "campaign ad ads budget optimi scale metric report fatigue performance result roas",
    "whatsapp": "whatsapp message chat bot faq assistant", "social": "facebook instagram page social meta connect link account post",
    "website": "website site domain deploy builder", "analytics": "analytic insight overview trend", "account": "notification alert",
}


def groups_for(text: str) -> List[str]:
    low = (text or "").lower()
    return [g for g, words in GROUP_WORDS.items() if any(w in low for w in words.split())]


def catalogue_text(context: str = "") -> str:
    """The model's tool list: every tool name (so it knows what exists), with full argument lines only for the
    groups the conversation is about. Keeps the per-turn prompt small."""
    active = set(groups_for(context)) or {"stores", "campaigns"}
    names: Dict[str, List[str]] = {}
    for t in TOOLS:
        names.setdefault(t.group, []).append(t.name)
    out = ["More tools you can call (exact names, by area): " + "; ".join(f"{g}: {', '.join(n)}" for g, n in names.items())]
    last = None
    for t in TOOLS:
        if t.group not in active:
            continue
        if t.group != last:
            out.append(f"[{t.group}] arguments:")
            last = t.group
        tag = " (asks the user to confirm)" if t.needs_confirm else (" (opens a screen)" if t.handoff else "")
        out.append(f"- {t.name} - {t.desc}{tag}")
    return "\n".join(out)


def spec_for(tool: Tool, args: Dict[str, Any]) -> Dict[str, Any]:
    """The confirm card shown before a write runs."""
    rows = []
    for k, v in args.items():
        if v in (None, "", [], {}):
            continue
        val = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        rows.append([k.replace("_", " ").capitalize(), val[:80]])
    return {"title": tool.title or tool.name.replace("_", " ").capitalize(), "subtitle": tool.desc.split(". {")[0].split(" {")[0][:90],
            "credits": tool.token_cost, "rows": rows[:8]}


def call(tool: Tool, args: Dict[str, Any], auth_header: Optional[str], default_store_id: Optional[str],
         user_id: Optional[str] = None) -> Tuple[Any, str]:
    """Run an API tool in-process as the user. Returns (data, status)."""
    if tool.handoff:
        return handoff_result(tool, args), "ok"
    if not auth_header:
        return None, "not signed in"
    args = dict(args or {})
    if "store_id" in tool.path_args and not args.get("store_id") and default_store_id:
        args["store_id"] = default_store_id
    path = tool.root + tool.path
    for p in tool.path_args:
        if not args.get(p):
            return None, f"missing required argument {p}"
        path = path.replace("{" + p + "}", str(args.pop(p)))
    if tool.name == "create_store" and not args.get("owner_id") and user_id:
        args["owner_id"] = user_id
    if tool.name == "create_segment" and not args.get("created_by") and user_id:
        args["created_by"] = user_id
    if default_store_id and tool.method == "GET" and "store_id" not in args and tool.name in {
            "list_products", "list_orders", "list_customers", "list_segments", "list_collections", "whatsapp_leads"}:
        args["store_id"] = default_store_id
    if default_store_id and tool.method in ("POST", "PUT") and "store_id" not in args and tool.name in {
            "create_product", "create_order", "create_customer", "create_segment", "create_collection", "create_website"}:
        args["store_id"] = default_store_id
    from starlette.testclient import TestClient
    from main import app
    headers = {"Authorization": auth_header}
    client = TestClient(app, raise_server_exceptions=False)
    if tool.method in ("GET", "DELETE"):
        resp = client.request(tool.method, path, params={k: v for k, v in args.items() if v is not None}, headers=headers)
    else:
        resp = client.request(tool.method, path, json=args, headers=headers)
    try:
        data = resp.json()
    except Exception:
        data = resp.text[:500]
    if resp.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else data
        return None, f"{resp.status_code}: {json.dumps(detail, ensure_ascii=False)[:400]}"
    return data, "ok"


FOCUS_STEPS = {"logo": "Press Upload (or Assets) under the logo to change it", "banner": "Change the banner image there",
               "brand_dna": "Open the Brand DNA section to review or regenerate it", "details": "Change the details you want"}


def handoff_result(tool: Tool, args: Optional[Dict[str, Any]] = None, store: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The card for a flow that happens on screen: where it opens, for which store, and the steps."""
    h = tool.handoff or {}
    args = args or {}
    store = store or {}
    focus = str(args.get("focus") or "details").lower()
    fill = {"store_id": store.get("store_id") or args.get("store_id") or "", "store_name": store.get("name") or "your store",
            "focus": focus, "focus_step": FOCUS_STEPS.get(focus, FOCUS_STEPS["details"]),
            "store_name_q": quote(str(store.get("name") or ""))}

    def sub(text: str) -> str:
        for k, v in fill.items():
            text = text.replace("{" + k + "}", str(v))
        return text

    path = sub(h.get("path", ""))
    if not fill["store_id"]:
        path = re.sub(r"[?&]store=(?=&|$)", "", path).replace("?&", "?")
    return {"page": h.get("page"), "title": sub(h.get("title", "")) or None, "path": path, "store_name": fill["store_name"],
            "steps": [sub(x) for x in h.get("steps", [])], "status_tool": h.get("status_tool")}
