# modules/agent/service.py
"""Shopivell agent: a chat that can actually DO things.

The agent is a tool loop over the same LLM plumbing the pipeline already uses
(OpenAI direct with OpenRouter fallback). Each turn the model receives the
conversation plus a JSON tool catalogue; it answers with either a plain reply or
a JSON tool call. Tools wrap real services:
  - show_ad_variations -> modules.ad_angles.service.generate_ad_angles (full pipeline)
  - generate_image     -> modules.assets.service.generate_image_bytes
  - create_campaign    -> a draft UrlCampaign + one ad set (+ content rows if copy exists)
  - navigate           -> deep links into the app (marketing, stores, settings...)
  - list_stores / list_campaigns -> quick context the model often needs first

Tool calls are appended to the assistant message as `parts`, so the UI can render
ad variation cards, images and clickable links instead of plain text.
"""
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from sqlalchemy.orm import Session

from modules.agent.credit_costs import DEFAULT_TOOL_COST, tool_costs
from modules.agent import tool_registry
from modules.agent.credits import (InsufficientTokens, charge_with_overdraft, estimate_tokens,
                                   get_balance)
from db_compat import UUID as PG_UUID
# Mapper registration order matters: relationships resolve by class name at first use,
# so import the model chain exactly like main.py does (business -> users -> stores ->
# assets -> campaigns) before touching campaign models in a bare runtime (tests, workers).
import modules.business.models as _business_models  # noqa: F401
import modules.users.models as _users_models  # noqa: F401
import modules.stores.models as _stores_models  # noqa: F401
import modules.assets.models as _assets_models  # noqa: F401
from modules.agent.models import AgentConversation, AgentMessage
from modules.campaigns.models import CampaignGoal, CampaignStatus, UrlAdContent, UrlAdSet, UrlCampaign

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Deep links the `navigate` tool may point the user to (mirrors App.tsx routes).
APP_ROUTES = [
    {"key": "marketing", "path": "/marketing", "desc": "Campaigns hub: create/see campaigns, drafts, assets"},
    {"key": "campaigns", "path": "/marketing/campaigns", "desc": "All campaigns list"},
    {"key": "campaign_drafts", "path": "/marketing/drafts", "desc": "Draft campaigns"},
    {"key": "assets", "path": "/marketing/assets", "desc": "Ad asset library (generated images live here)"},
    {"key": "stores", "path": "/stores", "desc": "Store management: brand kit, websites, settings"},
    {"key": "settings", "path": "/settings", "desc": "Settings (stores tab shows the brand kit)"},
    {"key": "messaging", "path": "/messaging", "desc": "WhatsApp/Messenger conversations and workflows"},
    {"key": "customers", "path": "/customers", "desc": "Customers and segments"},
    {"key": "orders", "path": "/orders", "desc": "Orders management"},
    {"key": "product", "path": "/product", "desc": "Products / inventory"},
    {"key": "analytics", "path": "/analytics", "desc": "Analytics dashboard"},
    {"key": "content", "path": "/content", "desc": "Content studio (image/video templates)"},
    {"key": "agent", "path": "/agent", "desc": "This agent chat"},
]

SYSTEM_HINT = (
    "You are the Shopivell Agent: you run the user's whole Shopivell app for them. You can do anything the app "
    "can: create and edit stores, products, orders and customers, connect WhatsApp, Facebook, Instagram and ad "
    "accounts, manage the WhatsApp assistant, build websites, run the ad pipeline, generate ad images, create, "
    "publish, pause and optimise campaigns, and read reports. Act with the app tools; do not tell the user to go "
    "do it themselves unless a tool says it opens a screen. Be concise and concrete; talk like a media buyer, not a chatbot. "
    "Every turn you must answer with EXACTLY ONE JSON object, no prose around it:\n"
    '{"reply": "short markdown text shown to the user",'
    ' "tool": {"name": "<tool>", "args": {...}} | null,'
    ' "need_more_info": "optional question if a required arg is missing"}\n'
    "If the user's request is complete, set tool to null after presenting results. "
    "Never invent tool names: use only names from the tool lists below. When asked to DO something in the app "
    "(add a customer, list orders, create a store, pause a campaign, connect WhatsApp), call the matching app tool "
    "and do it; use navigate only when the user just wants to be taken to a screen. Fill arguments from what the "
    "user said and ask only for what is truly missing.\n\n"
    "EXPENSIVE ACTIONS - generate_image, create_campaign, show_ad_variations: NEVER set "
    '"tool" to run these directly. Instead PROPOSE the action and wait for the user to '
    'confirm it in the UI (they press a Confirm button). Reply with:\n'
    '{"reply": "one short line telling them what you are about to do", "tool": null, '
    '"propose": {"tool": "<tool>", "args": {...}}, '
    '"spec": {"title": "...", "subtitle": "...", "credits": <int tokens>, '
    '"rows": [["Label", "value"], ...]}}\n'
    "The spec card is shown verbatim: title like 'Generate image ad', subtitle like "
    "'1:1 (square) image ad', and rows for the key choices (Concept, Model, Aspect ratio, "
    "Resolution, Product, Variations...) - 3 to 8 rows, short values. After the user "
    "confirms, the result appears in the chat; do not repeat the action.\n"
    "Cheap/read-only tools (navigate, list_stores, list_campaigns, scrape_url) still run "
    "immediately via \"tool\"."
)

# Flat token costs for tool side-effects. Tools that internally run their own LLM
# pipelines (angles, images) can't be metered call-by-call from here, so they carry an
# honest flat token price instead of pretending to be free.
TOOL_COSTS = {**tool_registry.costs(), **tool_costs()}   # AI prices: credit_costs.py; API tools: tool_registry.py

# Reserved tokens blocked before a turn starts (context + reply headroom).
TURN_RESERVE = 800

# The wallet is system-wide AI credit (agent, campaign pipeline, ad images), so a
# zero balance must not hard-block conversation — a chat reply is cheap and keeps
# the user oriented. Turns may dip to MAX_OVERDRAFT; anything pricier than that
# (images, ad pipelines) requires a top-up via the confirm cards.
MAX_OVERDRAFT = 2000

_TOOLS_DESCRIPTION = """Available tools. There are two lists: these core tools, then many more app tools below. You may call ANY tool named in either list:
- show_ad_variations {store_id?, url?, count?: 1-5} - run the real ad-angles pipeline (scrape, research, angles, copy variations) and show Copy-A/B/C cards. Needs a store_id or a website url.
- generate_image {prompt, headline?, subline?, cta_text?, store_id?} - generate one brand ad image (1024x1024) and show it. The prompt should describe the ad layout.
- create_campaign {name, store_id?, goal?: sales|leads|traffic|awareness|engagement, angle?, daily_budget?, url?} - create a DRAFT campaign (optionally with the last shown angle's copy).
- navigate {page: marketing|campaigns|campaign_drafts|assets|stores|settings|messaging|customers|orders|product|analytics|content|agent} - give the user a clickable link to that screen.
- list_stores {} - list the user's stores with ids (call this first when store_id is unknown).
- list_campaigns {store_id?} - list recent campaigns.
- scrape_url {url} - fetch a website's text so you can discuss it.

App actions (each wraps the real Shopivell feature, as the signed-in user). Send flat args; omit store_id to use the current store:
"""
_APP_RULES = """

Rules for app actions: The app shows the results of look-up tools as a table card, so never repeat the rows as a markdown table in your reply: write one short summary line instead (for example how many there are and which is current). Elsewhere use light markdown only: short lists and **bold**; use a markdown table only for a comparison you wrote yourself. To show an image that has a URL, write it as ![description](url). Every action is about ONE store. Use the store the user names; if they name none, use the [CURRENT] store; if they have several stores and the request could be about any of them, ask which one. Always pass store_id (or store_name) and say which store you used in your reply. Anything that needs a screen (uploading a logo or banner, editing store details, Brand DNA) uses open_store_editor so the button opens that exact store. Connecting WhatsApp, Facebook, Instagram or an ad account never needs details from the user: call the connect_* tool at once and the user gets the button and steps. create_store makes a new store; create_campaign makes an ad campaign, never confuse them. Look things up with a read tool before changing them (ids come from list/get results). Tools marked "asks the user to confirm" are shown to the user as a card, so just call them. Tools marked "opens a screen" need the user's own login with Meta: call them and the user gets a button plus the steps. If an API error comes back, fix the arguments and retry once, otherwise tell the user plainly what is missing.
"""


class AgentService:
    def __init__(self, db: Session, user_id: str, store_id: Optional[str] = None, auth_header: Optional[str] = None):
        self.db = db
        self.auth_header = auth_header
        self.user_id = user_id
        self.default_store_id = store_id
        self.low_balance_notice: Optional[str] = None

    # ---------------- LLM plumbing (same pattern as market_research) ----------------
    def _llm_ready(self) -> bool:
        return bool(OPENROUTER_API_KEY) or OPENAI_API_KEY.startswith("sk-")

    def _llm(self, messages: List[Dict[str, str]], model: Optional[str] = None) -> Tuple[Optional[str], int]:
        """One LLM attempt. Returns (content, tokens_used) - usage from the API when
        reported, estimated from message sizes when not."""
        est = sum(estimate_tokens(json.dumps(m)) for m in messages) + 300
        if OPENAI_API_KEY.startswith("sk-"):
            try:
                r = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                    json={"model": model or os.getenv("AGENT_LLM_MODEL", "gpt-6-luna"), "messages": messages},
                    timeout=90,
                )
                r.raise_for_status()
                data = r.json()
                used = ((data.get("usage") or {}).get("total_tokens")) or est
                return data["choices"][0]["message"]["content"], int(used)
            except Exception as e:
                logger.warning("[Agent] OpenAI direct failed: %s", e)
        if OPENROUTER_API_KEY:
            try:
                r = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}",
                             "HTTP-Referer": "https://shopivell.com", "X-Title": "Shopivell Agent",
                             "Content-Type": "application/json"},
                    json={"model": model or os.getenv("OPENROUTER_AGENT_LLM_MODEL", "openai/gpt-4o-mini"),
                          "max_tokens": 2000, "messages": messages},
                    timeout=120,
                )
                r.raise_for_status()
                data = r.json()
                used = ((data.get("usage") or {}).get("total_tokens")) or est
                return data["choices"][0]["message"]["content"], int(used)
            except Exception as e:
                logger.warning("[Agent] OpenRouter failed: %s", e)
        return None, 0

    def _parse_agent_json(self, content: str) -> Dict[str, Any]:
        """The model's JSON decision. Tolerates fences, trailing junk and slightly broken objects (a stray comma,
        an extra brace): when strict parsing fails, each known key is recovered on its own."""
        content = re.sub(r"^```(?:json)?|```$", "", (content or "").strip(), flags=re.MULTILINE).strip()
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        dec = json.JSONDecoder()
        out: Dict[str, Any] = {}
        m = re.search(r'"reply"\s*:\s*', content)
        if m:
            try:
                val, _ = dec.raw_decode(content[m.end():])
                if isinstance(val, str):
                    out["reply"] = val
            except Exception:
                pass
        for key in ("tool", "propose", "spec"):
            m = re.search(r'"%s"\s*:\s*' % key, content)
            if m:
                try:
                    val, _ = dec.raw_decode(content[m.end():])
                    if isinstance(val, dict):
                        out[key] = val
                except Exception:
                    pass
        m = re.search(r'"need_more_info"\s*:\s*', content)
        if m:
            try:
                val, _ = dec.raw_decode(content[m.end():])
                if isinstance(val, str) and val:
                    out["need_more_info"] = val
            except Exception:
                pass
        if out:
            return out
        return {"reply": content or ""}

    # ---------------- context helpers ----------------
    def _resolve_store(self, store_id: Optional[str]) -> Optional[Any]:
        from modules.stores.models import Store
        q = self.db.query(Store)
        if store_id:
            return q.filter(Store.id == store_id, Store.owner_id == self.user_id).first()
        if self.default_store_id:
            s = q.filter(Store.id == self.default_store_id).first()
            if s:
                return s
        return q.filter(Store.owner_id == self.user_id).first()

    def _store_context(self, store) -> Dict[str, Any]:
        if not store:
            return {}
        return {
            "store_id": str(store.id),
            "name": store.store_name,
            "business_type": store.business_type,
            "website": store.store_link,
            "city": store.store_city,
            "country": store.store_country,
        }

    def _user_stores(self) -> List[Dict[str, Any]]:
        if getattr(self, "_stores_cache", None) is None:
            from modules.stores.models import Store
            rows = self.db.query(Store).filter(Store.owner_id == self.user_id).all()
            self._stores_cache = [{"store_id": str(x.id), "name": x.store_name, "business_type": x.business_type,
                                   "city": x.store_city} for x in rows]
        return self._stores_cache

    def _match_store(self, args: Dict[str, Any], message: str = "") -> Optional[Dict[str, Any]]:
        """The exact store an action is about: an explicit id, else a store the user NAMED (in the args or the message),
        else the current store. A named store always wins over the current one."""
        stores = self._user_stores()
        sid = str(args.get("store_id") or "").strip()
        for st in stores:
            if sid and sid == st["store_id"]:
                return st
        wanted = " ".join(str(args.get(k) or "") for k in ("store_name", "store") if isinstance(args.get(k), str)) or sid
        for text in (wanted, message):
            low = (text or "").lower()
            if not low:
                continue
            hits = [st for st in stores if st["name"] and (st["name"].lower() in low or (len(low) > 2 and low in st["name"].lower()))]
            if len(hits) == 1:
                return hits[0]
        return next((st for st in stores if st["store_id"] == str(self.default_store_id)), None) or (stores[0] if len(stores) == 1 else None)

    def _named_store(self, user_texts: List[str]) -> Optional[Dict[str, Any]]:
        """A store the user named in their latest messages (newest first). Naming a store is the only thing that
        settles which store an action is for when they have several."""
        stores = self._user_stores()
        for text in user_texts:
            low = (text or "").lower()
            hits = [st for st in stores if st["name"] and st["name"].lower() in low]
            if len(hits) == 1:
                return hits[0]
        return None

    def _stores_block(self) -> str:
        stores = self._user_stores()
        if not stores:
            return "The user has no stores yet."
        cur = str(self.default_store_id or "")
        lines = [f"- {st['name']} ({st['business_type'] or 'store'}, {st['city'] or 'no city'}) id={st['store_id']}"
                 + (" [CURRENT]" if st["store_id"] == cur else "") for st in stores]
        return "The user's stores:\n" + "\n".join(lines)

    # ---------------- tools ----------------
    def _tool_list_stores(self, args: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        from modules.stores.models import Store
        stores = self.db.query(Store).filter(Store.owner_id == self.user_id).all()
        data = [{"store_id": str(s.id), "name": s.store_name, "business_type": s.business_type,
                 "website": s.store_link, "logo": getattr(s, "logo_url", None)} for s in stores]
        return data, {}

    def _tool_list_campaigns(self, args: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        store = self._resolve_store(args.get("store_id"))
        if not store:
            return [], {}
        camps = (self.db.query(UrlCampaign)
                 .filter(UrlCampaign.store_id == store.id)
                 .order_by(UrlCampaign.created_at.desc()).limit(8).all())
        return [{"campaign_id": str(c.id), "name": c.name, "status": c.status.value if c.status else None,
                 "goal": c.goal.value if c.goal else None, "daily_budget": c.daily_budget} for c in camps], {}

    def _tool_scrape_url(self, args: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        url = args.get("url") or ""
        text = ""
        try:
            import requests as _rq
            r = _rq.get(url if url.startswith("http") else f"https://{url}", timeout=25,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128"},
                        allow_redirects=True)
            html = r.text
            text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()[:3500]
        except Exception as e:
            return f"scrape failed: {e}", {}
        return text, {}

    def _tool_show_ad_variations(self, args: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Run the real pipeline: scrape -> structured -> research -> angles."""
        from modules.market_research.service import MarketResearchService
        from modules.ad_angles.service import generate_ad_angles, gather_site_text

        store = self._resolve_store(args.get("store_id"))
        url = args.get("url") or (store.store_link if store else None)
        if not url:
            raise ValueError("need a store_id or url")

        svc = MarketResearchService()
        try:
            r = requests.get(url if url.startswith("http") else f"https://{url}", timeout=30,
                             headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128"},
                             allow_redirects=True)
            content = r.text
        except Exception as e:
            content = ""
            logger.warning("[Agent] scrape of %s failed: %s", url, e)

        # Clean text for the prompt and the profile; the raw markup is still passed on for
        # conversion-signal detection (pixel / checkout / form fingerprints).
        clean_text = ""
        try:
            clean_text = gather_site_text(content, url)
        except Exception as e:
            logger.warning("[Agent] site text failed: %s", e)

        structured = {}
        try:
            import asyncio
            structured = asyncio.run(svc._extract_structured_website_data(clean_text or content, url))
        except Exception as e:
            logger.warning("[Agent] extraction failed: %s", e)

        profile = {
            **structured,
            "business_type": (structured.get("business_type") if isinstance(structured, dict) else None)
            or (store.business_type if store else None) or "general business",
            "company_name": (structured.get("company_name") if isinstance(structured, dict) else None)
            or (store.store_name if store else None) or "This business",
            "products": [p.get("name") for p in (structured.get("services_products") or []) if isinstance(p, dict)][:8]
            if isinstance(structured, dict) else [],
            "location": (store.store_city if store else None) or "Zimbabwe",
        }
        if not profile["products"]:
            profile["products"] = [p for p in (store.products_or_services if store else []) or []][:8] or \
                                  [structured.get("business_type") or "main offer"]

        competitors, keywords, trends = [], [], []
        try:
            competitors = svc.find_competitors(business_type=profile["business_type"], location=profile["location"],
                                               products=profile["products"], domain=url,
                                               company_name=profile["company_name"])
        except Exception as e:
            logger.warning("[Agent] competitors failed: %s", e)
        try:
            keywords = svc.find_keywords(structured.get("keyword_seeds") or [profile["company_name"]], "zw",
                                         business_type=profile["business_type"], location=profile["location"])
        except Exception as e:
            logger.warning("[Agent] keywords failed: %s", e)

        try:
            count = max(1, min(5, int(args.get("count") or 3)))
        except (TypeError, ValueError):
            count = 3
        angles = generate_ad_angles(profile, competitors, keywords, trends, count, content, clean_text)
        if not angles:
            raise ValueError("the ad pipeline returned no angles (LLM unavailable?)")

        cards = []
        for ai, a in enumerate(angles, 1):
            for vi, v in enumerate(a.get("copy_variations") or [], 1):
                cards.append({
                    "angle": a.get("angle_name"),
                    "label": f"Copy-{chr(64 + vi)}",
                    "primary_text": v.get("primary_text"),
                    "headline": v.get("headline"),
                    "description": v.get("description"),
                    "cta": v.get("call_to_action"),
                    "optimization": v.get("optimization"),
                    "image_direction": v.get("image_direction") or a.get("visual_direction"),
                    "targeting_hint": v.get("targeting_hint") or {},
                    "benefit_chips": v.get("benefit_chips") or [],
                    "campaign_objective": a.get("campaign_objective"),
                    "leads_the_creative": bool(a.get("leads_the_creative") and vi == 1),
                })
        return cards, {"store_id": str(store.id) if store else None, "url": url,
                       "angle_count": len(angles), "campaign_objective": (angles[0] or {}).get("campaign_objective")}

    def _tool_generate_image(self, args: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        from modules.assets.service import generate_image_bytes
        prompt = args.get("prompt") or ""
        if not prompt:
            raise ValueError("need a prompt")
        bits = []
        if args.get("headline"):
            bits.append(f'Headline EXACTLY: {args["headline"]}')
        if args.get("subline"):
            bits.append(f'Subline EXACTLY: {args["subline"]}')
        if args.get("cta_text"):
            bits.append(f'CTA pill EXACTLY: {args["cta_text"]}')
        full = prompt + (" " + " ".join(bits) if bits else "") + \
            " Square 1:1 premium advertisement, crisp rendered text, graphic-designer-made."
        image_data, error = generate_image_bytes(full)
        if error or not image_data:
            raise ValueError(f"image generation failed: {error}")

        # Persist as an Asset so it shows up in Marketing > Assets and can be attached to ads.
        asset_id = None
        try:
            from modules.assets.models import Asset, AssetType
            store = self._resolve_store(args.get("store_id"))
            if store:
                from PIL import Image
                import io
                buf = io.BytesIO()
                Image.open(io.BytesIO(image_data)).convert("RGB").save(buf, format="JPEG", quality=90, optimize=True)
                jpg = buf.getvalue()
                from modules.assets.service import AssetService
                svc = AssetService(self.db)
                asset, err = svc.save_generated_image(store.id, jpg, args.get("headline") or "Agent image",
                                                      call_to_action=args.get("cta_text"))
                if not err and asset:
                    asset_id = str(asset.id)
        except Exception as e:
            logger.warning("[Agent] asset save skipped: %s", e)

        import base64
        return {"b64_png": base64.b64encode(image_data).decode(), "asset_id": asset_id,
                "headline": args.get("headline")}, {}

    def _tool_create_campaign(self, args: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        store = self._resolve_store(args.get("store_id"))
        if not store:
            raise ValueError("no store found for this user - call list_stores first")
        try:
            goal = CampaignGoal((args.get("goal") or "sales").strip().lower())
        except ValueError:
            goal = CampaignGoal.SALES
        camp = UrlCampaign(
            store_id=store.id,
            name=(args.get("name") or "Agent campaign")[:255],
            description=args.get("angle") or None,
            source_url=args.get("url") or store.store_link,
            goal=goal,
            daily_budget=float(args.get("daily_budget") or 5.0),
            status=CampaignStatus.DRAFT,
        )
        self.db.add(camp)
        self.db.flush()
        ad_set = UrlAdSet(campaign_id=camp.id, name=f"{camp.name} - Ad Set 1")
        self.db.add(ad_set)
        self.db.flush()
        angle = args.get("angle") if isinstance(args.get("angle"), dict) else None
        if angle and angle.get("primary_text"):
            self.db.add(UrlAdContent(
                ad_set_id=ad_set.id,
                headline=(angle.get("headline") or "")[:255] or None,
                primary_text=angle.get("primary_text"),
                description=(angle.get("description") or "")[:255] or None,
                call_to_action=(angle.get("cta") or "Learn More")[:100],
                destination_url=args.get("url") or store.store_link,
                creative_metadata={"source": "agent", "image_direction": angle.get("image_direction"),
                                   "optimization": angle.get("optimization")},
                variation_label="Agent-A",
            ))
        self.db.commit()
        return {"campaign_id": str(camp.id), "name": camp.name, "status": camp.status.value,
                "with_copy": bool(angle and angle.get("primary_text"))}, {}

    def _tool_navigate(self, args: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        key = (args.get("page") or "").strip().lower()
        route = next((r for r in APP_ROUTES if r["key"] == key), None)
        if not route:
            raise ValueError(f"unknown page '{key}'; one of {', '.join(r['key'] for r in APP_ROUTES)}")
        return {"page": route["key"], "path": route["path"], "desc": route["desc"]}, {}

    # ---------------- dispatch ----------------
    def _run_tool(self, name: str, args: Dict[str, Any]) -> Tuple[Any, str]:
        try:
            if name == "list_stores":
                data, _ = self._tool_list_stores(args)
                return data, "ok"
            if name == "list_campaigns":
                data, _ = self._tool_list_campaigns(args)
                return data, "ok"
            if name == "scrape_url":
                text, _ = self._tool_scrape_url(args)
                return text[:1500], "ok"
            if name == "show_ad_variations":
                cards, meta = self._tool_show_ad_variations(args)
                return cards, f"ok ({meta.get('angle_count')} angles)"
            if name == "generate_image":
                data, _ = self._tool_generate_image(args)
                return data, "ok"
            if name == "create_campaign":
                data, _ = self._tool_create_campaign(args)
                return data, "ok"
            if name == "navigate":
                data, _ = self._tool_navigate(args)
                return data, "ok"
            reg = tool_registry.BY_NAME.get(name)
            if reg:
                args = dict(args or {})
                target = None
                if name not in ("create_store", "update_store"):   # there store_name is data, not a selector
                    target = self._match_store(args)
                    if target and not args.get("store_id"):
                        args["store_id"] = target["store_id"]
                    args.pop("store_name", None)
                data, status = tool_registry.call(reg, args, self.auth_header, (target or {}).get("store_id") or self.default_store_id, self.user_id)
                return data, status
            return None, f"unknown tool {name}"
        except Exception as e:
            logger.warning("[Agent] tool %s failed: %s", name, e)
            return None, str(e)

    # ---------------- main turn ----------------
    def chat(self, conversation_id: uuid.UUID, message: str) -> Dict[str, Any]:
        conv = (self.db.query(AgentConversation)
                .filter(AgentConversation.id == conversation_id, AgentConversation.user_id == self.user_id)
                .first())
        if not conv:
            raise ValueError("conversation not found")

        # Soft gate: conversation always works (the wallet is system-wide AI credit,
        # and a reply is cheap), but a drowning user gets one nudge. Expensive tools
        # are separately confirmed in the UI and hard-gated there.
        balance = get_balance(self.db, self.user_id)
        self.low_balance_notice = None   # no per-message nudge; paid actions explain themselves when blocked

        user_msg = AgentMessage(conversation_id=conv.id, role="user", content=message[:8000])
        self.db.add(user_msg)
        self.db.commit()

        history = (self.db.query(AgentMessage)
                   .filter(AgentMessage.conversation_id == conv.id)
                   .order_by(AgentMessage.created_at.asc()).limit(40).all())

        store = self._resolve_store(self.default_store_id)
        store_block = json.dumps(self._store_context(store)) if store else "none (call list_stores)"
        llm_messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_HINT + "\n\n" + _TOOLS_DESCRIPTION + "\n" +
             tool_registry.catalogue_text(" ".join([message] + [(m.content or "") for m in history[-4:]])) +
             _APP_RULES + f"\n\nCurrent store context: {store_block}\n\n{self._stores_block()}"}]
        for m in history:
            text = m.content or " ".join(
                str(p.get("summary") or p.get("text") or "") for p in (m.parts or []) if isinstance(p, dict))
            if not text:
                continue
            llm_messages.append({"role": m.role, "content": text[:4000]})
        llm_messages.append({"role": "user", "content": message})

        user_texts = [message] + [m.content or "" for m in reversed(history) if m.role == "user"][1:5]
        parts: List[Dict[str, Any]] = []
        reply = ""
        total_used = 0
        went_negative = False
        for _ in range(3):  # up to 3 tool hops per user turn
            raw, used = self._llm(llm_messages)
            total_used += used
            if not raw:
                reply = reply or "I couldn't reach the AI service just now - try again in a minute."
                break
            decision = self._parse_agent_json(raw)
            reply = decision.get("reply") or reply
            tool = decision.get("tool") if isinstance(decision.get("tool"), dict) else None

            # Expensive actions arrive as a proposal for the user to confirm
            # in the UI (Adstellar-style spec card with Confirm/Cancel) —
            # never executed inline by the model.
            propose = decision.get("propose") if isinstance(decision.get("propose"), dict) else None
            if propose and (propose.get("name") or propose.get("tool")):
                tool_name = str(propose.get("name") or propose.get("tool"))
                _reg = tool_registry.BY_NAME.get(tool_name)
                if _reg and not _reg.needs_confirm:   # reads and screen handoffs never need a confirm card
                    tool = {"name": tool_name, "args": propose.get("args") or {}}
                    propose = None
            if propose and (propose.get("name") or propose.get("tool")):
                p_args = propose.get("args") if isinstance(propose.get("args"), dict) else {}
                spec = decision.get("spec") if isinstance(decision.get("spec"), dict) else {}
                if _reg:
                    spec = tool_registry.spec_for(_reg, p_args)
                defaults = {
                    "generate_image": {"title": "Generate image ad", "subtitle": "1:1 (square) brand ad image"},
                    "create_campaign": {"title": "Create draft campaign", "subtitle": "Draft campaign with one ad set"},
                    "show_ad_variations": {"title": "Run ad pipeline", "subtitle": "Scrape, research, ad angles and copy"},
                }.get(tool_name, {"title": tool_name or "Action", "subtitle": ""})
                spec_rows = spec.get("rows") if isinstance(spec.get("rows"), list) else []
                if not spec_rows:
                    label_map = {"headline": "Headline", "subline": "Subline", "cta_text": "CTA",
                                 "name": "Name", "goal": "Goal", "daily_budget": "Daily budget",
                                 "count": "Variations", "url": "URL"}
                    spec_rows = [[label_map[k], str(v)] for k, v in p_args.items()
                                 if label_map.get(k) and v]
                    if tool_name == "generate_image":
                        spec_rows += [["Aspect ratio", "1:1 (square)"], ["Quality", "Standard"]]
                parts.append({
                    "type": "action_proposal",
                    "tool": tool_name,
                    "args": p_args,  # full args (incl. prompt) — the confirm endpoint reruns with these
                    "spec": {
                        "title": str(spec.get("title") or defaults["title"]),
                        "subtitle": str(spec.get("subtitle") or defaults["subtitle"]),
                        "credits": int(spec.get("credits") or TOOL_COSTS.get(tool_name, DEFAULT_TOOL_COST)),
                        "rows": [[str(r[0]), str(r[1])] for r in spec_rows
                                 if isinstance(r, (list, tuple)) and len(r) >= 2][:8],
                    },
                })
                break
            if not tool or not tool.get("name"):
                break
            name, args = tool.get("name"), tool.get("args") or {}
            name = tool_registry.resolve(name, list(TOOL_COSTS))
            reg = tool_registry.BY_NAME.get(name)

            # Store-scoped action: with several stores the user must have named one; otherwise ask, with buttons.
            if reg and reg.store_scoped and len(self._user_stores()) > 1:
                named = self._named_store(user_texts)
                if not named:
                    reply = "Which store is this for?"
                    parts.append({"type": "choices", "question": reply,
                                  "options": [{"label": st["name"], "value": st["name"],
                                               "hint": ", ".join(x for x in (st["business_type"], st["city"]) if x)}
                                              for st in self._user_stores()]})
                    break
                args = {**args, "store_id": named["store_id"]}
                args.pop("store_name", None)

            # App actions that change data always go through the confirm card, whatever the model did.
            if reg and reg.needs_confirm:
                shown = dict(args)
                if "store_id" in reg.path_args and not shown.get("store_id") and self.default_store_id:
                    shown["store_id"] = self.default_store_id
                parts.append({"type": "action_proposal", "tool": name, "args": shown,
                              "spec": tool_registry.spec_for(reg, args)})
                break

            # Flows that need the user's own Meta sign-in: report status, then hand over a button + steps.
            if reg and reg.handoff:
                target = self._match_store(args, " ".join(user_texts)) or {}
                if reg.name == "open_store_editor" and str(args.get("focus") or "").lower() not in tool_registry.FOCUS_STEPS:
                    low = " ".join(user_texts).lower()
                    args = {**args, "focus": "logo" if "logo" in low else "banner" if "banner" in low
                            else "brand_dna" if ("dna" in low or "brand voice" in low) else "details"}
                info = tool_registry.handoff_result(reg, args, target)
                state = ""
                st_tool = tool_registry.BY_NAME.get(info.get("status_tool") or "")
                if st_tool:
                    st_data, st_status = tool_registry.call(st_tool, {}, self.auth_header, target.get("store_id") or self.default_store_id, self.user_id)
                    n = len(st_data) if isinstance(st_data, list) else (len((st_data or {}).get("accounts") or []) if isinstance(st_data, dict) else 0)
                    state = f"{n} already connected" if st_status == "ok" else ""
                parts.append({"type": "tool", "tool": name, "status": "ok", "args": {}})
                parts.append({"type": "handoff", "page": info["page"], "title": info["title"], "path": info["path"],
                              "steps": info["steps"], "state": state, "store_name": info["store_name"]})
                reply = reply or f"Open {info['page']} for {info['store_name']} to finish this."
                break

            # Expensive tools are hard-gated at the overdraft ceiling: with the
            # wallet empty, chat keeps working but pipelined/image tools wait
            # for a top-up (the user still sees the failure as tool status).
            projected = total_used + TOOL_COSTS.get(name, DEFAULT_TOOL_COST)
            if TOOL_COSTS.get(name, DEFAULT_TOOL_COST) > 0 and get_balance(self.db, self.user_id) - projected < -MAX_OVERDRAFT:
                tool_part = {"type": "tool", "tool": name, "status": "insufficient_tokens",
                             "args": {k: v for k, v in args.items() if k != "prompt"}}
                parts.append(tool_part)
                reply = "That action needs more AI credits. Top up and ask me again."
                break
            result, status = self._run_tool(name, args)
            total_used += TOOL_COSTS.get(name, DEFAULT_TOOL_COST)
            tool_part = {"type": "tool", "tool": name, "status": status, "args": {
                k: v for k, v in args.items() if k != "prompt"}}
            parts.append(tool_part)
            if name == "show_ad_variations" and isinstance(result, list):
                parts.append({"type": "ad_variations", "variations": result,
                              "summary": f"{len(result)} copy variations"})
                result_for_llm = f"{len(result)} variations produced (first: {json.dumps(result[0])[:400]})"
            elif name == "generate_image" and isinstance(result, dict):
                parts.append({"type": "image", "b64_png": result.get("b64_png"), "asset_id": result.get("asset_id"),
                              "headline": result.get("headline"), "summary": "image ready"})
                result_for_llm = f"image generated (asset_id={result.get('asset_id')})"
            elif name == "navigate":
                parts.append({"type": "links", "links": [result]})
                result_for_llm = f"linked to {result.get('path')}"
            else:
                if (reg or name in ("list_stores", "list_campaigns")) and result is not None:
                    dp = _data_part(name, result)
                    if dp:
                        parts.append(dp)
                result_for_llm = json.dumps(result, default=str)[:1500] if result is not None else f"failed: {status}"
            # Feed the result back so the next hop can react or produce the final reply.
            llm_messages.append({"role": "assistant", "content": raw})
            llm_messages.append({"role": "user", "content": f"Tool {name} result: {result_for_llm}"})

        # Charge the wallet once for the whole turn (LLM usage + tool costs). The work
        # is already done, so let a finishing turn dip below zero, but a user who was
        # already at zero never got here (gated above).
        if total_used > 0:
            new_balance, went_negative = charge_with_overdraft(
                self.db, self.user_id, total_used, "chat" if not parts else "chat+tools",
                detail=f"{total_used} tokens: conversation {conv.id}", store_id=conv.store_id)
        else:
            new_balance, went_negative = balance, False

        assistant_msg = AgentMessage(conversation_id=conv.id, role="assistant",
                                     content=reply or "Done.", parts=parts or None)
        self.db.add(assistant_msg)
        if conv.title in (None, "", "New chat"):
            conv.title = (message or "New chat")[:60]
        conv.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(assistant_msg)
        return {"conversation_id": str(conv.id), "message_id": str(assistant_msg.id),
                "reply": assistant_msg.content, "parts": assistant_msg.parts or [],
                "tokens_used": total_used, "balance": new_balance, "went_negative": went_negative,
                "low_balance_notice": self.low_balance_notice}


def _data_part(name: str, result: Any) -> Optional[Dict[str, Any]]:
    """A compact table for the chat UI from a read tool's JSON (a list of records or one record)."""
    if isinstance(result, dict):
        for k in ("items", "results", "data", "accounts", "orders", "products", "customers", "pages", "conversations"):
            if isinstance(result.get(k), list):
                result = result[k]
                break
    scalar = lambda v: isinstance(v, (str, int, float, bool)) and v != ""
    title = name.replace("_", " ").capitalize()
    if isinstance(result, list):
        rows = [r for r in result if isinstance(r, dict)][:8]
        if not rows:
            return {"type": "data", "title": title, "columns": [], "rows": [], "total": len(result)}
        keys: List[str] = []
        for r in rows:                      # columns from every row, so one empty first row hides nothing
            for k in r.keys():
                if k not in keys and scalar(r.get(k)):
                    keys.append(k)
        cols = ([k for k in keys if not k.endswith("_at") and k != "id" and not k.endswith("_id")] or keys)[:6]
        return {"type": "data", "title": title, "columns": cols, "total": len(result),
                "rows": [["" if r.get(c) is None else str(r.get(c))[:80] for c in cols] for r in rows]}
    if isinstance(result, dict):
        kv = [[k.replace("_", " "), str(v)[:80]] for k, v in result.items() if scalar(v)][:12]
        return {"type": "data", "title": title, "columns": ["Field", "Value"], "rows": kv, "total": len(kv)} if kv else None
    return None


def _run_tool_standalone(svc: "AgentService", name: str, args: Dict[str, Any]) -> Tuple[Any, str]:
    """Run one agent tool outside a chat turn (the chat UI's Confirm button on a
    proposed action card). Same execution path as the in-turn dispatch, so costs
    and behavior match exactly."""
    return svc._run_tool(name, args)
