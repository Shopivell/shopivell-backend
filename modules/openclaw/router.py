"""
OpenClaw API Router
Full API for frontend to interact with OpenClaw ad management
Add to Shopivell backend: modules/openclaw/router.py

Version: 2.1.0 - Added Platinum Pharmacy prescription flow with quotations
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, Query, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Tuple
from collections import OrderedDict
from datetime import datetime, timedelta
import asyncio
import contextvars
import difflib
import re
import time
import httpx
import os
import logging

from database import get_db, SessionLocal
from modules.stores.models import Store
from utils.jwt_auth import get_current_user, get_current_user_optional, CurrentUser
from modules.users.models import User
# Deterministic Platinum Pharmacy rules (phone validation, whole-number prices,
# stock checks, spelling suggestions, pharmacist handover). Pure functions so the
# same rules are shared by the chat flow and the scenario tests.
from modules.openclaw.pharmacy_rules import (
    HEALTH_QUESTION_MESSAGE,
    PHONE_ERROR_MESSAGE,
    PHARMACIST_QUESTION_MESSAGE,
    PHARMACIST_REVIEW_MESSAGE,
    SURE_CHECK_MARKER,
    OUT_OF_STOCK,
    cart_subtotal,
    extract_phone,
    extract_sure_check_item,
    format_price,
    is_affirmative,
    is_conversational,
    is_medication_question,
    is_medication_related,
    is_multi_item_selection,
    is_negative,
    is_purchase_intent,
    is_uncertain_request,
    extract_name_correction,
    last_assistant_message,
    looks_like_address,
    looks_like_correction,
    looks_like_person_name,
    normalize_phone,
    parse_detail_query,
    phone_error_message,
    parse_price,
    parse_stock,
    round_price,
    suggest_product_names,
    sure_confirmation_message,
)
from modules.openclaw.brand_context import load_brand_context as _load_brand_context

logger = logging.getLogger(__name__)


async def _authorize_openclaw_request(request: Request, db: Session = Depends(get_db),
                                      current_user=Depends(get_current_user_optional)):
    """Require store-scoped access for staff-facing OpenClaw routes."""
    path = request.url.path
    # These endpoints have their own webhook or MCP authentication.
    if '/mcp/pharmacy' in path or path.endswith('/zernio-webhook'):
        return
    if not current_user:
        raise HTTPException(status_code=401, detail='Not authenticated')
    store_id = request.path_params.get('store_id')
    if store_id:
        from modules.users.access import require_store_capability
        capability = ('messages' if path.endswith('/sync-whatsapp-inbox') else
                      'products' if '/catalog/' in path else 'ads')
        require_store_capability(db, current_user, store_id, capability)
    elif request.path_params.get('campaign_id'):
        from modules.users.access import require_store_capability
        if not current_user.store_id:
            raise HTTPException(status_code=403, detail='Select a store first')
        store = require_store_capability(db, current_user, current_user.store_id, 'ads')
        targets = await resolve_meta_targets(store)
        tree = await _zernio('GET', '/ads/tree', params={'accountId': targets['account_id']})
        campaign_id = str(request.path_params['campaign_id'])
        matching = [campaign for campaign in (tree.get('campaigns') or [])
                    if campaign_id in {str(campaign.get('platformCampaignId') or ''),
                                       str(campaign.get('id') or ''), str(campaign.get('_id') or '')}]
        if not matching:
            raise HTTPException(status_code=404, detail='Campaign not found in this store')
    elif current_user.role.lower() == 'staff':
        # These older routes refer to global campaign IDs and cannot yet prove
        # that the resource belongs to the selected store.
        raise HTTPException(status_code=403, detail='This action is not available to staff')


router = APIRouter(prefix="/openclaw", tags=["OpenClaw"],
                   dependencies=[Depends(_authorize_openclaw_request)])

# ---------------------------------------------------------------------------
# Zernio REST integration
#
# The original migration targeted an OpenClaw "gateway" REST API
# (http://openclaw:18789/api/skills/<skill>/<action>). The deployed OpenClaw
# image does not expose that API — it serves the OpenClaw Control UI. Meta Ads
# and Click-to-WhatsApp are provided directly by Zernio's REST API, so we call
# Zernio directly. `call_openclaw` is kept as a compatibility shim that routes
# each skill action to the service that actually provides it:
#   * skills/zernio-ads/*  -> Zernio REST API (ads, CTWA, insights)
#   * skills/ad-creator/*  -> ad copy via the ads-copy model call; the image prompt is the
#                             ads-image OpenClaw agent's art direction, rendered by a media model
#   * api/agents/goal/generate        -> the real OpenClaw goal agent      (modules.openclaw.gateway)
#   * api/agents/planner/create       -> the real OpenClaw planner agent   (modules.openclaw.gateway)
#   * api/agents/evaluator/evaluate   -> the real OpenClaw evaluator agent (modules.openclaw.gateway)
#   * market research judgement       -> the real OpenClaw ads-research agent
#                                        (modules.market_research.service)
#   * api/agents/executor/run         -> _run_executor_task() below (no LLM call — the plan already
#                                        names skill/action/parameters, execution is deterministic dispatch)
#   * plugins/optimizer/* -> the Python optimizer (modules/optimizer) runs the rules; its weekly
#                            calibration is the OpenClaw calibrator agent.
#
# The reasoning agents have no direct-OpenAI path and no local fallback: when the gateway is
# not configured or unreachable they raise 503/502 instead of inventing a goal, plan or
# assessment.
# ---------------------------------------------------------------------------
ZERNIO_API_BASE = os.getenv("ZERNIO_API_BASE", "https://zernio.com/api/v1")
ZERNIO_API_KEY = os.getenv("ZERNIO_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# OpenClaw Gateway integration (real OpenClaw, not custom Python implementation)
OPENCLAW_BRAIN_ENABLED = os.getenv("OPENCLAW_BRAIN_ENABLED", "").lower() in ("1", "true", "yes")
OPENCLAW_GATEWAY_URL = os.getenv("OPENCLAW_GATEWAY_URL", "http://openclaw:18789")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "shopivell-openclaw-gateway-2026")
# Agent target on the gateway. "openclaw" is the configured default agent;
# "openclaw/<agentId>" selects a dedicated one.
OPENCLAW_AGENT_MODEL = os.getenv("OPENCLAW_AGENT_MODEL", "openclaw")
# A gateway that has more than one agent configured refuses the bare "openclaw"
# selector ("Multiple agents are configured, but this operation has no explicit
# owner"), and every turn died on it with our "temporary problem" reply. Always
# qualify the model with the agent that owns the pharmacy sessions.
OPENCLAW_AGENT_ID = os.getenv("OPENCLAW_AGENT_ID", "shopivell").strip() or "shopivell"
if "/" not in OPENCLAW_AGENT_MODEL:
    OPENCLAW_AGENT_MODEL = f"{OPENCLAW_AGENT_MODEL}/{OPENCLAW_AGENT_ID}"
# Gateway calls get their own, shorter budget: a brain that is up but wedged
# must not hold a customer's message for the full model timeout before the
# direct path below answers it.
OPENCLAW_GATEWAY_TIMEOUT = float(os.getenv("OPENCLAW_GATEWAY_TIMEOUT", "25"))


def _first(d, *keys, default=None):
    """Return the first present, non-None key from a dict (defensive parsing)."""
    if isinstance(d, dict):
        for k in keys:
            if d.get(k) is not None:
                return d[k]
    return default


def _safe_json(text: str) -> dict:
    import json as _json
    import re as _re
    try:
        return _json.loads(text)
    except Exception:
        m = _re.search(r"\{.*\}", text or "", _re.S)
        if m:
            try:
                return _json.loads(m.group(0))
            except Exception:
                pass
    return {}


async def _zernio(method: str, path: str, json_body: dict = None, params: dict = None) -> dict:
    """Low-level Zernio REST call (Bearer API-key auth)."""
    if not ZERNIO_API_KEY:
        raise HTTPException(status_code=503, detail="ZERNIO_API_KEY is not configured on the backend.")
    import asyncio as _asyncio
    headers = {"Authorization": f"Bearer {ZERNIO_API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Zernio (behind Cloudflare) intermittently returns 429/403 under bursty
        # traffic. Retry those transient statuses with backoff so a momentary
        # rate-limit doesn't surface as "no connected accounts" in the UI.
        last = None
        for attempt in range(3):
            resp = await client.request(method, f"{ZERNIO_API_BASE}{path}", headers=headers, json=json_body, params=params)
            if resp.status_code in (429, 403) and attempt < 2:
                last = resp
                await _asyncio.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=f"Zernio API error ({resp.status_code}): {resp.text[:500]}")
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text}
        # exhausted retries on 429/403
        raise HTTPException(status_code=last.status_code if last else 502,
                            detail=f"Zernio API error ({last.status_code if last else 502}): {(last.text[:500] if last else 'rate limited')}")


async def _send_interactive_message(conv_id: str, account_id: str, interactive_type: str,
                                     body_text: str, action: dict, header: str = None, footer: str = None,
                                     recipient_phone: str = None) -> dict:
    """
    Send an interactive WhatsApp message via Zernio API.

    Args:
        conv_id: Conversation ID
        account_id: WhatsApp account ID
        interactive_type: "button" or "list"
        body_text: Message body text
        action: Action payload (buttons or sections)
        header: Optional header text
        footer: Optional footer text
        recipient_phone: Phone number in E.164 format (e.g., +263...)

    Returns:
        API response dict
    """
    interactive = {
        "type": interactive_type,
        "body": {"text": body_text},
        "action": action
    }
    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}

    # Send via inbox endpoint with interactive payload
    # Zernio supports: list, cta_url, flow, location_request_message, voice_call (NOT button!)
    payload = {
        "accountId": account_id,
        "type": "interactive",
        "interactive": interactive
    }

    try:
        result = await _zernio("POST", f"/inbox/conversations/{conv_id}/messages", json_body=payload)
        logger.info("Interactive %s message sent to conversation %s", interactive_type, conv_id)
        return result
    except Exception as e:
        logger.warning("Interactive message failed: %s", str(e)[:200])
        raise


def build_button_action(buttons: list) -> dict:
    """
    Build action payload for reply buttons (max 3).

    Args:
        buttons: List of {"id": "btn_id", "title": "Button Text"}

    Returns:
        Action dict for interactive message
    """
    return {
        "buttons": [
            {"type": "reply", "reply": {"id": btn["id"], "title": btn["title"][:20]}}
            for btn in buttons[:3]
        ]
    }


def build_list_action(button_text: str, sections: list) -> dict:
    """
    Build action payload for list message.

    Args:
        button_text: Text on the list button (max 20 chars)
        sections: List of {"title": "Section", "rows": [{"id": "row_id", "title": "Row Title", "description": "..."}]}

    Returns:
        Action dict for interactive message
    """
    return {
        "button": button_text[:20],
        "sections": sections
    }


async def _llm(path: str, payload: dict, timeout: float = 60.0, session_key: str = None) -> dict:
    """Chat/image generation through OpenClaw Gateway, OpenAI, or OpenRouter.

    When OPENCLAW_BRAIN_ENABLED=true and a session_key is provided, requests are
    forwarded to the OpenClaw gateway which provides conversation memory and
    agent capabilities. Otherwise falls back to direct OpenAI/OpenRouter calls.
    """
    # Use OpenClaw Gateway when enabled and session_key is provided
    if OPENCLAW_BRAIN_ENABLED and session_key and path == "/chat/completions":
        base = OPENCLAW_GATEWAY_URL
        headers = {
            "Authorization": f"Bearer {OPENCLAW_GATEWAY_TOKEN}",
            "Content-Type": "application/json",
            "X-OpenClaw-Session-Key": session_key,  # For conversation isolation
        }
        # OpenClaw expects "openclaw" or "openclaw/<agentId>", not the model name
        openclaw_payload = payload.copy()
        openclaw_payload["model"] = OPENCLAW_AGENT_MODEL
        logger.info("[OpenClaw] Forwarding to gateway with session: %s", session_key[:30] + "...")
        gateway_error = None
        try:
            async with httpx.AsyncClient(timeout=min(float(timeout), OPENCLAW_GATEWAY_TIMEOUT)) as client:
                resp = await client.post(f"{base}/v1{path}", headers=headers, json=openclaw_payload)
        except Exception as e:
            gateway_error = f"{type(e).__name__}: {e}"
        else:
            if resp.status_code < 400:
                return resp.json()
            gateway_error = f"{resp.status_code}: {resp.text[:200]}"
        # A brain that is down, wedged or unhappy must not cost the customer
        # their reply - fall through to the direct model below, which is the
        # same model the pharmacy tool loop was already written against.
        logger.error("[OpenClaw] gateway failed (%s); answering from the direct model",
                     gateway_error)

    # Fallback: Prefer OpenAI direct over OpenRouter
    if OPENAI_API_KEY:
        base = "https://api.openai.com/v1"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    elif os.getenv("OPENROUTER_API_KEY", ""):
        or_key = os.getenv("OPENROUTER_API_KEY", "")
        base = "https://openrouter.ai/api/v1"
        headers = {"Authorization": f"Bearer {or_key}", "HTTP-Referer": "https://shopivell.com",
                   "X-Title": "Shopivell Ad Creator", "Content-Type": "application/json"}
    else:
        raise HTTPException(status_code=503,
                            detail="No OPENAI_API_KEY / OPENROUTER_API_KEY configured for ad creative generation.")
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{base}{path}", headers=headers, json=payload)
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code,
                                detail=f"LLM error ({resp.status_code}): {resp.text[:300]}")
        return resp.json()


async def _openclaw_agent_reply(system_prompt: str, user_text: str, session_key: str,
                                timeout: float = 45.0) -> str:
    """Run one WhatsApp turn on the real OpenClaw agent.

    The agent owns the conversation and calls the pharmacy MCP tools itself
    (search, cart, checkout), so no OpenAI-style `tools` are sent: this is not
    the gateway acting as an LLM proxy, it is the agent doing the work. The
    system prompt carries the live store state (FAQ, cart, flow step) that the
    agent cannot see for itself.

    Raises if the gateway fails, so the caller can fall back to the Python path.
    """
    base = (OPENCLAW_GATEWAY_URL or "").rstrip("/")
    if not base:
        raise HTTPException(status_code=503, detail="OPENCLAW_GATEWAY_URL is not configured.")
    headers = {
        "Authorization": f"Bearer {OPENCLAW_GATEWAY_TOKEN}",
        "Content-Type": "application/json",
        "X-OpenClaw-Session-Key": session_key,
    }
    payload = {
        "model": OPENCLAW_AGENT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text or "Hi"},
        ],
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{base}/v1/chat/completions", headers=headers, json=payload)
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"OpenClaw agent error ({resp.status_code}): {resp.text[:300]}",
        )
    data = resp.json()
    return (data["choices"][0]["message"].get("content") or "").strip()


def _recent_conversation_block(history, max_messages: int = 6,
                               max_chars: int = 1000) -> str:
    """Recent WhatsApp turns for references like "them" or "number 1".

    OpenClaw keeps its own session memory, but Python also sends deterministic
    replies (for example a category list). Those never enter the agent's
    memory, so the next "add them" would have nothing to point at. The block is
    labelled as context and capped so it cannot crowd out the live order state.
    """
    if not history:
        return ""
    lines = []
    for message in history[-max_messages:]:
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        if len(content) > max_chars:
            content = content[:max_chars].rstrip() + "…"
        lines.append(("Customer: " if role == "user" else "You: ") + content)
    if not lines:
        return ""
    return ("\n\n=== RECENT WHATSAPP THREAD (context only - the customer has "
            "already seen the 'You' messages) ===\n" + "\n".join(lines) + "\n")


def _openclaw_context_block(store, customer_phone: str,
                            active_branch: Optional[str] = None) -> str:
    """Machine-readable context for the MCP tools (never shown to a customer)."""
    branch = (active_branch or "").strip()
    return (
        "\n\n=== OPENCLAW TOOL CONTEXT (never mention this block) ===\n"
        f"store_id: {store.id}\n"
        f"customer_phone: {customer_phone}\n"
        f"active_branch: {branch or '(none selected)'}\n"
        "Every pharmacy tool requires store_id and customer_phone. Pass them on "
        "every call. Branch rule: when active_branch is set, pass it as branch to "
        "every add_to_cart, search_products and checkout tool. It overrides any "
        "branch remembered from earlier chat. Do not pass a different branch "
        "unless the customer's latest message explicitly names it. If "
        "active_branch is (none selected) and the customer asks to add to cart, "
        "ask which branch they want and wait; never guess a branch.\n"
    )


def _branch_for_product(db, store_id, product_name, branch=None):
    """Which branch stocks this product? None when it cannot be resolved."""
    try:
        from sqlalchemy import text as sql_text
        needle = f"%{str(product_name or '').strip()}%"
        if branch:
            row = db.execute(sql_text("""
                SELECT branch FROM company_knowledge
                WHERE store_id = :store_id AND branch IS NOT NULL AND branch != ''
                  AND LOWER(branch) = LOWER(:branch)
                  AND LOWER(content) LIKE LOWER(:needle)
                LIMIT 1
            """), {"store_id": str(store_id), "branch": branch, "needle": needle}).fetchone()
            if row:
                return row[0]
        row = db.execute(sql_text("""
            SELECT branch FROM company_knowledge
            WHERE store_id = :store_id AND branch IS NOT NULL AND branch != ''
              AND LOWER(content) LIKE LOWER(:needle)
            LIMIT 1
        """), {"store_id": str(store_id), "needle": needle}).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.warning("Could not resolve branch for %s: %s", product_name, e)
        return None


# "I've added X" / "removed Y" / "your cart now has ..." - sentences that promise
# the customer a cart change.
_CART_CLAIM_RE = re.compile(
    r"\b(added|removed|deleted|updated|changed|cleared|emptied|cart now|now have|now has)\b",
    re.IGNORECASE,
)


def _cart_claim_mismatch(reply: str, before, after) -> bool:
    """True when a reply promises a cart change that did not happen."""
    if not reply or not _CART_CLAIM_RE.search(reply):
        return False
    return list(before or []) == list(after or [])


async def _repair_cart_claim(db, store, customer_phone, messages, reply, cart_before,
                             model: str, max_tokens: int) -> str:
    """Give the model one chance to actually do what it just claimed.

    Confirmed live: gpt-4o-mini sometimes replies "I've removed the DOVE SOAP"
    (or "I've added X") without calling any tool, so the customer is told about a
    change the cart never got. Nothing in the reply can fix that - only the tool
    can - so the mismatch is spelled out and the model is asked to call it.
    """
    if not (db and store and customer_phone and reply):
        return reply
    state = _get_order_state(db, str(store.id), customer_phone) or {}
    if not _cart_claim_mismatch(reply, cart_before, state.get("cart_items") or []):
        return reply

    logger.warning("Reply claimed a cart change that did not happen - asking the model to redo it")
    retry_messages = list(messages)
    retry_messages.append({"role": "assistant", "content": reply})
    retry_messages.append({"role": "system", "content": (
        "CART CHECK FAILED: the cart did not change, so nothing was added, removed or "
        "updated. Your previous message was therefore wrong. Call the correct tool now "
        "(add_to_cart, update_cart or remove_from_cart) for what the customer asked, then "
        "tell them exactly what the tool result says. If the request is ambiguous, ask "
        "instead of guessing. Never claim a change a tool did not make."
    )})
    try:
        res = await _llm("/chat/completions", {
            "model": model, "messages": retry_messages, "max_tokens": max_tokens,
            "temperature": 0.3, "tools": PHARMACY_TOOLS, "tool_choice": "auto",
        }, timeout=30.0)
        msg = res["choices"][0]["message"]
        if not msg.get("tool_calls"):
            return (msg.get("content") or "").strip() or reply

        import json
        retry_messages.append(msg)
        for tool_call in msg["tool_calls"]:
            try:
                args = json.loads(tool_call["function"]["arguments"])
            except Exception:
                args = {}
            result = await _execute_pharmacy_tool(
                db, store, customer_phone, tool_call["function"]["name"], args)
            retry_messages.append({"role": "tool", "tool_call_id": tool_call["id"],
                                   "content": result})

        res2 = await _llm("/chat/completions", {
            "model": model, "messages": retry_messages,
            "max_tokens": max_tokens, "temperature": 0.4,
        }, timeout=30.0)
        return (res2["choices"][0]["message"]["content"] or "").strip() or reply
    except Exception as e:
        logger.warning("cart-claim repair failed: %s", e)
        return reply


# Questions the catalogue cannot answer. The spelling-tolerant product search
# must not run for these - "which branches do you have" was answered with
# "Did you mean ANKLE BRACE?" instead of the branch list.
# "lets continue" was matched to "LIL-LETS" products - added conversational phrases
_NON_PRODUCT_INTENTS = (
    "order", "orders", "cart", "checkout", "check out", "collect",
    "collection", "delivery", "deliver", "address", "payment", "pay",
    "ecocash", "onemoney", "innbucks", "cash", "branch", "branches",
    "hours", "opening", "open", "location", "located", "cancel", "refund",
    "hello", "hi", "hey", "thank", "thanks",
    # Conversational phrases that should never match products
    "continue", "lets", "proceed", "go ahead", "done", "finish", "finished",
    "ok", "okay", "yes", "no", "sure", "fine", "good", "great", "perfect",
    "name", "phone", "number", "my", "tell", "what", "whats", "show",
    "confirm", "confirmed", "details", "info", "information",
)


def _looks_like_product_question(text) -> bool:
    """False for messages about orders, branches, payment or delivery."""
    low = " " + re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()) + " "
    if not low.strip():
        return False
    if _is_cart_edit_message(text):
        return False
    return not any(f" {word} " in low for word in _NON_PRODUCT_INTENTS)


# Cart edits are commands, not product searches. "no take one out" was fuzzy-
# matched into "Did you mean NIVEA LOTION?" and answered with a product list
# instead of touching the cart.
_CART_EDIT_WORDS = (
    "remove", "removed", "removing", "delete", "deleted", "clear", "cleared",
    "empty", "emptied", "quantity", "qty", "another", "more", "less", "fewer",
    "make it", "change it", "take it out", "take one out", "take them out",
)


def _is_cart_edit_message(text) -> bool:
    low = " " + re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()) + " "
    if not low.strip():
        return False
    if any(f" {word} " in low for word in _CART_EDIT_WORDS):
        return True
    return bool(re.search(r"\b(add|give me)\b[^.?!]{0,15}\bone\b", low))


def _store_branches(db, store_id):
    """Branch names this store actually has catalogue entries for."""
    try:
        from sqlalchemy import text as sql_text
        rows = db.execute(sql_text("""
            SELECT DISTINCT branch FROM company_knowledge
            WHERE store_id = :store_id AND branch IS NOT NULL AND branch != ''
            ORDER BY branch
        """), {"store_id": str(store_id)}).fetchall()
        branches = [r[0] for r in rows if r[0]]
        # No branches means no catalogue yet - never invent another store's
        # branch names (Express Care used to be told about Angwa/Bulawayo).
        return branches
    except Exception as e:
        logger.warning("Could not list branches: %s", e)
        return []


def _listed_store_branches(db, store):
    """Combine branch names from the store's FAQ with its catalogue branches."""
    branches = _store_branches(db, store.id)
    try:
        from modules.whatsapp.models import FAQ
        faqs = (db.query(FAQ).filter(FAQ.store_id == store.id, FAQ.is_active.is_(True),
                                    FAQ.question.ilike('%branch%')).order_by(FAQ.display_order).all())
        names = []
        for faq in faqs:
            if not re.search(r'\b(?:where|which|locations?|branches)\b', faq.question or '', re.I):
                continue
            for line in (faq.answer or '').splitlines():
                match = re.match(r'^\s*\d+[.)]\s*(.+?)\s+[-–—]\s+', line)
                if not match:
                    continue
                name = match.group(1).strip()
                store_name = (store.store_name or '').strip()
                if store_name and name.lower().startswith(store_name.lower() + ' '):
                    name = name[len(store_name):].strip()
                if name and name.lower() not in {b.lower() for b in names}:
                    names.append(name)
            if names:
                break
        for branch in branches:
            if branch.lower() not in {name.lower() for name in names}:
                names.append(branch)
        return names or branches
    except Exception as exc:
        logger.warning('Could not read branch FAQ: %s', exc)
        return branches


def _catalogue_price(db, store_id, product_name, branch=None):
    """The real catalogue price for a product, parsed from its knowledge entry.

    Pass the branch the customer is shopping in: the same item is priced per
    branch ("BENYLIN 4 FLU" is $8 at Gweru and $9 at Angwa), so an unfiltered
    lookup can quote a price the branch does not charge. Within a branch the
    shortest title wins, which is the plain item rather than a bundle.
    """
    try:
        from sqlalchemy import text as sql_text
        needle = f"%{str(product_name or '').strip()}%"
        branch_filter = "AND LOWER(branch) = LOWER(:branch)" if branch else ""
        params = {"store_id": str(store_id), "needle": needle}
        if branch:
            params["branch"] = branch
        row = db.execute(sql_text(f"""
            SELECT content FROM company_knowledge
            WHERE store_id = :store_id AND LOWER(content) LIKE LOWER(:needle)
            {branch_filter}
            ORDER BY LENGTH(title) ASC
            LIMIT 1
        """), params).fetchone()
        if not row or not row[0]:
            return None
        match = re.search(r"price\s*:\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", str(row[0]), re.IGNORECASE)
        return float(match.group(1)) if match else None
    except Exception as e:
        logger.warning("Could not read catalogue price for %s: %s", product_name, e)
        return None


_META_CTAS = {
    "LEARN_MORE", "SHOP_NOW", "SIGN_UP", "BOOK_TRAVEL", "CONTACT_US", "DOWNLOAD",
    "GET_OFFER", "GET_QUOTE", "SUBSCRIBE", "WATCH_MORE", "ADD_TO_CART", "APPLY_NOW",
    "BOOK_NOW", "BUY_NOW", "BUY_TICKETS", "DONATE", "DONATE_NOW", "GET_DIRECTIONS",
    "GET_SHOWTIMES", "LISTEN_NOW", "ORDER_NOW", "PLAY_GAME", "REQUEST_TIME",
    "SEE_MENU", "START_ORDER", "INSTALL_MOBILE_APP", "USE_APP",
}


def _cta(v, default="LEARN_MORE"):
    v = (str(v or "")).strip().upper().replace(" ", "_")
    return v if v in _META_CTAS else default


def _goal(v, default="traffic"):
    # Zernio Meta goals: engagement, traffic, awareness, video_views,
    # lead_generation, lead_conversion, conversions, app_promotion,
    # catalog_sales, page_likes.
    m = {
        "conversions": "conversions", "sales": "conversions", "outcome_sales": "conversions",
        "traffic": "traffic", "outcome_traffic": "traffic", "link_clicks": "traffic",
        "awareness": "awareness", "reach": "awareness", "outcome_awareness": "awareness",
        "leads": "lead_generation", "lead_generation": "lead_generation", "outcome_leads": "lead_generation",
        "engagement": "engagement", "outcome_engagement": "engagement",
        "video_views": "video_views", "app_promotion": "app_promotion",
        "catalog_sales": "catalog_sales", "page_likes": "page_likes",
    }
    return m.get((str(v or "")).strip().lower(), default)


# Country name -> ISO 3166-1 alpha-2. Zernio requires 2-letter codes; the UI
# (country-state-city) may submit full names. Covers common markets; extend freely.
_COUNTRY_ISO = {
    "united states": "US", "united states of america": "US", "usa": "US", "america": "US",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB",
    "canada": "CA", "australia": "AU", "new zealand": "NZ", "ireland": "IE",
    "south africa": "ZA", "zimbabwe": "ZW", "zambia": "ZM", "botswana": "BW",
    "namibia": "NA", "mozambique": "MZ", "malawi": "MW", "kenya": "KE",
    "nigeria": "NG", "ghana": "GH", "tanzania": "TZ", "uganda": "UG",
    "egypt": "EG", "morocco": "MA", "ethiopia": "ET", "rwanda": "RW",
    "india": "IN", "pakistan": "PK", "bangladesh": "BD", "china": "CN",
    "japan": "JP", "south korea": "KR", "singapore": "SG", "malaysia": "MY",
    "indonesia": "ID", "philippines": "PH", "thailand": "TH", "vietnam": "VN",
    "united arab emirates": "AE", "uae": "AE", "saudi arabia": "SA", "qatar": "QA",
    "germany": "DE", "france": "FR", "spain": "ES", "italy": "IT", "portugal": "PT",
    "netherlands": "NL", "belgium": "BE", "switzerland": "CH", "austria": "AT",
    "sweden": "SE", "norway": "NO", "denmark": "DK", "finland": "FI", "poland": "PL",
    "brazil": "BR", "mexico": "MX", "argentina": "AR", "chile": "CL", "colombia": "CO",
}


def _iso_country(v) -> str:
    """Coerce a country value to a 2-letter ISO code (best effort)."""
    s = str(v or "").strip()
    if len(s) == 2 and s.isalpha():
        return s.upper()
    return _COUNTRY_ISO.get(s.lower(), "")


def _iso_countries(v, default=None) -> list:
    """Normalise a countries value (list or scalar, names or codes) to ISO codes."""
    default = default or ["US"]
    if v is None:
        return default
    items = v if isinstance(v, (list, tuple)) else [v]
    out = [c for c in (_iso_country(x) for x in items) if c]
    # de-dupe, preserve order
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c); uniq.append(c)
    return uniq or default


MIN_DAILY_BUDGET = float(os.getenv("AD_MIN_DAILY_BUDGET", "2.0"))


def _coerce_budget(v, default=20) -> float:
    """The Planner sometimes emits budget as a nested object (e.g. {"daily": 2},
    {"amount": 2, "type": "daily"}) instead of a plain number - Zernio's schema
    wants budgetAmount as a bare number and 400s with "expected number, received
    object" otherwise. Unwrap the common shapes; fall back to default."""
    if isinstance(v, dict):
        v = _first(v, "amount", "daily", "value", "daily_budget", "budget", default=None)
    try:
        amount = float(v)
    except (TypeError, ValueError):
        amount = float(default)
    # Meta rejects ad set budgets at/below ~$2 ("must be more than $2.00"), so a
    # planner that splits a small total into a tiny daily amount would always 400.
    return max(amount, MIN_DAILY_BUDGET)


def _ctwa_payload(d: dict) -> dict:
    # POST /ads/messaging (destination=whatsapp). Zernio locks CTA/destination.
    # status/campaignStatus default to PAUSED: Zernio treats a missing status as ACTIVE, so a
    # Click-to-WhatsApp ad without them goes live (and spends) as soon as Meta accepts it.
    payload = {
        "status": str(_first(d, "status", default="PAUSED")).upper(),
        "campaignStatus": str(_first(d, "campaign_status", "campaignStatus", "status", default="PAUSED")).upper(),
        "accountId": _first(d, "account_id", "accountId"),
        "adAccountId": _first(d, "ad_account_id", "adAccountId"),
        "name": __import__("utils.text_clean", fromlist=["clean_ad_name"]).clean_ad_name(
            _first(d, "name", default=f"CTWA - {d.get('product_name', 'Campaign')}")),
        "headline": _first(d, "headline", default=""),
        "body": _first(d, "body", "primary_text", default=""),
        "imageUrl": _first(d, "image_url", "imageUrl", default=""),
        "budgetAmount": _coerce_budget(_first(d, "budget", "budgetAmount", default=20)),
        "budgetType": _first(d, "budget_type", "budgetType", default="daily"),
        "currency": _first(d, "currency", default="USD"),
        "destination": "whatsapp",
        "countries": _iso_countries(_first(d, "countries")),
    }
    page_id = _first(d, "page_id", "pageId")
    if page_id:
        payload["pageId"] = str(page_id)
    wa = _first(d, "whatsapp_number", "whatsappPhoneNumber")
    if wa:
        payload["whatsappPhoneNumber"] = str(wa)
    adv = _first(d, "advantage_audience", "advantageAudience")
    advantage_on = bool(adv)
    if adv is not None:
        payload["advantageAudience"] = 1 if adv else 0
    age_min, age_max = _first(d, "age_min", "ageMin"), _first(d, "age_max", "ageMax")
    if age_min:
        payload["ageMin"] = max(13, min(65, int(age_min)))
    # Meta rejects a maxAge below 65 whenever Advantage+ audience is on ("maximum age
    # audience control can't be set to lower than 65" - confirmed live) - Advantage+
    # needs room to expand, so a hard age cap conflicts with it. Drop it rather than
    # send a value Meta will reject.
    if age_max and not advantage_on:
        payload["ageMax"] = max(13, min(65, int(age_max)))
    end = _first(d, "end_date", "endDate")
    if end:
        payload["endDate"] = str(end)
    welcome = _first(d, "welcome_text", "welcomeText")
    if welcome:
        payload["welcomeMessage"] = {"text": str(welcome)[:300]}
        if _first(d, "prefill_text", "prefillText"):
            payload["welcomeMessage"]["prefillText"] = str(_first(d, "prefill_text", "prefillText"))[:300]
    return payload


async def _store_whatsapp_number(store) -> Optional[str]:
    """The E.164 number of the store's connected WhatsApp Business account, from the Zernio
    account metadata. Passed as whatsappPhoneNumber so the ad opens a chat with the number
    the store's bot answers on (Meta otherwise picks the Page's paired number itself)."""
    if not store or not store.zernio_profile_id:
        return None
    try:
        # Filtered server-side by this store's own Zernio profile (the API key is shared
        # across stores), same as _resolve_store_whatsapp_account_id.
        listing = await _zernio("GET", "/accounts", params={"profileId": store.zernio_profile_id})
        account = next((a for a in (listing.get("accounts") or []) if a.get("platform") == "whatsapp"), None)
        raw = (((account or {}).get("metadata") or {}).get("displayPhoneNumber") or "")
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits:
            return "+" + digits
    except Exception as e:
        logger.info("could not resolve store WhatsApp number: %s", e)
    return None


def _campaign_payload(d: dict) -> dict:
    # POST /ads/create. Requires accountId (Zernio account) + adAccountId (act_),
    # goal (not objective), linkUrl, imageUrl and callToAction.
    # status defaults to PAUSED: Zernio treats a missing status as ACTIVE, which would
    # start spending the moment the ad passes Meta review.
    goal = _goal(_first(d, "goal", "objective", "campaign_goal"))
    po = _first(d, "promoted_object", "promotedObject", default={}) or {}
    # Meta's conversion goals need a pixel + event; without one Zernio 400s. Traffic
    # is the closest goal that needs no tracking setup.
    if goal in ("conversions", "lead_conversion") and not (po.get("pixelId") or po.get("customConversionId")):
        goal = "traffic"
    payload = {
        "status": str(_first(d, "status", default="PAUSED")).upper(),
        "accountId": _first(d, "account_id", "accountId"),
        "adAccountId": _first(d, "ad_account_id", "adAccountId"),
        "name": __import__("utils.text_clean", fromlist=["clean_ad_name"]).clean_ad_name(
            _first(d, "name", "product_name", default="Campaign")),
        "goal": goal,
        "headline": _first(d, "headline", default=""),
        "body": _first(d, "body", "primary_text", default=""),
        "linkUrl": _first(d, "link_url", "linkUrl", "url", "destination_url", default=""),
        "imageUrl": _first(d, "image_url", "imageUrl", default=""),
        "callToAction": _cta(_first(d, "call_to_action", "callToAction", "conversion_button")),
        "budgetAmount": _coerce_budget(_first(d, "budget", "budgetAmount", default=20)),
        "budgetType": _first(d, "budget_type", "budgetType", default="daily"),
        "currency": _first(d, "currency", default="USD"),
        "countries": _iso_countries(_first(d, "countries")),
    }
    # Meta needs the Facebook Page the ad is published as; without it the creative is
    # rejected ("Failed to parse URL"). Zernio only auto-fills it for some goals.
    page_id = _first(d, "page_id", "pageId")
    if page_id:
        payload["promotedObject"] = {**(_first(d, "promoted_object", "promotedObject", default={}) or {}),
                                     "pageId": str(page_id)}
    if _first(d, "validate_only", "validateOnly"):
        payload["validateOnly"] = True
    adv = _first(d, "advantage_audience", "advantageAudience")
    advantage_on = bool(adv)
    age_min, age_max = _first(d, "age_min", "ageMin"), _first(d, "age_max", "ageMax")
    if age_min:
        payload["ageMin"] = max(13, min(65, int(age_min)))
    # See _ctwa_payload: Meta rejects maxAge < 65 whenever Advantage+ audience is on.
    if age_max and not advantage_on:
        payload["ageMax"] = max(13, min(65, int(age_max)))
    if adv is not None:
        payload["advantageAudience"] = 1 if adv else 0
    start = _first(d, "start_date", "startDate")
    end = _first(d, "end_date", "endDate")
    if start:
        payload["startDate"] = str(start)
    if end:
        payload["endDate"] = str(end)
    return payload


async def _ensure_hosted_image(d: dict) -> dict:
    """If d's image_url/imageUrl is a raw data: URI (e.g. straight from
    generate_image, which can return base64 instead of a hosted URL depending
    on the model), upload it to Shopivell's own storage first. Zernio/Meta
    reject anything that isn't a fetchable http(s) URL outright ("Media must
    be a public http(s) URL the platform can download") - launch_campaign
    already handled this for its own call path, but _dispatch_zernio's
    create_campaign/create_ctwa_campaign (used by the autonomous Executor)
    didn't, so a base64 image from the ad-creator agent always failed here."""
    image_val = _first(d, "image_url", "imageUrl")
    if not image_val or not str(image_val).startswith("data:"):
        return d
    store_id = d.get("store_id")
    if not store_id:
        return d
    try:
        import base64 as _b64
        import uuid as _uuid
        raw = str(image_val).split(",", 1)[-1]
        img_bytes = _b64.b64decode(raw)
        from database import SessionLocal
        from modules.assets.service import AssetService
        from modules.assets.models import AssetType
        _db = SessionLocal()
        try:
            asset, err = AssetService(_db).create_asset_from_upload(
                store_id=_uuid.UUID(str(store_id)),
                filename=f"ad_{store_id}.png",
                file_data=img_bytes,
                mime_type="image/png",
                file_type=AssetType.IMAGE,
                name=d.get("name") or "Ad creative",
                source="ad_creative",
            )
            url = (asset.cloudinary_secure_url or asset.cloudinary_url) if asset else None
        finally:
            _db.close()
        if url:
            return {**d, "image_url": url, "imageUrl": url}
        logger.warning("could not upload data: image for campaign creation: %s", err)
    except Exception as e:
        logger.warning("could not upload data: image for campaign creation: %s", e)
    return d


_META_FIXES = {
    2446886: "Link your WhatsApp number to the Facebook Page (Page > Settings > Linked accounts > WhatsApp), "
             "make sure the Page, WhatsApp account and ad account are in the same business portfolio, then try again.",
    1487246: "That WhatsApp number is not linked to this Page / ad account. Link it in Meta (Page > Settings > "
             "Linked accounts > WhatsApp), then try again.",
}


def friendly_ad_error(exc: HTTPException) -> HTTPException:
    """Turn 'Zernio API error (400): {json...}' into the message Meta actually gave the user
    (its error_user_title / error_user_msg) plus what to do for the known ones, so the UI
    shows 'Page with WhatsApp Business account required' instead of a JSON blob.

    The upstream error text is truncated, so the JSON often can't be parsed; the fields are
    read straight from the text."""
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)

    def field(name):
        key = '"' + name + '":"'
        i = detail.find(key)
        if i < 0:
            return None
        i += len(key)
        out = []
        while i < len(detail):
            ch = detail[i]
            if ch == chr(92):
                i += 2
                continue
            if ch == '"':
                break
            out.append(ch)
            i += 1
        return "".join(out) or None

    title, msg = field("error_user_title"), field("error_user_msg")
    # The top-level "error" is never cut off (error_user_msg often is), minus its
    # "Meta Ads API error (400; code 100, subcode N): " prefix.
    top = field("error")
    if top:
        marker = "): "
        cut = top.find(marker)
        top = top[cut + len(marker):] if top.startswith("Meta Ads API error") and cut >= 0 else top
        if not msg or len(top) >= len(msg):
            msg = top
    subcode = None
    k = detail.find('"error_subcode":')
    if k >= 0:
        digits = ""
        for ch in detail[k + len('"error_subcode":'):]:
            if ch.isdigit():
                digits += ch
            elif digits:
                break
        subcode = int(digits) if digits else None
    # Zernio's own errors (not proxied from Meta) use a flatter shape: top-level
    # "error"/"code"/"dashboard_url", no error_user_title/msg/subcode. "error" above
    # already picks up the message; add the actionable link when Zernio gives one.
    code = field("code")
    dashboard_url = field("dashboard_url")
    if not (title or msg):
        return exc
    text = f"{title}: {msg}" if title and msg and title not in msg else (msg or title)
    fix = _META_FIXES.get(subcode)
    if fix:
        text = f"{text} {fix}"
    elif code == "PAYMENT_REQUIRED" and dashboard_url:
        text = f"{text} Add one here: {dashboard_url}"
    return HTTPException(status_code=exc.status_code, detail=text)


async def _resolve_meta_ad_account(profile_id: str) -> Optional[dict]:
    """Resolve the real Zernio accountId + Meta adAccountId (act_...) bound to a
    store's Zernio profile. The Planner is only ever given the raw /accounts
    listing (profile-level connections), which doesn't include the act_-prefixed
    ad account id - it has to be looked up per-account via /ads/accounts. Without
    this, the Planner either invents an id or reuses the wrong one, and Zernio
    400s with 'adAccountId must start with "act_"'. Same resolution launch_campaign
    already does for manually-launched campaigns; the autonomous Executor needs it
    too, but doesn't have a DB session to reuse that endpoint's exact code."""
    def _acc_profile(a):
        p = a.get("profileId") or a.get("profile")
        return str(p.get("_id") if isinstance(p, dict) else (p or ""))
    try:
        # No cross-store fallback (confirmed live: it leaked one tenant's real
        # connection into another's autonomous campaign runs) - only this profile's
        # own connection.
        listing = await _zernio("GET", "/accounts")
        accts = listing.get("accounts", []) if isinstance(listing, dict) else (listing or [])
        meta_accts = [a for a in accts if a.get("platform") in ("facebook", "metaads")]
        meta_acc = next((a for a in meta_accts if _acc_profile(a) == str(profile_id)), None)
        if not meta_acc:
            return None
        zernio_account_id = meta_acc.get("_id") or meta_acc.get("id")
        ad_accounts = await _zernio("GET", "/ads/accounts", params={"accountId": zernio_account_id})
        ad_list = ad_accounts.get("accounts", []) if isinstance(ad_accounts, dict) else (ad_accounts or [])
        if not ad_list:
            return None
        ad_account_id = ad_list[0].get("id") or ad_list[0].get("accountId")
        if not ad_account_id:
            return None
        return {"account_id": zernio_account_id, "ad_account_id": ad_account_id}
    except Exception as e:
        logger.warning("could not resolve Meta ad account for profile %s: %s", profile_id, e)
        return None


async def _dispatch_zernio(action: str, d: dict) -> dict:
    d = d or {}
    if action == "list_connected_accounts":
        # /accounts lists the platform accounts connected under the API key/profile
        # (Facebook, WhatsApp, etc.). /ads/accounts needs a specific accountId, so
        # it can't be used to discover what's connected.
        res = await _zernio("GET", "/accounts")
        return {"accounts": _first(res, "accounts", "data", default=res if isinstance(res, list) else [])}
    if action == "create_store_profile":
        # Ads are scoped under a Zernio profile. Create one for the store. Zernio
        # returns the profile as a Mongo document whose id is `_id` (a 24-char
        # ObjectId) — do NOT fall back to our own store UUID, which Zernio rejects
        # as "Invalid profileId format".
        import re as _re
        name = d.get("store_name") or "Store"
        try:
            res = await _zernio("POST", "/profiles", json_body={"name": name})
            prof = res.get("profile") if isinstance(res, dict) and isinstance(res.get("profile"), dict) else res
            pid = _first(prof, "_id", "id", "profileId", "profile_id")
        except HTTPException as e:
            # Zernio profile names are unique. If one already exists it returns 409
            # with the existing profile id — reuse it rather than failing.
            detail = e.detail if isinstance(e.detail, str) else str(e.detail)
            m = _re.search(r'"existingProfileId"\s*:\s*"([^"]+)"', detail)
            if m:
                pid = m.group(1)
            elif e.status_code == 409 or "already exists" in detail:
                # Fall back to looking the profile up by name.
                listing = await _zernio("GET", "/profiles")
                profs = listing.get("profiles", []) if isinstance(listing, dict) else (listing or [])
                match = next((p for p in profs if p.get("name") == name), None)
                pid = _first(match or {}, "_id", "id")
            else:
                raise
        if not pid:
            raise HTTPException(status_code=502, detail="Could not resolve a Zernio profile id.")
        return {"profile_id": pid}
    if action == "get_oauth_url":
        # Ask Zernio for the real provider OAuth URL. /connect/facebook/ads covers
        # Meta ads + page messaging; /connect/whatsapp connects a WhatsApp Business
        # account for conversational messaging. headless=true keeps the whole
        # experience white-labelled: after approval Zernio returns the user to our
        # redirect_url (app.shopivell.com) instead of showing Zernio's own UI.
        connect_path = "/connect/whatsapp" if d.get("connect_type") == "whatsapp" else "/connect/facebook/ads"
        params = {"profileId": d.get("profile_id"), "headless": "true"}
        if d.get("redirect_url"):
            params["redirect_url"] = d["redirect_url"]
        res = await _zernio("GET", connect_path, params=params)
        return {"auth_url": _first(res, "authUrl", "auth_url", "url", default=""), "raw": res}
    if action == "list_campaigns":
        acct = _first(d, "ad_account_id", "profile_id")
        res = await _zernio("GET", "/ads/tree", params={"adAccountId": acct})
        return {"campaigns": _first(res, "campaigns", "data", "tree", default=[])}
    if action in ("get_insights", "get_ctwa_insights"):
        params = {k: v for k, v in {
            "adId": d.get("ad_id"), "campaignId": d.get("campaign_id"),
            "datePreset": d.get("date_preset"),
        }.items() if v}
        return await _zernio("GET", "/ads/tree", params=params)
    if action == "get_all_store_insights":
        acct = _first(d, "ad_account_id", "profile_id")
        return await _zernio("GET", "/ads/tree", params={"adAccountId": acct, "datePreset": d.get("date_preset", "last_7d")})
    if action == "get_conversion_stats":
        acct = _first(d, "ad_account_id", "profile_id")
        return await _zernio("GET", "/ads/tree", params={"adAccountId": acct, "fields": "conversions,leads"})
    if action == "create_campaign":
        d = await _ensure_hosted_image(d)
        return await _zernio("POST", "/ads/create", json_body=_campaign_payload(d))
    if action == "create_ctwa_campaign":
        d = await _ensure_hosted_image(d)
        return await _zernio("POST", "/ads/messaging", json_body=_ctwa_payload(d))
    if action == "pause_ad":
        # Confirmed live against Zernio's OpenAPI spec: there is no PATCH /ads/{id} — status
        # lives at PUT /ads/campaigns/{id}/status (this 405'd before the fix).
        cid = _first(d, "ad_id", "campaign_id")
        return await _zernio("PUT", f"/ads/campaigns/{cid}/status",
                             json_body={"status": "paused", "platform": _first(d, "platform", default="facebook")})
    if action == "update_campaign":
        cid = _first(d, "ad_id", "campaign_id")
        updates = _first(d, "updates", default={k: v for k, v in d.items() if k not in ("ad_id", "campaign_id")})
        status = str(updates.get("status", "")).lower()
        if status in ("active", "paused"):
            return await _zernio("PUT", f"/ads/campaigns/{cid}/status",
                                 json_body={"status": status, "platform": _first(d, "platform", default="facebook")})
        return await _zernio("PUT", f"/ads/campaigns/{cid}",
                             json_body={**updates, "platform": _first(d, "platform", default="facebook")})
    if action == "scale_budget":
        # Budget lives on the ad set, not the campaign, so the campaign_id we're given has to
        # be resolved to its ad set(s) first via /ads/tree, then each gets its own PUT.
        cid = _first(d, "ad_id", "campaign_id")
        pct = _first(d, "percentage")
        new_budget = _first(d, "new_budget", "budget")
        max_budget = _first(d, "max_budget")
        tree = await _zernio("GET", "/ads/tree", params={"adAccountId": _first(d, "ad_account_id", "profile_id")})
        campaigns = _first(tree, "campaigns", "data", "tree", default=[])
        camp = next((c for c in campaigns if str(_first(c, "platformCampaignId", "id")) == str(cid)), None)
        ad_sets = (camp or {}).get("adSets") or []
        results = []
        for a in ad_sets:
            aid = a.get("platformAdSetId") or a.get("id")
            current = ((a.get("budget") or a.get("adSetBudget") or {}).get("amount")) or 0
            if new_budget is not None:
                amount = float(new_budget)
            elif pct is not None:
                amount = float(current) * (1 + float(pct) / 100.0)
            else:
                amount = float(current)
            if max_budget is not None:
                amount = min(amount, float(max_budget))
            res = await _zernio("PUT", f"/ads/ad-sets/{aid}",
                                json_body={"platform": _first(d, "platform", default="facebook"),
                                           "budget": {"amount": amount,
                                                      "type": (a.get("budget") or a.get("adSetBudget") or {}).get("type", "daily")}})
            results.append(res)
        return {"ad_sets_updated": len(results), "results": results}
    raise HTTPException(status_code=501, detail=f"Zernio action '{action}' is not implemented.")


async def _openai_image_edit(prompt: str, image_urls: list, size: str = "1024x1024") -> str:
    """POST /images/edits with the store's own real images (logo, uploaded
    product/uniform photos) as reference input, so the model edits/extends
    real brand assets instead of hallucinating a logo or uniform from text
    alone. Multipart, unlike _llm()'s JSON-only /images/generations path, so
    it's implemented separately. OpenAI direct only - no OpenRouter equivalent."""
    files = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, url in enumerate(image_urls[:3]):
            try:
                r = await client.get(url)
                r.raise_for_status()
                ctype = r.headers.get("content-type", "image/png").split(";")[0]
                ext = "png" if "png" in ctype else ("webp" if "webp" in ctype else "jpg")
                files.append(("image[]", (f"ref_{i}.{ext}", r.content, ctype)))
            except Exception as e:
                logger.warning("Could not fetch reference image %s for edit: %s", url, e)
    if not files:
        raise ValueError("no reference images could be fetched")
    data = {"model": os.getenv("AD_IMAGE_MODEL", "gpt-image-2.5-flare"), "prompt": prompt, "size": size, "n": "1"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/images/edits",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            data=data, files=files,
        )
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"image edit error: {resp.text[:300]}")
        res = resp.json()
    item = (res.get("data") or [{}])[0]
    return item.get("url") or (f"data:image/png;base64,{item['b64_json']}" if item.get("b64_json") else "")


def _clean_ph(v) -> str:
    """Planner sometimes leaves '{{task_0.x}}' template text or 'unknown' as a value."""
    v = str(v or "").strip()
    return "" if (not v or "{{" in v or v.lower().startswith("unknown")) else v


def _research_summary(research: dict) -> str:
    """Condense research_market's raw competitor/keyword/trend lists into a short
    brief an LLM can actually use to pick a specific ad angle, instead of dumping
    the whole payload into the prompt."""
    if not research:
        return ""
    parts = []
    comps = research.get("competitors") or []
    if comps:
        names = [c.get("name") for c in comps[:5] if c.get("name")]
        if names:
            parts.append(f"Known competitors in this market: {', '.join(names)}.")
    kws = research.get("keywords") or []
    if kws:
        terms = [k.get("keyword") for k in kws[:8] if k.get("keyword")]
        if terms:
            parts.append(f"What people actually search for in this niche: {', '.join(terms)}.")
    trends = research.get("trends") or []
    if trends:
        titles = [t.get("title") for t in trends[:3] if t.get("title")]
        if titles:
            parts.append(f"Current trends/headlines in this industry: {'; '.join(titles)}.")
    return " ".join(parts)


async def _dispatch_ad_creator(action: str, d: dict) -> dict:
    d = d or {}
    if action in ("generate_ad_copy", "generate_whatsapp_copy"):
        name = _clean_ph(d.get("product_name")) or "the product"
        desc = _clean_ph(d.get("product_description"))
        channel = ("for a Click-to-WhatsApp ad that gets the user to message the business on WhatsApp"
                   if action == "generate_whatsapp_copy" else "for a Meta conversion ad")
        prompt = f"Write ad copy {channel}. Product: {name}. Details: {desc}."

        store_id = d.get("store_id")
        brand = _load_brand_context(store_id) if store_id else {}
        if brand.get("store_name") or brand.get("about"):
            biz_bits = []
            if brand.get("store_name"):
                biz_bits.append(f"Business: {brand['store_name']}" +
                                 (f" ({brand['business_type']})" if brand.get("business_type") else "") + ".")
            if brand.get("about"):
                biz_bits.append(f"About the business (use this to keep copy on-brand and specific, "
                                 f"don't just restate it): {brand['about'][:400]}")
            if brand.get("owner_creative_prompt"):
                biz_bits.append(f"Owner's creative direction: {brand['owner_creative_prompt']}")
            prompt += "\n\n" + " ".join(biz_bits)

        research_brief = _research_summary(d.get("research"))
        if research_brief:
            prompt += (
                f"\n\nMarket research: {research_brief} Use this to choose ONE specific, differentiated "
                "ad angle (a real gap versus competitors, or a genuine trending demand signal) - don't "
                "just describe the product generically."
            )

        prompt += (
            '\n\nReturn strict JSON with keys "headline" (max 40 chars), "body" (max 125 chars), '
            'and "ad_angle" (one short sentence naming the specific angle you chose and why).'
        )

        # Optional seasonal/event context - only surfaced to the model as
        # something it MAY use, never as a theme it must include. Most ad
        # copy should not mention any of these; only a genuinely close and
        # relevant event should ever show up in the output.
        if store_id:
            try:
                from database import SessionLocal
                from modules.stores.models import Store
                from modules.marketing_events.router import get_relevant_upcoming_events
                _db = SessionLocal()
                try:
                    _store = _db.query(Store).filter(Store.id == store_id).first()
                    events = await get_relevant_upcoming_events(_db, _store)
                finally:
                    _db.close()
                if events:
                    events_str = "; ".join(f"{e['name']} (in {e['days_until']} day(s))" for e in events)
                    prompt += (
                        f"\n\nFor context only, upcoming events near this ad's launch: {events_str}. "
                        "Only reference one of these if it would genuinely strengthen THIS specific ad "
                        "(e.g. it's a natural fit for the product and timing) - do not force a seasonal "
                        "or holiday theme where it doesn't fit. Most ads should not mention any of these "
                        "at all; ignore them if none apply."
                    )
            except Exception as e:
                logger.info("Could not fetch upcoming events for ad copy (store %s): %s", store_id, e)
        # Bare id for direct OpenAI, "openai/..." slug for the OpenRouter fallback —
        # _llm() picks OpenAI when OPENAI_API_KEY is set, so the model id must match.
        # gpt-5.6-terra (and the 6/5.6 family generally) reject a non-default temperature
        # ("Only the default (1) value is supported") — confirmed against the live API —
        # so it's only sent on the OpenRouter fallback, where gpt-4o-mini still accepts it.
        payload = {
            "model": (os.getenv("AD_COPY_MODEL", "gpt-5.6-terra") if OPENAI_API_KEY
                      else os.getenv("OPENROUTER_AD_COPY_MODEL", "openai/gpt-4o-mini")),
            "messages": [
                {"role": "system", "content": "You are an expert Meta Ads copywriter. Reply with JSON only."},
                {"role": "user", "content": prompt},
            ],
        }
        if not OPENAI_API_KEY:
            payload["temperature"] = 0.7
        res = await _llm("/chat/completions", payload)
        parsed = _safe_json(res["choices"][0]["message"]["content"])
        body = parsed.get("body", "")
        return {"headline": parsed.get("headline", ""), "body": body, "primary_text": body,
                "ad_angle": parsed.get("ad_angle", "")}
    if action == "generate_image":
        store_id = d.get("store_id")
        brand = _load_brand_context(store_id) if store_id else {}
        references = []
        if brand.get("logo_url"):
            references.append({"url": brand["logo_url"],
                               "kind": "the business's real logo"})
        for url in brand.get("real_asset_urls") or []:
            references.append({"url": url,
                               "kind": "a real photo the owner uploaded of the business, "
                                       "its staff, products or premises"})
        if brand.get("screenshot_url"):
            references.append({"url": brand["screenshot_url"],
                               "kind": "the homepage of the business's website "
                                       "(its real brand colours and products)"})

        # What the image should be is the ads-image agent's judgement, grounded in
        # the store's own facts. The backend renders that prompt; it no longer
        # composes one from a template.
        from modules.openclaw.agent_service import art_direct_image
        direction = await art_direct_image(
            {
                "business": {
                    "name": brand.get("store_name"),
                    "type": brand.get("business_type"),
                    "about": (brand.get("about") or "")[:600],
                    "products": brand.get("products"),
                    "country": brand.get("country"),
                    "website": brand.get("link_url"),
                    "brand_colours": brand.get("color_theme"),
                    "owner_creative_direction": brand.get("owner_creative_prompt"),
                },
                "product_name": _clean_ph(d.get("product_name")),
                "product_description": _clean_ph(d.get("product_description")),
                "channel": "Meta / Instagram feed ad, square",
                "campaign_objective": _clean_ph(d.get("goal") or d.get("objective")),
                "planner_direction": _clean_ph(d.get("prompt")),
                "market_context": _research_summary(d.get("research")),
            },
            references,
            store_id=str(store_id or ""),
        )
        prompt = direction["prompt"]
        # Only the references the agent actually asked for, so the model isn't
        # handed a photo the art direction never mentions.
        ref_urls = [references[i - 1]["url"] for i in direction["reference_indices"]]

        url = ""
        if ref_urls and OPENAI_API_KEY:
            try:
                url = await _openai_image_edit(prompt, ref_urls)
            except Exception as e:
                logger.warning("image edit with reference assets failed, falling back to text-to-image: %s", e)
                url = ""

        if not url:
            if OPENAI_API_KEY:
                # Direct OpenAI, not OpenRouter — GPT-Image-2.5 "flare": high-volume ad
                # creative at ~50% lower latency than gpt-image-1 with better quality.
                # Use "gpt-image-2.5-sunburst" (via AD_IMAGE_MODEL) for precision edits.
                res = await _llm("/images/generations", {
                    "model": os.getenv("AD_IMAGE_MODEL", "gpt-image-2.5-flare"),
                    "prompt": prompt, "size": "1024x1024", "n": 1,
                }, timeout=120.0)
                item = (res.get("data") or [{}])[0]
                url = item.get("url") or (f"data:image/png;base64,{item['b64_json']}" if item.get("b64_json") else "")
            elif os.getenv("OPENROUTER_API_KEY", ""):
                # OpenRouter fallback only when no OPENAI_API_KEY is configured. OpenRouter
                # has no /images/generations — image models return the PNG as a data URI
                # in message.images on the chat endpoint.
                res = await _llm("/chat/completions", {
                    "model": os.getenv("OPENROUTER_AD_IMAGE_MODEL", "openai/gpt-5-image-mini"),
                    "modalities": ["image", "text"],
                    "messages": [{"role": "user", "content": prompt}],
                }, timeout=120.0)
                images = ((res.get("choices") or [{}])[0].get("message") or {}).get("images") or []
                url = ((images[0].get("image_url") or {}).get("url") or "") if images else ""
            else:
                raise HTTPException(status_code=503,
                                    detail="No OPENAI_API_KEY / OPENROUTER_API_KEY configured for image generation.")
        return {"image_url": url, "url": url}
    if action == "research_market":
        # The Planner emits this before campaign_creation tasks; previously
        # unimplemented (501), which failed every plan that included it.
        from modules.market_research.service import MarketResearchService
        svc = MarketResearchService()
        def _real(v):
            v = str(v or "").strip()
            return "" if (not v or "unknown" in v.lower() or "{{" in v or "determine" in v.lower()) else v
        rb = _load_brand_context(d.get("store_id")) if d.get("store_id") else {}
        niche = (rb.get("business_type") or _real(d.get("niche")) or _real(d.get("product_name")) or "business")
        country = rb.get("country") or _real(d.get("target_country")) or "US"
        country_code = (_iso_countries([rb.get("country_code") or country]) or ["US"])[0]
        products = [p for p in (rb.get("products") or []) if isinstance(p, str)][:5] or             ([_real(d.get("product_name"))] if _real(d.get("product_name")) else [])
        result: Dict[str, Any] = {}
        try:
            result["competitors"] = svc.find_competitors(
                business_type=niche, location=country, products=products, country_code=country_code,
                company_name=rb.get("store_name") or None,
                domain=(rb.get("link_url") or "").replace("https://", "").replace("http://", "").strip("/") or None)
        except HTTPException:
            raise  # the ads-research agent is unavailable: fail loudly, not with an empty report
        except Exception as e:
            logger.warning("research_market competitors failed: %s", e)
            result["competitors"] = []
        try:
            result["keywords"] = svc.find_keywords(
                products or [niche], country_code=country_code.lower(), business_type=niche, location=country)
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("research_market keywords failed: %s", e)
            result["keywords"] = []
        try:
            result["trends"] = svc.find_trends(niche, location=country, country_code=country_code)
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("research_market trends failed: %s", e)
            result["trends"] = []
        return result
    if action == "generate_full_campaign":
        copy = await _dispatch_ad_creator("generate_ad_copy", d)
        image = await _dispatch_ad_creator("generate_image", d)
        return {"copy": copy, "image": image}
    raise HTTPException(status_code=501, detail=f"ad-creator action '{action}' is not implemented.")


async def _run_executor_task(task: dict) -> dict:
    """Execute one planner task by dispatching to the skill/action it names.

    No LLM call: the planner already decided skill, action and parameters, so
    execution is deterministic. Retries with exponential backoff up to the
    task's own max_retries (the planner sets that budget per task)."""
    task = task or {}
    skill = (task.get("skill") or "").strip()
    action = (task.get("action") or "").strip()
    parameters = task.get("parameters") or {}
    max_retries = max(1, int(task.get("max_retries", 1) or 1))

    if skill == "zernio-ads":
        dispatch = _dispatch_zernio
    elif skill == "ad-creator":
        dispatch = _dispatch_ad_creator
    else:
        return {"success": False, "error": f"Unknown skill '{skill}' for task {task.get('id')}"}

    last_error = None
    for attempt in range(max_retries):
        try:
            result = await dispatch(action, parameters)
            return {"success": True, "result": result}
        except HTTPException as e:
            last_error = str(e.detail)
        except Exception as e:
            last_error = str(e)
        if attempt < max_retries - 1:
            await asyncio.sleep(1.5 * (attempt + 1))
    return {"success": False, "error": last_error or f"Task '{action}' failed"}


async def call_openclaw(method: str, endpoint: str, data: dict = None) -> dict:
    """Compatibility shim routing OpenClaw skill/agent actions to real services.

    The OpenClaw gateway REST API the migration targeted does not exist on the
    deployed platform, so route each action to the service that provides it.
    """
    data = data or {}
    if "/skills/zernio-ads/" in endpoint:
        return await _dispatch_zernio(endpoint.rsplit("/", 1)[-1], data)
    if "/skills/ad-creator/" in endpoint:
        return await _dispatch_ad_creator(endpoint.rsplit("/", 1)[-1], data)
    if endpoint == "/api/agents/goal/generate":
        from modules.openclaw.agent_service import generate_goals
        goals = await generate_goals(
            data.get("store_id", ""),
            data.get("performance") or {},
            data.get("constraints") or {},
            data.get("store_name", ""),
            data.get("niche", ""),
            data.get("country", ""),
            data.get("business", ""),
        )
        return {"goals": goals}
    if endpoint == "/api/agents/planner/create":
        from modules.openclaw.agent_service import generate_plan
        plan = await generate_plan(
            data.get("goal") or {},
            data.get("available_budget") or 0,
            data.get("existing_campaigns"),
            data.get("store_context"),
            store_id=data.get("store_id", ""),
        )
        return {"plan": plan}
    if endpoint == "/api/agents/evaluator/evaluate":
        from modules.openclaw.agent_service import evaluate_progress
        evaluation = await evaluate_progress(
            data.get("goal") or {},
            data.get("plan") or {},
            data.get("task_results") or [],
            data.get("performance") or {},
            store_id=data.get("store_id", ""),
            store_context=data.get("store_context"),
        )
        return {"evaluation": evaluation}
    if endpoint == "/api/agents/executor/run":
        return await _run_executor_task(data.get("task") or {})
    raise HTTPException(
        status_code=501,
        detail=f"Unknown OpenClaw endpoint '{endpoint}'. Known agent endpoints: "
               "/api/agents/goal/generate, /api/agents/planner/create, "
               "/api/agents/evaluator/evaluate, /api/agents/executor/run.",
    )


# ============ Request/Response Models ============

class AdSettingsUpdate(BaseModel):
    ads_enabled: Optional[bool] = None
    target_roas: Optional[float] = None
    target_cpa: Optional[float] = None
    target_cpql: Optional[float] = None


class GenerateCampaignRequest(BaseModel):
    product_id: Optional[str] = None
    product_name: str
    product_description: str
    product_price: Optional[float] = None
    campaign_goal: str = "conversions"
    brand_voice: str = "professional"
    budget: float = 20.0


class GenerateCTWARequest(BaseModel):
    product_name: str
    product_description: str
    whatsapp_number: str
    budget: float = 20.0


class GenerateImageRequest(BaseModel):
    product_name: str
    product_description: str
    style: str = "lifestyle"
    dimensions: str = "square"
    brand_colors: Optional[List[str]] = None
    store_id: Optional[str] = None


class GenerateCopyRequest(BaseModel):
    product_name: str
    product_description: str
    angle: str
    variations: int = 3
    store_id: Optional[str] = None


class OptimizerConfigUpdate(BaseModel):
    scale_winner: Optional[Dict[str, Any]] = None
    kill_loser: Optional[Dict[str, Any]] = None
    pause_no_spend: Optional[Dict[str, Any]] = None
    creative_fatigue: Optional[Dict[str, Any]] = None
    # Targets the rules compare against; without them scale/kill stay off.
    target_roas: Optional[float] = None
    target_cpa: Optional[float] = None
    # False lets the optimizer actually change budgets (with ads_enabled and
    # OPTIMIZER_DRY_RUN=false); it defaults to dry run.
    dry_run: Optional[bool] = None
    # Opt-in: when True, target_roas/target_cpa are periodically re-proposed by a model
    # grounded in this store's real niche/performance instead of staying a manual number.
    auto_calibrate: Optional[bool] = None


# ============ Store Ad Settings ============

@router.get("/stores/{store_id}/ad-settings")
async def get_ad_settings(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get store ad settings"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    return {
        "ads_enabled": getattr(store, 'ads_enabled', False),
        "target_roas": getattr(store, 'target_roas', 2.5),
        "target_cpa": getattr(store, 'target_cpa', 10.0),
        "target_cpql": getattr(store, 'target_cpql', None),
        "zernio_profile_id": getattr(store, 'zernio_profile_id', None),
    }


@router.patch("/stores/{store_id}/ad-settings")
async def update_ad_settings(
    store_id: str,
    settings: AdSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update store ad settings"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    if settings.ads_enabled is not None:
        store.ads_enabled = settings.ads_enabled
    if settings.target_roas is not None:
        store.target_roas = settings.target_roas
    if settings.target_cpa is not None:
        store.target_cpa = settings.target_cpa
    if settings.target_cpql is not None:
        store.target_cpql = settings.target_cpql

    db.commit()
    db.refresh(store)

    return {
        "ads_enabled": store.ads_enabled,
        "target_roas": store.target_roas,
        "target_cpa": store.target_cpa,
        "target_cpql": store.target_cpql,
        "zernio_profile_id": store.zernio_profile_id,
    }


# ============ Zernio Connection ============

class FacebookPagesRequest(BaseModel):
    temp_token: str


class WhatsappNumbersRequest(BaseModel):
    profile_id: str
    temp_token: str


class ZernioFinalizeRequest(BaseModel):
    profile_id: str
    connect_token: str
    temp_token: Optional[str] = None
    user_profile: Optional[Any] = None
    platform: str = "facebook"          # "facebook" (ads) or "whatsapp"
    page_id: Optional[str] = None       # selected Facebook page id
    phone_number_id: Optional[str] = None  # selected WhatsApp number id
    waba_id: Optional[str] = None       # selected WhatsApp Business Account id


@router.post("/facebook-pages")
async def facebook_pages(
    payload: FacebookPagesRequest,
    current_user: User = Depends(get_current_user),
):
    """List the Facebook Pages available to a pending headless connection.

    In headless mode Zernio returns only the user's basic profile (not their
    pages) at the select_page step, so the frontend callback fetches the pages
    here using the temp token, then posts the chosen page id to /zernio-finalize.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            "https://graph.facebook.com/v20.0/me/accounts",
            params={"access_token": payload.temp_token, "fields": "id,name,category"},
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=f"Facebook pages error: {r.text[:200]}")
    return {"pages": r.json().get("data", [])}


@router.post("/whatsapp-numbers")
async def whatsapp_numbers(
    payload: WhatsappNumbersRequest,
    current_user: User = Depends(get_current_user),
):
    """List the WhatsApp phone numbers available to a pending headless connection.

    Headless WhatsApp returns step=select_phone_number with profileId + tempToken;
    the numbers are listed via GET /connect/whatsapp/select-phone-number, then the
    chosen phoneNumberId + wabaId are posted to /zernio-finalize.
    """
    res = await _zernio(
        "GET",
        "/connect/whatsapp/select-phone-number",
        params={"profileId": payload.profile_id, "tempToken": payload.temp_token},
    )
    numbers = _first(res, "numbers", "phoneNumbers", "data", default=res if isinstance(res, list) else [])
    return {"numbers": numbers}


@router.post("/stores/{store_id}/connect-zernio")
async def connect_zernio(
    store_id: str,
    redirect_url: str,
    connect_type: str = "ads",   # "ads" (Meta ads + CTWA) or "whatsapp"
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Start the headless white-label Zernio OAuth flow.

    Returns an auth_url the frontend redirects the user to. After the user
    approves on Facebook/WhatsApp, Zernio (headless mode) redirects them back to
    `redirect_url` (app.shopivell.com/...) with connect params, which the frontend
    then posts to /zernio-finalize.
    """
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    if str(store.owner_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Only the store owner can connect accounts")

    # Reuse the store's Zernio profile if it already has a valid one. A valid
    # Zernio profile id is a 24-char hex ObjectId; a stored value containing "-"
    # is a stale store-UUID from an earlier bug — discard and recreate.
    profile_id = store.zernio_profile_id
    if not profile_id or "-" in str(profile_id):
        result = await call_openclaw("POST", "/api/skills/zernio-ads/create_store_profile", {
            "store_id": store_id,
            "store_name": store.store_name,
        })
        profile_id = result.get("profile_id")
        # Persist the profile now so the finalize step (and future connects) reuse it.
        store.zernio_profile_id = profile_id
        db.commit()

    try:
        oauth_result = await call_openclaw("POST", "/api/skills/zernio-ads/get_oauth_url", {
            "profile_id": profile_id,
            "redirect_url": redirect_url,
            "connect_type": connect_type,
        })
    except HTTPException as e:
        raise friendly_ad_error(e)

    return {"auth_url": oauth_result.get("auth_url"), "profile_id": profile_id}


async def _sync_zernio_whatsapp_to_shopivell(db: Session, store: Store, waba_id: str, phone_number_id: str) -> None:
    """Mirror a Zernio-connected WhatsApp number into shopivell's own WhatsAppAccount
    table so the number doesn't only exist on Zernio's side (which only serves Zernio's
    CTWA ads, not shopivell's own bot) - it actually works for send/receive via
    _ensure_sandbox_wa_account's Zernio-routed path even with no direct Meta token,
    since Zernio holds that token internally and can be told to send on our behalf."""
    try:
        accounts_result = await call_openclaw("GET", "/api/skills/zernio-ads/list_connected_accounts",
                                               {"profile_id": store.zernio_profile_id})
    except Exception as e:
        logger.warning(f"[Zernio->Shopivell WA sync] Could not list accounts: {e}")
        return
    accts = accounts_result.get("accounts") or []
    match = next((a for a in accts if a.get("platform") == "whatsapp"
                  and (a.get("metadata") or {}).get("phoneNumberId") == phone_number_id), None)
    if not match:
        logger.warning(f"[Zernio->Shopivell WA sync] No matching WhatsApp account found for {phone_number_id}")
        return
    wa = _ensure_sandbox_wa_account(db, store, match)
    if wa:
        db.commit()
        logger.info(f"[Zernio->Shopivell WA sync] Mirrored {phone_number_id} for store {store.id} "
                    f"(sends/receives via Zernio; add a permanent access token to use direct Meta instead).")


@router.post("/stores/{store_id}/zernio-finalize")
async def zernio_finalize(
    store_id: str,
    payload: ZernioFinalizeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Finalize a headless Zernio connection.

    The frontend callback page collects the params Zernio appended to the
    redirect_url (connect_token, tempToken, userProfile) plus the page/number the
    user picked, and posts them here. We complete the connection with Zernio and
    mark the store connected.
    """
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    if str(store.owner_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Only the store owner can connect accounts")

    if payload.platform == "whatsapp":
        # WhatsApp finalize: POST /connect/whatsapp/select-phone-number with the
        # selected number + WABA and the temp token (no X-Connect-Token).
        path = "/connect/whatsapp/select-phone-number"
        body = {
            "profileId": payload.profile_id,
            "phoneNumberId": payload.phone_number_id,
            "wabaId": payload.waba_id,
            "tempToken": payload.temp_token,
        }
        headers = {"Authorization": f"Bearer {ZERNIO_API_KEY}", "Content-Type": "application/json"}
    else:
        # Facebook finalize: POST /connect/facebook/select-page with X-Connect-Token.
        path = "/connect/facebook/select-page"
        body = {
            "profileId": payload.profile_id,
            "tempToken": payload.temp_token,
            "userProfile": payload.user_profile,
            "pageId": payload.page_id,
        }
        headers = {
            "Authorization": f"Bearer {ZERNIO_API_KEY}",
            "X-Connect-Token": payload.connect_token,
            "Content-Type": "application/json",
        }
    body = {k: v for k, v in body.items() if v is not None}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{ZERNIO_API_BASE}{path}", headers=headers, json=body)
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"Zernio finalize error ({resp.status_code}): {resp.text[:400]}")
        try:
            result = resp.json()
        except Exception:
            result = {"raw": resp.text}

    store.zernio_profile_id = payload.profile_id
    store.ads_enabled = True
    db.commit()

    if payload.platform == "whatsapp" and payload.waba_id and payload.phone_number_id:
        await _sync_zernio_whatsapp_to_shopivell(db, store, payload.waba_id, payload.phone_number_id)
        # Best-effort: auto-provision Meta Conversions API tracking too, so the
        # tenant doesn't need the separate manual step in Settings. Provisioning
        # is idempotent (safe no-op if already provisioned); an account missing
        # the required Meta permission just fails quietly here - same case the
        # manual "Enable Conversion Tracking" button in Settings handles/retries.
        try:
            account_id = await _resolve_store_whatsapp_account_id(db, store)
            if account_id:
                await _zernio("POST", "/whatsapp/dataset", json_body={"accountId": account_id})
        except Exception as e:
            logger.info("Auto-provisioning conversion tracking skipped for store %s: %s", store.id, e)

    return {"success": True, "profile_id": payload.profile_id, "platform": payload.platform, "result": result}


@router.delete("/stores/{store_id}/connected-accounts/{account_id}")
async def disconnect_connected_account(
    store_id: str,
    account_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Disconnect a Facebook/Instagram/Meta-ads/WhatsApp account via Zernio.

    All stores share ONE Zernio API key (the free tier caps it at 2 connected accounts
    total), so this can only remove an account actually visible to this store's own
    profile - never an arbitrary id - and disconnecting it stops ad/WhatsApp management
    for whichever store was using it, not just this one. Any campaigns already live in
    Meta itself keep running; only Shopivell's ability to manage them through Zernio stops."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or not store.zernio_profile_id:
        raise HTTPException(status_code=400, detail="Store is not connected to Zernio")
    if str(store.owner_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Only the store owner can disconnect accounts")
    listing = await _zernio("GET", "/accounts")
    accts = listing.get("accounts", []) if isinstance(listing, dict) else (listing or [])
    match = next((a for a in accts if str(a.get("_id") or a.get("id")) == str(account_id)), None)
    if not match:
        raise HTTPException(status_code=404, detail="Connected account not found.")
    try:
        await _zernio("DELETE", f"/accounts/{account_id}")
    except HTTPException as e:
        raise friendly_ad_error(e)
    return {"disconnected": True, "account_id": account_id, "platform": match.get("platform")}


@router.get("/stores/{store_id}/connected-accounts")
async def get_connected_accounts(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get connected Meta ad accounts for a store"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        return {"accounts": []}

    result = await call_openclaw("GET", "/api/skills/zernio-ads/list_connected_accounts", {
        "profile_id": store.zernio_profile_id
    })
    all_accounts = result.get("accounts", [])

    # Zernio returns every account on the API key, and the whole platform shares ONE
    # Zernio key across every tenant's store - so this MUST filter to only this
    # store's own profile. A previous version fell back to showing every account on
    # the key when this store's profile had none of its own, which meant any tenant
    # with no Zernio connection would see (and, through launch_campaign/
    # resolve_meta_targets, could actually publish ads and send WhatsApp messages
    # through) another tenant's real connected Facebook Page and WhatsApp number.
    # Confirmed live: this leaked one store's real connection to every other store.
    # No fallback: a store with nothing bound to its own profile is not connected.
    pid = str(store.zernio_profile_id or "")

    def _acc_profile(a):
        p = a.get("profileId") or a.get("profile")
        if isinstance(p, dict):
            return str(p.get("_id") or p.get("id") or "")
        return str(p or "")

    scoped = [a for a in all_accounts if pid and _acc_profile(a) == pid]
    return {"accounts": scoped}


# ============ Campaign Management ============

@router.get("/stores/{store_id}/campaigns")
async def get_campaigns(
    store_id: str,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all campaigns for a store, normalized into the flat shape the Insights
    dashboard expects (this replaced the deleted modules/marketing/campaigns
    endpoint - the frontend's DB-backed Campaign shape doesn't exist anymore, so
    this is assembled fresh from Zernio's nested campaign/adSet/metrics tree).

    _dispatch_zernio's list_campaigns action passes a profileId where /ads/tree
    needs a real Zernio accountId (confirmed live - the two are different ids),
    so this resolves the account directly instead of going through it."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or not store.zernio_profile_id:
        return {"campaigns": [], "total_count": 0}

    accts_res = await _zernio("GET", "/accounts", params={"profileId": store.zernio_profile_id})
    accounts = accts_res.get("accounts") or []
    meta_account = next((a for a in accounts if a.get("platform") in ("facebook", "metaads")), None)
    if not meta_account:
        return {"campaigns": [], "total_count": 0}
    account_id = meta_account.get("_id") or meta_account.get("id")

    tree = await _zernio("GET", "/ads/tree", params={"accountId": account_id})

    # Zernio's tree has no ad set start/end, so the schedule is the one we saved when
    # publishing (UrlCampaign.start_date/end_date), matched on the Meta campaign id.
    schedules: Dict[str, tuple] = {}
    publish_infos: Dict[str, dict] = {}
    name_infos: List[tuple] = []
    try:
        from modules.campaigns.models import UrlCampaign
        for uc in db.query(UrlCampaign).filter(UrlCampaign.store_id == store.id).all():
            ids = uc.platform_campaign_ids or {}
            meta_id = ids.get("meta")
            if meta_id and (uc.start_date or uc.end_date):
                schedules[str(meta_id)] = (uc.start_date, uc.end_date)
            if isinstance(ids.get("publish"), dict):
                info = ids["publish"]
            else:
                # Published before publish info was saved: fall back to the analysed campaign.
                first_set = sorted(uc.ad_sets or [], key=lambda s: s.created_at or datetime.min)
                first_set = first_set[0] if first_set else None
                age = first_set.age_range if first_set and isinstance(first_set.age_range, dict) else {}
                info = {
                    "destination": "website",
                    # Legacy website ads were created as traffic (a conversions goal without a
                    # pixel falls back to traffic), whatever the analysed campaign's goal said.
                    "goal": "traffic",
                    "countries": [str(x).upper() for x in (uc.countries or [])]
                                 or ([str(store.country_code).upper()] if store.country_code else []),
                    "audience": {"age_min": age.get("min"), "age_max": age.get("max"), "advantage_audience": None,
                                 "tags": [str(t) for t in ((first_set.audience_tags if first_set else None) or [])][:8]},
                }
            if meta_id:
                publish_infos[str(meta_id)] = info
            if uc.name:
                # Zernio names a published campaign "<campaign name> - <ad set name> - Campaign",
                # so older campaigns whose Meta id was never saved can still be matched by name.
                name_infos.append((uc.name, info, (uc.start_date, uc.end_date)))
        name_infos.sort(key=lambda t: len(t[0]), reverse=True)
    except Exception as e:
        logger.warning("could not load campaign schedules: %s", e)

    campaigns = []
    for c in (tree.get("campaigns") or []):
        ad_sets = c.get("adSets") or []
        sched = schedules.get(str(c.get("platformCampaignId") or ""), (None, None))
        start_iso = sched[0].isoformat() if sched[0] else None
        end_iso = sched[1].isoformat() if sched[1] else None
        pub = publish_infos.get(str(c.get("platformCampaignId") or ""), {})
        if not pub:
            cname = str(c.get("campaignName") or c.get("name") or "")
            for nm, info, dates in name_infos:
                if cname.startswith(nm + " - "):
                    pub = info
                    if not (start_iso or end_iso) and (dates[0] or dates[1]):
                        start_iso = dates[0].isoformat() if dates[0] else None
                        end_iso = dates[1].isoformat() if dates[1] else None
                    break
        metrics_list = [a.get("metrics") or {} for a in ad_sets]
        first_budget = (ad_sets[0].get("budget") or ad_sets[0].get("adSetBudget") or {}) if ad_sets else {}
        c_status = str(c.get("status") or "").upper()

        # All countries targeted across this campaign's ad sets (usually one, but a
        # campaign can have several ad sets targeting different regions).
        countries: List[str] = []
        for a in ad_sets:
            for country in ((a.get("targeting") or {}).get("countries") or []):
                if country not in countries:
                    countries.append(country)
        if not countries and c.get("targeting", {}).get("countries"):
            countries = c["targeting"]["countries"]

        ad_sets_detail = []
        for a in ad_sets:
            a_budget = a.get("budget") or a.get("adSetBudget") or {}
            ads_detail = []
            for ad in a.get("ads") or []:
                creative = ad.get("creative") or {}
                ads_detail.append({
                    "id": ad.get("platformAdId") or ad.get("_id") or "",
                    "name": ad.get("name") or "",
                    "status": str(ad.get("status") or ad.get("configuredStatus") or "").upper(),
                    "review_status": ad.get("reviewStatus"),
                    "headline": creative.get("headline") or "",
                    "body": creative.get("body") or "",
                    "image_url": creative.get("imageUrl") or "",
                    "thumbnail_url": creative.get("thumbnailUrl") or "",
                    "link_url": creative.get("linkUrl") or "",
                    # WhatsApp ads use Meta's own message button, whatever the copy's AI-picked button was.
                    "call_to_action": "WHATSAPP" if pub.get("destination") == "whatsapp" else (creative.get("callToAction") or ""),
                })
            a_targeting = a.get("targeting") or {}
            ad_sets_detail.append({
                "id": a.get("platformAdSetId") or a.get("id") or "",
                "name": a.get("adSetName") or "",
                "status": str(a.get("status") or "").upper(),
                "daily_budget": a_budget.get("amount", 0) if a_budget.get("type") == "daily" else 0,
                "lifetime_budget": a_budget.get("amount", 0) if a_budget.get("type") == "lifetime" else 0,
                "countries": a_targeting.get("countries") or [],
                # Zernio's own /ads/tree only echoes back this much of the targeting
                # it actually applied (not the fuller age/gender/interest spec that
                # may have been requested at creation) - advantage_audience is Meta's
                # "let us find your audience automatically" toggle.
                "advantage_audience": bool(a_targeting.get("advantage_audience")),
                "created_at": a.get("createdTime") or "",
                "spend": (a.get("metrics") or {}).get("spend", 0),
                "impressions": (a.get("metrics") or {}).get("impressions", 0),
                "clicks": (a.get("metrics") or {}).get("clicks", 0),
                "ads": ads_detail,
            })

        campaigns.append({
            "id": c.get("platformCampaignId") or c.get("id") or "",
            # Zernio's /ads/tree returns the campaign name as "campaignName", not
            # "name" - this previously always fell through to "(unnamed)".
            "name": c.get("campaignName") or c.get("name") or "(unnamed)",
            "status": c_status if c_status in ("ACTIVE", "PAUSED") else "ARCHIVED",
            "objective": c.get("goal") or pub.get("goal") or "",
            "destination": pub.get("destination") or "",
            "whatsapp_number": pub.get("whatsapp_number"),
            "audience": pub.get("audience"),
            "meta_campaign_id": c.get("platformCampaignId"),
            "daily_budget": first_budget.get("amount", 0) if first_budget.get("type") == "daily" else 0,
            "lifetime_budget": first_budget.get("amount", 0) if first_budget.get("type") == "lifetime" else 0,
            "countries": countries or pub.get("countries") or [],
            "ad_set_count": len(ad_sets),
            "ad_count": sum(len(a.get("ads") or []) for a in ad_sets),
            "spend": sum(m.get("spend", 0) for m in metrics_list),
            "impressions": sum(m.get("impressions", 0) for m in metrics_list),
            "clicks": sum(m.get("clicks", 0) for m in metrics_list),
            # Click-to-WhatsApp: how many people actually sent a first message, as
            # opposed to just clicking the ad (a click doesn't guarantee they hit
            # send once WhatsApp opened) - Meta's own attributed conversion event.
            "messages_started": sum((m.get("funnel") or {}).get("messagingConversationsStarted", 0)
                                    for m in metrics_list),
            "created_at": c.get("createdTime") or c.get("createdAt") or "",
            "start_date": start_iso,
            "end_date": end_iso,
            "ad_sets": ad_sets_detail,
        })

    if status and status != "all":
        campaigns = [c for c in campaigns if c["status"] == status.upper()]
    return {"campaigns": campaigns, "total_count": len(campaigns)}


@router.get("/campaigns/{campaign_id}/insights")
async def get_campaign_insights(
    campaign_id: str,
    date_preset: str = "last_7d",
    current_user: User = Depends(get_current_user)
):
    """Get insights for a campaign"""
    result = await call_openclaw("GET", "/api/skills/zernio-ads/get_insights", {
        "ad_id": campaign_id,
        "date_preset": date_preset
    })
    return result


@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: str,
    reason: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Pause a campaign"""
    result = await call_openclaw("POST", "/api/skills/zernio-ads/pause_ad", {
        "ad_id": campaign_id,
        "reason": reason
    })
    return {"success": True}


async def _activate_campaign(store, campaign_id: str, daily_budget: Optional[float] = None) -> dict:
    """Switch a Meta campaign fully on. On Meta the campaign, its ad set and its ad each
    have their own on/off switch, and flipping the campaign alone leaves a paused ad set
    (and ad) paused, so the campaign looks active but nothing delivers. Created campaigns
    start with all three paused. Optionally sets the ad set daily budget first."""
    targets = await resolve_meta_targets(store)
    tree = await _zernio("GET", "/ads/tree", params={"accountId": targets["account_id"]})
    camp = next((c for c in (tree.get("campaigns") or [])
                 if str(c.get("platformCampaignId") or c.get("id")) == str(campaign_id)), None)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found in the connected Meta ad account.")
    switched = {"budget_set": [], "ads": [], "ad_sets": []}
    for a in camp.get("adSets") or []:
        aid = a.get("platformAdSetId") or a.get("id")
        if daily_budget is not None:
            await _zernio("PUT", f"/ads/ad-sets/{aid}", json_body={
                "platform": "facebook", "budget": {"amount": round(float(daily_budget), 2), "type": "daily"}})
            switched["budget_set"].append(aid)
        for ad in a.get("ads") or []:
            adid = ad.get("platformAdId") or ad.get("_id")
            await _zernio("PUT", f"/ads/{adid}/status", json_body={"status": "active"})
            switched["ads"].append(adid)
        await _zernio("PUT", f"/ads/ad-sets/{aid}/status", json_body={"status": "active", "platform": "facebook"})
        switched["ad_sets"].append(aid)
    await _zernio("PUT", f"/ads/campaigns/{campaign_id}/status", json_body={"status": "active", "platform": "facebook"})
    return {"campaign_id": campaign_id, "activated": True, **switched}


class ActivateCampaignRequest(BaseModel):
    daily_budget: Optional[float] = None


@router.post("/stores/{store_id}/campaigns/{campaign_id}/activate")
async def activate_campaign(
    store_id: str,
    campaign_id: str,
    request: ActivateCampaignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Start a paused campaign (campaign + ad set + ad), optionally fixing the daily budget."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or not store.zernio_profile_id:
        raise HTTPException(status_code=400, detail="Store not connected to Zernio")
    return await _activate_campaign(store, campaign_id, request.daily_budget)


@router.post("/campaigns/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Resume a paused campaign (all three Meta switches, not just the campaign's)."""
    store_id = current_user.store_id
    store = db.query(Store).filter(Store.id == store_id).first() if store_id else None
    if not store or not store.zernio_profile_id:
        raise HTTPException(status_code=400, detail="No active Zernio-connected store to resume this campaign in.")
    await _activate_campaign(store, campaign_id)
    return {"success": True}


@router.post("/campaigns/{campaign_id}/scale")
async def scale_campaign_budget(
    campaign_id: str,
    percentage: float,
    max_budget: Optional[float] = None,
    current_user: User = Depends(get_current_user)
):
    """Scale campaign budget"""
    result = await call_openclaw("POST", "/api/skills/zernio-ads/scale_budget", {
        "ad_id": campaign_id,
        "percentage": percentage,
        "max_budget": max_budget
    })
    return result


# ============ AI Campaign Generation ============

@router.post("/stores/{store_id}/generate-campaign")
async def generate_campaign(
    store_id: str,
    request: GenerateCampaignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate a full campaign using AI"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    result = await call_openclaw("POST", "/api/skills/ad-creator/generate_full_campaign", {
        "store_id": store_id,
        "product_name": request.product_name,
        "product_description": request.product_description,
        "product_price": request.product_price,
        "store_name": store.store_name,
        "target_country": store.country_code or "ZW",
        "campaign_goal": request.campaign_goal,
        "brand_voice": request.brand_voice,
        "brand_colors": [store.color_theme] if store.color_theme else None,
        "budget": request.budget
    })

    return result


@router.post("/stores/{store_id}/generate-ctwa-campaign")
async def generate_ctwa_campaign(
    store_id: str,
    request: GenerateCTWARequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate a Click-to-WhatsApp campaign"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Generate WhatsApp-specific copy
    copy_result = await call_openclaw("POST", "/api/skills/ad-creator/generate_whatsapp_copy", {
        "store_id": store_id,
        "product_name": request.product_name,
        "product_description": request.product_description,
        "product_data": {
            "name": request.product_name,
            "description": request.product_description
        },
        "angle": {"name": "Conversation", "hook": "Chat with us!"},
        "store_name": store.store_name
    })

    # Generate image
    image_result = await call_openclaw("POST", "/api/skills/ad-creator/generate_image", {
        "store_id": store_id,
        "product_name": request.product_name,
        "product_description": request.product_description,
        "style": "lifestyle",
        "dimensions": "square",
        "brand_colors": [store.color_theme] if store.color_theme else None
    })

    return {
        "copy": copy_result,
        "image": image_result,
        "whatsapp_number": request.whatsapp_number,
        "budget": request.budget,
        "ready_for_launch": True
    }


@router.post("/stores/{store_id}/launch-campaign")
async def launch_campaign(
    store_id: str,
    campaign_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Launch a generated campaign via Zernio"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or not store.zernio_profile_id:
        raise HTTPException(status_code=400, detail="Store not connected to Zernio")

    pid = str(store.zernio_profile_id)

    def _acc_profile(a):
        p = a.get("profileId") or a.get("profile")
        return str(p.get("_id") if isinstance(p, dict) else (p or ""))

    # Find this store's connected Meta account (Zernio account id). Confirmed live:
    # falling back to any Meta account on the shared key when this store's own
    # profile had none meant a store with no connection of its own could silently
    # launch a real, billed campaign through another tenant's real connected
    # Facebook Page and ad account. No fallback - only this store's own connection.
    listing = await _zernio("GET", "/accounts")
    accts = listing.get("accounts", []) if isinstance(listing, dict) else (listing or [])
    meta_accts = [a for a in accts if a.get("platform") in ("facebook", "metaads")]
    meta_acc = next((a for a in meta_accts if _acc_profile(a) == pid), None)
    if not meta_acc:
        raise HTTPException(status_code=400, detail="No Meta (Facebook/ads) account connected to this store.")
    zernio_account_id = meta_acc.get("_id") or meta_acc.get("id")

    # Resolve the Meta ad account (act_...) under it.
    ad_accounts = await _zernio("GET", "/ads/accounts", params={"accountId": zernio_account_id})
    ad_list = ad_accounts.get("accounts", []) if isinstance(ad_accounts, dict) else (ad_accounts or [])
    if not ad_list:
        raise HTTPException(status_code=400, detail="No Meta ad account is available on the connected account.")
    ad_account_id = ad_list[0].get("id") or ad_list[0].get("accountId")

    # Zernio requires a hosted imageUrl. The UI's ad creative is often base64
    # (AI-generated), so upload it to storage and use the resulting URL when no
    # hosted image_url was supplied.
    if not _first(campaign_data, "image_url", "imageUrl"):
        b64 = campaign_data.get("image_base64") or campaign_data.get("generated_image_base64")
        if b64:
            try:
                import base64 as _b64
                raw = b64.split(",", 1)[-1] if isinstance(b64, str) and "," in b64 else b64
                img_bytes = _b64.b64decode(raw)
                from modules.assets.service import AssetService
                from modules.assets.models import AssetType
                # create_asset_from_upload (not the lower-level _upload_file) so this
                # also creates the Asset DB row the Assets library reads from -
                # otherwise the file exists in storage but never shows up there.
                asset, err = AssetService(db).create_asset_from_upload(
                    store_id=store.id,
                    filename=f"ad_{store_id}.png",
                    file_data=img_bytes,
                    mime_type="image/png",
                    file_type=AssetType.IMAGE,
                    name=campaign_data.get("name") or f"Ad creative - {campaign_data.get('headline', 'campaign')}",
                    source="ad_creative",
                )
                url = asset.cloudinary_secure_url or asset.cloudinary_url if asset else None
                if url:
                    campaign_data = {**campaign_data, "image_url": url}
                else:
                    logger.warning("ad image upload failed: %s", err)
            except Exception as e:
                logger.warning("could not upload ad image_base64: %s", e)

    # Assemble the create data with sensible store-derived defaults.
    # WhatsApp (Click-to-WhatsApp) is the default destination; "website" opts out.
    is_ctwa = campaign_data.get("destination") != "website"
    targets = {}
    try:
        targets = await resolve_meta_targets(store)
    except Exception as e:
        logger.info("could not resolve Meta page for launch: %s", e)
    data = {
        "link_url": store.store_link or store.domain or "https://shopivell.com",
        "currency": store.currency or "USD",
        "countries": [store.country_code] if store.country_code else ["US"],
        "status": "PAUSED",
        "age_min": 25,
        "age_max": 55,
        "advantage_audience": 1,
        **({"page_id": targets["page_id"]} if targets.get("page_id") else {}),
        **campaign_data,
        # These override any client-supplied values (resolved server-side).
        "account_id": zernio_account_id,
        "ad_account_id": ad_account_id,
    }
    if is_ctwa:
        data["whatsapp_number"] = campaign_data.get("whatsapp_number") or await _store_whatsapp_number(store)
        data.setdefault("welcome_text", f"Hi! Thanks for reaching out to {store.store_name}. How can we help you today?")
        data.setdefault("prefill_text", f"Hi, I'd like to know more about {store.store_name}.")
    action = "create_ctwa_campaign" if is_ctwa else "create_campaign"
    try:
        result = await call_openclaw("POST", f"/api/skills/zernio-ads/{action}", data)
    except HTTPException as e:
        raise friendly_ad_error(e)

    return {"success": True, "campaign_id": result.get("id") or result.get("campaign_id"), "result": result}


# ============ Creative Generation ============

@router.post("/generate-image")
async def generate_ad_image(
    request: GenerateImageRequest,
    current_user: User = Depends(get_current_user)
):
    """Generate an ad image using GPT-Image-2.5"""
    result = await call_openclaw("POST", "/api/skills/ad-creator/generate_image", {
        "store_id": request.store_id or (str(current_user.last_active_store_id) if getattr(current_user, "last_active_store_id", None) else None),
        "product_name": request.product_name,
        "product_description": request.product_description,
        "style": request.style,
        "dimensions": request.dimensions,
        "brand_colors": request.brand_colors
    })
    return result


@router.post("/generate-copy")
async def generate_ad_copy(
    request: GenerateCopyRequest,
    current_user: User = Depends(get_current_user)
):
    """Generate ad copy variations"""
    result = await call_openclaw("POST", "/api/skills/ad-creator/generate_ad_copy", {
        "store_id": request.store_id or (str(current_user.last_active_store_id) if getattr(current_user, "last_active_store_id", None) else None),
        "product_name": request.product_name,
        "product_description": request.product_description,
        "angle": {"name": request.angle},
        "product_data": {
            "name": request.product_name,
            "description": request.product_description
        },
        "format": "single_image",
        "variations": request.variations
    })
    return {"variations": result}


# ============ Optimizer ============

@router.get("/stores/{store_id}/optimizer/status")
async def get_optimizer_status(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get optimizer status for a store (modules.optimizer, not the OpenClaw plugin)."""
    from modules.optimizer import service as optimizer
    return optimizer.get_status(db, _owned_store(db, store_id, current_user))


@router.get("/stores/{store_id}/optimizer/history")
async def get_optimizer_history(
    store_id: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get optimizer decision history (dry-run, applied and failed)."""
    from modules.optimizer import service as optimizer
    return optimizer.get_history(db, _owned_store(db, store_id, current_user), limit)


@router.post("/stores/{store_id}/optimizer/calibrate")
async def calibrate_optimizer_targets(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Run model-driven target_roas/target_cpa calibration now, grounded in this
    store's real niche/performance (see modules/optimizer/calibration.py). One-off;
    turning on auto_calibrate via /optimizer/config repeats this weekly on its own."""
    from modules.optimizer import service as optimizer
    return optimizer.calibrate_now(db, _owned_store(db, store_id, current_user))


@router.post("/stores/{store_id}/optimizer/config")
async def update_optimizer_config(
    store_id: str,
    config: OptimizerConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update optimizer targets, rule overrides and the per-store dry-run switch."""
    from modules.optimizer import service as optimizer
    return optimizer.update_config(db, _owned_store(db, store_id, current_user), config.dict(exclude_none=True))


def _owned_store(db: Session, store_id: str, user: User) -> Store:
    """The store if this user owns it; 404 otherwise (don't leak another store's ads)."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or str(store.owner_id) != str(user.id):
        raise HTTPException(status_code=404, detail="Store not found")
    return store


# ============ Lead & Conversion Stats ============

@router.get("/stores/{store_id}/lead-stats")
async def get_lead_stats(
    store_id: str,
    date_range: str = "last_7d",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get lead statistics for CTWA campaigns"""
    # This would query the local database for lead scoring data
    # For now, return placeholder
    return {
        "total_leads": 0,
        "qualified_leads": 0,
        "hot_leads": 0,
        "conversion_rate": 0,
        "avg_lead_score": 0
    }


@router.get("/stores/{store_id}/conversion-stats")
async def get_conversion_stats(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get offline conversion statistics"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or not store.zernio_profile_id:
        return {"events_sent": 0, "events_matched": 0, "match_rate": 0, "by_event_type": {}}

    result = await call_openclaw("GET", "/api/skills/zernio-ads/get_conversion_stats", {
        "profile_id": store.zernio_profile_id,
        "date_range": "last_30d"
    })
    return result


# ============ CTWA Insights ============

@router.get("/campaigns/{campaign_id}/ctwa-insights")
async def get_ctwa_insights(
    campaign_id: str,
    date_preset: str = "last_7d",
    current_user: User = Depends(get_current_user)
):
    """Get Click-to-WhatsApp specific insights"""
    result = await call_openclaw("GET", "/api/skills/zernio-ads/get_ctwa_insights", {
        "campaign_id": campaign_id,
        "date_preset": date_preset
    })
    return result


# ============ Autonomous Multi-Agent System ============

class AutonomousSessionRequest(BaseModel):
    auto_generate_goals: bool = True
    budget_limit: float = 500.0
    daily_budget: float = 2.0
    start_delay_hours: float = 24.0
    evaluation_interval_minutes: int = 60
    max_concurrent_tasks: int = 3
    time_limit_hours: Optional[float] = None
    pause_on_error: bool = True
    initial_goals: Optional[List[Dict[str, Any]]] = None


class GoalRequest(BaseModel):
    type: str  # maximize_roas, minimize_cpa, etc.
    description: str
    target_metric: str
    target_value: float
    deadline: Optional[str] = None
    priority: str = "high"  # critical, high, medium, low


# In-memory session storage (use Redis/DB in production)
_autonomous_sessions: Dict[str, dict] = {}
# Serialises goal execution per session so an added goal cannot interleave with a running plan.
_autonomous_session_locks: Dict[str, asyncio.Lock] = {}


@router.post("/stores/{store_id}/autonomous/start")
async def start_autonomous_session(
    store_id: str,
    request: AutonomousSessionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Start an autonomous advertising session.

    The system will:
    1. Analyze current performance and generate goals (or use provided goals)
    2. Create execution plans for each goal
    3. Execute tasks (create campaigns, optimize, scale, etc.)
    4. Continuously evaluate and adjust until goals are achieved
    """
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    if not store.zernio_profile_id:
        raise HTTPException(status_code=400, detail="Store must be connected to Zernio first")

    # Fail before a session exists if the agents have nowhere to run.
    from modules.openclaw import gateway
    gateway.ensure_configured()

    # Get current performance
    try:
        insights = await call_openclaw("GET", "/api/skills/zernio-ads/get_all_store_insights", {
            "profile_id": store.zernio_profile_id,
            "date_preset": "last_7d"
        })
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail=f"Could not read current ad performance: {getattr(exc, 'detail', exc)}")

    # Real performance snapshot. A metric with no underlying data stays None rather
    # than being filled in with a plausible-looking constant - the goal and evaluator
    # agents must be able to tell "no data" apart from "zero".
    campaigns = insights.get("campaigns") or insights.get("data") or insights.get("tree") or []

    def _metric(row: dict, *keys) -> float:
        for key in keys:
            value = (row or {}).get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    total_spend = sum(_metric(c, "spend") for c in campaigns)
    total_revenue = sum(_metric(c, "revenue") for c in campaigns)
    conversions = sum(_metric(c, "conversions") for c in campaigns)
    clicks = sum(_metric(c, "clicks") for c in campaigns)
    impressions = sum(_metric(c, "impressions") for c in campaigns)

    performance = {
        "roas": round(total_revenue / total_spend, 4) if total_spend else None,
        "cpa": round(total_spend / conversions, 2) if conversions else None,
        "ctr": round(clicks / impressions, 6) if impressions else (
            round(sum(_metric(c, "ctr") for c in campaigns) / len(campaigns), 6) if campaigns else None),
        "conversion_rate": round(conversions / clicks, 4) if clicks else None,
        "conversions": conversions,
        "clicks": clicks,
        "total_spend": round(total_spend, 2),
        "total_revenue": round(total_revenue, 2),
        "active_campaigns": len([c for c in campaigns
                                 if str(c.get("status", "")).upper() == "ACTIVE"]),
        "date_range": "last_7d"
    }

    # Create session
    session_id = f"session-{store_id}-{int(datetime.utcnow().timestamp())}"

    session = {
        "id": session_id,
        "store_id": store_id,
        "profile_id": store.zernio_profile_id,
        "config": request.dict(),
        "performance": performance,
        "state": "initializing",
        "goals": [],
        "plans": [],
        "evaluations": [],
        "goals_achieved": [],
        "goals_failed": [],
        "completed_tasks": [],
        "failed_tasks": [],
        "total_spend": 0,
        "started_at": datetime.utcnow().isoformat(),
        "last_update": datetime.utcnow().isoformat()
    }

    _autonomous_sessions[session_id] = session

    # Start autonomous loop in background
    background_tasks.add_task(
        run_autonomous_loop,
        session_id,
        store.zernio_profile_id,
        performance,
        request
    )

    return {
        "session_id": session_id,
        "state": "initializing",
        "message": "Autonomous session started. Goals will be generated and executed."
    }


async def _run_ui_campaign_flow(store_id: str, name: str, daily_budget: float, goal: Optional[str],
                                total_budget: float = 0, start_delay_hours: float = 24.0) -> dict:
    """Create a campaign exactly the way the UI's "Analyze & create campaign" does, so the
    autonomous agents and the UI share one engine (site scrape, brand identification,
    market research, ad angles, reference photos, real-logo image, copy checks): run the
    UI's own scrape-stream flow, wait for its background image job, then publish through
    the UI's own publish-meta step. Created PAUSED: nothing spends until activated."""
    import json as _json
    import time as _time
    import uuid as _uuid
    from database import SessionLocal
    from modules.stores.models import Store
    from modules.campaigns.router import scrape_url_stream, publish_campaign_to_meta, PublishMetaRequest
    from modules.campaigns.models import UrlAdSet, UrlAdContent

    db = SessionLocal()
    try:
        store = db.query(Store).filter(Store.id == store_id).first()
        url = (store.store_link or (f"https://{store.domain}" if store.domain else None)) if store else None
        if not url:
            raise HTTPException(status_code=400, detail="Store has no website URL to analyze.")
        resp = await scrape_url_stream(url=url, store_id=_uuid.UUID(str(store_id)),
                                       campaign_name=name, target=None, db=db)
        campaign_id, err = None, None
        async for chunk in resp.body_iterator:
            text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else str(chunk)
            for ln in text.splitlines():
                if ln.startswith("data: "):
                    try:
                        ev = _json.loads(ln[6:])
                    except ValueError:
                        continue
                    if ev.get("event") == "complete":
                        campaign_id = ev.get("campaign_id")
                    elif ev.get("event") == "error":
                        err = ev.get("message")
        if not campaign_id:
            raise HTTPException(status_code=502, detail=f"Campaign analysis failed: {err}")
        cid = _uuid.UUID(campaign_id)

        deadline = _time.time() + 300
        while True:
            db.expire_all()
            ready = (db.query(UrlAdContent).join(UrlAdSet, UrlAdContent.ad_set_id == UrlAdSet.id)
                     .filter(UrlAdSet.campaign_id == cid, UrlAdContent.media_url.isnot(None)).count())
            if ready:
                break
            if _time.time() > deadline:
                raise HTTPException(status_code=504, detail="Ad image was not ready in time.")
            await asyncio.sleep(8)

        # Time-box the run: starts tomorrow (review buffer while it is paused) and runs as many
        # days as the total cap allows at the daily budget (e.g. $20 cap / $2 per day = 10 days).
        from datetime import timedelta
        start_dt = (datetime.utcnow() + timedelta(hours=max(start_delay_hours, 1.0))).replace(
            minute=0, second=0, microsecond=0)
        days = max(1, int(total_budget // daily_budget)) if total_budget and daily_budget else 7
        end_dt = start_dt + timedelta(days=days)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        pub = await publish_campaign_to_meta(
            cid, PublishMetaRequest(daily_budget=daily_budget, goal=goal, status="PAUSED",
                                    start_date=start_dt.strftime(fmt), end_date=end_dt.strftime(fmt)), db)
        return {"campaign_id": campaign_id, **pub}
    finally:
        db.close()


async def _agent_store_context(store_id: str, profile_id: str) -> Tuple[dict, dict]:
    """Real business facts and connected accounts for the agent prompts.

    The planner is only allowed to use account ids it is given here; it never
    invents one, and the executor force-injects the server-resolved Meta ad
    account for create_campaign tasks regardless.
    """
    try:
        accounts_result = await call_openclaw("GET", "/api/skills/zernio-ads/list_connected_accounts",
                                              {"profile_id": profile_id})
    except Exception as e:
        logger.warning("Could not list connected accounts for profile %s: %s",
                       profile_id, getattr(e, "detail", e))
        accounts_result = {}
    resolved_targets = await _resolve_meta_ad_account(profile_id)
    brand = _load_brand_context(store_id)
    business_summary = (
        f"{brand.get('store_name')} - {brand.get('business_type') or ''}. "
        f"{(brand.get('about') or '')[:500]} Products/services: {brand.get('products') or 'n/a'}. "
        f"Website: {brand.get('link_url') or 'n/a'}. Country: {brand.get('country') or 'n/a'}."
    ) if brand.get("store_name") else ""
    store_context = {
        "business": {
            "name": brand.get("store_name"), "type": brand.get("business_type"),
            "about": (brand.get("about") or "")[:600], "products": brand.get("products"),
            "link_url": brand.get("link_url"), "country": brand.get("country"),
        } if brand.get("store_name") else {},
        "summary": business_summary,
        "profile_id": profile_id,
        "connected_accounts": accounts_result.get("accounts") or accounts_result.get("data") or [],
    }
    if resolved_targets:
        store_context["resolved_account_id"] = resolved_targets["account_id"]
        store_context["resolved_ad_account_id"] = resolved_targets["ad_account_id"]
    return store_context, brand


def _session_lock(session_id: str) -> asyncio.Lock:
    """One goal runs at a time per session, so an added goal cannot interleave."""
    lock = _autonomous_session_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _autonomous_session_locks[session_id] = lock
    return lock


async def _run_goal_locked(session: dict, goal: dict, config: AutonomousSessionRequest,
                           store_context: dict, brand: dict) -> None:
    async with _session_lock(session["id"]):
        session["active_goals"] = int(session.get("active_goals") or 0) + 1
        try:
            await _execute_goal(session, goal, config, store_context, brand)
        finally:
            session["active_goals"] = max(0, int(session.get("active_goals") or 0) - 1)


async def _execute_goal(session: dict, goal: dict, config: AutonomousSessionRequest,
                        store_context: dict, brand: dict) -> None:
    """Plan one goal with the planner agent, run its tasks, then let the evaluator judge it."""
    # Ask the planner agent for this goal's plan.
    plan_result = await call_openclaw("POST", "/api/agents/planner/create", {
        "store_id": session["store_id"],
        "goal": goal,
        "available_budget": max(0.0, config.budget_limit - session["total_spend"]),
        "store_context": store_context,
    })
    plan = (plan_result or {}).get("plan") or {}
    if not plan.get("tasks"):
        raise HTTPException(status_code=502,
                            detail="OpenClaw planner agent returned a plan with no executable tasks.")
    session["plans"].append(plan)
    session["last_update"] = datetime.utcnow().isoformat()

    resolved_account_id = store_context.get("resolved_account_id")
    resolved_ad_account_id = store_context.get("resolved_ad_account_id")
    task_outputs: Dict[str, Any] = {}
    goal_tasks: List[Dict[str, Any]] = []

    # The Planner's dependency ids ("task_0", "task_1", ...) are positional, not
    # the task's own "id" field - keyed that way here too, so a later task can
    # pull in an earlier one's output.
    for task_index, task in enumerate(plan.get("tasks", [])):
        if session["state"] != "running":
            break

        # Thread prior tasks' results into this one's parameters. Without this,
        # e.g. a campaign_creation task that depends on a creative task never
        # actually receives the generated headline/body/image, and Zernio
        # rejects the campaign for missing required fields.
        params = dict(task.get("parameters") or {})
        params.setdefault("store_id", session["store_id"])
        # Resolve "{{task_N.field}}" placeholders the Planner sometimes emits;
        # unresolved ones are dropped so real defaults (store facts) apply instead.
        import re as _re
        for pk, pv in list(params.items()):
            if isinstance(pv, str) and "{{" in pv:
                m = _re.fullmatch(r"\s*\{\{\s*(task_\d+)\.([\w]+)\s*\}\}\s*", pv)
                src = task_outputs.get(m.group(1)) if m else None
                if isinstance(src, dict) and src.get(m.group(2)) not in (None, ""):
                    params[pk] = src[m.group(2)]
                else:
                    params.pop(pk)
            elif isinstance(pv, dict):
                if any(isinstance(x, str) and "{{" in x for x in pv.values()):
                    params.pop(pk)
        plan_creates = any(t.get("skill") == "zernio-ads" and t.get("action") == "create_campaign"
                           for t in plan.get("tasks", []))
        if plan_creates and task.get("skill") == "ad-creator":
            entry = {"task": {**task, "parameters": params},
                     "result": {"skipped": "handled by the campaign engine (same as the UI's Analyze & create campaign)"},
                     "timestamp": datetime.utcnow().isoformat()}
            session["completed_tasks"].append(entry)
            goal_tasks.append({"task": entry["task"], "success": True, "result": entry["result"]})
            continue
        if task.get("skill") == "zernio-ads" and task.get("action") == "pause_ad" and not (
                params.get("ad_id") or params.get("campaign_id")):
            entry = {"task": {**task, "parameters": params},
                     "result": {"skipped": "no campaign id to pause yet; new campaigns are created PAUSED"},
                     "timestamp": datetime.utcnow().isoformat()}
            session["completed_tasks"].append(entry)
            goal_tasks.append({"task": entry["task"], "success": True, "result": entry["result"]})
            continue
        for dep in task.get("dependencies") or []:
            dep_result = task_outputs.get(dep)
            if not isinstance(dep_result, dict):
                continue
            for key in ("headline", "body", "primary_text"):
                if dep_result.get(key) and not params.get(key):
                    params[key] = dep_result[key]
            image_val = dep_result.get("image_url") or dep_result.get("url")
            if image_val and not (params.get("image_url") or params.get("imageUrl")):
                params["image_url"] = image_val
            if any(dep_result.get(k) for k in ("competitors", "keywords", "trends")) and not params.get("research"):
                params["research"] = {k: dep_result[k] for k in ("competitors", "keywords", "trends") if k in dep_result}

        # Ad-creator tasks (copy/image) still missing research context after
        # dependency-based threading - same unreliable-Planner-dependencies
        # issue as the zernio-ads fallback below, so scan every prior output
        # for the most recent research_market result regardless of whether
        # this task declared it as a dependency.
        if task.get("skill") == "ad-creator" and task.get("action") in (
                "generate_ad_copy", "generate_whatsapp_copy", "generate_image") and not params.get("research"):
            for prior in reversed(list(task_outputs.values())):
                if isinstance(prior, dict) and any(prior.get(k) for k in ("competitors", "keywords", "trends")):
                    params["research"] = {k: prior[k] for k in ("competitors", "keywords", "trends") if k in prior}
                    break

        # Fallback for campaign-creation tasks still missing creative fields
        # after dependency-based threading above - the Planner's own
        # "dependencies" references aren't always reliable, so fall back to
        # the most recent creative output produced anywhere in this plan.
        if task.get("skill") == "zernio-ads" and task.get("action") in (
                "create_campaign", "create_ctwa_campaign"):
            # Never trust the Planner's own account_id/ad_account_id - it
            # only ever saw the profile-level connected_accounts listing,
            # not the act_-prefixed ad account id, so it can 400 with
            # 'adAccountId must start with "act_"' or target the wrong
            # account entirely. Force the server-resolved real ids.
            if brand.get("link_url"):
                params.setdefault("link_url", brand["link_url"])
            if brand.get("country_code"):
                params.setdefault("countries", [brand["country_code"]])
            if resolved_account_id:
                params["account_id"] = resolved_account_id
                params["accountId"] = resolved_account_id
            if resolved_ad_account_id:
                params["ad_account_id"] = resolved_ad_account_id
                params["adAccountId"] = resolved_ad_account_id
            if not params.get("body") and not params.get("primary_text"):
                for prior in reversed(list(task_outputs.values())):
                    if isinstance(prior, dict) and prior.get("body"):
                        params.setdefault("headline", prior.get("headline"))
                        params["body"] = prior["body"]
                        params.setdefault("primary_text", prior.get("primary_text") or prior["body"])
                        break
            if not (params.get("image_url") or params.get("imageUrl")):
                for prior in reversed(list(task_outputs.values())):
                    if isinstance(prior, dict) and (prior.get("image_url") or prior.get("url")):
                        params["image_url"] = prior.get("image_url") or prior.get("url")
                        break
            # The Planner doesn't always include copy/image steps. Generate
            # brand-grounded creative here so a campaign is never created (or
            # rejected) for lack of it.
            research = next((
                {k: pr[k] for k in ("competitors", "keywords", "trends") if k in pr}
                for pr in reversed(list(task_outputs.values()))
                if isinstance(pr, dict) and any(pr.get(k) for k in ("competitors", "keywords", "trends"))
            ), None)
            creative_in = {"store_id": session["store_id"],
                           "product_name": brand.get("store_name"),
                           "product_description": brand.get("about"), "research": research}
            if task.get("action") == "create_campaign":
                pass  # the UI engine (see _run_ui_campaign_flow) generates its own creative
            elif not params.get("body") and not params.get("primary_text"):
                gen = await _dispatch_ad_creator(
                    "generate_whatsapp_copy" if task.get("action") == "create_ctwa_campaign"
                    else "generate_ad_copy", creative_in)
                params.update({"headline": params.get("headline") or gen.get("headline"),
                               "body": gen.get("body"), "primary_text": gen.get("primary_text"),
                               "ad_angle": gen.get("ad_angle")})
            if task.get("action") != "create_campaign" and not (params.get("image_url") or params.get("imageUrl")):
                img = await _dispatch_ad_creator("generate_image", creative_in)
                params["image_url"] = img.get("image_url")
        task = {**task, "parameters": params}

        try:
            if task.get("skill") == "zernio-ads" and task.get("action") == "create_campaign":
                try:
                    # Daily amount comes from the session setting, never the Planner:
                    # its "budget" is sometimes a total, which would become $20/day.
                    flow = await _run_ui_campaign_flow(
                        session["store_id"], str(params.get("name") or "Autonomous campaign")[:80],
                        max(config.daily_budget, MIN_DAILY_BUDGET), params.get("goal"),
                        total_budget=config.budget_limit, start_delay_hours=config.start_delay_hours)
                    task_result = {"success": True, "result": flow}
                except Exception as flow_err:
                    detail = getattr(flow_err, "detail", None) or str(flow_err)
                    task_result = {"success": False, "error": str(detail)}
            else:
                task_result = await call_openclaw("POST", "/api/agents/executor/run", {
                    "task": task
                })

            if task_result.get("success"):
                result = task_result.get("result")
                if isinstance(result, dict) and (isinstance(result.get("copy"), dict) or isinstance(result.get("image"), dict)):
                    result = {**result, **(result.get("copy") or {}), **(result.get("image") or {})}
                task_outputs[f"task_{task_index}"] = result
                session["completed_tasks"].append({
                    "task": task,
                    "result": result,
                    "timestamp": datetime.utcnow().isoformat()
                })
                goal_tasks.append({"task": task, "success": True, "result": result})
                if isinstance(result, dict) and result.get("spend"):
                    session["total_spend"] += result["spend"]
            else:
                failure = {"task": task, "error": task_result.get("error"),
                           "timestamp": datetime.utcnow().isoformat()}
                session["failed_tasks"].append(failure)
                goal_tasks.append({"task": task, "success": False, "error": failure["error"]})

        except Exception as e:
            failure = {"task": task, "error": str(e), "timestamp": datetime.utcnow().isoformat()}
            session["failed_tasks"].append(failure)
            goal_tasks.append({"task": task, "success": False, "error": str(e)})

            if config.pause_on_error:
                session["state"] = "paused"
                break

        session["last_update"] = datetime.utcnow().isoformat()

    # The evaluator agent judges the goal from the real task results and the
    # measured performance. It is the only thing that may call a goal achieved.
    evaluation = (await call_openclaw("POST", "/api/agents/evaluator/evaluate", {
        "store_id": session["store_id"],
        "goal": goal,
        "plan": plan,
        "task_results": goal_tasks,
        "performance": session.get("performance") or {},
        "store_context": store_context,
    })).get("evaluation")
    if not evaluation:
        raise HTTPException(status_code=502,
                            detail="OpenClaw evaluator agent returned no assessment.")
    session["evaluations"].append(evaluation)
    session["last_update"] = datetime.utcnow().isoformat()

    assessment = evaluation.get("assessment")
    recommendation_types = {r.get("type") for r in evaluation.get("recommendations") or []}
    if assessment == "achieved":
        goal["status"] = "achieved"
        session["goals_achieved"].append(goal)
    elif assessment == "failed":
        goal["status"] = "failed"
        session["goals_failed"].append(goal)
    elif "abandon" in recommendation_types:
        goal["status"] = "abandoned"
        session["goals_failed"].append(goal)
    elif goal.get("status") in (None, "pending"):
        goal["status"] = "active"
    goal["progress_percentage"] = evaluation.get("progress_percentage")

    if "pause" in recommendation_types and session["state"] == "running":
        session["state"] = "paused"


async def _run_session_goals(session: dict, goals: List[dict], config: AutonomousSessionRequest,
                             store_context: dict, brand: dict) -> None:
    for goal in goals:
        if session["state"] != "running":
            break
        await _run_goal_locked(session, goal, config, store_context, brand)
        if session["total_spend"] >= config.budget_limit:
            session["state"] = "completed"
            break

    if session["state"] == "running" and not session.get("active_goals"):
        session["state"] = "completed"


async def run_autonomous_loop(
    session_id: str,
    profile_id: str,
    performance: dict,
    config: AutonomousSessionRequest
):
    """Background task that runs the autonomous loop."""
    session = _autonomous_sessions.get(session_id)
    if not session:
        return

    try:
        session["state"] = "running"
        store_context, brand = await _agent_store_context(session["store_id"], profile_id)

        # Step 1: Generate or use provided goals (the goal agent, not code).
        if config.initial_goals:
            goals = config.initial_goals
        else:
            goal_result = await call_openclaw("POST", "/api/agents/goal/generate", {
                "store_id": session["store_id"],
                "store_name": brand.get("store_name") or "",
                "niche": brand.get("business_type") or "",
                "country": brand.get("country") or "",
                "business": store_context.get("summary") or "",
                "performance": performance,
                "constraints": {
                    "max_budget": config.budget_limit,
                    "max_daily_spend": config.budget_limit / 30
                }
            })
            goals = (goal_result or {}).get("goals") or []
            if not goals:
                raise HTTPException(status_code=502,
                                    detail="OpenClaw goal agent returned no goals for this store.")

        for goal in goals:
            goal.setdefault("status", "pending")
        session["goals"] = goals
        session["last_update"] = datetime.utcnow().isoformat()

        # Step 2: plan, execute and evaluate each goal.
        await _run_session_goals(session, goals, config, store_context, brand)

    except Exception as e:
        session["state"] = "failed"
        session["error"] = getattr(e, "detail", None) or str(e)
        logger.warning("[OpenClaw] autonomous session %s failed: %s", session_id, session["error"])

    session["last_update"] = datetime.utcnow().isoformat()
    session["ended_at"] = datetime.utcnow().isoformat()


def _goal_needs_work(goal: dict, session: dict) -> bool:
    """Whether resuming should run this goal.

    A goal that already has an evaluator assessment is not re-planned on resume:
    the evaluator paused the session for a human, and re-running the plan could
    duplicate live campaign spend. Goals that never started, or that were
    interrupted before any assessment, do run again.
    """
    status = goal.get("status")
    if status == "pending":
        return True
    if status in ("achieved", "failed", "abandoned"):
        return False
    return not any((ev or {}).get("goal_id") == goal.get("id")
                   for ev in session.get("evaluations") or [])


async def resume_autonomous_loop(session_id: str) -> None:
    """Continue a paused session with the goals it has not finished."""
    session = _autonomous_sessions.get(session_id)
    if not session:
        return
    try:
        config = AutonomousSessionRequest(**session["config"])
        store_context, brand = await _agent_store_context(session["store_id"], session["profile_id"])
        pending = [g for g in session.get("goals") or [] if _goal_needs_work(g, session)]
        await _run_session_goals(session, pending, config, store_context, brand)
    except Exception as e:
        session["state"] = "failed"
        session["error"] = getattr(e, "detail", None) or str(e)
        logger.warning("[OpenClaw] autonomous session %s failed on resume: %s", session_id, session["error"])

    session["last_update"] = datetime.utcnow().isoformat()
    session["ended_at"] = datetime.utcnow().isoformat()


async def run_added_goal(session_id: str, goal: dict) -> None:
    """Run one goal the user added to a session after it started."""
    session = _autonomous_sessions.get(session_id)
    if not session:
        return
    was_running = session["state"] == "running"
    try:
        config = AutonomousSessionRequest(**session["config"])
        store_context, brand = await _agent_store_context(session["store_id"], session["profile_id"])
        session["state"] = "running"
        await _run_goal_locked(session, goal, config, store_context, brand)
        if not was_running and session["state"] == "running" and not session.get("active_goals"):
            session["state"] = "completed"
            session["ended_at"] = datetime.utcnow().isoformat()
    except Exception as e:
        session["state"] = "failed"
        session["error"] = getattr(e, "detail", None) or str(e)
        logger.warning("[OpenClaw] added goal failed on session %s: %s", session_id, session["error"])

    session["last_update"] = datetime.utcnow().isoformat()


@router.get("/stores/{store_id}/autonomous/sessions")
async def list_autonomous_sessions(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all autonomous sessions for a store"""
    sessions = [
        s for s in _autonomous_sessions.values()
        if s.get("store_id") == store_id
    ]
    return {"sessions": sessions}


@router.get("/autonomous/{session_id}/status")
async def get_autonomous_session_status(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get status of an autonomous session"""
    session = _autonomous_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    evaluations = session.get("evaluations") or []
    return {
        "id": session["id"],
        "state": session["state"],
        "goals": session.get("goals", []),
        "goals_achieved": session.get("goals_achieved", []),
        "goals_failed": session.get("goals_failed", []),
        "evaluation_count": len(evaluations),
        "last_evaluation": evaluations[-1] if evaluations else None,
        "completed_tasks": len(session.get("completed_tasks", [])),
        "failed_tasks": len(session.get("failed_tasks", [])),
        "total_spend": session.get("total_spend", 0),
        "error": session.get("error"),
        "started_at": session.get("started_at"),
        "last_update": session.get("last_update"),
        "ended_at": session.get("ended_at")
    }


@router.post("/autonomous/{session_id}/pause")
async def pause_autonomous_session(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """Pause an autonomous session"""
    session = _autonomous_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session["state"] == "running":
        session["state"] = "paused"
        return {"success": True, "state": "paused"}

    return {"success": False, "message": f"Cannot pause session in state: {session['state']}"}


@router.post("/autonomous/{session_id}/resume")
async def resume_autonomous_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """Resume a paused autonomous session"""
    session = _autonomous_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session["state"] != "paused":
        return {"success": False, "message": f"Cannot resume session in state: {session['state']}"}

    pending = [g for g in session.get("goals") or [] if _goal_needs_work(g, session)]
    if not pending:
        session["state"] = "completed"
        session["ended_at"] = datetime.utcnow().isoformat()
        return {"success": False, "state": "completed",
                "message": "Every goal in this session has already been judged."}

    from modules.openclaw import gateway
    gateway.ensure_configured()

    session["state"] = "running"
    session.pop("error", None)
    background_tasks.add_task(resume_autonomous_loop, session_id)
    return {"success": True, "state": "running", "resumed_goals": len(pending)}


@router.post("/autonomous/{session_id}/stop")
async def stop_autonomous_session(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """Stop an autonomous session"""
    session = _autonomous_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session["state"] = "completed"
    session["ended_at"] = datetime.utcnow().isoformat()
    return {"success": True, "state": "completed"}


@router.post("/autonomous/{session_id}/add-goal")
async def add_goal_to_session(
    session_id: str,
    goal: GoalRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """Add a goal to a session and run it (or queue it behind an active plan)."""
    session = _autonomous_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session["state"] not in ["running", "paused"]:
        raise HTTPException(status_code=400, detail="Cannot add goal to completed session")

    new_goal = {
        "id": f"goal-{int(datetime.utcnow().timestamp())}",
        "type": goal.type,
        "description": goal.description,
        "target_metric": goal.target_metric,
        "target_value": goal.target_value,
        "deadline": goal.deadline,
        "priority": goal.priority,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }

    from modules.openclaw import gateway
    gateway.ensure_configured()

    session["goals"].append(new_goal)
    background_tasks.add_task(run_added_goal, session_id, new_goal)
    return {"success": True, "goal": new_goal, "state": session["state"]}


# ============ Reporting ============

@router.get("/stores/{store_id}/report/weekly")
async def get_weekly_report(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get weekly performance report"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or not store.zernio_profile_id:
        raise HTTPException(status_code=400, detail="Store not connected")

    insights = await call_openclaw("GET", "/api/skills/zernio-ads/get_all_store_insights", {
        "profile_id": store.zernio_profile_id,
        "date_preset": "last_7d"
    })

    campaigns = insights.get("campaigns", [])

    return {
        "period": "last_7d",
        "summary": {
            "total_spend": sum(c.get("spend", 0) for c in campaigns),
            "total_impressions": sum(c.get("impressions", 0) for c in campaigns),
            "total_clicks": sum(c.get("clicks", 0) for c in campaigns),
            "total_conversions": sum(c.get("conversions", 0) for c in campaigns),
            "average_ctr": sum(c.get("ctr", 0) for c in campaigns) / max(len(campaigns), 1),
            "average_roas": sum(c.get("roas", 0) for c in campaigns) / max(len(campaigns), 1)
        },
        "campaigns": campaigns,
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/stores/{store_id}/report/demographics")
async def get_demographics_report(
    store_id: str,
    campaign_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get demographic breakdown of ad performance"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or not store.zernio_profile_id:
        raise HTTPException(status_code=400, detail="Store not connected")

    # Get insights with demographic breakdowns
    params = {
        "date_preset": "last_30d",
        "breakdowns": ["age", "gender"]
    }

    if campaign_id:
        params["ad_id"] = campaign_id

    insights = await call_openclaw("GET", "/api/skills/zernio-ads/get_insights", params)

    return {
        "demographics": insights,
        "generated_at": datetime.utcnow().isoformat()
    }


# ============ Zernio Webhook (inbound WhatsApp -> bot reply) ============
#
# Zernio delivers inbound messages over webhooks (event `message.received`),
# not through the REST inbox, so two-way WhatsApp needs a public receiver.
# Flow:
#   Zernio --message.received--> POST /v1/openclaw/zernio-webhook
#     -> resolve the store for business context
#     -> generate a reply with OpenAI
#     -> POST /inbox/conversations/{conversationId}/messages  (service reply,
#        allowed inside the 24h window the customer's inbound just opened)
#
# Register once with:
#   POST /webhooks/settings {name, url, events:["message.received"], secret}
# Signature: Zernio signs the raw body with HMAC-SHA256 -> X-Zernio-Signature.

ZERNIO_WEBHOOK_SECRET = os.getenv("ZERNIO_WEBHOOK_SECRET", "")
# Which store's persona the shared sandbox bot speaks as (the sandbox account is
# not bound to any store). Optional; falls back to the most recent ads store.
WHATSAPP_BOT_STORE_ID = os.getenv("WHATSAPP_BOT_STORE_ID", "")


def _verify_zernio_signature(raw: bytes, signature: str) -> bool:
    """Best-effort HMAC-SHA256 verification of a Zernio webhook body."""
    if not ZERNIO_WEBHOOK_SECRET:
        return True  # no secret configured -> accept (test mode)
    if not signature:
        return False
    import hmac as _hmac
    import hashlib as _hashlib
    digest = _hmac.new(ZERNIO_WEBHOOK_SECRET.encode(), raw, _hashlib.sha256).hexdigest()
    candidate = signature.split("=", 1)[1] if "=" in signature else signature
    return _hmac.compare_digest(digest, candidate.strip())


def _resolve_bot_store(db: Session, account: dict):
    """Pick the store whose business info the bot should answer with."""
    # 1) Account bound to a store's Zernio profile.
    prof = account.get("profileId") or account.get("profile") if isinstance(account, dict) else None
    pid = (prof.get("_id") if isinstance(prof, dict) else prof) or None
    if pid:
        s = db.query(Store).filter(Store.zernio_profile_id == str(pid)).first()
        if s:
            return s
    # 2) Explicitly configured store for the sandbox.
    if WHATSAPP_BOT_STORE_ID:
        s = db.query(Store).filter(Store.id == WHATSAPP_BOT_STORE_ID).first()
        if s:
            return s
    # 3) Best-effort: the most recently updated ads-enabled store.
    return (
        db.query(Store)
        .filter(Store.ads_enabled == True)  # noqa: E712
        .order_by(Store.updated_at.desc())
        .first()
    )


def _business_context(store) -> str:
    """Compact business brief for the bot's system prompt."""
    if not store:
        return "You are a helpful WhatsApp assistant for a Shopivell online store."
    parts = [f"Business name: {store.store_name}"]
    for label, val in [
        ("What they sell / category", store.store_category),
        ("Business type", store.business_type),
        # The onboarding scraper writes its AI-generated business summary into
        # store_voice (store_description is left blank in that flow) - fall back
        # to it so the bot still gets that write-up when store_description is empty.
        ("Description", store.store_description or store.store_voice),
        ("Products or services", ", ".join(store.products_or_services) if isinstance(store.products_or_services, list) else None),
        ("Address", store.store_address),
        ("City", store.store_city),
        ("Country", store.store_country),
        ("Currency", store.currency),
        ("Phone", store.store_phone),
        ("Email", store.store_email),
        ("Hours", str(store.operating_hours) if store.operating_hours else None),
        # Only show as "Brand voice" when it wasn't already used above as the
        # Description fallback, so the same text isn't duplicated in the prompt.
        ("Brand voice", store.store_voice if store.store_description else None),
        ("Tone", store.store_tone),
        ("Store link", store.store_link),
    ]:
        if val:
            parts.append(f"{label}: {val}")
    return "\n".join(parts)


def _faq_context(db: Session, store) -> str:
    """Pull this store's active FAQ entries so the bot can answer from them
    directly (e.g. location, hours, policies), not just the static Store
    columns _business_context covers."""
    if not store:
        return ""
    try:
        from modules.whatsapp.models import FAQ
        faqs = (
            db.query(FAQ)
            .filter(FAQ.store_id == store.id, FAQ.is_active == True)
            .order_by(FAQ.display_order)
            .limit(50)
            .all()
        )
    except Exception as e:
        logger.warning("Failed to load FAQs for bot context (store %s): %s", store.id, e)
        return ""
    if not faqs:
        return ""
    return "\n".join(f"Q: {f.question}\nA: {f.answer}" for f in faqs)


def _bot_config(db: Session, store) -> tuple:
    """This tenant's configured assistant persona name and custom rules
    (Settings > WhatsApp Business > Bot Name / Bot Rules), falling back to the
    platform default name and no extra rules when unset."""
    default_name = "Yamurai"
    if not store:
        return default_name, None
    try:
        from modules.whatsapp.models import StoreBotConfig
        from modules.openclaw.pharmacy_rules import PHARMACY_BOT_INSTRUCTIONS, PHARMACY_REPLY_TEMPLATES
        config = db.query(StoreBotConfig).filter(StoreBotConfig.store_id == store.id).first()
        name = (config.bot_name.strip() if config and config.bot_name and config.bot_name.strip()
                else default_name)
        rule_parts = []
        if config and config.bot_personality and config.bot_personality.strip():
            rule_parts.append(config.bot_personality.strip())
        is_pharmacy = _is_pharmacy_store(store)
        store_rules = (config.pharmacy_instructions if config and config.pharmacy_instructions is not None
                       else PHARMACY_BOT_INSTRUCTIONS if is_pharmacy else [])
        if store_rules:
            rule_parts.append("STORE-SPECIFIC ASSISTANT RULES:\n" + "\n".join(f"- {rule}" for rule in store_rules))
        templates = (config.reply_templates if config and config.reply_templates is not None
                     else PHARMACY_REPLY_TEMPLATES if is_pharmacy else [])
        if templates:
            formatted_templates = "\n".join(
                f"- {template.get('label', 'Reply template')}: {template.get('text', '')}"
                for template in templates if isinstance(template, dict)
            )
            if formatted_templates:
                rule_parts.append(
                    "STORE REPLY TEMPLATES:\n" + formatted_templates +
                    "\nUse a matching template when appropriate, filling in its placeholders. "
                    "Do not use a template when it conflicts with mandatory safety or platform rules."
                )
        return name, "\n\n".join(rule_parts) or None
    except Exception as e:
        logger.warning("Failed to load bot config for store %s: %s", store.id, e)
    return default_name, None


DEFAULT_HANDOFF_KEYWORDS = ["speak to human", "talk to someone", "customer service", "manager"]
DEFAULT_HANDOFF_MESSAGE = "A team member will be with you shortly."

# Prescription keywords trigger pharmacist handoff
PRESCRIPTION_KEYWORDS = [
    "prescription", "script", "rx", "doctor's note", "doctors note",
    "prescribed", "my prescription", "fill prescription", "refill",
    "medication refill", "chronic medication", "repeat prescription"
]
PRESCRIPTION_HANDOFF_MESSAGE = "*Prescription Request*\n\nThank you for reaching out. A pharmacist will assist you with your prescription shortly.\n\nPlease have your prescription ready to share."


# ============== ORDER MANAGEMENT HELPERS ==============

# Dry-run order state (used by the /test-bot-reply endpoint).
#
# A scripted test conversation has to exercise the whole order flow - cart,
# checkout, confirmation - to be worth anything, but it must not write real
# carts or orders. When a dry-run store is active for the current context the
# helpers below keep that state in memory instead of the database.
#
# Sessions are kept per (store, phone) for a short while so a test can also be
# stepped one message at a time. They are bounded and never touch the database.

_DRY_RUN_STORE: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "pharmacy_dry_run_store", default=None
)

_DRY_RUN_SESSIONS: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_DRY_RUN_MAX_SESSIONS = 25
_DRY_RUN_TTL_SECONDS = 30 * 60

# Webhook message deduplication - prevents processing the same message multiple times
# (e.g., when Zernio retries on slow response)
_PROCESSED_MESSAGES: "OrderedDict[str, float]" = OrderedDict()
_PROCESSED_MSG_MAX = 1000
_PROCESSED_MSG_TTL = 60  # 60 seconds TTL


def _is_message_duplicate(msg_id: str) -> bool:
    """Check if message was already processed. Returns True if duplicate."""
    if not msg_id:
        return False
    now = time.time()
    # Clean expired entries
    for old_id, ts in list(_PROCESSED_MESSAGES.items()):
        if now - ts > _PROCESSED_MSG_TTL:
            _PROCESSED_MESSAGES.pop(old_id, None)
        else:
            break  # OrderedDict is sorted by insertion time
    # Check if already processed
    if msg_id in _PROCESSED_MESSAGES:
        return True
    # Mark as processed
    _PROCESSED_MESSAGES[msg_id] = now
    while len(_PROCESSED_MESSAGES) > _PROCESSED_MSG_MAX:
        _PROCESSED_MESSAGES.popitem(last=False)
    return False


def _dry_run_store() -> Optional[Dict[str, Any]]:
    """Return the active in-memory order store, or None when writing for real."""
    return _DRY_RUN_STORE.get()


def _dry_run_session(store_id: str, phone: str, reset: bool = False) -> Dict[str, Any]:
    """Fetch (or start) the in-memory order store for a test conversation."""
    key = f"{store_id}:{phone}"
    now = time.time()
    for stale_key, session in list(_DRY_RUN_SESSIONS.items()):
        if now - session.get("touched", 0) > _DRY_RUN_TTL_SECONDS:
            _DRY_RUN_SESSIONS.pop(stale_key, None)

    if reset or key not in _DRY_RUN_SESSIONS:
        _DRY_RUN_SESSIONS[key] = {"states": {}, "orders": [], "touched": now}

    session = _DRY_RUN_SESSIONS[key]
    session["touched"] = now
    while len(_DRY_RUN_SESSIONS) > _DRY_RUN_MAX_SESSIONS:
        _DRY_RUN_SESSIONS.popitem(last=False)
    return session


class dry_run_order_state:
    """Use as a context manager to keep order state in memory for a test run."""

    def __init__(self, session: Optional[Dict[str, Any]] = None):
        self._token = None
        self.store: Dict[str, Any] = session if session is not None else {"states": {}, "orders": []}

    def __enter__(self) -> Dict[str, Any]:
        self._token = _DRY_RUN_STORE.set(self.store)
        return self.store

    def __exit__(self, *exc_info) -> bool:
        if self._token is not None:
            _DRY_RUN_STORE.reset(self._token)
        return False


def _normalize_state_phone(phone: str) -> str:
    """Normalize phone number for consistent state lookups.

    Strips leading + and ensures consistent format to prevent state mismatches
    when Zernio sends different formats (+263... vs 263...).
    """
    if not phone:
        return ""
    # Strip leading +, spaces, and dashes for consistent lookup
    return phone.lstrip("+").replace(" ", "").replace("-", "")


def _get_order_state(db: Session, store_id: str, customer_phone: str) -> Optional[Dict]:
    """Get the current order state for a customer."""
    # Normalize phone for consistent lookup
    customer_phone = _normalize_state_phone(customer_phone)

    dry = _dry_run_store()
    if dry is not None:
        entry = dry["states"].get(customer_phone)
        return dict(entry) if entry else None

    try:
        from sqlalchemy import text
        result = db.execute(text("""
            SELECT current_state, cart_items, selected_branch, customer_name,
                   customer_address, collection_method, payment_method,
                   customer_phone_delivery, payment_provider, payment_phone
            FROM whatsapp_order_states
            WHERE store_id = CAST(:store_id AS uuid) AND customer_phone = :phone
        """), {"store_id": store_id, "phone": customer_phone}).fetchone()
        if result:
            return {
                "current_state": result[0],
                "cart_items": result[1] or [],
                "selected_branch": result[2],
                "customer_name": result[3],
                "customer_address": result[4],
                "collection_method": result[5],
                "payment_method": result[6],
                "customer_phone_delivery": result[7],
                "payment_provider": result[8],
                "payment_phone": result[9]
            }
    except Exception as e:
        logger.warning("Error getting order state: %s", e)
        try:
            db.rollback()
        except:
            pass
    return None


def _update_order_state(db: Session, store_id: str, customer_phone: str, **updates) -> bool:
    """Update or create order state for a customer."""
    # Normalize phone for consistent storage/lookup
    customer_phone = _normalize_state_phone(customer_phone)

    dry = _dry_run_store()
    if dry is not None:
        entry = dict(dry["states"].get(customer_phone) or {})
        entry.update(updates)
        entry.setdefault("cart_items", [])
        dry["states"][customer_phone] = entry
        return True

    try:
        from sqlalchemy import text
        import json
        from datetime import datetime, timedelta

        # Check if state exists
        existing = db.execute(text("""
            SELECT id FROM whatsapp_order_states
            WHERE store_id = CAST(:store_id AS uuid) AND customer_phone = :phone
        """), {"store_id": store_id, "phone": customer_phone}).fetchone()

        if existing:
            # Build update query
            set_clauses = ["updated_at = NOW()"]
            params = {"store_id": store_id, "phone": customer_phone}
            for key, value in updates.items():
                if key == "cart_items":
                    set_clauses.append(f"{key} = CAST(:val_{key} AS jsonb)")
                    params[f"val_{key}"] = json.dumps(value)
                else:
                    set_clauses.append(f"{key} = :val_{key}")
                    params[f"val_{key}"] = value

            db.execute(text(f"""
                UPDATE whatsapp_order_states
                SET {', '.join(set_clauses)}
                WHERE store_id = CAST(:store_id AS uuid) AND customer_phone = :phone
            """), params)
        else:
            # Create new state - generate UUID for id
            import uuid as uuid_module
            cart_items = updates.get("cart_items", [])
            new_id = str(uuid_module.uuid4())
            now = datetime.now()
            db.execute(text("""
                INSERT INTO whatsapp_order_states
                (id, store_id, customer_phone, current_state, cart_items, selected_branch,
                 customer_name, customer_address, collection_method, payment_method,
                 customer_phone_delivery, payment_provider, payment_phone,
                 created_at, updated_at, expires_at)
                VALUES (CAST(:id AS uuid), CAST(:store_id AS uuid), :phone, :state, CAST(:cart AS jsonb), :branch, :name, :address,
                        :collection, :payment, :phone_delivery, :provider, :pay_phone,
                        :created_at, :updated_at, :expires)
            """), {
                "id": new_id,
                "store_id": store_id,
                "phone": customer_phone,
                "state": updates.get("current_state", "idle"),
                "cart": json.dumps(cart_items),
                "branch": updates.get("selected_branch"),
                "name": updates.get("customer_name"),
                "address": updates.get("customer_address"),
                "collection": updates.get("collection_method"),
                "payment": updates.get("payment_method"),
                "phone_delivery": updates.get("customer_phone_delivery"),
                "provider": updates.get("payment_provider"),
                "pay_phone": updates.get("payment_phone"),
                "created_at": now,
                "updated_at": now,
                "expires": now + timedelta(hours=24)
            })
        db.commit()
        return True
    except Exception as e:
        logger.error("Error updating order state: %s", e)
        db.rollback()
        return False


def _order_prefix(db: Session, store_id: str) -> str:
    """Order number prefix from the store's own name.

    Was hardcoded to "PP", so an Express Care order was confirmed as
    "PP-20261022-..." - the wrong pharmacy. "Platinum Pharmacy" still gives PP
    and "Express Care Pharmacy" gives EC.
    """
    try:
        from sqlalchemy import text
        row = db.execute(text("SELECT store_name FROM stores WHERE id = :sid"),
                         {"sid": str(store_id)}).fetchone()
        words = re.findall(r"[A-Za-z]+", (row[0] if row else "") or "")
        return "".join(word[0] for word in words[:2]).upper() or "OR"
    except Exception as e:
        logger.warning("Could not build an order prefix for store %s: %s", store_id, e)
        return "OR"


def _create_order(db: Session, store_id: str, customer_phone: str, order_data: Dict) -> Optional[str]:
    """Create a new order and return the order number."""
    prefix = _order_prefix(db, store_id)
    dry = _dry_run_store()
    if dry is not None:
        # Note: the real path imports datetime/uuid further down, so bind our
        # own names here rather than referencing those locals too early.
        import uuid as uuid_module
        from datetime import datetime as datetime_module
        order_number = f"{prefix}-{datetime_module.now().strftime('%Y%m%d')}-DRY{uuid_module.uuid4().hex[:4].upper()}"
        dry["orders"].append({"order_number": order_number,
                              "customer_phone": customer_phone,
                              **order_data})
        _update_order_state(db, store_id, customer_phone, current_state="idle", cart_items=[])
        return order_number

    try:
        from sqlalchemy import text
        import json
        import uuid
        from datetime import datetime

        order_id = str(uuid.uuid4())
        date_str = datetime.now().strftime("%Y%m%d")
        order_number = f"{prefix}-{date_str}-{order_id[:4].upper()}"

        db.execute(text("""
            INSERT INTO whatsapp_orders
            (id, store_id, order_number, customer_phone, customer_name, customer_address,
             branch, items, subtotal, delivery_fee, total_amount, collection_method,
             payment_method, payment_provider, status)
            VALUES (CAST(:id AS uuid), CAST(:store_id AS uuid), :order_number, :phone, :name, :address,
                    :branch, CAST(:items AS jsonb), :subtotal, :delivery_fee, :total,
                    :collection, :payment, :provider, 'pending')
        """), {
            "id": order_id,
            "store_id": store_id,
            "order_number": order_number,
            "phone": customer_phone,
            "name": order_data.get("customer_name"),
            "address": order_data.get("customer_address"),
            "branch": order_data.get("branch"),
            "items": json.dumps(order_data.get("items", [])),
            "subtotal": order_data.get("subtotal", 0),
            "delivery_fee": order_data.get("delivery_fee", 0),
            "total": order_data.get("total_amount", 0),
            "collection": order_data.get("collection_method", "delivery"),
            "payment": order_data.get("payment_method", "cod"),
            "provider": order_data.get("payment_provider")
        })
        # The Orders screen reads customer_orders. Keep a corresponding record
        # in the same transaction as the WhatsApp order and any delivery.
        from modules.orders.models import CustomerOrder
        items = order_data.get("items") or []
        item_summary = ", ".join(
            f"{item.get('product_name', 'Item')} x{item.get('quantity', 1)}"
            for item in items
        )
        db.add(CustomerOrder(
            id=uuid.UUID(order_id), store_id=uuid.UUID(str(store_id)),
            order_number=order_number, total_amount=order_data.get("total_amount", 0),
            status="pending", customer_name=order_data.get("customer_name") or "Customer",
            phone=order_data.get("delivery_phone") or customer_phone,
            product_name=item_summary[:255] or None,
            quantity=sum(int(item.get("quantity") or 1) for item in items),
            payment_method=order_data.get("payment_provider") or order_data.get("payment_method"),
            payment_status="unpaid",
            delivery_status="pending" if order_data.get("collection_method") == "delivery" else None,
            tracking_info=order_number if order_data.get("collection_method") == "delivery" else None,
        ))
        if order_data.get("collection_method") == "delivery":
            from modules.delivery.models import Delivery, DeliveryTracking, DeliveryStatus
            db.flush()  # The delivery references the Orders record.
            delivery = Delivery(
                store_id=uuid.UUID(str(store_id)),
                order_id=uuid.UUID(order_id),
                tracking_number=order_number,
                customer_name=order_data.get("customer_name") or "Customer",
                customer_phone=order_data.get("delivery_phone") or customer_phone,
                delivery_address=order_data.get("customer_address") or "",
                delivery_cost=order_data.get("delivery_fee", 0),
                package_description=", ".join(
                    f"{item.get('product_name', '')} x{item.get('quantity', 1)}"
                    for item in order_data.get("items", [])),
                special_instructions=f"WhatsApp order {order_number}",
                status=DeliveryStatus.PENDING,
            )
            db.add(delivery)
            db.flush()
            db.add(DeliveryTracking(delivery_id=delivery.id, status=DeliveryStatus.PENDING,
                                    notes=f"Created from WhatsApp order {order_number}"))
        db.commit()

        # Clear the order state
        _update_order_state(db, store_id, customer_phone, current_state="idle", cart_items=[])

        return order_number
    except Exception as e:
        logger.error("Error creating order: %s", e)
        db.rollback()
        return None


def _get_order_history(db: Session, store_id: str, customer_phone: str, limit: int = 5) -> list:
    """Get order history for a customer."""
    # Normalize phone for consistent lookup
    customer_phone = _normalize_state_phone(customer_phone)

    try:
        from sqlalchemy import text
        result = db.execute(text("""
            SELECT order_number, status, total_amount, payment_method, payment_provider,
                   collection_method, created_at
            FROM whatsapp_orders
            WHERE store_id = CAST(:store_id AS uuid) AND customer_phone = :phone
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"store_id": store_id, "phone": customer_phone, "limit": limit}).fetchall()

        orders = []
        for row in result:
            orders.append({
                "order_number": row[0],
                "status": row[1],
                "total_amount": float(row[2]) if row[2] else 0,
                "payment_method": row[3],
                "payment_provider": row[4],
                "collection_method": row[5],
                "created_at": row[6].strftime("%Y-%m-%d %H:%M") if row[6] else ""
            })
        return orders
    except Exception as e:
        logger.warning("Error getting order history: %s", e)
        return []


def _initiate_mobile_payment(db: Session, order_number: str, payment_phone: str) -> Optional[Dict]:
    """Initiate mobile money payment for an order."""
    if _dry_run_store() is not None:
        # Never trigger a real PayNow prompt from a test run.
        return {"dry_run": True,
                "instructions": "DRY RUN - no mobile money prompt was sent."}

    try:
        from modules.whatsapp.payment_service import WhatsAppPaymentService, get_order_by_number

        order = get_order_by_number(db, order_number)
        if not order:
            logger.error(f"Order not found for payment: {order_number}")
            return None

        if order["payment_method"] == "cod":
            return {"skip": True, "message": "Cash on delivery - no payment needed"}

        payment_service = WhatsAppPaymentService(db)
        result, error = payment_service.initiate_mobile_payment(
            order_id=order["id"],
            order_number=order_number,
            amount=order["total_amount"],
            customer_phone=payment_phone,
            payment_provider=order["payment_provider"] or "ecocash"
        )

        if error:
            logger.error(f"Payment initiation failed: {error}")
            return {"error": error}

        return result
    except Exception as e:
        logger.error(f"Error initiating payment: {e}")
        return None


def _calculate_delivery_fee(distance_km: float) -> float:
    """Calculate delivery fee: free within 10km, $0.40/km after that."""
    if distance_km <= 10:
        return 0.0
    return (distance_km - 10) * 0.40


def _format_cart_summary(cart_items: List[Dict], delivery_fee: float = 0) -> str:
    """Format cart items for display (whole-number prices)."""
    if not cart_items:
        return "Your cart is empty."

    subtotal = cart_subtotal(cart_items)
    total = subtotal + round_price(delivery_fee)

    lines = ["*YOUR CART*", ""]
    for i, item in enumerate(cart_items, 1):
        qty = int(item.get("quantity", 1) or 1)
        line_total = round_price(item.get("price", 0)) * qty
        lines.append(f"{i}. {item.get('product_name')} x{qty} - {format_price(line_total)}")
    lines.append(f"\nSubtotal: {format_price(subtotal)}")
    lines.append(f"*TOTAL: {format_price(total)}*")
    return "\n".join(lines)


# ============== END ORDER MANAGEMENT HELPERS ==============


# ============== PHARMACY BOT TOOLS ==============
# Tool definitions for OpenAI function calling

PHARMACY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search for products in the pharmacy inventory. ALWAYS use this tool when customer asks about ANY product, brand, or category - including follow-up questions like 'do you have X as well' or 'what about Y'. Use for: product inquiries, availability checks, price questions, brand searches. Tolerates misspellings: if the result starts with 'DID_YOU_MEAN:', ask the customer to confirm the corrected product before showing prices or ordering.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Product name, brand, or type to search for (e.g., 'nivea', 'toothpaste', 'lotion', 'panadol', 'shampoo')"
                    },
                    "branch": {
                        "type": "string",
                        "description": ("Branch to search in - use a name from "
                                        "list_branches. If not specified, searches all branches.")
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": "Add a product to the customer's cart. Use when customer wants to order/buy a product. Make ONE call per product - if the customer asks for several products, call this tool once for each of them (never combine or drop any). Prices must be the whole-number price shown to the customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "Exact name of the product to add"
                    },
                    "price": {
                        "type": "number",
                        "description": "Price of the product"
                    },
                    "quantity": {
                        "type": "integer",
                        "description": ("Quantity to add (default 1). 'Add another one' / '"
                                        "'one more' is 1 - it means one extra unit, never "
                                        "a doubled quantity."),
                        "default": 1
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch to order from (a name from list_branches)"
                    }
                },
                "required": ["product_name", "price", "branch"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_cart",
            "description": ("Remove a product from the customer's cart, or reduce its quantity. "
                            "Use product_name='all' to empty the cart."),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string",
                                     "description": "Product to remove, or 'all' to clear the cart"},
                    "quantity": {"type": "integer",
                                 "description": "How many to remove (default: the whole line)"},
                },
                "required": ["product_name"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_cart",
            "description": ("Edit an item that is ALREADY in the cart: set a new quantity "
                            "(absolute - 'make it 3' is quantity=3, quantity=0 removes it) or "
                            "replace it with another catalogue product."),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string",
                                     "description": "Cart item to change (partial name is fine)"},
                    "quantity": {"type": "integer", "minimum": 0,
                                 "description": ("New TOTAL quantity for that item. "
                                                 "0 removes the line.")},
                    "new_product_name": {"type": "string",
                                         "description": "Optional exact catalogue name to replace it with"},
                },
                "required": ["product_name", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": ("Look up this customer's OWN orders: their latest order, one order "
                            "number, or their recent order history. ALWAYS use this for 'what is "
                            "my order number', 'where is my order', 'my orders'."),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {"type": "string",
                                     "description": "Optional specific order number to look up"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_branches",
            "description": ("List all branches in the store information and identify those "
                            "with online catalogue data. For other branches, ask the team "
                            "to confirm stock and prices; do not assume items are unavailable."),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_branch",
            "description": ("Save the branch the customer chose to shop from. Use when they answer "
                            "a branch menu or name the branch they want. Use a branch name returned "
                            "by list_branches."),
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Exact branch name from list_branches (e.g. Angwa)"
                    }
                },
                "required": ["branch"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_cart",
            "description": "Show the customer's current cart with all items and total",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_collection_method",
            "description": "Set how the customer wants to collect their order",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["walk_in", "delivery"],
                        "description": "Collection method: walk_in (pick up from branch) or delivery"
                    }
                },
                "required": ["method"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_delivery_details",
            "description": "Set all delivery details for the order (name, phone, address) in one call. If the customer has only given one or two details, use update_delivery_name / update_delivery_phone / update_delivery_address instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "Customer's full name"},
                    "phone": {
                        "type": "string",
                        "description": "Customer's phone number - must be a valid 10-digit number, e.g. 0771234567 or +263771234567"
                    },
                    "address": {"type": "string", "description": "Delivery address"}
                },
                "required": ["customer_name", "phone", "address"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_payment_method",
            "description": "Set payment method for the order",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["cash", "ecocash", "onemoney", "innbucks"],
                        "description": "Payment method"
                    },
                    "mobile_number": {
                        "type": "string",
                        "description": "Mobile money number (required for ecocash/onemoney/innbucks) - must be a valid 10-digit number, e.g. 0771234567 or +263771234567"
                    }
                },
                "required": ["method"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_order",
            "description": "Finalize and place the order. ONLY call this AFTER: 1) Cart has items, 2) Collection method is set (walk-in or delivery), 3) Payment method is set, 4) Customer has seen the final order summary with total, 5) Customer explicitly confirms the ORDER (not just adding products). For EcoCash/OneMoney/InnBucks it also sends the PayNow mobile prompt; tell the customer to approve it and never say payment succeeded until they confirm. DO NOT call this when customer is just confirming they want to add products to cart.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "show_delivery_details",
            "description": "Show the customer their current delivery details (name, phone, address). Use when customer asks 'what is my address', 'do you have my details', 'tell me my info', 'what do you have for me', etc.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_delivery_name",
            "description": "Update the customer's delivery name. Use when they say 'change my name to X', 'my name is X', 'call me X', etc. If they give a name and phone number together, pass both in this call and the phone is saved too.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Customer's full name (a phone number in the same value is extracted and saved as the phone)"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_delivery_phone",
            "description": "Update only the customer's delivery phone number. Use when they say 'change my number to X', 'my phone is X', 'use this number X', etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "Phone number (10 digits, e.g. 0771234567)"}
                },
                "required": ["phone"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_delivery_address",
            "description": "Update only the customer's delivery address. Use when they say 'my address is X', 'deliver to X', 'change address to X', etc. Before calling, ensure the address includes street/house number, suburb/area, and city (e.g. '670 Ushewekunze Street, Mabelreign, Harare').",
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "Full delivery address: house number + street, suburb/area, city (e.g. '670 Ushewekunze Street, Mabelreign, Harare')"}
                },
                "required": ["address"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "go_back_to_cart",
            "description": "Return customer to shopping/cart state. Use when they say 'add more products', 'continue shopping', 'go back', 'I want to order more', 'cancel checkout', etc.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "start_checkout",
            "description": "Start the checkout process. Use when customer says 'checkout', 'place order', 'buy now', 'I'm done ordering'. Shows collection method options.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]


# ============== MCP SERVER FOR OPENCLAW ==============
# Model Context Protocol endpoint that exposes pharmacy tools to OpenClaw

# Tools that only read data. OpenClaw requires human approval for unannotated
# MCP calls, so every tool is annotated with its real safety profile.
MCP_READ_ONLY_TOOLS = {
    "search_products",
    "list_branches",
    "view_cart",
    "get_order_status",
    "show_delivery_details",
}

def _convert_openai_tool_to_mcp(tool: dict) -> dict:
    """Convert OpenAI function calling format to MCP tool format.

    Adds store_id and customer_phone context parameters that OpenClaw must pass
    since MCP doesn't have per-conversation session context.
    """
    func = tool.get("function", {})
    original_params = func.get("parameters", {"type": "object", "properties": {}})

    # Deep copy and add context parameters
    import copy
    params = copy.deepcopy(original_params)

    # Add context parameters to properties
    context_props = {
        "store_id": {
            "type": "string",
            "description": "Store ID (UUID) - REQUIRED for all operations. Get from conversation context."
        },
        "customer_phone": {
            "type": "string",
            "description": "Customer phone number (e.g. '263781234567') - REQUIRED for cart/order operations."
        }
    }
    if "properties" not in params:
        params["properties"] = {}
    params["properties"].update(context_props)

    # Add to required list
    required = list(params.get("required", []))
    required.extend(["store_id", "customer_phone"])
    params["required"] = required

    # Safety annotations. Without them OpenClaw treats every MCP call as
    # approval-required in prompting session postures, so an agent turn either
    # stalls or answers without ever calling the tool.
    name = func.get("name") or ""
    read_only = name in MCP_READ_ONLY_TOOLS

    return {
        "name": name,
        "description": func.get("description") + " [Requires store_id and customer_phone context]",
        "inputSchema": params,
        "annotations": {
            "title": name.replace("_", " ").title(),
            "readOnlyHint": read_only,
            "destructiveHint": False,
            "idempotentHint": read_only,
            "openWorldHint": False,
        },
    }

# MCP tool definitions (converted from PHARMACY_TOOLS with context params added)
MCP_TOOLS = [_convert_openai_tool_to_mcp(t) for t in PHARMACY_TOOLS]


from typing import Union

class MCPRequest(BaseModel):
    """MCP JSON-RPC 2.0 request."""
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None  # JSON-RPC allows string or integer IDs
    method: str
    params: Optional[dict] = None


class MCPResponse(BaseModel):
    """MCP JSON-RPC 2.0 response."""
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[dict] = None

    class Config:
        # Exclude None values from JSON output (JSON-RPC 2.0 spec compliance)
        # Success responses should not have 'error', error responses should not have 'result'
        json_encoders = {type(None): lambda _: None}

    def dict(self, **kwargs):
        # Ensure we exclude None values to be JSON-RPC 2.0 compliant
        kwargs.setdefault('exclude_none', True)
        return super().dict(**kwargs)


from fastapi.responses import JSONResponse as FastAPIJSONResponse, Response, StreamingResponse
import uuid as uuid_module

# ============== MCP SSE SESSION MANAGEMENT ==============
# For SSE transport, we need to track active sessions and their message queues
_MCP_SSE_SESSIONS: Dict[str, asyncio.Queue] = {}
_MCP_SSE_SESSION_TTL = 300  # 5 minutes


async def _mcp_sse_cleanup():
    """Clean up stale SSE sessions (called periodically)."""
    # Simple cleanup - in production, track timestamps
    pass


@router.options("/mcp/pharmacy")
@router.options("/mcp/pharmacy/sse")
@router.options("/mcp/pharmacy/message")
async def mcp_pharmacy_options():
    """Handle CORS preflight for MCP endpoints."""
    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-Session-Key, Authorization",
            "Access-Control-Max-Age": "86400",
        }
    )


@router.get("/mcp/pharmacy")
async def mcp_pharmacy_sse(
    request: Request,
    db: Session = Depends(get_db),
    store_id: str = Query(None, description="Store ID for context"),
    phone: str = Query(None, description="Customer phone for context"),
):
    """
    MCP SSE endpoint - establishes Server-Sent Events connection.

    This is the main entry point for MCP SSE transport:
    1. Client GETs this endpoint (optionally with store_id and phone params)
    2. Server returns SSE stream with 'endpoint' event containing POST URL
    3. Client POSTs JSON-RPC messages to that URL
    4. Server sends responses via this SSE stream

    The store_id and phone params are embedded in the message endpoint URL
    so they're available for tool execution context.
    """
    import json

    # Generate unique session ID
    session_id = str(uuid_module.uuid4())

    # Store context for this session
    _MCP_SSE_SESSIONS[f"{session_id}:context"] = {"store_id": store_id, "phone": phone}

    # Create message queue for this session
    message_queue: asyncio.Queue = asyncio.Queue()
    _MCP_SSE_SESSIONS[session_id] = message_queue

    # Get base URL for the message endpoint
    base_url = str(request.base_url).rstrip("/")
    # Handle proxy headers
    forwarded_proto = request.headers.get("x-forwarded-proto", "https")
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if forwarded_host:
        message_url = f"{forwarded_proto}://{forwarded_host}/v1/openclaw/mcp/pharmacy/message?session={session_id}"
    else:
        message_url = f"{base_url}v1/openclaw/mcp/pharmacy/message?session={session_id}"

    async def event_generator():
        """Generate SSE events."""
        try:
            # Send endpoint event first (tells client where to POST messages)
            endpoint_event = f"event: endpoint\ndata: {message_url}\n\n"
            yield endpoint_event
            logger.info("MCP SSE session %s: sent endpoint event", session_id)

            # Keep connection alive and send responses
            while True:
                try:
                    # Wait for messages with timeout (for keepalive)
                    message = await asyncio.wait_for(message_queue.get(), timeout=30.0)

                    if message is None:  # Shutdown signal
                        break

                    # Send message as SSE event
                    event_data = f"event: message\ndata: {json.dumps(message)}\n\n"
                    yield event_data
                    logger.info("MCP SSE session %s: sent message event", session_id)

                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"

        except asyncio.CancelledError:
            logger.info("MCP SSE session %s: connection cancelled", session_id)
        finally:
            # Cleanup session and context
            _MCP_SSE_SESSIONS.pop(session_id, None)
            _MCP_SSE_SESSIONS.pop(f"{session_id}:context", None)
            logger.info("MCP SSE session %s: cleaned up", session_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.post("/mcp/pharmacy/message")
async def mcp_pharmacy_message(
    request: Request,
    session: str = Query(..., description="SSE session ID"),
    db: Session = Depends(get_db),
    x_session_key: str = Header(None, alias="X-Session-Key"),
):
    """
    MCP message endpoint for SSE transport.

    Receives JSON-RPC messages and sends responses via the SSE stream.
    """
    import json

    # Get the session queue
    message_queue = _MCP_SSE_SESSIONS.get(session)
    if not message_queue:
        return FastAPIJSONResponse(
            status_code=400,
            content={"error": "Invalid or expired session"}
        )

    # Parse request body
    try:
        body = await request.json()
    except Exception as e:
        return FastAPIJSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        )

    # Handle the JSON-RPC request
    jsonrpc_request = MCPRequest(**body) if isinstance(body, dict) else None
    if not jsonrpc_request:
        return FastAPIJSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        )

    # Get context from session (stored when SSE connection was established)
    # First try X-Session-Key header, then fall back to stored context
    store_id = None
    customer_phone = None
    store = None

    if x_session_key and x_session_key.startswith("pharmacy:"):
        parts = x_session_key.split(":")
        if len(parts) >= 3:
            store_id = parts[1]
            customer_phone = parts[2]
    else:
        # Fall back to context stored from SSE URL params
        session_context = _MCP_SSE_SESSIONS.get(f"{session}:context", {})
        store_id = session_context.get("store_id")
        customer_phone = session_context.get("phone")

    if store_id:
        store = db.query(Store).filter(Store.id == store_id).first()

    # Process the request and build response
    response_data = {"jsonrpc": "2.0", "id": jsonrpc_request.id}

    if jsonrpc_request.method == "initialize":
        response_data["result"] = {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "shopivell-pharmacy", "version": "1.0.0"},
            "capabilities": {"tools": {}}
        }
    elif jsonrpc_request.method == "tools/list":
        response_data["result"] = {"tools": MCP_TOOLS}
    elif jsonrpc_request.method == "tools/call":
        params = jsonrpc_request.params or {}
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})

        if not tool_name:
            response_data["error"] = {"code": -32602, "message": "Missing tool name"}
        else:
            # Extract context from tool arguments (MCP tools have store_id and customer_phone as params)
            arg_store_id = tool_args.pop("store_id", None)
            arg_customer_phone = tool_args.pop("customer_phone", None)

            # Use args context if available, otherwise fall back to session context
            final_store_id = arg_store_id or store_id
            final_customer_phone = arg_customer_phone or customer_phone

            if not final_store_id or not final_customer_phone:
                response_data["error"] = {
                    "code": -32602,
                    "message": "Missing store_id or customer_phone. These are required for all pharmacy tools."
                }
            else:
                # Get store from args context if different
                final_store = store
                if arg_store_id and arg_store_id != store_id:
                    final_store = db.query(Store).filter(Store.id == arg_store_id).first()

                if not final_store:
                    response_data["error"] = {"code": -32602, "message": f"Store not found: {final_store_id}"}
                else:
                    try:
                        result = await _execute_pharmacy_tool(
                            db, final_store, final_customer_phone, tool_name, tool_args, ""
                        )
                        response_data["result"] = {"content": [{"type": "text", "text": result}]}
                    except Exception as e:
                        logger.error("MCP tool execution failed: %s", e)
                        response_data["error"] = {"code": -32603, "message": f"Tool execution failed: {str(e)}"}
    else:
        response_data["error"] = {"code": -32601, "message": f"Unknown method: {jsonrpc_request.method}"}

    # Send response via SSE stream
    await message_queue.put(response_data)

    # Also return accepted status
    return Response(status_code=202, headers={"Access-Control-Allow-Origin": "*"})


MCP_SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

# Shared secret for the MCP endpoint. Unset keeps the endpoint open (old
# behaviour); set MCP_PHARMACY_TOKEN on the backend and send the same value as
# "Authorization: Bearer <token>" from OpenClaw's mcp.servers headers.
MCP_PHARMACY_TOKEN = os.getenv("MCP_PHARMACY_TOKEN", "")


def _mcp_authorised(authorization: Optional[str], token_header: Optional[str]) -> bool:
    if not MCP_PHARMACY_TOKEN:
        return True
    supplied = token_header or ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    import hmac
    return hmac.compare_digest(supplied, MCP_PHARMACY_TOKEN)


@router.post("/mcp/pharmacy")
async def mcp_pharmacy_endpoint(
    request: MCPRequest,
    db: Session = Depends(get_db),
    x_session_key: str = Header(None, alias="X-Session-Key"),
    authorization: Optional[str] = Header(None),
    x_mcp_token: Optional[str] = Header(None, alias="X-MCP-Token"),
):
    """
    MCP (Model Context Protocol) endpoint for pharmacy tools - streamable HTTP.

    OpenClaw calls this endpoint to initialise, list tools and execute them.
    It is stateless on purpose: no session id or server-side stream is needed,
    so it survives proxies, restarts and multiple workers (the SSE transport
    this replaced lost its in-memory session as soon as Cloudflare closed the
    stream, which made every tools/list call return "Invalid or expired
    session").

    Session key format: "pharmacy:<store_id>:<phone>"
    """

    def mcp_response(id: Optional[str], result: dict = None, error: dict = None,
                     status_code: int = 200) -> FastAPIJSONResponse:
        """Return a proper JSON-RPC 2.0 response for MCP."""
        response_data = {"jsonrpc": "2.0", "id": id}
        if error is not None:
            response_data["error"] = error
        else:
            response_data["result"] = result
        return FastAPIJSONResponse(
            status_code=status_code,
            content=response_data,
            media_type="application/json",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, X-Session-Key, Authorization, X-MCP-Token, MCP-Protocol-Version",
            }
        )

    # Notifications (no id) must be acknowledged with 202 and no body. Replying
    # with a JSON-RPC error made strict clients treat the server as broken, so
    # they never asked for the tool list.
    if request.id is None and (request.method or "").startswith("notifications/"):
        return Response(status_code=202, headers={"Access-Control-Allow-Origin": "*"})

    if not _mcp_authorised(authorization, x_mcp_token):
        return mcp_response(
            request.id,
            error={"code": -32001, "message": "Unauthorized: invalid MCP token"},
            status_code=401,
        )

    try:
        # Parse session key for context
        store_id = None
        customer_phone = None
        store = None

        if x_session_key and x_session_key.startswith("pharmacy:"):
            parts = x_session_key.split(":")
            if len(parts) >= 3:
                store_id = parts[1]
                customer_phone = parts[2]
                store = db.query(Store).filter(Store.id == store_id).first()

        # Handle different MCP methods
        if request.method == "initialize":
            requested = ((request.params or {}).get("protocolVersion") or "").strip()
            negotiated = requested if requested in MCP_SUPPORTED_PROTOCOL_VERSIONS else MCP_SUPPORTED_PROTOCOL_VERSIONS[0]
            return mcp_response(
                request.id,
                result={
                    "protocolVersion": negotiated,
                    "serverInfo": {
                        "name": "shopivell-pharmacy",
                        "version": "1.0.0"
                    },
                    "capabilities": {
                        "tools": {"listChanged": False}
                    },
                    "instructions": (
                        "Shopivell pharmacy tools. Every tool requires store_id and "
                        "customer_phone; pass the values given for this conversation. "
                        "Prices are in USD. Never invent stock or prices."
                    )
                }
            )

        elif request.method == "ping":
            return mcp_response(request.id, result={})

        elif request.method in ("resources/list", "resources/templates/list"):
            return mcp_response(request.id, result={"resources": []})

        elif request.method == "prompts/list":
            return mcp_response(request.id, result={"prompts": []})

        elif request.method == "logging/setLevel":
            return mcp_response(request.id, result={})

        elif request.method == "tools/list":
            return mcp_response(request.id, result={"tools": MCP_TOOLS})

        elif request.method == "tools/call":
            params = request.params or {}
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            if not tool_name:
                return mcp_response(
                    request.id,
                    error={"code": -32602, "message": "Missing tool name"}
                )

            # Extract context from tool arguments (MCP tools have store_id and customer_phone as params)
            arg_store_id = tool_args.pop("store_id", None)
            arg_customer_phone = tool_args.pop("customer_phone", None)

            # Use args context if available, otherwise fall back to header context
            final_store_id = arg_store_id or store_id
            final_customer_phone = arg_customer_phone or customer_phone

            if not final_store_id or not final_customer_phone:
                return mcp_response(
                    request.id,
                    error={"code": -32602, "message": "Missing store_id or customer_phone. Pass them as tool arguments."}
                )

            # Get store
            final_store = store
            if arg_store_id and arg_store_id != store_id:
                final_store = db.query(Store).filter(Store.id == arg_store_id).first()

            if not final_store:
                return mcp_response(
                    request.id,
                    error={"code": -32602, "message": f"Store not found: {final_store_id}"}
                )

            # Execute the tool using existing handler
            try:
                result = await _execute_pharmacy_tool(
                    db, final_store, final_customer_phone, tool_name, tool_args, ""
                )
                return mcp_response(
                    request.id,
                    result={"content": [{"type": "text", "text": result}]}
                )
            except Exception as e:
                logger.error("MCP tool execution failed: %s", e)
                return mcp_response(
                    request.id,
                    error={"code": -32603, "message": f"Tool execution failed: {str(e)}"}
                )

        else:
            return mcp_response(
                request.id,
                error={"code": -32601, "message": f"Unknown method: {request.method}"}
            )

    except Exception as e:
        logger.error("MCP endpoint error: %s", e)
        return mcp_response(
            request.id,
            error={"code": -32603, "message": str(e)}
        )


# "add another one" is ONE extra unit. The model read it as "double what is in
# the cart" and turned 2 into 4, so the arithmetic is corrected from the
# customer's own words instead of trusting the model's quantity.
_ONE_EXTRA = re.compile(
    r"\b(anoth\w*|one more|one extra|just one|add one|add 1|\+\s?1|one again)\b", re.I)

_QUANTITY_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                   "seven": 7, "eight": 8, "nine": 9, "ten": 10, "pair": 2, "a": 1, "an": 1}


def _requested_quantity(text: str) -> int:
    """Units the customer asked for, or 1 when they did not say.

    Only counting cues are read, so "i'll take 2 of the benylin 4 flu" is 2 while
    the "4" in the product name is ignored.
    """
    if not text:
        return 1
    lowered = str(text).lower()
    # No bare "x4" pattern: "150MM X4.5M" in a pasted price list was read as a
    # quantity and turned one plaster into "4x PLASTER OF PARIS 50MM".
    for pattern in (r"\b(?:take|want|need|add|order|buy|get|give me)\s+(\d{1,2})\b(?!\s*[.)])",
                    r"\b(\d{1,2})\s*(?:x\b|of\b|units?\b|boxes?\b|packs?\b|bottles?\b|tubes?\b)"):
        match = re.search(pattern, lowered)
        if match:
            return max(1, min(99, int(match.group(1))))
    words = r"(one|two|three|four|five|six|seven|eight|nine|ten|pair|a|an)"
    match = (re.search(rf"\b(?:take|want|need|add|order|buy|get|give me)\s+{words}\b", lowered)
             or re.search(rf"\b{words}\s+(?:of|units|boxes|packs|bottles|tubes)\b", lowered))
    return _QUANTITY_WORDS.get(match.group(1), 1) if match else 1


def _pending_quantity(history, item_name: str) -> int:
    """Units requested in the message that named this item (for the sure-check)."""
    if not item_name:
        return 1
    needle = item_name.split()[0].lower()
    for message in reversed(history or []):
        if message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        if needle and needle in content.lower():
            return _requested_quantity(content)
    return 1


# Category names a customer types -> the catalogue words that make up that
# category. Numbers are deliberately not keys: a bare "1" once became the
# skincare catalogue and answered "We have NIVEA products available".
_CATEGORY_SEARCH_TERMS = {
    "skincare": "nivea OR vaseline OR dove OR lotion OR cream OR moisturizer",
    "skin care": "nivea OR vaseline OR dove OR lotion OR cream OR moisturizer",
    "skin": "nivea OR vaseline OR dove OR lotion OR cream OR moisturizer",
    "haircare": "shampoo OR conditioner OR hair",
    "hair care": "shampoo OR conditioner OR hair",
    "hair": "shampoo OR conditioner OR hair",
    "oral care": "toothpaste OR mouthwash OR toothbrush OR colgate",
    "oral": "toothpaste OR mouthwash OR toothbrush OR colgate",
    "toothpaste": "toothpaste OR colgate OR aquafresh",
    "cosmetics": "lipstick OR mascara OR makeup OR cosmetic OR foundation",
    "makeup": "lipstick OR mascara OR makeup OR cosmetic OR foundation",
    "baby": "baby OR diaper OR nappy",
    "baby products": "baby OR diaper OR nappy",
    "medications": "tablet OR capsule OR syrup OR panadol OR medicine",
    "medicine": "tablet OR capsule OR syrup OR panadol",
    "meds": "tablet OR capsule OR syrup OR panadol OR medicine",
    "first aid": "bandage OR plaster OR antiseptic OR first aid",
    "firstaid": "bandage OR plaster OR antiseptic OR first aid",
    # The categories the storefronts actually use. "personal care products" was
    # answered with "Did you mean *Sensodyne*?" because nothing here matched, so
    # the query fell through to spelling suggestions.
    "personal care": "nivea OR dove OR vaseline OR soap OR deodorant OR wipes OR lotion",
    "personal": "nivea OR dove OR vaseline OR soap OR deodorant OR wipes OR lotion",
    "toiletries": "soap OR deodorant OR shampoo OR toothpaste OR tissue",
    "wellness": "vitamin OR supplement OR immune OR omega OR multivitamin",
    "supplements": "vitamin OR supplement OR multivitamin OR omega",
    "beauty": "lipstick OR foundation OR mascara OR perfume OR eyeshadow",
    "baby & kids": "baby OR kids OR diaper OR nappy OR wipes",
    "baby and kids": "baby OR kids OR diaper OR nappy OR wipes",
    "body lotion": "lotion",
    "body lotions": "lotion",
    "confectionery": "sweets OR chocolate OR candy OR biscuits",
}

# Categories that mean the same shelf, so "hair care and oral care" is two
# categories rather than four synonyms.
_CATEGORY_DISPLAY = {
    "skincare": "Skincare", "skin care": "Skincare", "skin": "Skincare",
    "haircare": "Haircare", "hair care": "Haircare", "hair": "Haircare",
    "oral care": "Oral Care", "oral": "Oral Care", "toothpaste": "Oral Care",
    "cosmetics": "Cosmetics", "makeup": "Cosmetics", "beauty": "Beauty",
    "baby": "Baby Products", "baby products": "Baby Products",
    "baby & kids": "Baby & Kids", "baby and kids": "Baby & Kids",
    "medications": "Medications", "medicine": "Medications", "meds": "Medications",
    "first aid": "First Aid", "firstaid": "First Aid",
    "personal care": "Personal Care", "personal": "Personal Care",
    "toiletries": "Toiletries", "wellness": "Wellness", "supplements": "Wellness",
    "body lotion": "Body Lotions", "body lotions": "Body Lotions",
    "confectionery": "Confectionery",
}


def _is_general_catalogue_request(message: str) -> bool:
    """Recognize a general catalogue question, without answering advice requests."""
    text = re.sub(r'[^a-z0-9\s]', ' ', str(message or '').lower())
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^(?:hi|hello|hey)\s+', '', text)
    return bool(re.fullmatch(
        r'(?:what (?:(?:kind|type|types) of )?(?:products|items|categories) (?:do you (?:have|sell|stock|offer)|are available)(?: in (?:your |the )?(?:store|stock))?'
        r'|what do you (?:sell|stock|offer|have)'
        r'|(?:show|list|tell) (?:me )?(?:your |the )?(?:products|items|categories|product range)'
        r'|(?:your |the )?(?:products|product range|product categories|categories))', text))


def _catalogue_categories_reply(db, store, branch: Optional[str] = None) -> str:
    """Describe categories backed by this store's active online catalogue."""
    from sqlalchemy import text as sql_text
    params = {'store_id': str(store.id)}
    branch_clause = ''
    if branch:
        branch_clause = ' AND LOWER(branch) = LOWER(:branch)'
        params['branch'] = branch
    rows = db.execute(sql_text('''
        SELECT title, content FROM company_knowledge
        WHERE store_id = :store_id AND content_type = 'product' AND is_active = true
    ''' + branch_clause), params).fetchall()
    if not rows:
        where = f' for {branch}' if branch else ''
        return f'I don’t have an online product list{where} yet. Our team can check what is available.'
    texts = [f'{title or ""} {content or ""}'.lower() for title, content in rows]
    categories = [
        ('Baby products', 'baby products'),
        ('Oral care', 'oral care'),
        ('Skincare', 'skincare'),
        ('Haircare', 'hair care'),
        ('Personal care and toiletries', 'personal care'),
        ('Cosmetics and beauty', 'cosmetics'),
        ('Vitamins and supplements', 'wellness'),
        ('First aid', 'first aid'),
        ('Medicines', 'medications'),
    ]
    found = []
    for label, key in categories:
        terms = _CATEGORY_SEARCH_TERMS[key].lower().split(' or ')
        if any(any(re.search(r'\b' + re.escape(term) + r'\b', text) for term in terms) for text in texts):
            found.append(label)
    if not found:
        return 'We have products in our online catalogue. Tell me what you are looking for and I can check.'
    where = f' for {branch}' if branch else ''
    return (f'Our online catalogue{where} includes:\n\n'
            + '\n'.join(f'• {category}' for category in found)
            + '\n\nTell me what you are looking for and I can check the products and prices.')


def _named_categories(text: str) -> List[tuple]:
    """(display, key) for every shelf a message names, de-duplicated."""
    cleaned = re.sub(r"\b(products?|items?|stuff|range|category|categories)\b",
                     " ", str(text or "").lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    groups: List[tuple] = []
    for key in sorted(_CATEGORY_SEARCH_TERMS, key=len, reverse=True):
        if key in cleaned and len(key) > 2:
            display = _CATEGORY_DISPLAY.get(key, key.title())
            if all(display != seen for seen, _ in groups):
                groups.append((display, key))
    return groups


# Words that carry no product identity on their own. After the shelf name is
# removed, a message made only of these is a category browse ("do you have any
# body lotions?"). If a brand or product word survives ("nivea body lotion"),
# the OpenClaw agent must search the catalogue instead of listing the shelf.
_CATEGORY_FILLER_WORDS = {
    "a", "all", "an", "and", "any", "are", "at", "available", "be", "browse",
    "buy", "can", "categories", "category", "could", "do", "does", "for",
    "from", "get", "give", "have", "hello", "hey", "hi", "how", "i", "in",
    "is", "it", "items", "list", "looking", "me", "much", "my", "need",
    "of", "on", "or", "our", "please", "products", "range", "see", "sell",
    "show", "some", "stuff", "the", "there", "to", "want", "we", "what",
    "which", "with", "would", "you", "your",
}


def _is_pure_category_request(text: str) -> bool:
    """True only when the message's product words are all shelf words."""
    if not _named_categories(text):
        return False
    cleaned = " " + re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()) + " "
    for key in sorted(_CATEGORY_SEARCH_TERMS, key=len, reverse=True):
        cleaned = re.sub(rf"\b{re.escape(key)}\b", " ", cleaned)
    words = [word for word in re.findall(r"[a-z0-9]+", cleaned)
             if word not in _CATEGORY_FILLER_WORDS]
    return not words


def _category_browse_reply(db, store, text: str,
                           branch: Optional[str] = None) -> Optional[str]:
    """List the products in the shelf a message names, or None if it names none."""
    groups = _named_categories(text)
    if not groups:
        return None
    sections, total = [], 0
    for display, key in groups[:3]:
        products = _category_catalogue(db, store, key, branch, limit=15)
        if not products:
            continue
        total += len(products)
        lines = "\n".join(f"{i}. {p['name']} - {p['price']}"
                          for i, p in enumerate(products, 1))
        sections.append(f"*{display}*\n{lines}")
    if not sections:
        return None
    where = f" at our {branch} branch" if branch else ""
    if len(groups) == 1:
        label = groups[0][0].lower()
        # "Baby Products products" and "Body Lotions products" read badly.
        noun = "" if label.endswith("s") else " products"
        header = f"Here are the {label}{noun}{where}:"
    else:
        header = f"Here is what we have{where}:"
    return (header + "\n\n" + "\n\n".join(sections)
            + "\n\nReply with the numbers you want to add.")


def _category_catalogue(db, store, category_key: str, branch: Optional[str] = None,
                        limit: int = 15) -> List[Dict[str, str]]:
    """Products in one browse category, de-duplicated, everyday names first."""
    terms = _CATEGORY_SEARCH_TERMS.get(category_key, category_key).split(" OR ")
    items_per_term = max(3, limit // max(1, len(terms)))
    found, seen = [], set()
    for term in terms:
        for product in _search_products_by_keyword(db, store, term.strip(),
                                                   limit=items_per_term, branch=branch):
            name = product.get("name") or ""
            if not name or name in seen:
                continue
            seen.add(name)
            found.append(product)
    # Skincare means cosmetic care: hair products belong to haircare.
    if category_key in ("skincare", "skin care", "skin"):
        without_hair = [p for p in found if not _is_haircare(p)]
        found = without_hair or found
    # "Baby" shares the word "diaper" with the adult range. Adult diapers are
    # not baby products, so keep them out unless the shelf is genuinely empty.
    if category_key in ("baby", "baby products", "baby & kids", "baby and kids"):
        without_adult = [p for p in found
                         if "adult" not in (p.get("name") or "").lower()]
        found = without_adult or found
    return _rank_for_browsing(found)[:limit]


async def _execute_pharmacy_tool(db: Session, store, customer_phone: str, tool_name: str,
                                 args: dict, user_text: str = "") -> str:
    """Execute a pharmacy tool and return the result as a string."""
    store_id = str(store.id) if store else None
    # One line per tool call: which tool the model chose and with what. Needed to
    # tell "the model mis-called the tool" apart from "the tool mis-behaved".
    logger.info("Pharmacy tool %s(%s) for %s", tool_name,
                ", ".join(f"{k}={v!r}" for k, v in (args or {}).items()
                          if k not in ("store_id", "customer_phone")),
                customer_phone)

    if tool_name == "search_products":
        query = args.get("query", "")
        branch = _clean_branch(args.get("branch"))
        query_lower = query.lower().strip() if query else ""

        # Handle "yes" confirmation for category - extract category from the query itself
        # The AI should pass the category name when user confirms, not just "yes"
        # But as a fallback, map common confirmations to skip re-confirmation
        confirmation_words = ["yes", "yeah", "yep", "sure", "ok", "okay", "correct", "right", "show me", "show"]
        if query_lower in confirmation_words:
            # User is confirming but AI didn't extract the category - return helpful message
            return "FOUND: Please tell me which category you'd like to see: Skincare, Haircare, Oral Care, Cosmetics, Baby Products, Medications, or First Aid."

        # Handle generic browsing queries (no specific product)

        # Words that indicate a generic browsing request (not a specific product)
        generic_words = ["more", "else", "other", "anything", "everything", "something", "stuff", "options", "browse", "categories", "products", "items", "available"]

        # Branch names - if query is ONLY a branch name, treat as generic
        branch_names = ["angwa", "bulawayo", "gweru", "rezende"]
        is_only_branch_name = query_lower in branch_names

        # Specific product/brand names - if query contains these, it's NOT generic
        specific_products = ["nivea", "vaseline", "dove", "colgate", "palmers", "lotion", "cream",
                            "shampoo", "toothpaste", "soap", "lipstick", "mascara", "perfume",
                            "panadol", "tablet", "syrup", "vitamin", "sunscreen", "deodorant",
                            "foundation", "powder", "zaron", "aquafresh"]

        has_generic_word = any(word in query_lower for word in generic_words)
        has_specific_product = any(prod in query_lower for prod in specific_products)

        is_generic_query = (
            not query or
            len(query_lower) < 3 or
            is_only_branch_name or
            (has_generic_word and not has_specific_product)
        )

        logger.info("Search query='%s', has_generic=%s, has_specific=%s, is_generic=%s",
                   query_lower, has_generic_word, has_specific_product, is_generic_query)

        # Map category NAMES to search terms. Numbers are deliberately not keys:
        # a bare "1" (answering the branch question, a menu, a quantity) was
        # turned into "nivea OR vaseline OR dove OR lotion OR cream", so the bot
        # answered "We have NIVEA products available at all branches!" as if that
        # were the whole catalogue. An unrecognised number now falls through to
        # the generic "what are you looking for?" instead of inventing a category.
        category_mapping = _CATEGORY_SEARCH_TERMS

        # "personal care products" / "hair care items" name a category with a
        # filler word stuck on the end; drop it before matching, or the exact
        # category is missed and a spelling suggestion answers instead.
        category_query = re.sub(r"\b(products?|items?|stuff|range|category|categories)\b",
                                " ", query_lower)
        category_query = re.sub(r"\s+", " ", category_query).strip()

        # "hair care and oral care" names two shelves. Asked to confirm one and
        # the other was lost - the real transcript got "Did you mean *Chorle*?".
        # Only a pure shelf request may browse: "nivea body lotion" is a product
        # search, not a request to list every body lotion in the catalogue.
        pure_category = _is_pure_category_request(query)
        category_groups: List[tuple] = []
        if pure_category:
            for cat_name in sorted(category_mapping, key=len, reverse=True):
                if cat_name in category_query and len(cat_name) > 2:
                    display = _CATEGORY_DISPLAY.get(cat_name, cat_name.title())
                    if all(display != seen_display for seen_display, _ in category_groups):
                        category_groups.append((display, cat_name))
        if len(category_groups) >= 2:
            sections = []
            for display, key in category_groups[:3]:
                products = _category_catalogue(db, store, key, branch, limit=12)
                if not products:
                    continue
                lines = "\n".join(f"{i}. {p['name']} - {p['price']}"
                                  for i, p in enumerate(products, 1))
                sections.append(f"*{display}*\n{lines}")
            if sections:
                where = f" at {branch} branch" if branch else ""
                return (f"FOUND: Products in these categories{where}:\n\n"
                        + "\n\n".join(sections)
                        + "\n\nReply with the numbers you want to add.")

        # Check if query matches a category (exact match or category name in query)
        matched_category = None
        is_exact_match = False
        if pure_category:
            if category_query in category_mapping:
                matched_category = category_query
                is_exact_match = True
            else:
                # Check if any category name is contained in the query
                # Prioritize longer matches (e.g., "skin care" before "skin")
                for cat_name in sorted(category_mapping.keys(), key=len, reverse=True):
                    if cat_name in category_query and len(cat_name) > 2:
                        matched_category = cat_name
                        is_exact_match = False
                        break

        if matched_category:
            # For partial matches, ask for confirmation first
            if not is_exact_match:
                # Map category to friendly display name and exact search term
                category_info = {
                    "skin care": ("Skincare", "skincare"), "skincare": ("Skincare", "skincare"), "skin": ("Skincare", "skincare"),
                    "hair care": ("Haircare", "haircare"), "haircare": ("Haircare", "haircare"), "hair": ("Haircare", "haircare"),
                    "oral care": ("Oral Care", "oral care"), "oral": ("Oral Care", "oral care"), "toothpaste": ("Oral Care", "oral care"),
                    "cosmetics": ("Cosmetics", "cosmetics"), "makeup": ("Cosmetics", "cosmetics"),
                    "baby": ("Baby Products", "baby"), "baby products": ("Baby Products", "baby"),
                    "medications": ("Medications", "medications"), "medicine": ("Medications", "medications"), "meds": ("Medications", "medications"),
                    "first aid": ("First Aid", "first aid"), "firstaid": ("First Aid", "first aid"),
                }
                display_name, search_term = category_info.get(matched_category, (matched_category.title(), matched_category))
                branch_text = f" from {branch} branch" if branch else ""
                return f"CONFIRM_CATEGORY:{search_term}: Did you mean *{display_name}* products{branch_text}? If yes, I'll show you {display_name.lower()} products."

            # Search for actual products in that category - search ALL terms for variety
            search_terms = category_mapping[matched_category].split(" OR ")
            all_products = []
            # Search each term with a smaller limit to get variety
            items_per_term = max(3, 15 // len(search_terms))
            for term in search_terms:
                products = _search_products_by_keyword(db, store, term.strip(), limit=items_per_term, branch=branch)
                all_products.extend(products)

            # Remove duplicates while preserving variety
            seen = set()
            unique_products = []
            for p in all_products:
                if p['name'] not in seen:
                    seen.add(p['name'])
                    unique_products.append(p)

            # Skin care means cosmetic care: hair products belong to haircare,
            # and cosmetics lead so a browse never opens with a medicine.
            if matched_category in ("skincare", "skin care", "skin"):
                without_hair = [p for p in unique_products if not _is_haircare(p)]
                unique_products = without_hair or unique_products
            unique_products = _rank_for_browsing(unique_products)

            if unique_products:
                result = f"FOUND: Products in this category at {branch or 'all'} branch(es):\n"
                for i, p in enumerate(unique_products[:15], 1):
                    result += f"{i}. {p['name']} - {p['price']}\n"
                if len(unique_products) > 15:
                    result += f"\n...and {len(unique_products) - 15} more products."
                return result
            return f"NOT FOUND: No products in this category at {branch} branch."

        # "what creams do you have" / "any lotions" - browse by type. A plain
        # substring search would list medicated items alphabetically first, so
        # filter to the requested type and lead with cosmetics.
        type_word = _detect_product_type(query_lower)
        if type_word and branch:
            type_matches = [
                p for p in _search_products_by_keyword(db, store, type_word, limit=200, branch=branch)
                if type_word in (p.get("name") or "").lower()
            ]
            if type_word not in ("shampoo", "conditioner"):
                skin_only = [p for p in type_matches if not _is_haircare(p)]
                type_matches = skin_only or type_matches
            seen_types = set()
            unique_types = []
            for p in type_matches:
                if p["name"] not in seen_types:
                    seen_types.add(p["name"])
                    unique_types.append(p)
            type_matches = unique_types
            if type_matches:
                ranked = _rank_for_browsing(type_matches)
                result = f"FOUND: {type_word.title()} products at {branch} branch (everyday brands first):\n"
                for i, p in enumerate(ranked[:15], 1):
                    result += f"{i}. {p['name']} - {p['price']}\n"
                if len(ranked) > 15:
                    result += f"\n...and {len(ranked) - 15} more {type_word} products."
                return result

        if is_generic_query:
            return _catalogue_categories_reply(db, store, branch)

        # Check if customer already has a branch selected (from cart items)
        state = _get_order_state(db, store_id, customer_phone)
        if state:
            cart_items = state.get("cart_items", [])
            if cart_items and not branch:
                # Customer has items in cart - use their existing branch
                existing_branch = cart_items[0].get("branch") or state.get("selected_branch")
                if existing_branch:
                    branch = existing_branch
                    logger.info("Auto-selecting branch '%s' based on existing cart", branch)

        if branch:
            # Spelling-tolerant search: exact hit, else a "did you mean"
            # suggestion (typos, missing characters, "4" vs "for", ...)
            smart = _search_products_smart(db, store, query, limit=20, branch=branch)
            products = smart["products"]
            if products:
                result = f"FOUND: Products matching '{query}' at {branch} branch:\n"
                for i, p in enumerate(products[:15], 1):
                    result += f"{i}. {p['name']} - {p['price']}\n"
                if len(products) > 15:
                    result += f"\n...and {len(products) - 15} more products available."
                return result
            if smart["did_you_mean"]:
                return _format_did_you_mean(smart, query, branch)
            return f"NOT FOUND: No products matching '{query}' in the online catalogue for {branch}. Ask the team to confirm availability at that branch; do not say it is out of stock solely because it is missing from the catalogue."
        else:
            # Search all branches and collect which ones have the product
            branches = _store_branches(db, store_id)
            branches_with_stock = {}
            for b in branches:
                products = _search_products_by_keyword(db, store, query, limit=20, branch=b)
                if not products:
                    products = _search_products_by_tokens(db, store, query, limit=20,
                                                          branch=b)
                if products:
                    branches_with_stock[b] = products

            if not branches_with_stock:
                # Nothing matched exactly anywhere - try spelling suggestions
                smart = _search_products_smart(db, store, query, limit=20)
                if smart["did_you_mean"]:
                    return _format_did_you_mean(smart, query)

            if branches_with_stock:
                if len(branches_with_stock) == 1:
                    # Only one branch has it - show products directly
                    branch_name = list(branches_with_stock.keys())[0]
                    products = branches_with_stock[branch_name]
                    result = f"FOUND: Products matching '{query}' (only available at {branch_name} branch):\n"
                    for i, p in enumerate(products[:15], 1):
                        result += f"{i}. {p['name']} - {p['price']}\n"
                    if len(products) > 15:
                        result += f"\n...and {len(products) - 15} more products available."
                    return result
                else:
                    # Multiple branches have it - list the branches with stock
                    result = f"FOUND: '{query}' is available at these branches:\n"
                    for i, (branch_name, products) in enumerate(branches_with_stock.items(), 1):
                        result += f"{i}. {branch_name} ({len(products)} products)\n"
                    result += "\nAsk the customer which branch they want to see prices for."
                    return result
            return f"NOT FOUND: No products matching '{query}' found in any branch. Tell the customer we don't currently have this item in stock and offer to help with something else."

    elif tool_name == "add_to_cart":
        product_name = args.get("product_name")
        price = args.get("price", 0)
        quantity = args.get("quantity", 1)
        # "all" is not a branch. The model says branch='all' whenever the search
        # covered every branch, and the branch check below then rejected the add
        # ("Cannot add products from all branch"), so two real NIVEA lotions the
        # customer picked were refused.
        branch = _clean_branch(args.get("branch"))

        if not product_name:
            return "Could not add to cart: no product name given. Search for the product first and use the EXACT name from the results."

        # The model sometimes passes a whole sentence as the product name
        # ("from Angwa branch to your cart along with nivea cream"), which then
        # becomes a bogus cart line and hides the product that was asked for.
        if len(product_name.split()) > 10 or any(
                marker in product_name.lower()
                for marker in ("along with", "to your cart", "your cart", "?", "\n")):
            return ("Could not add: that is not a product name. Search for the product "
                    "and call add_to_cart with the EXACT name from the results.")
        try:
            quantity = max(1, int(quantity or 1))
        except (TypeError, ValueError):
            quantity = 1
        if user_text and _ONE_EXTRA.search(user_text) and quantity > 1:
            logger.info("Clamping %r to one extra unit (model asked for %s)",
                        user_text, quantity)
            quantity = 1
        # Prices are always rounded to the nearest whole number
        price = round_price(price)
        if price <= 0:
            return (f"Could not add '{product_name}': the price is missing. "
                    f"Search for the product first and use the EXACT price from the results.")

        # Get or create order state
        state = _get_order_state(db, store_id, customer_phone)
        cart_items = state.get("cart_items", []) if state else []

        # Resolve the branch BEFORE reading the price. A stale or invented
        # branch used to make the catalogue lookup fail, so the model told a
        # customer an item was out of stock even though it was stocked at the
        # branch their cart was already using.
        existing_branch = ((cart_items[0].get("branch") if cart_items else None)
                           or (state or {}).get("selected_branch"))
        if branch and existing_branch and branch.lower() != existing_branch.lower():
            return (f"Cannot add products from {branch} branch. Your cart is already "
                    f"set to {existing_branch} branch. STOP adding the rest of this "
                    f"list. Tell the customer their cart is at {existing_branch}, and "
                    f"ask whether to add the items there or clear the cart before "
                    f"switching to {branch}.")
        if not branch:
            branch = existing_branch
        if not branch:
            branches = _store_branches(db, store_id)
            if len(branches) > 1:
                return ("BRANCH_REQUIRED: Ask the customer which branch they want "
                        "before adding anything. Available branches: "
                        + ", ".join(branches)
                        + ". Do not guess a branch and do not add until they answer.")
            if len(branches) == 1:
                branch = branches[0]
            else:
                branch = _branch_for_product(db, store_id, product_name)

        # Never let the model invent a price: if the catalogue knows this
        # product, its price wins (this is how "Benylin ... $6" got in).
        real_price = _catalogue_price(db, store_id, product_name, branch=branch)
        if real_price is None:
            available_branch = _branch_for_product(db, store_id, product_name)
            if available_branch and branch and available_branch.lower() != branch.lower():
                return (f"NOT AT {branch}: '{product_name}' is not stocked at "
                        f"{branch}. It is available at {available_branch}. Ask the "
                        f"customer whether to add it from {available_branch} or "
                        f"choose another branch or product. Do not say it is out "
                        f"of stock in the whole store.")
            # The store sells only what its catalogue holds. Without this the
            # model could add an invented product ("Panado Syrup") at an
            # invented price just because the customer named it.
            return (f"Could not add '{product_name}': it is not in this store's catalogue. "
                    f"Search for the product first and use the EXACT name and price from "
                    f"the results. Never invent a product or a price.")
        if round_price(real_price) != price:
            logger.warning("Correcting invented price for %r: model=%s catalogue=%s",
                           product_name, price, round_price(real_price))
            price = round_price(real_price)

        # Repeated confirmations are idempotent unless another unit was requested.
        for item in cart_items:
            if (item.get("product_name") or "").strip().lower() == product_name.strip().lower():
                if not user_text or not (_ONE_EXTRA.search(user_text) or _requested_quantity(user_text) > 1):
                    return (f"{product_name} is already in your cart (quantity {item.get('quantity', 1)}). "
                            "Would you like to proceed to checkout?")

        # Same product added again -> grow the quantity instead of a second line
        merged = False
        for item in cart_items:
            if (item.get("product_name") or "").strip().lower() == product_name.strip().lower():
                item["quantity"] = int(item.get("quantity", 1) or 1) + quantity
                item["price"] = price
                merged = True
                break
        if not merged:
            cart_items.append({
                "product_name": product_name,
                "price": price,
                "quantity": quantity,
                "branch": branch
            })

        _update_order_state(db, store_id, customer_phone,
                           cart_items=cart_items,
                           current_state="awaiting_checkout",
                           selected_branch=branch)

        subtotal = cart_subtotal(cart_items)
        item_count = sum(int(i.get("quantity", 1) or 1) for i in cart_items)
        return (f"Added {quantity}x {product_name} at {format_price(price)} each.\n"
                f"Cart: {len(cart_items)} item(s) ({item_count} total) - "
                f"Subtotal {format_price(subtotal)}.\n\nWould you like to proceed to checkout?")

    elif tool_name == "update_cart":
        product_name = (args.get("product_name") or "").strip()
        new_name = (args.get("new_product_name") or "").strip()
        state = _get_order_state(db, store_id, customer_phone) or {}
        items = list(state.get("cart_items") or [])
        if not items:
            return "The cart is empty - there is nothing to edit. Add the product first."
        if not product_name:
            return ("Could not edit: no product name given. The cart has: "
                    + ", ".join(i.get("product_name", "?") for i in items)
                    + ". Ask which of those they mean.")
        try:
            quantity = int(args.get("quantity"))
        except (TypeError, ValueError):
            return ("Could not edit: quantity must be a whole number. Ask the customer "
                    "how many they want and call update_cart again.")
        if quantity < 0:
            return ("Could not edit: quantity cannot be negative. Ask the customer how "
                    "many they want.")
        needle = product_name.lower()
        matches = [i for i in items
                   if needle in (i.get("product_name") or "").lower()
                   or (i.get("product_name") or "").lower() in needle]
        if not matches:
            return (f"Could not edit '{product_name}': it is not in the cart. The cart has: "
                    + ", ".join(i.get("product_name", "?") for i in items)
                    + ". Use the name of an item that is in the cart.")
        target = matches[0]
        old_qty = int(target.get("quantity", 1) or 1)
        if quantity == 0:
            # "make it 0" / "I don't want it any more" is a removal, not an
            # error - refusing it made the model claim a change that never
            # happened (it answered "removed" over an unchanged cart).
            items = [i for i in items if i is not target]
            _update_order_state(db, store_id, customer_phone, cart_items=items)
            remaining = (", ".join(f"{i['product_name']} x{int(i.get('quantity', 1) or 1)}"
                                   for i in items) or "empty")
            return (f"Removed {target.get('product_name')} (quantity set to 0). "
                    f"Cart now: {remaining}.")
        if new_name:
            # Same branch as the line being changed - prices differ by branch.
            real_price = _catalogue_price(db, store_id, new_name,
                                          branch=target.get("branch"))
            if real_price is None:
                return (f"Could not change '{target.get('product_name')}' to '{new_name}': "
                        "that product is not in the catalogue. Search for it first and use "
                        "the EXACT name from the results, or leave the item as it is.")
            target["product_name"] = new_name
            target["price"] = round_price(real_price)
        target["quantity"] = quantity
        _update_order_state(db, store_id, customer_phone, cart_items=items)
        return (f"Cart updated: {target.get('product_name')} is now x{quantity} "
                f"(was x{old_qty}) at {format_price(target.get('price', 0))} each.\n"
                + _format_cart_summary(items))

    elif tool_name == "get_order_status":
        wanted = (args.get("order_number") or "").strip()
        orders = _get_order_history(db, store_id, customer_phone, limit=5)
        if not orders:
            return ("No orders found for this customer. Do NOT invent an order number - "
                    "say you cannot find one and ask whether it was placed with a "
                    "different phone number.")
        if wanted:
            exact = [o for o in orders
                     if (o.get("order_number") or "").lower() == wanted.lower()]
            if not exact:
                recent = ", ".join(o.get("order_number", "?") for o in orders[:3])
                return (f"No order '{wanted}' for this customer. Their recent orders are: "
                        f"{recent}.")
            orders = exact
        lines = []
        for o in orders:
            lines.append(
                f"{o.get('order_number')} - {str(o.get('status') or 'unknown').title()} - "
                f"{format_price(o.get('total_amount') or 0)} - "
                f"{(o.get('payment_provider') or o.get('payment_method') or 'n/a')} - "
                f"{o.get('created_at') or ''}")
        return "Orders (newest first):\n" + "\n".join(l.strip(" -") for l in lines)

    elif tool_name == "list_branches":
        branches = _listed_store_branches(db, store)
        if not branches:
            return ("No branch list is configured for this store. Do not guess branch "
                    "names - offer to check with the team.")
        catalogue = _store_branches(db, store_id)
        return ("Branches: " + ", ".join(branches) + ". Catalogue available for: "
                + (", ".join(catalogue) or "none")
                + ". For other branches, ask the team to check stock and pricing; do not guess.")

    elif tool_name == "view_cart":
        state = _get_order_state(db, store_id, customer_phone)
        cart_items = state.get("cart_items", []) if state else []
        if not cart_items:
            return "Your cart is empty."
        return _format_cart_summary(cart_items)

    elif tool_name == "remove_from_cart":
        product_name = (args.get("product_name") or "").strip()
        state = _get_order_state(db, store_id, customer_phone) or {}
        items = list(state.get("cart_items") or [])
        if not items:
            return "The cart is already empty - there is nothing to remove."

        if product_name.lower() in ("all", "everything", "*", ""):
            _update_order_state(db, store_id, customer_phone, cart_items=[])
            return "Cleared the cart. Tell me what you would like to add instead."

        needle = product_name.lower()
        matches = [i for i in items
                   if needle in (i.get("product_name") or "").lower()
                   or (i.get("product_name") or "").lower() in needle]
        if not matches:
            have = ", ".join(i.get("product_name", "?") for i in items)
            return (f"Could not remove '{product_name}': it is not in the cart. "
                    f"The cart has: {have}. Remove one of those, or say 'clear cart'.")

        target = matches[0]
        removed_all = True
        try:
            wanted = int(args.get("quantity")) if args.get("quantity") else None
        except (TypeError, ValueError):
            wanted = None
        # "remove one" means one UNIT, not the line: the model left quantity
        # out and cleared a 2-unit line while telling the customer it removed
        # one. The customer's own wording decides when the model is silent.
        if wanted is None and user_text and re.search(
                r"\b(remove|delete|drop|take out|take off)\s+(one|1)\b", user_text, re.I):
            wanted = 1
        current_qty = int(target.get("quantity", 1) or 1)
        if wanted and 0 < wanted < current_qty:
            target["quantity"] = current_qty - wanted
            removed_all = False

        if removed_all:
            items = [i for i in items if i is not target]
        _update_order_state(db, store_id, customer_phone, cart_items=items)

        if items:
            remaining = ", ".join(
                f"{i['product_name']} x{int(i.get('quantity', 1) or 1)}" for i in items)
        else:
            remaining = "empty"
        removed_qty = current_qty - int(target.get("quantity", 1) or 1) if not removed_all else current_qty
        removed_text = (f"Removed {removed_qty} x *{target.get('product_name')}*." if removed_qty < current_qty
                        else f"Removed the whole line (*{target.get('product_name')}* x{current_qty}).")
        return (f"{removed_text} "
                f"Cart now: {remaining}.")

    elif tool_name == "set_branch":
        chosen = (args.get("branch") or "").strip()
        if not chosen:
            return "Please choose a branch."
        branches = _listed_store_branches(db, store)
        match = next((b for b in branches if b.lower() == chosen.lower()), None)
        if not match:
            # Let the model recover from a partial answer ("angwa" for "Angwa Branch").
            match = next((b for b in branches if chosen.lower() in b.lower()
                          or b.lower() in chosen.lower()), None)
        if not match:
            available = ", ".join(branches) or "none configured"
            return (f"Unknown branch *{chosen}*. Available branches: {available}. "
                    "Ask the customer to choose one of these.")
        _update_order_state(db, store_id, customer_phone, selected_branch=match)
        return f"Branch set to *{match}*. What can I help you with today?"

    elif tool_name == "set_collection_method":
        raw_method = str(args.get("method") or "").strip().lower()
        if raw_method in ("walk_in", "walkin", "walk-in", "pickup", "pick_up",
                          "collect", "collection"):
            method = "walkin"
        elif raw_method in ("delivery", "deliver", "delivered"):
            method = "delivery"
        else:
            return ("Unknown collection method. Ask the customer to choose walk-in "
                    "collection or delivery.")
        state = _get_order_state(db, store_id, customer_phone)
        cart_items = state.get("cart_items", []) if state else []
        subtotal = cart_subtotal(cart_items)

        if method == "delivery" and subtotal < 10:
            return f"Delivery requires a minimum order of {format_price(10)}. Your current subtotal is {format_price(subtotal)}. Please add more items or choose walk-in collection."

        _update_order_state(db, store_id, customer_phone, collection_method=method)
        return await _resume_checkout(db, store, customer_phone, user_text)

    elif tool_name == "set_delivery_details":
        state = _get_order_state(db, store_id, customer_phone) or {}
        if not state.get("cart_items"):
            return ("Your cart is empty, so there are no delivery details to save "
                    "yet. Add the items to the cart first.")
        # The model sometimes passes "Name, 0716522473" as one field. Pull the
        # number out first so a combined answer saves both details in one turn.
        raw_name = (args.get("customer_name") or "").strip()
        customer_name, name_phone = _strip_phone_from_text(raw_name)
        phone_raw = args.get("phone") or name_phone
        phone_clean, phone_error = normalize_phone(phone_raw)
        if not phone_clean:
            # The phone may have arrived inside the address instead.
            raw_address = str(args.get("address") or "").strip()
            address_without_phone, address_phone = _strip_phone_from_text(raw_address)
            if address_phone:
                phone_clean = address_phone
                args = {**args, "address": address_without_phone}
        partial = {}
        if len(customer_name) >= 2 and not re.search(r"\d", customer_name):
            partial["customer_name"] = customer_name
        address = (args.get("address") or "").strip()
        if looks_like_address(address):
            partial["customer_address"] = address
        if phone_clean:
            partial["customer_phone_delivery"] = phone_clean
        if partial:
            _update_order_state(db, store_id, customer_phone, **partial)
        state = _get_order_state(db, store_id, customer_phone) or {}
        customer_name = partial.get("customer_name") or state.get("customer_name") or ""
        phone_clean = phone_clean or state.get("customer_phone_delivery")
        args = {**args, "address": partial.get("customer_address") or state.get("customer_address") or ""}
        if not phone_clean:
            return ("DELIVERY DETAILS INCOMPLETE: the phone number is not valid.\n"
                    f"{phone_error}\n"
                    "Ask the customer for their 10-digit phone number and call "
                    "set_delivery_details again with name, corrected phone and address.")
        if len(customer_name) < 2 or re.search(r"\d", customer_name):
            return ("DELIVERY DETAILS INCOMPLETE: the customer name is missing. "
                    "Ask for their full name and call set_delivery_details again.")

        address = (args.get("address") or "").strip()
        if not looks_like_address(address):
            return ("DELIVERY DETAILS INCOMPLETE: the delivery address is missing or is not "
                    "a real address. Ask the customer for the street, area/suburb and city "
                    "(e.g. 670 Ushewekunze, Harare), then call set_delivery_details again.")
        _update_order_state(db, store_id, customer_phone,
                           customer_name=customer_name,
                           customer_phone_delivery=phone_clean,
                           customer_address=address,
                           current_state="payment")
        return await _resume_checkout(db, store, customer_phone, user_text)

    elif tool_name == "set_payment_method":
        raw_method = str(args.get("method") or "").strip().lower()
        mobile_number = args.get("mobile_number")

        payment_provider = None
        if raw_method in ["ecocash", "eco cash", "onemoney", "one money",
                          "innbucks", "inn bucks"]:
            method = raw_method.replace(" ", "")
            payment_provider = method
            method = "mobile_money"
            # Just naming the wallet ("EcoCash") is enough - reuse the number
            # already collected for delivery instead of dead-ending on a
            # missing mobile_number.
            if not mobile_number:
                existing = _get_order_state(db, store_id, customer_phone) or {}
                mobile_number = (existing.get("payment_phone")
                                 or existing.get("customer_phone_delivery"))
            # Mobile money needs a valid 10-digit number to send the prompt to
            phone_clean, phone_error = normalize_phone(mobile_number)
            if not phone_clean:
                return (f"To pay with {payment_provider.title()}, please send the "
                        f"*10-digit mobile money number* (e.g. 0771234567).\n"
                        f"{phone_error}")
            mobile_number = phone_clean
        elif raw_method in ["cash", "cod", "cash on delivery",
                            "pay on collection", "pay on delivery"]:
            method = "cash"
        else:
            return ("Please choose a payment method: Cash, EcoCash, OneMoney or InnBucks.")

        _update_order_state(db, store_id, customer_phone,
                           payment_method=method,
                           payment_provider=payment_provider,
                           payment_phone=mobile_number,
                           current_state="confirm")

        # Payment may arrive before delivery details; collect missing fields first.
        saved = _get_order_state(db, store_id, customer_phone) or {}
        if saved.get("collection_method") == "delivery" and _delivery_next_state(saved) != "payment":
            return await _resume_checkout(db, store, customer_phone, user_text)

        # Show order summary (all prices rounded to whole numbers)
        state = _get_order_state(db, store_id, customer_phone)
        cart_items = state.get("cart_items", []) if state else []
        subtotal = cart_subtotal(cart_items)
        delivery_fee = 0  # Free delivery for now
        total = subtotal + delivery_fee

        summary = "*ORDER SUMMARY*\n\n"
        for item in cart_items:
            qty = int(item.get("quantity", 1) or 1)
            line_total = round_price(item.get("price", 0)) * qty
            summary += f"- {item['product_name']}: {format_price(item.get('price', 0))} x {qty} = {format_price(line_total)}\n"
        summary += f"\nSubtotal: {format_price(subtotal)}\n"
        summary += f"Delivery: {'FREE' if delivery_fee == 0 else format_price(delivery_fee)}\n"
        summary += f"*TOTAL: {format_price(total)}*\n\n"
        # A stored NULL defeats the "delivery" default: .get(key, default) only
        # applies when the key is missing, and this crashed the whole turn (the
        # customer saw "temporary problem" right after giving their EcoCash
        # number) even though the tool had already saved it.
        collection_label = (state.get('collection_method') or 'delivery').replace('_', ' ').title()
        summary += f"Collection: {collection_label}\n"
        summary += f"Payment: {(payment_provider or method).title()}\n\n"
        summary += "Reply YES to confirm your order."

        return summary

    elif tool_name == "confirm_order":
        state = _get_order_state(db, store_id, customer_phone)
        if not state or not state.get("cart_items"):
            return "No items in cart to order. Please add items first."

        # Validate that all required steps have been completed
        if not state.get("collection_method"):
            return "Collection method not set. Please ask the customer how they want to collect their order (walk-in or delivery) before confirming."

        if not state.get("payment_method") and not state.get("payment_provider"):
            return "Payment method not set. Please ask the customer how they want to pay before confirming the order."

        # A delivery order without a usable address cannot be dispatched, so it
        # must never be confirmed (this used to be silently allowed).
        if (state.get("collection_method") or "delivery") == "delivery":
            if not (state.get("customer_name") or "").strip():
                return "DELIVERY NAME MISSING: ask for the customer's full name before confirming."
            delivery_phone, _ = normalize_phone(state.get("customer_phone_delivery"))
            if not delivery_phone:
                return "DELIVERY PHONE MISSING: ask for the customer's 10-digit delivery phone number before confirming."
            address = (state.get("customer_address") or "").strip()
            if not address:
                return ("DELIVERY ADDRESS MISSING: ask the customer for their delivery "
                        "address (street, area/suburb and city) before confirming the order.")
            if not looks_like_address(address):
                return (f"DELIVERY ADDRESS INVALID: *{address}* is not a usable delivery address. "
                        "Ask the customer for the street, area/suburb and city, then try again.")

        cart_items = state.get("cart_items", [])
        subtotal = cart_subtotal(cart_items)
        delivery_fee = 0
        total = subtotal + delivery_fee

        # A mobile-money order must have a number to send the PayNow prompt to
        # BEFORE the order is created. set_payment_method normally saves it, but
        # an old/stale state must not produce an unpaid order that can never be
        # prompted (the "EcoCash but no OTP" failure).
        mobile_provider = (state.get("payment_provider") or "").strip().lower()
        is_mobile_money = bool(mobile_provider) or state.get("payment_method") == "mobile_money"
        payment_phone = None
        if is_mobile_money:
            payment_phone, phone_error = normalize_phone(
                state.get("payment_phone")
                or state.get("customer_phone_delivery")
                or customer_phone
            )
            if not payment_phone:
                return (f"PAYMENT NUMBER MISSING: the customer chose "
                        f"{mobile_provider.title() or 'mobile money'}, but there is no "
                        f"valid 10-digit mobile money number on file. Ask for the number "
                        f"(e.g. 0771234567), save it with set_payment_method, then confirm "
                        f"the order again.\n{phone_error}")

        order_data = {
            "customer_name": state.get("customer_name"),
            "customer_address": state.get("customer_address"),
            "delivery_phone": state.get("customer_phone_delivery"),
            "branch": (state.get("branch")
                       or (cart_items[0].get("branch") if cart_items else None)
                       or (_store_branches(db, store_id) or [None])[0]),
            "items": cart_items,
            "subtotal": subtotal,
            "delivery_fee": delivery_fee,
            "total_amount": total,
            "collection_method": state.get("collection_method") or "delivery",
            "payment_method": "cod" if state.get("payment_method") == "cash" else "mobile_money",
            "payment_provider": state.get("payment_provider")
        }

        order_number = _create_order(db, store_id, customer_phone, order_data)

        if order_number:
            payment_label = (mobile_provider.title() if is_mobile_money
                             else "Cash")
            result = ("*ORDER PLACED — PAYMENT PENDING*\n\n" if is_mobile_money
                      else "*ORDER CONFIRMED!*\n\n")
            result += f"Order #: {order_number}\n"
            result += f"Total: {format_price(total)}\n"
            result += f"Payment: {payment_label}\n"

            if is_mobile_money:
                # Creating the order is not payment: send the actual PayNow
                # mobile prompt to the customer's wallet and tell them what to
                # approve. Without this the order sat unpaid with no OTP.
                payment = _initiate_mobile_payment(db, order_number, payment_phone)
                provider_label = mobile_provider.title() or "Mobile money"
                if payment and payment.get("success"):
                    instructions = (payment.get("instructions")
                                    or "Check your phone for the payment prompt.")
                    result += (f"\n*{provider_label} payment request sent*\n"
                               f"Amount: {format_price(total)}\n"
                               f"Number: {payment_phone}\n\n"
                               f"{instructions}\n\n"
                               f"Approve the prompt on your phone. Your payment is "
                               f"still pending until the provider confirms it.\n")
                elif payment and payment.get("dry_run"):
                    result += f"\n{payment.get('instructions', 'DRY RUN - no prompt sent.')}\n"
                else:
                    error = (payment or {}).get("error") if payment else None
                    result += (f"\n*PAYMENT NOT SENT*\n"
                               f"The order is saved, but the {provider_label} payment "
                               f"request could not be started"
                               + (f": {error}" if error else ".")
                               + "\nPlease reply *PAY* to try again or choose Cash.\n")

            result += f"\nThank you for shopping with {store.store_name}!"
            return result
        else:
            return "Sorry, there was an error placing your order. Please try again."

    elif tool_name == "show_delivery_details":
        state = _get_order_state(db, store_id, customer_phone)
        if not state:
            return "No delivery details on file yet."
        name = state.get("customer_name") or "Not provided"
        phone = state.get("customer_phone_delivery") or "Not provided"
        address = state.get("customer_address") or "Not provided"
        return (
            f"*Your delivery details:*\n"
            f"• Name: {name}\n"
            f"• Phone: {phone}\n"
            f"• Address: {address}\n\n"
            "You can update any of these by telling me the new value."
        )

    elif tool_name == "update_delivery_name":
        state = _get_order_state(db, store_id, customer_phone) or {}
        if not state.get("cart_items"):
            return ("Your cart is empty, so there are no delivery details to save "
                    "yet. Add the items to the cart first.")
        raw = (args.get("name") or "").strip()
        # Understand "my name is X", "change my name to X" and "call me X",
        # then split a phone number typed in the same message.
        candidate = extract_name_correction(raw) or raw
        name, phone_clean = _strip_phone_from_text(candidate)
        if not looks_like_person_name(name):
            return ("Please provide the customer's name - just their name, not a "
                    "sentence or a product.")
        updates = {"customer_name": name}
        if phone_clean:
            updates["customer_phone_delivery"] = phone_clean
            updates["payment_phone"] = phone_clean
        if (state.get("current_state") or "") in (
                "delivery_step_name", "delivery_step_phone", "delivery_step_address"):
            updates["current_state"] = _delivery_next_state(
                state, name=name, phone=phone_clean or state.get("customer_phone_delivery"))
        _update_order_state(db, store_id, customer_phone, **updates)
        saved = f"Name updated to *{name}*."
        if phone_clean:
            saved += f" Phone saved as *{phone_clean}*."
        next_state = updates.get("current_state")
        if next_state == "delivery_step_phone":
            saved += " Now ask for the customer's phone number."
        elif next_state == "delivery_step_address":
            saved += (" Now ask for the delivery address (street, suburb and city, "
                      "e.g. 670 Ushewekunze Street, Mabelreign, Harare).")
        elif next_state == "payment":
            saved += " Now ask which payment method they want."
        return saved

    elif tool_name == "update_delivery_phone":
        state = _get_order_state(db, store_id, customer_phone) or {}
        if not state.get("cart_items"):
            return ("Your cart is empty, so there are no delivery details to save "
                    "yet. Add the items to the cart first.")
        raw = str(args.get("phone") or "").strip()
        _, extracted = _strip_phone_from_text(raw)
        phone_clean, phone_error = normalize_phone(extracted or raw)
        if not phone_clean:
            return phone_error_message(raw, state.get("customer_phone_delivery"))
        updates = {"customer_phone_delivery": phone_clean,
                   "payment_phone": phone_clean}
        if (state.get("current_state") or "") in (
                "delivery_step_name", "delivery_step_phone", "delivery_step_address"):
            updates["current_state"] = _delivery_next_state(state, phone=phone_clean)
        _update_order_state(db, store_id, customer_phone, **updates)
        saved = f"Phone updated to *{phone_clean}*."
        if updates.get("current_state") == "delivery_step_name":
            saved += " Now ask for the customer's name."
        elif updates.get("current_state") == "delivery_step_address":
            saved += (" Now ask for the delivery address (street, suburb and city, "
                      "e.g. 670 Ushewekunze Street, Mabelreign, Harare).")
        elif updates.get("current_state") == "payment":
            saved += " Now ask which payment method they want."
        return saved

    elif tool_name == "update_delivery_address":
        state = _get_order_state(db, store_id, customer_phone) or {}
        raw = str(args.get("address") or "").strip()
        address = re.sub(r"^(?:actually|sorry|ok|okay|no)[\s,]+", "", raw, flags=re.I)
        address = re.sub(r"^(?:my\s+(?:delivery\s+)?address\s+is|it'?s)\s+", "",
                         address, flags=re.I).strip(" .,;:-")
        if len(address) < 5:
            return "Please provide a valid address including street, area and city (e.g. '670 Ushewekunze Street, Mabelreign, Harare')."
        # Validate address has required components
        if not looks_like_address(address):
            return (f"The address *{address}* seems incomplete. "
                    "Please include: house number/name, street, suburb/area, and city. "
                    "Example: '670 Ushewekunze Street, Mabelreign, Harare'")
        if not state.get("cart_items"):
            from sqlalchemy import text as sql_text
            try:
                rows = db.execute(sql_text("""
                    SELECT id, order_number FROM whatsapp_orders
                    WHERE store_id = CAST(:store_id AS uuid)
                      AND regexp_replace(customer_phone, '[^0-9]', '', 'g') = :phone
                      AND collection_method = 'delivery' AND status = 'pending'
                    ORDER BY created_at DESC LIMIT 2 FOR UPDATE
                """), {"store_id": store_id, "phone": _normalize_state_phone(customer_phone)}).fetchall()
                if not rows:
                    return "I couldn't find a pending delivery order to update. Please share your order number so our team can help."
                if len(rows) > 1:
                    return "You have more than one pending delivery. Please contact the store with the order number to update its address."
                row = rows[0]
                delivery_status = db.execute(sql_text("SELECT status FROM deliveries WHERE store_id = CAST(:store_id AS uuid) AND tracking_number = :number FOR UPDATE"),
                                             {"store_id": store_id, "number": row[1]}).scalar()
                if delivery_status and str(delivery_status).lower() != "pending":
                    return f"Order *{row[1]}* is already being handled. Please contact the store to change the delivery address."
                db.execute(sql_text("UPDATE whatsapp_orders SET customer_address = :address WHERE id = :id"),
                           {"address": address, "id": row[0]})
                db.execute(sql_text("UPDATE deliveries SET delivery_address = :address, updated_at = NOW() WHERE store_id = CAST(:store_id AS uuid) AND tracking_number = :number AND status = 'PENDING'"),
                           {"address": address, "store_id": store_id, "number": row[1]})
                db.commit()
                return f"I've updated the delivery address for order *{row[1]}* to *{address}*."
            except Exception:
                db.rollback()
                logger.exception("Could not update confirmed delivery address")
                return "I couldn't update the delivery address just now. Please contact the store with your order number."
        updates = {"customer_address": address}
        current = (state.get("current_state") or "")
        if current in ("delivery_step_name", "delivery_step_phone", "delivery_step_address"):
            updates["current_state"] = _delivery_next_state(state, address=address)
        _update_order_state(db, store_id, customer_phone, **updates)
        saved = f"Address updated to *{address}*."
        if updates.get("current_state") == "delivery_step_name":
            saved += " Now ask for the customer's name."
        elif updates.get("current_state") == "delivery_step_phone":
            saved += " Now ask for the customer's phone number."
        elif updates.get("current_state") == "payment":
            saved += " Now ask which payment method they want."
        return saved

    elif tool_name == "go_back_to_cart":
        _update_order_state(db, store_id, customer_phone, current_state="cart")
        state = _get_order_state(db, store_id, customer_phone)
        cart_items = state.get("cart_items", []) if state else []
        if cart_items:
            cart_text = "*Your Cart:*\n"
            for item in cart_items:
                qty = int(item.get("quantity", 1) or 1)
                cart_text += f"• {item['product_name']} x{qty} - {format_price(round_price(item['price']) * qty)}\n"
            cart_text += f"\n*Subtotal:* {format_price(cart_subtotal(cart_items))}\n\n"
            cart_text += "What else would you like to add? Say *checkout* when ready."
            return cart_text
        return "Your cart is empty. What would you like to order?"

    elif tool_name == "start_checkout":
        state = _get_order_state(db, store_id, customer_phone)
        cart_items = state.get("cart_items", []) if state else []
        if not cart_items:
            return "Your cart is empty. Please add items before checking out."
        if state.get("collection_method"):
            return await _resume_checkout(db, store, customer_phone, user_text)
        _update_order_state(db, store_id, customer_phone,
                            current_state="awaiting_collection")
        subtotal = cart_subtotal(cart_items)
        return (
            f"*Cart Total:* {format_price(subtotal)}\n\n"
            "How would you like to collect your order?\n"
            "1. *Walk-in* - Pick up from our branch\n"
            "2. *Delivery* - We deliver to you\n\n"
            "Reply with 1 or 2."
        )

    return "Tool not found."

# ============== END PHARMACY BOT TOOLS ==============


_PRODUCT_STOCK_COLUMNS = ("status, available, on_hand, sell_when_out_of_stock, "
                           "inventory_tracked")


def _availability_from_product_row(row) -> str:
    """Availability of a products-table row.

    Same rule the Meta catalogue sync uses in this file:
        available = available or on_hand; in stock when that is > 0, or when the
        store sells items that are out of stock; anything not "Active" is out.
    One deliberate difference: when inventory is NOT tracked we cannot judge, so
    the product is treated as in stock rather than hidden.
    """
    if not row:
        return "unknown"
    status, available, on_hand, sell_when_out_of_stock, inventory_tracked = list(row)[:5]
    if status and str(status).lower() != "active":
        return OUT_OF_STOCK
    if sell_when_out_of_stock:
        return "in_stock"
    # Drivers disagree on the type (psycopg2 -> bool, sqlite3 -> 0/1), so compare
    # the value as text rather than with `is False`.
    if inventory_tracked is not None and str(inventory_tracked).strip().lower() in ("false", "0", "f", "no"):
        return "in_stock"
    try:
        stock_qty = int((available if available else on_hand) or 0)
    except (TypeError, ValueError):
        stock_qty = 0
    return "in_stock" if stock_qty > 0 else OUT_OF_STOCK


def _product_stock(db: Session, store_id: str, source_id, name: str, content: str) -> str:
    """Active/in-stock check for a catalogue knowledge entry.

    Reads stock hints written in the entry itself ("Out of stock", "In Stock:
    No", ...) and, when we can find the live products-table row, that row's real
    availability - linked either by source_id or, for catalogues uploaded as
    knowledge rows (no link), by exact product title.
    """
    stock = parse_stock(content)
    if stock == OUT_OF_STOCK:
        return stock
    try:
        from sqlalchemy import text as sql_text
        row = None
        if source_id:
            row = db.execute(sql_text(
                f"SELECT {_PRODUCT_STOCK_COLUMNS} FROM products WHERE id = :pid"
            ), {"pid": str(source_id)}).fetchone()
        if not row and name:
            row = db.execute(sql_text(
                f"SELECT {_PRODUCT_STOCK_COLUMNS} FROM products "
                "WHERE store_id = :sid AND LOWER(title) = :title LIMIT 1"
            ), {"sid": store_id, "title": name.strip().lower()}).fetchone()
        if row:
            # Branch catalogues can explicitly omit stock; linking them to a
            # non-tracked Product must not turn unknown availability into stock.
            if (stock == "unknown" and re.search(r"(?im)^Branch:\s*\S", content or "")
                    and str(row[4]).strip().lower() in ('false', '0', 'f', 'no')):
                return stock
            return _availability_from_product_row(row)
    except Exception as e:
        logger.debug("Stock lookup failed for product '%s' (%s): %s", name, source_id, e)
        try:
            db.rollback()
        except Exception:
            pass
    return stock


# Product names in a pharmacy catalogue mix cosmetics with medicines. When a
# customer browses a type ("creams", "lotions") or a care category ("skin
# care"), the cosmetic items should lead and medicated ones should not be the
# first thing shown. These markers let us rank without changing what is sold.
COSMETIC_CATEGORY_MARKERS = (
    "moistur", "lotion", "body cream", "body butter", "body oil", "body wash",
    "face wash", "cleanser", "serum", "scrub", "sunscreen", "sun protection",
    "sunblock", "petroleum jelly", "lip care", "lipstick", "mascara", "cosmetic",
    "makeup", "foundation", "powder", "blush", "eyeshadow", "lip liner",
    "deodorant", "shampoo", "conditioner", "hair oil", "hair care", "skin care",
    "skincare", "foot care", "baby", "nappy", "diaper", "toothpaste", "mouthwash",
)

MEDICINE_CATEGORY_MARKERS = (
    "tablet", "capsule", "syrup", "suspension", "injection", "antibiotic",
    "analgesic", "antacid", "antifungal", "antiviral", "steroid", "prescription",
    "medic", "pharmac", "drops", "ointment",
)

COSMETIC_BRANDS = (
    "nivea", "vaseline", "dove", "aveeno", "garnier", "loreal", "l'oreal",
    "sorbet", "zora", "babymed", "oxy", "palmers", "palmer's", "b/opal",
    "neutrogena", "clean & clear", "eucerin", "cetaphil", "johnson", "ponds",
    "fair & lovely", "fair and lovely", "cerave", "maybelline", "mac ", "zaron",
    "bio oil", "bio-oil", "sunscreen", "sunblock", "photo guard", "slk",
)

HAIRCARE_MARKERS = (
    "shampoo", "conditioner", "scalp", "hair oil", "hair food", "hair moisturis",
    "hair moisturiz", "hair spray", "hair relaxer", "relaxer", "edge control",
    "hair dye", "wig", "weave",
)

# A bare type word means "browse what you have of this kind", not a product name.
PRODUCT_TYPE_WORDS = {
    "cream": "cream", "creams": "cream",
    "lotion": "lotion", "lotions": "lotion",
    "moisturizer": "moisturiz", "moisturizers": "moisturiz",
    "moisturiser": "moisturis", "moisturisers": "moisturis",
    "cleanser": "cleanser", "cleansers": "cleanser",
    "serum": "serum", "serums": "serum",
    "scrub": "scrub", "scrubs": "scrub",
    "sunscreen": "sunscreen", "sunscreens": "sunscreen",
    "body wash": "body wash", "body washes": "body wash",
    "face wash": "face wash", "face washes": "face wash",
    "soap": "soap", "soaps": "soap",
    "shampoo": "shampoo", "shampoos": "shampoo",
    "conditioner": "conditioner", "conditioners": "conditioner",
    "toothpaste": "toothpaste", "toothpastes": "toothpaste",
}


def _cosmetic_score(product: Dict[str, str]) -> int:
    """How strongly a catalogue row reads as a cosmetic rather than a medicine."""
    category = (product.get("category") or "").lower()
    name = (product.get("name") or "").lower()
    score = 0
    if any(marker in category for marker in COSMETIC_CATEGORY_MARKERS):
        score += 2
    if any(marker in category for marker in MEDICINE_CATEGORY_MARKERS):
        score -= 2
    if any(name.startswith(brand) or f" {brand}" in name for brand in COSMETIC_BRANDS):
        score += 2
    return score


def _is_haircare(product: Dict[str, str]) -> bool:
    category = (product.get("category") or "").lower()
    name = (product.get("name") or "").lower()
    if "hair care" in category or "haircare" in category:
        return True
    return any(marker in name for marker in HAIRCARE_MARKERS)


def _rank_for_browsing(products: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Cosmetics first, then the rest, each alphabetically - stable per query."""
    return sorted(products, key=lambda p: (-_cosmetic_score(p), (p.get("name") or "").lower()))


def _detect_product_type(query_lower: str) -> str:
    """Return the type word when the query is only asking for a kind of product."""
    cleaned = re.sub(r"[?.!,]", " ", query_lower or "").strip()
    cleaned = re.sub(r"^(do you have|have you got|i want|i need|show me|any|some|what|which)\s+", "", cleaned).strip()
    cleaned = re.sub(r"\s+(do you have|available|please)$", "", cleaned).strip()
    return PRODUCT_TYPE_WORDS.get(cleaned, "")


def _search_products_by_keyword(db: Session, store, keyword: str, limit: int = 20,
                                branch: str = None,
                                include_out_of_stock: bool = False) -> List[Dict[str, str]]:
    """Search for products in the knowledge base matching a keyword (brand/name).
    Returns list of products with name, price (rounded to a whole number) and
    stock status. Pass empty keyword to get all products. Optionally filter by
    branch if specified. Products that are not active/in stock are left out."""
    if not store:
        return []
    try:
        from sqlalchemy import func, text
        from modules.whatsapp.models import CompanyKnowledge
        keyword_lower = keyword.lower().strip() if keyword else ""
        store_id_str = str(store.id)

        # Normalize common spelling variations (user input -> database format)
        spelling_fixes = {
            "tooth paste": "toothpaste",
            "sun screen": "sunscreen",
            "sun block": "sunblock",
            "lip stick": "lipstick",
            "eye liner": "eyeliner",
            "eye shadow": "eyeshadow",
            "hand wash": "handwash",
            "body wash": "bodywash",
            "face wash": "facewash",
            "mouth wash": "mouthwash",
            "hair spray": "hairspray",
            "nail polish": "nailpolish",
            "skin care": "skincare",
            # "body lotion" and "hand cream" used to be collapsed to "lotion"
            # and "cream". That made a full request ("nivea body lotion aloe
            # hydration 400ml") miss the catalogue row that contains exactly
            # those words, and the agent told the customer the item was out of
            # stock. Keep the qualifier: the token fallback below handles the
            # separators, and the exact search is more precise without it.
        }
        for wrong, correct in spelling_fixes.items():
            if wrong in keyword_lower:
                keyword_lower = keyword_lower.replace(wrong, correct)

        # Handle plurals - remove trailing 's' for common product searches
        # e.g., "vitamins" -> "vitamin", "lotions" -> "lotion"
        plural_fixes = {
            "vitamins": "vitamin",
            "lotions": "lotion",
            "creams": "cream",
            "shampoos": "shampoo",
            "soaps": "soap",
            "tablets": "tablet",
            "capsules": "capsule",
            "syrups": "syrup",
            "medicines": "medicine",
            "perfumes": "perfume",
            "lipsticks": "lipstick",
            "foundations": "foundation",
        }
        if keyword_lower in plural_fixes:
            keyword_lower = plural_fixes[keyword_lower]

        # Build query based on keyword and branch filters
        branch_filter = "AND branch = :branch" if branch else ""

        if keyword_lower:
            query = text(f"""
                SELECT content, source_id FROM company_knowledge
                WHERE store_id = :store_id
                AND is_active = true
                AND content_type IN ('product', 'manual')
                AND LOWER(content) LIKE :pattern
                {branch_filter}
                LIMIT :limit
            """)
            params = {"store_id": store_id_str, "pattern": f"%{keyword_lower}%", "limit": limit}
        else:
            query = text(f"""
                SELECT content, source_id FROM company_knowledge
                WHERE store_id = :store_id
                AND is_active = true
                AND content_type IN ('product', 'manual')
                {branch_filter}
                LIMIT :limit
            """)
            params = {"store_id": store_id_str, "limit": limit}

        if branch:
            params["branch"] = branch
        try:
            results = db.execute(query, params).fetchall()
        except Exception as branch_err:
            # Knowledge tables without a `branch` column (older installs) would
            # otherwise return nothing at all - retry without the branch filter.
            if branch:
                logger.warning("Branch filter failed (%s) - retrying without branch", branch_err)
                try:
                    db.rollback()
                except Exception:
                    pass
                return _search_products_by_keyword(db, store, keyword, limit=limit,
                                                   branch=None,
                                                   include_out_of_stock=include_out_of_stock)
            raise
        products = []
        for row in results:
            content = row[0] or ""
            source_id = row[1] if len(row) > 1 else None
            lines = content.split("\n")
            name = ""
            price = ""
            category = ""
            for line in lines:
                if line.lower().startswith("product:"):
                    name = line.split(":", 1)[1].strip()
                elif line.lower().startswith("price:"):
                    price = line.split(":", 1)[1].strip()
                elif line.lower().startswith("category:"):
                    category = line.split(":", 1)[1].strip()
            if not name:
                continue
            # Only offer products that are ACTIVE and IN STOCK
            stock = _product_stock(db, store_id_str, source_id, name, content)
            if stock == OUT_OF_STOCK and not include_out_of_stock:
                logger.info("Skipping out-of-stock/inactive product '%s'", name)
                continue
            numeric_price = parse_price(price)
            products.append({
                "name": name,
                # Prices are always shown rounded to the nearest whole number
                "price": format_price(numeric_price) if numeric_price is not None
                         else (price or "Price on request"),
                "stock": stock,
                # Kept for ranking only - not shown to the customer.
                "category": category,
            })
        return products
    except Exception as e:
        import traceback
        logger.warning("Failed to search products for store %s: %s\n%s", store.id, e, traceback.format_exc())
        return []


_PRODUCT_QUERY_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "with", "from", "to", "in", "on",
    "at", "of", "my", "me", "i", "we", "you", "your", "please", "some", "any",
    "this", "that", "these", "those", "is", "are", "do", "does", "have", "has",
    "add", "get", "give", "buy", "order", "want", "need", "like", "cart",
    "branch", "price", "cost", "stock", "available", "angwa", "bulawayo",
    "gweru", "rezende", "harare", "x",
}

_PRODUCT_UNIT_TOKENS = {
    "ml", "mg", "g", "l", "kg", "s", "pcs", "pack", "packs", "tablet",
    "tablets", "capsule", "capsules",
}

# Shelf words are useful for matching a name but poor anchors: searching every
# "lotion" tells us nothing about which lotion the customer meant.
_PRODUCT_GENERIC_WORDS = {
    "body", "lotion", "cream", "soap", "wash", "shampoo", "conditioner",
    "syrup", "tablet", "tablets", "capsule", "capsules", "spray", "oil",
    "gel", "powder", "solution", "suspension", "baby", "adult", "care",
    "skin", "face", "hair", "hand", "foot", "sun", "sunscreen", "sunblock",
    "moisturiser", "moisturizer", "moisturising", "moisturizing", "vitamin",
    "vitamins", "supplement", "supplements", "deodorant", "toothpaste",
    "mouthwash", "medicine", "medicines",
}

_PRODUCT_WORD_RE = re.compile(r"[a-z0-9]+")


def _product_words(value: str) -> List[str]:
    """Lower-case words with separators and unit spacing normalised.

    "MILD&GENTLE 200ML" and "mild gentle 200 ml" become the same words. This is
    what lets a customer's full product name match a catalogue title that uses
    '&', '/', '-' or no space between the size and the unit.
    """
    text = str(value or "").lower().replace("&", " and ")
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    return _PRODUCT_WORD_RE.findall(text)


def _product_query_tokens(query: str) -> List[str]:
    """Meaningful words for token matching, without quantities or filler."""
    words = _product_words(query)
    tokens = []
    for index, word in enumerate(words):
        if word in _PRODUCT_QUERY_STOPWORDS:
            continue
        if word.isdigit():
            next_is_unit = (index + 1 < len(words)
                            and words[index + 1] in _PRODUCT_UNIT_TOKENS)
            # "2 clicks baby lotion" starts with a quantity, while "400 ml"
            # is a size. Keep sizes, drop quantities.
            if not next_is_unit and len(word) <= 2:
                continue
            if not next_is_unit and int(word) <= 99:
                continue
        tokens.append(word)
    return list(dict.fromkeys(tokens))


def _search_products_by_tokens(db: Session, store, query: str, limit: int = 20,
                               branch: str = None) -> List[Dict[str, str]]:
    """Find catalogue rows when the words match but the punctuation does not.

    Exact LIKE search needs the customer's words to appear contiguously. "nivea
    body lotion aloe hydration 400ml" missed "NIVEA BODY LOTION
    ALOE&HYDRATION 400ML" because of the ampersand, so the agent said the item
    was unavailable. We anchor on the brand (or another distinctive word), then
    require most of the customer's words to be present in the product name.
    """
    tokens = _product_query_tokens(query)
    if len(tokens) < 2:
        return []

    # A brand is a much better anchor than a shelf word. Fall back to the
    # longest distinctive words if every token is generic.
    distinctive = [t for t in tokens
                   if t not in _PRODUCT_GENERIC_WORDS and not t.isdigit()]
    anchors = []
    if distinctive:
        anchors.append(distinctive[0])
    anchors.extend(sorted(distinctive, key=len, reverse=True))
    anchors = list(dict.fromkeys(anchors))[:4]
    if not anchors:
        return []

    candidates: Dict[str, Dict[str, str]] = {}
    for anchor in anchors:
        for product in _search_products_by_keyword(db, store, anchor, limit=300,
                                                   branch=branch):
            candidates.setdefault(product.get("name", "").lower(), product)
        if len(candidates) >= max(limit * 4, 30):
            break

    # ceil(0.75 * number of words), so a long name may contain a couple of
    # extras ("for dry skin") without matching an unrelated product.
    needed = max(2, (len(tokens) * 3 + 3) // 4)
    # A size is not a "most words" hint: 200ml must not match 500ml just because
    # every other word is the same.
    size_tokens = [token for token in tokens if token.isdigit()]
    scored = []
    for product in candidates.values():
        name_words = set(_product_words(product.get("name", "")))
        if size_tokens and not all(token in name_words for token in size_tokens):
            continue
        matched = sum(1 for token in tokens if token in name_words)
        if matched >= needed:
            scored.append((matched / len(tokens), matched, product))

    scored.sort(key=lambda row: (-row[0], -row[1], row[2].get("name", "")))
    return [product for _, _, product in scored[:limit]]


def _load_product_names(db: Session, store, branch: str = None, limit: int = 1500) -> List[str]:
    """All active product names for this store (used for spelling suggestions)."""
    if not store:
        return []
    try:
        from sqlalchemy import text
        branch_filter = "AND branch = :branch" if branch else ""
        query = text(f"""
            SELECT content FROM company_knowledge
            WHERE store_id = :store_id
            AND is_active = true
            AND content_type IN ('product', 'manual')
            {branch_filter}
            LIMIT :limit
        """)
        params = {"store_id": str(store.id), "limit": limit}
        if branch:
            params["branch"] = branch
        try:
            rows = db.execute(query, params).fetchall()
        except Exception:
            if branch:
                db.rollback()
                return _load_product_names(db, store, branch=None, limit=limit)
            raise
        names = []
        for row in rows:
            content = row[0] or ""
            for line in content.split("\n"):
                if line.lower().startswith("product:"):
                    name = line.split(":", 1)[1].strip()
                    if name:
                        names.append(name)
                    break
        return names
    except Exception as e:
        logger.warning("Failed to load product names for store %s: %s", getattr(store, "id", store), e)
        return []


_PRODUCT_FILLER_RE = re.compile(
    r"^(?:please\s+)?(?:also\s+)?(?:can\s+you\s+|could\s+you\s+)?(?:add|order|buy|take|get|give|i\s+want|i\s+need|"
    r"i'd\s+like|i\s+would\s+like|i\s+will\s+take|i'll\s+take|get\s+me|give\s+me|"
    r"do\s+you\s+have|have\s+you\s+got|how\s+much\s+(?:is|for)|show\s+me|looking\s+for|"
    r"is\s+there|are\s+there)\s+",
    re.IGNORECASE,
)
_PRODUCT_TAIL_RE = re.compile(
    r"\s+(?:to\s+my\s+cart|in\s+my\s+cart|to\s+the\s+cart|again|as\s+well|too|please)\s*[.!?]*$",
    re.IGNORECASE,
)


def _clean_product_query(text: str) -> str:
    """Strip the request around a product name: 'also add dove soap' -> 'dove soap'.

    Without this, the fuzzy search scored "also"/"add" against the catalogue and
    produced a did-you-mean, so the bot asked the customer to confirm a spelling
    instead of adding the product they had just asked for.
    """
    cleaned = str(text or "").strip()
    for _ in range(3):
        stripped = _PRODUCT_FILLER_RE.sub("", cleaned).strip()
        if stripped == cleaned:
            break
        cleaned = stripped
    cleaned = _PRODUCT_TAIL_RE.sub("", cleaned).strip()
    return cleaned or str(text or "").strip()


def _search_products_smart(db: Session, store, query: str, limit: int = 20,
                           branch: str = None) -> Dict[str, Any]:
    """Product search with spelling tolerance.

    1. Exact/substring search on the typed words (active + in stock only)
    2. If nothing matches, fuzzy-match the typed words against the catalogue so
       typos and WhatsApp shorthand still resolve ("nivia" -> Nivea,
       "benylin 4 flu" / "benylin for flu" -> Benylin)

    Returns {"products": [...], "did_you_mean": str|None, "typed_query": str}.
    """
    result = {"products": [], "did_you_mean": None, "typed_query": query or ""}
    products = _search_products_by_keyword(db, store, query, limit=limit, branch=branch)
    if not products and query:
        # "hiv test kit" missed "HIV TEST KITS (BLOOD)" because only a fixed
        # list of plurals was handled, so asking again with different wording
        # produced products the first question had denied. Try both forms.
        for variant in (re.sub(r"\b(\w{4,})s\b", r"\1", query),
                        re.sub(r"\b(\w{4,})\b(?!s)(?!.*\b\1s\b)", r"\1s", query, count=1)):
            if variant and variant != query:
                products = _search_products_by_keyword(db, store, variant,
                                                       limit=limit, branch=branch)
                if products:
                    break
    if products:
        result["products"] = products
        return result

    # Words match but punctuation/size spacing does not ("aloe hydration" vs
    # "ALOE&HYDRATION"). Try the token match before guessing a spelling.
    token_products = _search_products_by_tokens(db, store, query, limit=limit,
                                                branch=branch)
    if token_products:
        result["products"] = token_products
        return result

    names = _load_product_names(db, store, branch=branch)
    if not names and branch:
        names = _load_product_names(db, store)
    suggestions = suggest_product_names(query, names, limit=3)

    # Only suggest products we can actually sell: the suggestion must resolve to
    # active, in-stock products, otherwise it stays "not found" (suggesting an
    # out-of-stock item is worse than saying we don't have it).
    for best_name, best_score in suggestions:
        brand_token = best_name.split()[0].lower()
        for candidate in (brand_token, best_name.lower()):
            products = _search_products_by_keyword(db, store, candidate, limit=limit, branch=branch)
            if products:
                result["did_you_mean"] = best_name
                result["products"] = products
                logger.info("Spelling suggestion for '%s' -> '%s' (score %.2f)",
                            query, best_name, best_score)
                return result
        logger.info("Spelling suggestion '%s' for '%s' skipped - not active/in stock",
                    best_name, query)
    return result


def _format_did_you_mean(search_result: Dict[str, Any], query: str, branch: str = None) -> str:
    """Tool output for a misspelled/indirect product request."""
    did_you_mean = search_result.get("did_you_mean")
    products = search_result.get("products") or []
    if not did_you_mean:
        return (f"NOT FOUND: No products matching '{query}' found. Tell the customer we "
                f"don't currently have this item in stock and offer to help with something else.")

    brand = did_you_mean.split()[0].capitalize()
    lines = [f"DID_YOU_MEAN: {did_you_mean}",
             f"Customer typed: '{query}'. The closest product we stock is *{did_you_mean}*."]
    if products:
        lines.append(f"Products found:\n" + _format_product_list(products[:10]))
    lines.append(
        f"IMPORTANT: Ask the customer to confirm the spelling, e.g. "
        f"'Did you mean *{brand}*? We stock the following:' and show the products above. "
        f"Wait for their confirmation before adding anything to the cart."
    )
    return "\n".join(lines)


def _format_product_list(products: List[Dict[str, str]]) -> str:
    """Format a list of products with prices for WhatsApp display."""
    if not products:
        return ""
    lines = []
    for i, p in enumerate(products, 1):
        lines.append(f"{i}. {p['name']} - {p['price']}")
    return "\n".join(lines)


# The pharmacy sells ONLY what the branch price lists import into
# company_knowledge (scripts/import_branch_catalogue.py). There is deliberately
# no hardcoded medicine list here any more: it quoted prices for drugs a branch
# may not stock (Panadol, Metformin, Amoxicillin are not in any branch file), so
# a customer could be sold something that does not exist in that branch.

# Words that carry no product meaning - never used as a catalogue search term.
_MEDICATION_STOPWORDS = {
    "want", "need", "needs", "have", "has", "had", "give", "take", "buy", "order",
    "add", "get", "got", "please", "some", "any", "the", "and", "for", "with",
    "from", "that", "this", "these", "those", "you", "your", "can", "could",
    "would", "should", "will", "like", "just", "also", "now", "yes", "okay", "ok",
    "hi", "hello", "hey", "morning", "afternoon", "evening", "thank", "thanks",
    "much", "very", "how", "what", "which", "where", "when", "who", "does", "did",
    "do", "is", "are", "was", "were", "my", "me", "i", "a", "an", "of", "to",
    "in", "on", "at", "it", "its", "there", "here", "about", "price", "cost",
    "stock", "available", "availability", "pharmacy", "pharmacist", "chemist",
    "medicine", "medicines", "medication", "medications", "tablet", "tablets",
    "capsule", "capsules", "syrup", "syr", "mg", "ml", "box", "boxes", "pack",
    "packs", "bottle", "bottles", "sachet", "sachets", "each", "one", "two",
}


def _catalogue_matches(db, store, text: str, branch: Optional[str] = None,
                       limit: int = 8) -> List[Dict[str, str]]:
    """Catalogue rows for the product words in `text` (real names, real prices).

    Longest word first, so "ibuprofen" is tried before "flu". Out-of-stock rows
    are already filtered out by _search_products_by_keyword.
    """
    if not (db and store and text):
        return []
    words = [w for w in re.findall(r"[a-z][a-z0-9'\-]{2,}", text.lower())
             if w not in _MEDICATION_STOPWORDS]
    words = sorted(set(words), key=len, reverse=True)[:6]
    found, seen = [], set()
    for word in words:
        for product in _search_products_by_keyword(db, store, word, limit=limit,
                                                   branch=branch):
            key = (product.get("name") or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            found.append({**product, "term": word})
    return found


def _search_medications(db, store, user_text: str, branch: Optional[str] = None,
                        limit: int = 8) -> List[Dict[str, str]]:
    """Medicines the customer's words point at, straight from the catalogue."""
    return _catalogue_matches(db, store, user_text, branch=branch, limit=limit)


def _format_medication_quotation(medications: List[Dict], quantities: Dict[str, int] = None,
                                 store_name: str = None) -> str:
    """Format medications as a quotation with prices and total."""
    if not medications:
        return ""

    lines = [f"*QUOTATION - {store_name or 'Your pharmacy'}*", ""]
    total = 0

    for i, med in enumerate(medications, 1):
        qty = (quantities or {}).get(med["name"], 1)
        # Catalogue rows carry "$3.50"; round to the nearest whole number.
        unit = round_price(parse_price(med["price"]) or 0)
        subtotal = unit * qty
        total += subtotal
        lines.append(f"{i}. {med['name']}")
        lines.append(f"   Price: {format_price(unit)} x {qty} = {format_price(subtotal)}")

    lines.append("")
    lines.append(f"*TOTAL: {format_price(total)} USD*")
    lines.append("")
    lines.append("Reply with the item numbers you want to order.")
    lines.append("Payment: Medical Aid or Cash accepted.")

    return "\n".join(lines)


_GREETING_WORDS = {
    "hi", "hie", "hey", "heya", "hello", "hallo", "yo", "howdy", "greetings",
    "morning", "afternoon", "evening",
    # The typos customers actually send. "helo" used to fall through to product
    # search and be answered with "Did you mean *Heel*?" - foot balm for a hello.
    "helo", "hlo", "hii", "helloo", "halloo", "heyy", "hiii", "heloo",
}
_GREETING_FILLER = {
    "again", "there", "team", "everyone", "all", "sir", "madam", "please", "back",
    "once", "family", "friends", "platinum", "pharmacy", "good",
}


def _is_greeting_only(text: str) -> bool:
    """True when the message is only a greeting - "hi", "hello again", "Hi there!".

    Customers rarely type exactly "hello": they write "hello again", "hi there",
    "hey team" or add punctuation and emoji. The old exact-match list missed
    those, so a returning customer's greeting fell through to the "answer their
    query directly" rule and the reply lost the business name.
    """
    cleaned = re.sub(r"[^a-z\s]", " ", (text or "").lower())
    words = cleaned.split()
    if not words:
        return False
    def _is_greeting_word(word: str) -> bool:
        if word in _GREETING_WORDS:
            return True
        if len(word) < 2:
            return False
        return any(abs(len(word) - len(g)) <= 1
                   and difflib.SequenceMatcher(None, word, g).ratio() >= 0.8
                   for g in _GREETING_WORDS)

    return (any(_is_greeting_word(word) for word in words)
            and all(_is_greeting_word(word) or word in _GREETING_FILLER for word in words))


def _branded_greeting(db: Session, store, customer_phone: Optional[str],
                      user_text: str, returning: bool = False) -> Optional[str]:
    """Deterministic greeting reply for a greeting-only message.

    The model reliably drops the business name and, worse, a greeting used to
    run through product search ("hi there" came back as "Did you mean
    Cerave?"). A greeting needs no model: answer it from code, unless an order
    is already in progress - then the conversation flow must continue.

    The greeting names the business, lists every branch the store actually
    sells from, and asks which one the customer wants. An old state row left
    behind by a completed order is not "mid-checkout": only a cart with items
    or one of the real checkout steps continues the flow. Treating any state
    row as active is what made a returning customer's "hi" fall through to the
    model and lose the branded welcome.

    Returns None to let the normal reply path handle the message.
    """
    if not _is_greeting_only(user_text):
        return None
    name = getattr(store, "store_name", None) or "our store"
    chosen_branch = None
    if customer_phone and store is not None:
        try:
            state = _get_order_state(db, str(store.id), customer_phone) or {}
            # Mid-checkout the step must continue, not restart with a greeting.
            # "idle"/"cart" with an empty cart is a finished conversation, not
            # an order in progress.
            current_state = (state.get("current_state") or "").strip().lower()
            if state.get("cart_items") or current_state in _CHECKOUT_STATES:
                return None
            chosen_branch = state.get("selected_branch")
        except Exception as e:
            logger.warning("Could not check order state for greeting: %s", e)

    branches = _listed_store_branches(db, store) if store is not None else []
    welcome = (f"Welcome back to {name}. How can I help you today?"
               if returning else
               f"Welcome to {name}. How can I help you today?")
    lines = [welcome]

    if len(branches) > 1:
        lines += ["", "Our branches:"]
        for index, branch in enumerate(branches, 1):
            marker = " (current)" if (chosen_branch
                                      and branch.lower() == chosen_branch.lower()) else ""
            lines.append(f"{index}. {branch}{marker}")
        if chosen_branch:
            lines += ["", f"You're currently shopping from *{chosen_branch}*."]
        else:
            lines += ["", "Which branch would you like to shop from?"]
    elif len(branches) == 1:
        lines += ["", f"You can shop from our *{branches[0]}* branch."]

    return "\n".join(lines)


# The bot asks "which branch?" in a few places. Reading the answer is
# bookkeeping, not a model turn: "1" used to be run as a product search (the
# old category map turned "1" into "nivea OR vaseline OR dove"), so the bot
# answered "We have NIVEA products available at all branches!" and asked for
# the branch again.
_BRANCH_QUESTION_MARKERS = (
    "which branch", "select a branch", "choose a branch", "available branches",
)

# Lead-ins that turn a question into a product name ("do you have nivea" -> "nivea").
_PRODUCT_QUERY_LEADINS = (
    "do you have", "have you got", "is there", "are there", "i want", "i'd like",
    "i would like", "i need", "looking for", "price of", "how much is",
    "how much for", "show me", "can i get", "please", "any",
)


def _branches_for_store(db: Session, store) -> List[str]:
    """Branches available for selection, including those in the store FAQ."""
    if store is None:
        return []
    return _listed_store_branches(db, store)


def _branch_choice(user_text: str, branches: List[str]) -> Optional[str]:
    """The branch the customer picked by number or name, when that is all they typed."""
    text = re.sub(r"[^a-z0-9\s]", " ", str(user_text or "").lower())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    for index, branch in enumerate(branches, 1):
        if text == str(index) or text == str(branch).lower():
            return branch
    return None


def _product_query_from(text: str) -> str:
    """The product part of a message: "do you have nivea cream?" -> "nivea cream"."""
    query = str(text or "").strip().strip(" ?!.")
    for lead in _PRODUCT_QUERY_LEADINS:
        if query.lower().startswith(lead):
            query = query[len(lead):].strip(" ,?!.")
    return query


def _branch_choice_reply(db: Session, store, user_text: str,
                         history: Optional[List[Dict[str, str]]],
                         customer_phone: Optional[str]) -> Optional[str]:
    """Reply to a branch answer from code, so it can never become a product guess."""
    if not (store and user_text and history and customer_phone):
        return None
    if not any(marker in last_assistant_message(history).lower()
               for marker in _BRANCH_QUESTION_MARKERS):
        return None

    chosen = _branch_choice(user_text, _branches_for_store(db, store))
    if not chosen:
        return None
    try:
        _update_order_state(db, str(store.id), customer_phone, selected_branch=chosen)
    except Exception as e:
        logger.warning("Could not save the chosen branch: %s", e)

    # If they had just asked for something, show it at that branch - otherwise
    # simply confirm the branch and ask what they need.
    previous = ""
    for message in reversed(history):
        if message.get("role") == "user":
            previous = (message.get("content") or "").strip()
            break

    query = _product_query_from(previous)
    if query and not _is_greeting_only(previous) and not query.isdigit() \
            and query.lower() != str(chosen).lower():
        matches = _search_products_by_keyword(db, store, query, limit=8, branch=chosen)
        if matches:
            lines = "\n".join(f"{i}. {p['name']} - {p['price']}"
                              for i, p in enumerate(matches[:8], 1))
            return (f"Great - *{chosen}* branch.\n\n"
                    f"Here's what we have for *{query}*:\n{lines}\n\n"
                    "Would you like to add any of these?")

    return f"Great - *{chosen}* branch.\n\nWhat can I help you with today?"


def _unanswered_query_reply(store_name: Optional[str] = None) -> str:
    """Reply for a question the bot genuinely cannot answer.

    A customer must never be left on read: the bot says it has passed the
    question on (the owner alert is fired separately) and offers the one thing
    it can always do - look up a product by name. Deliberately invents nothing:
    no prices, no stock, no opening hours.
    """
    business = store_name or "our team"
    return (
        f"Thanks for getting in touch with {business}. I've passed your question to our "
        "team and someone will reply here shortly.\n\n"
        "If it's about a product, send me the name or brand and I'll check stock and "
        "prices for you."
    )


def _check_handoff(db: Session, store, user_text: str) -> Optional[str]:
    """If user_text matches one of this tenant's configured handoff keywords
    (Settings > WhatsApp Business > Handoff Keywords, defaulting to the built-in
    list below when unset), returns the handoff message to send instead of
    generating an AI reply. Returns None when no handoff is triggered."""
    if not store or not user_text:
        return None
    keywords = DEFAULT_HANDOFF_KEYWORDS
    message = DEFAULT_HANDOFF_MESSAGE
    try:
        from modules.whatsapp.models import StoreBotConfig
        config = db.query(StoreBotConfig).filter(StoreBotConfig.store_id == store.id).first()
        if config:
            if config.handoff_keywords:
                keywords = config.handoff_keywords
            if config.handoff_message and config.handoff_message.strip():
                message = config.handoff_message.strip()
    except Exception as e:
        logger.warning("Failed to load handoff config for store %s: %s", store.id, e)
    text_lower = user_text.lower()

    # Check for prescription keywords first (pharmacist handoff)
    if any(kw.lower() in text_lower for kw in PRESCRIPTION_KEYWORDS if kw):
        return PRESCRIPTION_HANDOFF_MESSAGE

    # Check for general handoff keywords
    if any(kw.lower() in text_lower for kw in keywords if kw):
        return message
    return None


def _named_medication(db, store, text: str, branch: Optional[str] = None) -> Optional[str]:
    """The catalogue product the CUSTOMER explicitly named, or None.

    Only products this store sells at the branch being shopped count - "i want
    panadol" returns None when no branch price list has Panadol, so the bot
    never double-checks an order for a drug it cannot sell. The returned name is
    the catalogue's own, which is what the double-check must confirm (a pack
    size, not a guess at one).
    """
    if not text:
        return None
    matches = _catalogue_matches(db, store, text, branch=branch, limit=8)
    if not matches:
        return None

    def rank(product):
        name = (product.get("name") or "").lower()
        term = product.get("term") or ""
        # A name that starts with the word the customer used, then the plain
        # (shortest) pack rather than a bundle/combo.
        return (not name.startswith(term), len(name))

    return min(matches, key=rank)["name"]


# Checkout steps where the customer is typing structured answers (name/phone/
# address/payment) - the medication rules must not swallow those.
_CHECKOUT_STATES = {
    "delivery_step_name", "delivery_step_phone", "delivery_step_address",
    "payment", "confirm", "payment_retry", "awaiting_collection",
}


# Any of these in the store's own wording marks it as a pharmacy, which decides
# who the medication handover promises to bring in.
_PHARMACY_MARKERS = ("pharmacy", "pharmacist", "chemist", "dispensary", "drugstore")


def _is_pharmacy_store(store) -> bool:
    if not store:
        return False
    text = " ".join(
        str(getattr(store, field, "") or "") for field in
        ("store_name", "store_category", "business_type", "store_description")
    ).lower()
    return any(marker in text for marker in _PHARMACY_MARKERS)


def _medication_question_guard(store, user_text: str) -> Optional[str]:
    """Never answer a medication/prescription question with the model.

    Dosage, safety, interactions, pregnancy/child use, side effects, overdose,
    symptoms and prescriptions are pharmacist work. The detector is pure and
    deterministic (pharmacy_rules.is_medication_question), and it runs before
    any product search or model call, so the only thing the customer can get
    back is the handover message - never medical advice, never a product the
    bot picked for a symptom.

    Returns the handover reply, or None when the message is not a clinical
    question (a normal shopping turn).
    """
    if not is_medication_question(user_text):
        return None
    logger.info("Medication/prescription question handed to a pharmacist: %r", user_text)
    if _is_pharmacy_store(store):
        return PHARMACIST_QUESTION_MESSAGE
    return HEALTH_QUESTION_MESSAGE


def _pharmacy_intent_gate(db: Session, store, user_text: str,
                          history: Optional[List[Dict[str, str]]],
                          customer_phone: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Medication safety gate for a pharmacy (runs before the LLM).

    Business rules:
      * Unsure customer -> NEVER suggest medication; hand the request to the
        pharmacist ("your request is under review by our pharmacist").
      * Sure customer -> double-check ("are you really sure?") before the
        order continues; 'yes' continues, 'no' hands over to the pharmacist.

    Returns (reply, rewritten_user_text):
      (None, None)  -> carry on with the normal flow
      (reply, None) -> answer directly with `reply`
      (None, text)  -> continue the normal flow, restating the request as `text`
    """
    if not (store and user_text and customer_phone):
        return None, None

    text = user_text.strip()
    if not text:
        return None, None

    state = _get_order_state(db, str(store.id), customer_phone) or {}
    if (state.get("current_state") or "") in _CHECKOUT_STATES:
        return None, None

    last_bot = last_assistant_message(history)
    pending_item = extract_sure_check_item(last_bot)

    # 1) We just asked "are you really sure ...?" - handle the answer
    if pending_item:
        if is_affirmative(text):
            # Add it here. Leaving this to the model produced quotations for
            # items that were never added, so the cart stayed empty and the
            # order could not be confirmed.
            branch = (state.get("selected_branch")
                      or _branch_for_product(db, str(store.id), pending_item)
                      or (_store_branches(db, str(store.id)) or [None])[0])
            # Branch first, then price: the same pack costs different amounts at
            # different branches, so the cart must use this branch's price.
            price = _catalogue_price(db, str(store.id), pending_item, branch=branch)
            if price:
                # "i'll take 2" survives the double-check: the unit count comes
                # from the message that named the item, not a hardcoded 1.
                quantity = _pending_quantity(history, pending_item)
                items = list(state.get("cart_items") or [])
                if any((i.get("product_name") or "").lower() == pending_item.lower() for i in items):
                    return (f"{pending_item} is already in your cart. Would you like to proceed to checkout?"), None
                items.append({"product_name": pending_item,
                              "price": round_price(price),
                              "quantity": quantity, "branch": branch})
                _update_order_state(db, str(store.id), customer_phone, cart_items=items, current_state="awaiting_checkout")
                return (f"Added {quantity}x *{pending_item}* at "
                        f"{format_price(round_price(price))} each. "
                        f"Cart now: {len(items)} item(s), subtotal "
                        f"{format_price(cart_subtotal(items))}. Would you like to proceed to checkout?"), None
            # Confirmed but not in the catalogue: restate it so the flow continues
            return None, f"Yes, I am sure. I want {pending_item}."
        if is_negative(text) or is_uncertain_request(text):
            return PHARMACIST_REVIEW_MESSAGE, None
        # Some other message entirely - fall through and treat it fresh

    # 2) Customer does not know what they want -> hand over, never suggest
    if is_uncertain_request(text):
        return PHARMACIST_REVIEW_MESSAGE, None

    # 3) Customer named a medication and wants it -> double-check they're sure
    if is_medication_related(text) and is_purchase_intent(text):
        # But a pasted list or "add these to the cart" is a whole order: one
        # item's double-check cannot stand in for it. Asking it added that
        # single line and dropped every other product the customer selected.
        if is_multi_item_selection(text):
            return None, None
        named = _named_medication(db, store, text,
                                  branch=state.get("selected_branch"))
        if named:
            return sure_confirmation_message(named), None
        # Wants "something for" a symptom but named no product - that is an
        # unsure request, so hand it to the pharmacist instead of guessing.
        return PHARMACIST_REVIEW_MESSAGE, None

    return None, None


_CHECKOUT_COLLECTION_WORDS = {
    "walk in": "walkin", "walkin": "walkin", "walk in please": "walkin",
    "collect": "walkin", "collection": "walkin", "pick up": "walkin", "pickup": "walkin",
    "delivery": "delivery", "deliver": "delivery", "delivered": "delivery",
    "delivery please": "delivery",
}
_CHECKOUT_PAYMENT_WORDS = {
    "cash": "cash", "pay cash": "cash", "card": "cash", "swipe": "cash",
    "ecocash": "ecocash", "eco cash": "ecocash", "onemoney": "onemoney",
    "one money": "onemoney", "innbucks": "innbucks", "inn bucks": "innbucks",
}


async def _resume_checkout(db, store, customer_phone, user_text=""):
    """Resume from saved fields; repeated tool calls must not reset checkout."""
    state = _get_order_state(db, str(store.id), customer_phone) or {}
    if state.get("collection_method") == "delivery":
        step = _delivery_next_state(state)
        prompts = {
            "delivery_step_name": "What is your full name for delivery?",
            "delivery_step_phone": "What is your 10-digit phone number for delivery?",
            "delivery_step_address": "What is your delivery address (street, suburb and city)?",
        }
        if step in prompts:
            _update_order_state(db, str(store.id), customer_phone, current_state=step)
            return prompts[step]
    if state.get("payment_method") or state.get("payment_provider"):
        return await _execute_pharmacy_tool(
            db, store, customer_phone, "set_payment_method",
            {"method": state.get("payment_provider") or state.get("payment_method"),
             "mobile_number": state.get("payment_phone")}, user_text)
    _update_order_state(db, str(store.id), customer_phone, current_state="payment")
    return "How would you like to pay?\n1. Cash\n2. EcoCash\n3. OneMoney\n4. InnBucks"


async def _checkout_choice_reply(db, store, user_text: str, customer_phone: str,
                                 history: Optional[List[Dict[str, str]]] = None) -> Optional[str]:
    """Answer a bare collection/payment choice from code, saving it immediately.

    The model sometimes only talks ("Walk-in it is! How would you like to pay?")
    without calling set_collection_method, so confirm_order later refuses because
    the choice was never stored, and the customer is asked again. A bare answer
    is handled here instead - it can only ever do what the customer just said.
    """
    if not (db and store and user_text and customer_phone):
        return None
    state = _get_order_state(db, str(store.id), customer_phone) or {}
    if not state.get("cart_items"):
        return None
    lowered = re.sub(r"[^a-z0-9 ]", " ", str(user_text).lower())
    lowered = re.sub(r"\s+", " ", lowered).strip()
    if not lowered or len(lowered.split()) > 3:
        return None
    # Never answer for a step that is collecting a name/phone/address: the
    # customer's name can legitimately be "Cash", and the order-flow tests send
    # exactly that. Only a bare choice at the collection/payment step counts.
    current = (state.get("current_state") or "").lower()
    if current in _CHECKOUT_STATES and current not in ("payment", "awaiting_collection"):
        return None

    # "2" answering "Delivery or Walk-in?": read the menu the bot just sent, so
    # the choice is saved instead of being left to the model.
    if lowered in ("1", "2") and not state.get("collection_method") and history:
        asked = last_assistant_message(history).lower()
        if "delivery" in asked and ("walk" in asked or "pick" in asked):
            method = "walkin" if lowered == "1" else "delivery"
            return await _execute_pharmacy_tool(db, store, customer_phone,
                                                "set_collection_method",
                                                {"method": method}, user_text)

    method = _CHECKOUT_COLLECTION_WORDS.get(lowered)
    if method and not state.get("collection_method"):
        return await _execute_pharmacy_tool(db, store, customer_phone,
                                            "set_collection_method", {"method": method},
                                            user_text)
    payment = _CHECKOUT_PAYMENT_WORDS.get(lowered)
    if payment and state.get("collection_method") and not state.get("payment_method"):
        return await _execute_pharmacy_tool(db, store, customer_phone,
                                            "set_payment_method", {"method": payment},
                                            user_text)
    return None


# A numbered list is a promise: "1. X - $3" means the customer can answer "1".
# Nothing read those answers. In the real 0781276999 conversation every bare
# number - "2" for the branch, "6" for a mouthwash, "1, and 2" for two baby
# products, "2" for Delivery - was sent to search_products as the query, so the
# list on screen was ignored and the order could never be completed.
_NUMBERED_LINE = re.compile(r"^\s*(?:[*•\-]\s*)?(\d{1,2})\s*[.)]\s*(?P<body>.+?)\s*$")
_NUMBERED_PRICE = re.compile(r"^(?P<name>.+?)\s*[-–]\s*\$?\s*(?P<price>\d+(?:\.\d{1,2})?)\s*$")
# Words that may surround the numbers without changing what they mean.
_SELECTION_NOISE = {
    "add", "adds", "adding", "and", "plus", "also", "them", "both", "please", "pls",
    "i", "want", "wants", "need", "take", "the", "item", "items", "one", "ones",
    "no", "number", "numbers", "those", "these", "all", "of", "x", "for", "me",
    "get", "buy", "order", "thanks", "thank", "you", "too", "as", "well",
}


def _numbered_items(text: str) -> List[Dict[str, Any]]:
    """The numbered lines of a bot message, with any price attached."""
    items: List[Dict[str, Any]] = []
    for line in str(text or "").replace("\u00a0", " ").splitlines():
        match = _NUMBERED_LINE.match(line)
        if not match:
            continue
        # A cart line is "2. NAME x2 - $12" (line total, with a quantity). Not a
        # menu: reading one as a menu added $12 of mouthwash for a "2" that
        # meant Delivery.
        if re.search(r"\s[x×]\s*\d{1,3}\s*-\s*\$", line):
            continue
        body = match.group("body").replace("*", "").strip().strip(".")
        priced = _NUMBERED_PRICE.match(body)
        name = priced.group("name") if priced else body
        name = re.sub(r"\s+[x×]\s*\d{1,3}$", "", name, flags=re.I)
        price = priced.group("price") if priced else None
        name = re.sub(r"\s+", " ", name).strip(" -–:")
        if not name:
            continue
        try:
            price_value = round_price(float(price)) if price else None
        except (TypeError, ValueError):
            price_value = None
        items.append({"index": int(match.group(1)), "label": name, "price": price_value})
    return items


def _numbered_selection(text: str, count: int) -> List[int]:
    """The list numbers a reply refers to: "6", "1, and 2", "add 6 and 7, 13"."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", str(text or "").lower())
    words = [w for w in cleaned.split() if w]
    if not words or len(words) > 14:
        return []
    numbers, leftovers = [], []
    for word in words:
        if word.isdigit():
            numbers.append(int(word))
        elif word not in _SELECTION_NOISE:
            leftovers.append(word)
    if leftovers or not numbers:
        return []
    picked: List[int] = []
    for number in numbers:
        if 1 <= number <= count and number not in picked:
            picked.append(number)
    return picked


def _clean_branch(branch: Optional[str]) -> Optional[str]:
    """The branch name in a tool argument, or None when the model said "all"."""
    if not branch:
        return None
    value = str(branch).strip()
    if value.lower() in {"all", "any", "all branches", "every branch", "both",
                         "none", "null", "n/a", "all store branches"}:
        return None
    return value or None


def _phone_in_text(text: str) -> Optional[str]:
    """A phone number typed in the same breath as the choice ("2 0771234567")."""
    match = re.search(r"(?:\+263|00263|0)\s?\d(?:[\s-]?\d){8}\b", str(text or ""))
    return re.sub(r"[\s-]", "", match.group(0)) if match else None


def _strip_phone_from_text(text: str) -> Tuple[str, Optional[str]]:
    """Split "Farai Rato, 0716522473" into ("Farai Rato", "0716522473").

    A model often passes the whole customer message to update_delivery_name.
    Pulling the number out here keeps the name clean and saves both details in
    one turn, instead of rejecting the line as "not a name" and asking again.
    """
    raw = str(text or "").strip()
    found = _phone_in_text(raw)
    if not found:
        return raw, None
    phone, _ = normalize_phone(found)
    if not phone:
        return raw, None
    cleaned = re.sub(r"(?:\+263|00263|0)\s?\d(?:[\s-]?\d){8}\b", " ", raw)
    cleaned = re.sub(r"[\s,;|/]+", " ", cleaned).strip(" .,;:-")
    return cleaned, phone


def _delivery_next_state(state, name=None, phone=None, address=None) -> str:
    """The next missing detail in the delivery flow.

    The state is derived from what is actually saved, so a phone arriving at
    the name step (or a name arriving at the phone step) still moves the flow
    forward instead of asking for the same detail twice.
    """
    state = state or {}
    name_value = (name if name is not None else state.get("customer_name")) or ""
    phone_value = (phone if phone is not None
                   else state.get("customer_phone_delivery")) or ""
    address_value = (address if address is not None
                     else state.get("customer_address")) or ""
    if not str(name_value).strip():
        return "delivery_step_name"
    if not normalize_phone(phone_value)[0]:
        return "delivery_step_phone"
    if not str(address_value).strip():
        return "delivery_step_address"
    return "payment"


def _payment_word(label: str) -> Optional[str]:
    """The payment method a menu line offers ("EcoCash - via *151*#" -> ecocash)."""
    lowered = str(label or "").lower()
    for word, method in (("ecocash", "ecocash"), ("eco cash", "ecocash"),
                         ("onemoney", "onemoney"), ("one money", "onemoney"),
                         ("innbucks", "innbucks"), ("inn bucks", "innbucks"),
                         ("cash", "cash")):
        if word in lowered:
            return method
    return None


# "add these" / "all of them" after a list means every line of that list.
_SELECT_ALL_WORDS = {"these", "them", "all", "both", "everything"}
_SELECT_ALL_FILLER = _SELECTION_NOISE | _SELECT_ALL_WORDS | {
    "to", "cart", "order", "it", "list", "please", "now",
}


def _selects_all(text: str) -> bool:
    """True when the reply means "every product on that list"."""
    words = re.findall(r"[a-z]+", str(text or "").lower())
    if not words or not any(word in _SELECT_ALL_WORDS for word in words):
        return False
    return all(word in _SELECT_ALL_FILLER for word in words)


def _branch_in_text(text: str, branches: List[str]) -> Optional[str]:
    """The branch a bot message says the products are at ("Bulawayo branch")."""
    lowered = str(text or "").lower()
    for branch in branches:
        if f"{branch.lower()} branch" in lowered or f"at {branch.lower()}" in lowered:
            return branch
    return None


async def _numbered_choice_reply(db, store, user_text: str,
                                 history: Optional[List[Dict[str, str]]],
                                 customer_phone: Optional[str]) -> Optional[str]:
    """Answer "6" / "1, and 2" against the numbered list the bot just sent.

    Products are added by their catalogue name (the store's price wins, so a
    stale list can never set the price), the collection and payment menus are
    saved where the customer can see them, and a category list is opened.
    """
    if not (db and store and user_text and customer_phone and history):
        return None
    # The list is the last message - except when "which branch?" came in
    # between ("add 6 and 7, 13, 14" was answered that way), so allow exactly
    # that one step back. Looking back further made "2" for Delivery add an old
    # list's second product instead. A cart display is not a menu - its
    # "1. NAME x2 - $10" lines are what the customer already has.
    says = [message.get("content") or "" for message in (history or [])
            if message.get("role") == "assistant"]
    if not says:
        return None
    is_cart_display = re.compile(r"\bsubtotal\b|order summary|your cart", re.I)
    last_bot = says[-1]
    items = [] if is_cart_display.search(last_bot) else _numbered_items(last_bot)
    if len(items) < 2 and "which branch" in last_bot.lower() and len(says) >= 2:
        earlier = says[-2]
        if not is_cart_display.search(earlier):
            earlier_items = _numbered_items(earlier)
            if len(earlier_items) >= 2:
                items, last_bot = earlier_items, earlier
    if len(items) < 2:
        return None
    picked = _numbered_selection(user_text, len(items))
    take_all = not picked and _selects_all(user_text)
    if not picked and not take_all:
        return None
    chosen = list(items) if take_all else [items[number - 1] for number in picked]
    state = _get_order_state(db, str(store.id), customer_phone) or {}
    labels = [item["label"].lower() for item in chosen]
    lowered_bot = (last_bot or "").lower()
    branches = _branches_for_store(db, store)

    # 1) Branch menu: "1. Angwa" -> the branch the customer is shopping from.
    if branches and not state.get("cart_items") and all(
            any(label == branch.lower() for branch in branches) for label in labels):
        branch = next(branch for branch in branches if branch.lower() == labels[0])
        _update_order_state(db, str(store.id), customer_phone, selected_branch=branch)
        return f"Great - *{branch}* branch.\n\nWhat can I help you with today?"

    # 2) Collection menu: "1. Walk-in / 2. Delivery" -> saved immediately.
    if ("collect" in lowered_bot and "delivery" in lowered_bot
            and not state.get("collection_method")
            and all(re.search(r"walk[- ]?in|delivery|pick ?up|collect", label) for label in labels)
            and not any(item["price"] for item in chosen)):
        method = "delivery" if "deliver" in labels[0] else "walkin"
        return await _execute_pharmacy_tool(db, store, customer_phone,
                                            "set_collection_method", {"method": method},
                                            user_text)

    # 3) Payment menu: "1. Cash / 2. EcoCash" (often with a trail of
    # explanation after a dash, so match the method word, not the whole line).
    pay_methods = [_payment_word(label) for label in labels]
    if ("pay" in lowered_bot and all(pay_methods)
            and not state.get("payment_method")):
        pay_args = {"method": pay_methods[0]}
        number = _phone_in_text(user_text)
        if number:
            pay_args["mobile_number"] = number
        tool_reply = await _execute_pharmacy_tool(
            db, store, customer_phone, "set_payment_method", pay_args, user_text)
        if tool_reply.upper().startswith("PAYMENT DETAILS INCOMPLETE"):
            # The tool's text is aimed at the model ("call set_payment_method
            # again") - a customer must only be asked for the number.
            method = pay_methods[0]
            label = "EcoCash" if method == "ecocash" else method.title()
            return (f"{label} it is - which number should the payment request go to?\n\n"
                    "Send the 10-digit number, e.g. 0771234567.")
        return tool_reply

    # 4) Product list with prices -> add exactly those products. A medicine is
    # never added straight from a number or an "add all": it keeps the
    # pharmacist double-check the gate applies to a named medicine.
    if all(item["price"] for item in chosen):
        medicines = [item for item in chosen
                     if is_medication_related(item["label"].lower())]
        chosen = [item for item in chosen if item not in medicines]
        branch = (state.get("selected_branch")
                  or _branch_in_text(last_bot, branches)
                  or next((i.get("branch") for i in (state.get("cart_items") or []) if i.get("branch")), None))
        results, added = [], []
        for item in chosen:
            tool_reply = await _execute_pharmacy_tool(
                db, store, customer_phone, "add_to_cart",
                {"product_name": item["label"], "price": item["price"],
                 "quantity": 1, "branch": branch}, user_text)
            results.append(tool_reply)
            if tool_reply.startswith("Added "):
                added.append(item["label"])

        cart = (_get_order_state(db, str(store.id), customer_phone) or {}).get("cart_items") or []
        cart_names = {(i.get("product_name") or "").lower() for i in cart}
        missing = [item["label"] for item in chosen if item["label"].lower() not in cart_names]
        if not added and missing and not medicines:
            # Nothing from the list could be added (not stocked, or a branch
            # clash) - say why instead of pretending the list was understood.
            return results[0]
        if not added and medicines:
            return sure_confirmation_message(medicines[0]["label"])
        lines = ["*ADDED TO CART*", ""]
        for item in chosen:
            if item["label"] not in missing:
                lines.append(f"- {item['label']} - {format_price(item['price'])}")
        if missing:
            lines.append("")
            lines.append("Not available: " + ", ".join(missing))
        lines.append("")
        lines.append(_format_cart_summary(cart))
        if medicines:
            # A medicine from the list keeps the pharmacist double-check.
            lines.append("")
            lines.append(sure_confirmation_message(medicines[0]["label"]))
        lines.append("")
        if not medicines:
            lines.append("Would you like to proceed to checkout?")
        return "\n".join(lines)

    # 5) Category list without prices ("1. Skincare (Nivea, ...)") -> open it.
    if all(not item["price"] for item in chosen) and "categor" in lowered_bot:
        branch = state.get("selected_branch") or _branch_in_text(last_bot, branches)
        sections = []
        for item in chosen[:3]:
            term = re.sub(r"\s*\(.*?\)", "", item["label"]).strip()
            result = await _execute_pharmacy_tool(
                db, store, customer_phone, "search_products",
                {"query": term, "branch": branch}, user_text)
            body = re.sub(r"^(FOUND:|NOT FOUND:)\s*", "", result).strip()
            sections.append(f"*{term.title()}*\n{body}")
        return "\n\n".join(sections)
    return None


_DELIVERY_NAME_NOISE = {
    "yes", "yeah", "no", "ok", "okay", "sure", "cancel", "stop", "help", "cart",
    "checkout", "done", "hi", "hello", "hey", "thanks", "thank", "you", "please",
    "delivery", "collect", "cash", "ecocash", "what", "which", "where", "how",
    # Sentences a customer types when they are not giving a name. Without these
    # "i dont know" and "maybe later" were saved as the customer's name.
    "i", "im", "i'm", "dont", "don't", "do", "not", "no", "know", "maybe",
    "later", "skip", "none", "nothing", "have", "want", "need", "am", "is",
    "are", "my", "me", "the", "a", "an", "and", "or", "id", "i'd", "ill",
}


def _looks_like_a_name(text: str) -> bool:
    """True for the shortest thing a customer types at "what is your name?"."""
    value = str(text or "").strip()
    if not value or "?" in value or len(value) > 160:
        return False
    words = value.split()
    if not 1 <= len(words) <= 10:
        return False
    for word in words:
        if not re.fullmatch(r"[^\W\d_][^\W\d_'\-]*(?:['\-][^\W\d_]+)*", word, re.UNICODE):
            return False
        if word.lower() in _DELIVERY_NAME_NOISE:
            return False
    return True


async def _delivery_name_reply(db, store, user_text: str, history, customer_phone: str) -> Optional[str]:
    """Save a name typed at the delivery-name step instead of product-matching it.

    "farai rato" was answered with "Did you mean *Ara-crampstop*?", which is how
    the real 0781276999 checkout stalled for an hour.
    """
    if not (db and store and user_text and customer_phone):
        return None
    state = _get_order_state(db, str(store.id), customer_phone) or {}
    if (state.get("current_state") or "") != "delivery_step_name":
        return None
    if not _looks_like_a_name(user_text):
        return None
    if _named_categories(user_text) or is_medication_question(user_text):
        return None

    name = " ".join(str(user_text).split())
    next_step = _delivery_next_state(state, name=name)
    _update_order_state(db, str(store.id), customer_phone,
                        customer_name=name, current_state=next_step)
    if next_step != "delivery_step_phone":
        return f"Thanks, *{name}*!\n\n" + await _resume_checkout(db, store, customer_phone, user_text)
    on_file = state.get("customer_phone_delivery")
    lines = [f"Thanks, *{name}*!", "", "*Step 2 of 3*",
             "What is your *phone number*?", "", "_Example: 0771234567_"]
    if on_file:
        lines += ["", f"The number I have for you is *{on_file}* - reply *YES* to keep it."]
    return "\n".join(lines)


async def _generate_bot_reply(
    db: Session, user_text: str, store, history: Optional[List[Dict[str, str]]] = None,
    image_urls: Optional[List[str]] = None,
    customer_phone: Optional[str] = None,
    conv_id: Optional[str] = None,
    account_id: Optional[str] = None
) -> str:
    # Payment status must come from the provider/order, never from the model's
    # reading of an approval prompt or an order confirmation.
    if customer_phone and not image_urls and re.search(
        r'\b(?:payment|paynow|ecocash|onemoney|innbucks)\b', user_text, re.I
    ) and re.search(r'\b(?:status|paid|successful|succeeded|failed|went through|confirmed|check)\b', user_text, re.I):
        from modules.whatsapp.models import WhatsAppOrder
        from modules.whatsapp.payment_service import WhatsAppPaymentService
        order = (db.query(WhatsAppOrder).filter(
            WhatsAppOrder.store_id == store.id,
            WhatsAppOrder.customer_phone.in_([customer_phone, _normalize_state_phone(customer_phone)])
        ).order_by(WhatsAppOrder.created_at.desc()).first())
        if order:
            state = WhatsAppPaymentService(db).check_payment_status(str(order.id))
            status_value = state.get('status')
            messages = {
                'paid': 'Your payment was confirmed as successful.',
                'failed': 'Your payment failed. No successful payment has been confirmed. Please contact the store to retry or choose another payment method.',
                'cancelled': 'Your payment was cancelled. No successful payment has been confirmed. Please contact the store to retry or choose another payment method.',
                'canceled': 'Your payment was cancelled. No successful payment has been confirmed. Please contact the store to retry or choose another payment method.',
                'refunded': 'Your payment was refunded.',
                'processing': 'Your payment is still pending. It has not been confirmed as successful.',
                'unavailable': 'I could not check the payment provider right now. Your payment has not been confirmed; please try again shortly.',
                'error': 'I could not check your payment status right now. Please try again shortly.',
            }
            return f"Order *{order.order_number}*: " + messages.get(status_value, 'Your payment has not been confirmed yet.')
    # Greetings are answered from code, before any model or product search runs.
    if not image_urls:
        greeting = _branded_greeting(db, store, customer_phone, user_text, returning=bool(history))
        if greeting:
            return greeting

    # MEDICATION / PRESCRIPTION QUESTIONS: hand over to a pharmacist before any
    # tool or model runs - including the caption on a photo, so "here is my
    # script" never reaches the model just because an image came with it.
    pharmacist_reply = _medication_question_guard(store, user_text)
    if pharmacist_reply:
        return pharmacist_reply

    if store and _is_pharmacy_store(store) and not image_urls and _is_general_catalogue_request(user_text):
        try:
            state = _get_order_state(db, str(store.id), customer_phone) if customer_phone else None
            return _catalogue_categories_reply(db, store, (state or {}).get('selected_branch'))
        except Exception:
            logger.exception('Could not list catalogue categories for store %s', store.id)
            return 'Tell me what product you are looking for and I can check the catalogue.'

    context = _business_context(store)
    faq_text = _faq_context(db, store)
    if faq_text:
        context += "\n\n=== FAQ ===\n" + faq_text
    name = store.store_name if store else "the store"
    bot_name, custom_rules = _bot_config(db, store)

    # The pharmacy flow (product search, cart, checkout, medication gates) is
    # for ANY pharmacy store. It used to be hardcoded to Platinum, so Express
    # Care got no tools and no catalogue context and could not sell anything.
    is_pharmacy_store = _is_pharmacy_store(store)

    # When the real OpenClaw agent is driving a pharmacy turn, it must own
    # product search and cart/checkout tool calls. Python keeps the hard safety
    # gates above and the store state below, but it must not inject a second,
    # possibly stale, product search result into the agent's prompt.
    use_openclaw_agent = bool(
        OPENCLAW_BRAIN_ENABLED and is_pharmacy_store and customer_phone and not image_urls
    )

    # Menus, names and checkout answers are read by the model from the
    # conversation history and saved through tools. The deterministic
    # pre-model gates that used to answer these turns were removed: they kept
    # their own stale copy of the order state, so a fresh "2 = Delivery" could
    # be rejected because an old walk-in choice was still stored.
    pharmacy_state = {}
    current_state = ""
    if is_pharmacy_store and customer_phone:
        pharmacy_state = _get_order_state(db, str(store.id), customer_phone) or {}
        current_state = pharmacy_state.get("current_state", "") or ""

    if is_pharmacy_store and customer_phone and not image_urls:
        if not pharmacy_state.get("cart_items"):
            last_reply = last_assistant_message(history)
            if (any(marker in last_reply.lower().replace("*", "") for marker in ("order confirmed", "order placed"))
                    and is_affirmative(user_text)):
                match = re.search(r"\b[A-Z]{2}-\d{8}-[A-Z0-9]{4}\b", last_reply, re.I)
                reference = f" *{match.group(0)}*" if match else ""
                return (f"Your order{reference} has already been placed. "
                        "Your payment is confirmed once it goes through.")
            if (re.search(r"\b(?:change|update|correct)\b.*\baddress\b", user_text, re.I)
                    and not looks_like_address(user_text)):
                return "Please send the new delivery address for your order, including the street, suburb and city."
        if (not pharmacy_state.get("cart_items") and looks_like_address(user_text)
                and (re.search(r"\b(?:address|deliver|delivery)\b", user_text, re.I)
                     or "address" in last_assistant_message(history).lower())):
            return await _execute_pharmacy_tool(db, store, customer_phone,
                                                "update_delivery_address", {"address": user_text}, user_text)
        if (current_state == "awaiting_checkout"
                and "proceed to checkout" in last_assistant_message(history).lower()
                and not extract_sure_check_item(last_assistant_message(history))):
            if is_affirmative(user_text):
                return await _execute_pharmacy_tool(db, store, customer_phone, "start_checkout", {}, user_text)
            if is_negative(user_text):
                return await _execute_pharmacy_tool(db, store, customer_phone, "go_back_to_cart", {}, user_text)
            if re.fullmatch(r"(?:i\s+)?(?:want|like|will take|take)\s+(?:that|this)\s+(?:one|item|product)[.! ]*", user_text.strip(), re.I):
                return "That item is already in your cart. Would you like to proceed to checkout?"
        name_reply = await _delivery_name_reply(db, store, user_text, history, customer_phone)
        if name_reply:
            return name_reply

    # MEDICATION SAFETY GATE: an unsure customer is handed to the pharmacist
    # (never suggested medication), a sure one is asked to double-check first.
    if is_pharmacy_store and customer_phone and user_text and not image_urls:
        gate_reply, rewritten_text = _pharmacy_intent_gate(
            db, store, user_text, history, customer_phone
        )
        if gate_reply:
            logger.info("Pharmacy gate replying directly for %s", customer_phone)
            return gate_reply
        if rewritten_text:
            logger.info("Pharmacy gate restating request: %s", rewritten_text)
            user_text = rewritten_text

    if is_pharmacy_store and customer_phone and not image_urls:
        choice_reply = await _checkout_choice_reply(
            db, store, user_text, customer_phone, history)
        if choice_reply:
            return choice_reply

    if (is_pharmacy_store and customer_phone and not image_urls
            and pharmacy_state.get("current_state") == "confirm"
            and is_affirmative(user_text)):
        return await _execute_pharmacy_tool(
            db, store, customer_phone, "confirm_order", {}, user_text)

    # Get current order state for context (cart, branch, etc.)
    order_state_context = ""
    current_branch = None
    cart_before = []
    if is_pharmacy_store and customer_phone:
        try:
            state = _get_order_state(db, str(store.id), customer_phone)
            if state:
                cart_items = state.get("cart_items", [])
                cart_before = list(cart_items)
                # Determine current branch from cart or state
                if cart_items:
                    current_branch = cart_items[0].get("branch") or state.get("selected_branch")
                else:
                    current_branch = state.get("selected_branch")

                # Build context for AI - always include state info, not just when cart has items
                order_state_context = "\n\n=== CURRENT ORDER STATE ===\n"
                current_state = state.get("current_state", "cart")

                # Flow state descriptions for AI context
                state_descriptions = {
                    "cart": "Customer is browsing/shopping. Can search products, add to cart, or checkout.",
                    "awaiting_collection": "Customer is choosing collection method (walk-in or delivery). When they choose, call set_collection_method with their choice.",
                    "delivery_step_name": "Customer needs to provide their NAME for delivery. Use update_delivery_name tool when they provide it.",
                    "delivery_step_phone": "Customer needs to provide their PHONE NUMBER for delivery. Use update_delivery_phone tool when they provide it.",
                    "delivery_step_address": "Customer needs to provide their DELIVERY ADDRESS. Ask for their full address with an example (e.g. '670 Ushewekunze Street, Mabelreign, Harare'). Use update_delivery_address tool when they provide it.",
                    "payment": "Customer is choosing payment method (Cash, EcoCash, OneMoney, InnBucks). When they choose, call set_payment_method with their choice.",
                    "confirm": "Customer is reviewing order summary and needs to confirm. Use confirm_order tool when they say yes.",
                    "payment_retry": "Payment failed. Customer can retry, switch to cash, or choose another method.",
                }

                order_state_context += f"**FLOW STATE: {current_state}**\n"
                order_state_context += f"_{state_descriptions.get(current_state, 'Unknown state')}_\n\n"

                if current_branch:
                    order_state_context += f"**ACTIVE BRANCH: {current_branch}** (all searches and orders are from this branch)\n\n"

                # Cart info
                if cart_items:
                    subtotal = cart_subtotal(cart_items)
                    order_state_context += f"Cart has {len(cart_items)} item(s):\n"
                    for item in cart_items:
                        order_state_context += f"- {item.get('product_name')}: {format_price(item.get('price', 0))} x {item.get('quantity', 1)}\n"
                    order_state_context += f"Subtotal: {format_price(subtotal)}\n\n"
                else:
                    order_state_context += "Cart is empty.\n\n"

                # Delivery details (always show what we have)
                order_state_context += "**DELIVERY DETAILS ON FILE:**\n"
                order_state_context += f"- Name: {state.get('customer_name') or 'Not provided'}\n"
                order_state_context += f"- Phone: {state.get('customer_phone_delivery') or 'Not provided'}\n"
                order_state_context += f"- Address: {state.get('customer_address') or 'Not provided'}\n\n"

                if state.get("collection_method"):
                    order_state_context += f"Collection method: {state.get('collection_method')}\n"
                if state.get("payment_method"):
                    order_state_context += f"Payment method: {state.get('payment_method')}\n"

                order_state_context += "\nIMPORTANT: Use the appropriate tools to update details. When customer provides name/phone/address, call the corresponding update tool.\n"
        except Exception as e:
            logger.warning("Could not get order state: %s", e)

    # Get available branches early for the pharmacy flow
    available_branches = []
    if is_pharmacy_store:
        try:
            available_branches = _listed_store_branches(db, store)
        except Exception as e:
            logger.warning("Could not fetch branches: %s", e)

    # A message that names a shelf is answered here, from the catalogue, before
    # the model. This is safe for the OpenClaw agent too: it is a deterministic
    # catalogue read, not a conversational gate, and the agent still owns the
    # cart action when the customer replies with a number.
    if is_pharmacy_store and user_text and current_state not in _CHECKOUT_STATES \
            and _is_pure_category_request(user_text) and not is_purchase_intent(user_text) \
            and not _is_cart_edit_message(user_text):
        browse = _category_browse_reply(db, store, user_text,
                                        pharmacy_state.get("selected_branch"))
        if browse:
            logger.info("Category browse answered from code: %r", user_text)
            return browse

    # Search for products/medications if customer mentions a brand/product name.
    # Skip this when the OpenClaw agent is driving the turn: its MCP search is
    # the source of truth and a stale Python "not found" would make the agent
    # tell the customer an item is out of stock.
    product_context = ""
    medication_context = ""
    found_product_keyword = None
    products_by_branch = {}  # Track which branches have the product
    spelling_suggestion = None  # "Did you mean ...?" for misspelled products

    if is_pharmacy_store and user_text and current_state not in _CHECKOUT_STATES \
            and not _numbered_selection(user_text, 99) and not use_openclaw_agent:
        user_lower = user_text.lower()

        # Check if user is asking for price comparison (might be a follow-up question)
        price_comparison_phrases = ["which is cheaper", "which branch is cheaper", "cheapest",
                                   "best price", "lowest price", "compare price", "price comparison",
                                   "which has better price", "where is it cheaper", "cheaper branch"]
        is_price_comparison_query = any(phrase in user_lower for phrase in price_comparison_phrases)

        # If asking for price comparison but no product in current message, check history
        if is_price_comparison_query and history:
            # Look for product mentions in recent history
            history_text = " ".join([m.get("content", "") for m in (history or [])[-6:]]).lower()
            brands_to_check = ["nivea", "vaseline", "olay", "neutrogena", "revlon", "maybelline",
                              "loreal", "pantene", "palmers", "dove", "garnier", "simple"]
            for brand in brands_to_check:
                if brand in history_text and brand not in user_lower:
                    # Found a product in history, search for it
                    logger.info("Price comparison follow-up: found '%s' in history", brand)
                    for branch in available_branches:
                        products = _search_products_by_keyword(db, store, brand, limit=10, branch=branch)
                        if products:
                            products_by_branch[branch] = products
                    if products_by_branch:
                        found_product_keyword = brand
                    break

        # First check for medications/prescriptions - only what the branch's
        # own price list holds, so a quotation can never invent a product.
        quote_state = _get_order_state(db, str(store.id), customer_phone) or {}

        medications = _search_medications(db, store, user_text,
                                          branch=quote_state.get("selected_branch"),
                                          limit=5)
        if medications:
            medication_context = "\n\n=== MEDICATION QUOTATION ===\n"
            medication_context += _format_medication_quotation(
                medications, store_name=store.store_name)
            medication_context += "\n\nIMPORTANT: Show this EXACT quotation to the customer. Include all items and the total."

        # Check for product keywords (brands and common terms)
        # Include common typos and variations
        # Include specific variants like "nivea men" before generic "nivea" so they match first
        brands_to_search = ["nivea men", "nivea for men", "nivea women", "nivea for women",
                           "nivea q10", "nivea q 10", "vaseline men", "vaseline cera",
                           "nivea", "nivia", "niva", "vaseline", "vasline", "olay", "neutrogena",
                           "revlon", "maybelline", "mac", "loreal", "l'oreal", "pantene",
                           "schwarzkopf", "sorbet", "palmers", "pool", "slk", "skin republic",
                           "simple", "zora", "zaron", "rexona", "sunscreen", "sunblock", "serum",
                           "shampoo", "conditioner", "lotion", "cream", "lipstick", "mascara",
                           "powder", "blush", "panadol", "panado", "aspirin", "ibuprofen",
                           "antibiotic", "vitamin", "q10", "q 10", "collagen", "moisturizer",
                           "moisturiser", "soap", "deodorant", "perfume", "cologne", "baby",
                           "diaper", "nappy", "tablet", "syrup", "capsule", "ointment"]

        # Map multi-word searches to database search terms
        search_term_mapping = {
            "nivea men": "nivea men",
            "nivea for men": "nivea men",
            "nivea women": "nivea women",
            "nivea for women": "nivea women",
            "nivea q10": "nivea q10",
            "nivea q 10": "nivea q10",
            "vaseline men": "vaseline men",
            "vaseline cera": "vaseline cera"
        }

        # Map typos to correct search terms
        typo_corrections = {"nivia": "nivea", "niva": "nivea", "vasline": "vaseline"}

        detected_typo = None
        corrected_term = None
        for brand in brands_to_search:
            if brand in user_lower:
                found_product_keyword = brand
                # Check if this is a multi-word search term mapping
                if brand in search_term_mapping:
                    search_term = search_term_mapping[brand]
                # Check if this is a known typo
                elif brand in typo_corrections:
                    detected_typo = brand
                    corrected_term = typo_corrections[brand]
                    search_term = corrected_term
                else:
                    search_term = brand
                logger.info("Product search triggered: keyword='%s', search_term='%s', typo=%s", brand, search_term, detected_typo)
                # Search across ALL branches to check availability
                for branch in available_branches:
                    products = _search_products_by_keyword(db, store, search_term, limit=25, branch=branch)
                    if products:
                        products_by_branch[branch] = products
                        logger.info("Found %d products for '%s' in branch '%s'", len(products), search_term, branch)
                break

        # Also check for general product queries (e.g., "do you have X")
        # Skip this if user is referring to an image (e.g., "do you have it/this/that")
        image_reference_words = ["it", "this", "that", "these", "those", "the product", "this product", "that product"]
        if not found_product_keyword and any(phrase in user_lower for phrase in ["do you have", "is there", "looking for", "i need", "i want", "searching for"]):
            # Extract what they're looking for - get words after the phrase
            for phrase in ["do you have", "is there", "looking for", "i need", "i want", "searching for"]:
                if phrase in user_lower:
                    search_term = user_lower.split(phrase)[-1].strip().strip("?").strip()
                    # Skip if it's a reference to an image (e.g., "it", "this", "that")
                    if search_term and len(search_term) > 2 and search_term.lower() not in image_reference_words:
                        found_product_keyword = search_term
                        for branch in available_branches:
                            products = _search_products_by_keyword(db, store, search_term, limit=25, branch=branch)
                            if products:
                                products_by_branch[branch] = products
                        break

        # Check for follow-up questions about a product mentioned in conversation history
        # e.g., "what type do you have", "which ones", "show me", "list them"
        followup_phrases = ["what type", "which type", "what kind", "which kind", "what do you have",
                           "which ones", "show me", "list them", "what options", "what varieties",
                           "in stock", "available", "do you have any"]
        if not found_product_keyword and history and any(phrase in user_lower for phrase in followup_phrases):
            # Look through recent history for a product mention
            logger.info("Checking history for product context (follow-up question)")
            for msg in reversed(history[-10:]):
                if msg.get("role") == "user":
                    msg_lower = msg.get("content", "").lower()
                    # Check if this historical message mentions a brand
                    for brand in brands_to_search:
                        if brand in msg_lower:
                            found_product_keyword = brand
                            if brand in search_term_mapping:
                                search_term = search_term_mapping[brand]
                            else:
                                search_term = brand
                            logger.info("Found product '%s' in history for follow-up question", brand)
                            for branch in available_branches:
                                products = _search_products_by_keyword(db, store, search_term, limit=25, branch=branch)
                                if products:
                                    products_by_branch[branch] = products
                            break
                    if found_product_keyword:
                        break

        # Reuse the price comparison check from earlier
        wants_price_comparison = is_price_comparison_query

        # Spelling-tolerant fallback: the brand list above didn't match, so
        # fuzzy-match the message against the catalogue. This is what makes
        # "benylin 4 flu", "benylin for flu" and "benilyn" all resolve to Benylin.
        #
        # It must ONLY run for product questions. "whats my order number" and
        # "which branches do you have" were being fuzzy-matched into "Did you
        # mean Cerelac?" / "Did you mean ANKLE BRACE?" and answered with a
        # spelling prompt instead of the thing that was asked.
        # "personal care products" and "hair care and oral care" name a shelf,
        # not a product. Left to the fuzzy match below they became "Did you mean
        # *Sensodyne*?" and "Did you mean *Hair*?" - the two answers a real
        # customer complained about.
        # "add 6 and 7, 13, 14" with no list on screen is a question about which
        # item, never a product search - it used to come back as "Did you mean
        # *3/0 VICRYL 26MM REVERSE CUTTING 75CM*?".
        # A bare number is read against the menu the bot just sent (the model
        # sees that menu in the conversation history). It is never a product
        # search, so the preview above is skipped for numbered replies.

        if not found_product_keyword and not products_by_branch and \
                _looks_like_product_question(user_text):
            smart = _search_products_smart(db, store, _clean_product_query(user_text), limit=25)
            if smart["products"]:
                found_product_keyword = smart["typed_query"] or user_text
                spelling_suggestion = smart["did_you_mean"]
                if spelling_suggestion:
                    logger.info("Fuzzy product match: '%s' -> '%s'", user_text, spelling_suggestion)
                # Search each branch so the normal "which branch" flow still works
                for branch in available_branches:
                    term = spelling_suggestion.split()[0].lower() if spelling_suggestion else None
                    products = _search_products_by_keyword(
                        db, store, term or found_product_keyword, limit=25, branch=branch
                    )
                    if products:
                        products_by_branch[branch] = products
                if not products_by_branch:
                    products_by_branch = {"All branches": smart["products"]}

        # Build product context based on whether we found products
        if products_by_branch and found_product_keyword:
            # Found products - list availability by branch
            branches_with_product = list(products_by_branch.keys())
            # Keep the price next to every name: the model used to be given
            # names only and then invented a price (DOVE SOAP quoted as $1 when
            # the catalogue says $4.40).
            product_names = []
            for branch, prods in products_by_branch.items():
                for p in prods[:5]:
                    entry = f"{p['name']} - {p['price']}"
                    if entry not in product_names:
                        product_names.append(entry)

            # If user wants price comparison, show prices from ALL branches
            if wants_price_comparison:
                product_context = f"\n\n=== PRICE COMPARISON FOR '{found_product_keyword.upper()}' ACROSS BRANCHES ===\n"
                for branch in sorted(products_by_branch.keys()):
                    prods = products_by_branch[branch]
                    product_context += f"\n**{branch} Branch:**\n"
                    for p in prods[:5]:  # Show top 5 products per branch
                        product_context += f"  - {p['name']}: {p['price']}\n"

                product_context += (
                    "\n\nIMPORTANT: The customer wants to compare prices across branches. "
                    "Compare the prices shown above and tell them which branch has the CHEAPEST price "
                    "for the product they're looking for. Be specific about which product and the price difference.\n"
                    "Example: 'The cheapest option is at [Branch] where [Product] costs $X, "
                    "compared to $Y at [Other Branch].'"
                )
            # A misspelled / indirect product name - confirm the spelling first
            elif spelling_suggestion:
                product_context = f"\n\n=== SPELLING CORRECTION NEEDED ===\n"
                product_context += f"Customer typed: '{found_product_keyword}'\n"
                product_context += f"Did they mean: '{spelling_suggestion}'?\n"
                product_context += f"We have {sum(len(p) for p in products_by_branch.values())} matching products.\n"
                product_context += f"Products: {', '.join(product_names[:5])}\n"
                product_context += (
                    "\n\nIMPORTANT: First ask the customer to confirm the spelling, e.g. "
                    f"'Did you mean *{spelling_suggestion.split()[0].capitalize()}*? "
                    "We have these options:' then list the products above. "
                    "Do NOT add anything to the cart until they confirm."
                )
            # Check if we detected a typo - ask for confirmation first
            elif detected_typo and corrected_term:
                product_context = f"\n\n=== SPELLING CORRECTION NEEDED ===\n"
                product_context += f"Customer typed: '{detected_typo}'\n"
                product_context += f"Did they mean: '{corrected_term}'?\n"
                product_context += f"We have {sum(len(p) for p in products_by_branch.values())} '{corrected_term.upper()}' products available.\n"
                product_context += f"Sample products: {', '.join(product_names[:3])}\n"
                product_context += (
                    "\n\nIMPORTANT: First ask the customer to confirm they meant the corrected spelling.\n"
                    f"Example response: 'Did you mean *{corrected_term.capitalize()}*? "
                    f"We have {corrected_term.capitalize()} products available. Please confirm and I\\'ll show you the options.'\n"
                    "Wait for their confirmation (yes, yeah, correct, etc.) before showing branch options."
                )
            else:
                product_context = f"\n\n=== PRODUCT AVAILABILITY FOR '{found_product_keyword.upper()}' ===\n"
                product_context += f"Found {sum(len(p) for p in products_by_branch.values())} matching products.\n"
                product_context += f"Available at branches: {', '.join(branches_with_product)}\n"
                product_context += f"Products (name - price): {', '.join(product_names[:8])}\n"
                product_context += (
                    "\n\nIMPORTANT: These results are the source of truth. Answer with the "
                    "product name and price shown and say which branch it is available at.\n"
                    "DO NOT ask which branch - the search already covered every branch.\n"
                    "If the customer asked for the product, add it with add_to_cart; if they "
                    "only asked whether we have it, show it and let them decide."
                )
        elif found_product_keyword and not products_by_branch:
            # Searched but found nothing
            product_context = f"\n\n=== PRODUCT SEARCH: '{found_product_keyword.upper()}' ===\n"
            product_context += "No matching products found in our inventory.\n"
            product_context += "Let the customer know we don't currently have this item and offer to help with something else."

        # If an image is sent, handle image identification
        if image_urls and not product_context and not medication_context:
            # Load products for image matching - load multiple popular brands
            popular_brands = ["nivea", "vaseline", "olay", "loreal", "pantene", "neutrogena",
                            "dove", "garnier", "maybelline", "revlon", "palmers", "simple"]
            all_products = []

            # First try to extract brand from user text if any
            detected_brand = None
            if user_text:
                for brand in popular_brands:
                    if brand in user_text.lower():
                        detected_brand = brand
                        break

            if detected_brand:
                # Load products matching the detected brand
                all_products = _search_products_by_keyword(db, store, detected_brand, limit=50)
                product_context = f"\n\n=== {detected_brand.upper()} PRODUCTS IN STOCK ===\n"
            else:
                # Load products from multiple popular brands for better matching
                product_context = "\n\n=== PRODUCTS IN STOCK (SAMPLE) ===\n"
                for brand in popular_brands[:6]:  # Load from top 6 brands
                    brand_products = _search_products_by_keyword(db, store, brand, limit=15)
                    all_products.extend(brand_products)
                # Also load some general products
                general_products = _search_products_by_keyword(db, store, "", limit=30)
                all_products.extend(general_products)
                # Remove duplicates (keep first occurrence)
                seen = set()
                unique_products = []
                for p in all_products:
                    if p['name'] not in seen:
                        seen.add(p['name'])
                        unique_products.append(p)
                all_products = unique_products[:80]  # Limit to 80 products

            if all_products:
                product_context += _format_product_list(all_products)
                product_context += (
                    "\n\n=== IMAGE IDENTIFICATION INSTRUCTIONS ===\n"
                    "The customer sent an image of a product. YOU MUST:\n"
                    "1. Identify the product/brand in the image (e.g., 'I can see this is a Nivea Q10 product')\n"
                    "2. Search the product list above for matches:\n"
                    "   - If you find the EXACT product, confirm: 'Yes, we have [product name] in stock!'\n"
                    "   - If you find SIMILAR products (same brand), say: 'We have these [brand] products available:' and list 3-5 options\n"
                    "   - If the brand exists in our list but not that specific variant, say: 'We don't have that exact variant, but we have these [brand] options:'\n"
                    "3. NEVER say 'I'm unable to confirm' or 'contact your nearest branch' if you can identify the brand and we have ANY products from that brand!\n"
                    "4. Say which branch each option is available at (do not ask which branch -\n"
                    "   the list above already covers every branch).\n\n"
                    "CRITICAL: If you see a Nivea product in the image and we have ANY Nivea products in the list, you MUST list those Nivea products as options!"
                )
            else:
                product_context = (
                    "\n\n=== IMAGE HANDLING ===\n"
                    "The customer sent a product image. Identify what you see and let them know "
                    "you'll check availability. Ask them to confirm the product name so you can search."
                )

    # Without prior history, this is the first message in the conversation - a
    # one-time welcome + self-introduction is appropriate. With history, the
    # model already sees the prior exchange below, so instruct it not to
    # re-introduce/re-welcome every single reply (that repeated "I'm X" intro
    # on every message was the reported bug).
    # Check if user sent a bare greeting (hi, hello, hey, etc.)
    is_bare_greeting = _is_greeting_only(user_text)

    # Check if user is selecting a branch (branches already fetched above)
    # IMPORTANT: Only interpret numbers as branch selection if bot JUST asked about branches
    user_lower = user_text.strip().lower() if user_text else ""
    selected_branch = None
    invalid_branch_selection = False

    # Check if the last bot message was asking about branches
    is_branch_context = False
    if history:
        for msg in reversed(history[-3:]):
            if msg.get("role") == "assistant":
                last_bot = (msg.get("content") or "").lower()
                # Check if bot was asking about branches specifically
                if any(phrase in last_bot for phrase in _BRANCH_QUESTION_MARKERS):
                    is_branch_context = True
                break

    if available_branches and is_branch_context:
        # Only check for branch selection if context is branch-related
        for i, branch in enumerate(available_branches, 1):
            if user_lower == str(i) or user_lower == branch.lower():
                selected_branch = branch
                logger.info("Branch selected: '%s' (user input: '%s')", selected_branch, user_lower)
                break

        # Check if user typed a number that's out of range (invalid branch selection)
        if not selected_branch and user_lower.isdigit():
            num = int(user_lower)
            if num > len(available_branches) or num < 1:
                invalid_branch_selection = True
                logger.info("Invalid branch selection: '%s' (only %d branches available)", user_lower, len(available_branches))

    # Check if user is confirming something (spelling correction, availability check, etc.)
    confirmation_phrases = ["yes", "yeah", "yep", "correct", "that's right", "thats right", "right",
                           "yea", "sure", "ok", "okay", "yes please", "yes check", "please check",
                           "check", "yes i want", "i want to check", "please", "go ahead"]
    is_confirmation = user_lower in confirmation_phrases or user_lower.startswith("yes")

    # Check if user is selecting a menu category (1. Prescriptions, 2. Cosmetics)
    is_category_context = False
    selected_category = None
    if history:
        for msg in reversed(history[-3:]):
            if msg.get("role") == "assistant":
                last_bot = (msg.get("content") or "").lower()
                if "1. prescriptions" in last_bot or "2. cosmetics" in last_bot:
                    is_category_context = True
                break

    if is_category_context and user_lower in ["1", "2", "prescriptions", "cosmetics", "cosmetics & personal care", "personal care"]:
        if user_lower == "1" or "prescription" in user_lower:
            selected_category = "prescriptions"
        elif user_lower == "2" or "cosmetic" in user_lower or "personal care" in user_lower:
            selected_category = "cosmetics"

    if selected_branch:
        logger.info("User selected branch '%s', history length: %d", selected_branch, len(history) if history else 0)

    if is_pharmacy_store:
        # Build branch menu if we have multiple branches
        branch_menu = ""
        if len(available_branches) > 1:
            branch_menu = "\n".join([f"{i}. {b}" for i, b in enumerate(available_branches, 1)])

        # Pharmacy conversation flow with branch support
        if selected_category:
            # User selected a menu category (Prescriptions or Cosmetics)
            if selected_category == "prescriptions":
                greeting_rule = (
                    "The customer selected Prescriptions. Respond with:\n"
                    "'For prescriptions, please share a photo of your prescription or tell me the medication name.\n\n"
                    "_Note: Some medications require a valid prescription from a licensed doctor._'"
                )
            else:  # cosmetics
                greeting_rule = (
                    "The customer selected Cosmetics & Personal Care. Show them the categories:\n"
                    "'Great choice! What are you looking for?\n\n"
                    "1. Skincare (Nivea, Vaseline, Olay)\n"
                    "2. Haircare (Shampoos, Conditioners)\n"
                    "3. Oral Care (Toothpaste, Mouthwash)\n"
                    "4. Body Care (Lotions, Deodorants)\n\n"
                    "Or just tell me what product you need!'"
                )
        elif product_context:
            # Customer asked about a product - context already instructs to confirm and ask branch
            greeting_rule = (
                "The customer is asking about products. Follow the instructions in the product context below. "
                "If there's a spelling correction needed, ask for confirmation first."
            )
        elif is_confirmation and history:
            # User confirmed something - look for context in history
            confirmed_product = None
            offered_availability_check = False

            for msg in reversed(history[-6:] if history else []):
                msg_content = (msg.get("content") or "").lower()
                if msg.get("role") == "assistant":
                    # Check if bot asked about spelling correction
                    if "did you mean" in msg_content:
                        for term in ["nivea", "vaseline", "olay", "loreal", "pantene"]:
                            if term in msg_content:
                                confirmed_product = term
                                break
                        break
                    # Check if bot offered to check availability (after image identification)
                    if "check availability" in msg_content or "which branch" in msg_content:
                        offered_availability_check = True
                        # Try to find the product mentioned
                        for term in ["nivea", "vaseline", "olay", "loreal", "pantene", "lotion", "cream", "body"]:
                            if term in msg_content:
                                confirmed_product = term
                                break
                        break

            if confirmed_product:
                # Search for products across branches
                branch_products = {}
                for branch in available_branches:
                    products = _search_products_by_keyword(db, store, confirmed_product, limit=25, branch=branch)
                    if products:
                        branch_products[branch] = len(products)

                if branch_products:
                    greeting_rule = (
                        f"The customer confirmed they want {confirmed_product.capitalize()} products. "
                        "Show the matching products with their prices and the branch each one "
                        "is available at. Do NOT ask which branch - search_products already "
                        "covers every branch. If they want the product, add it to the cart."
                    )
                else:
                    greeting_rule = (
                        f"The customer confirmed but we couldn't find {confirmed_product} products. "
                        "Apologize and offer to help with something else."
                    )
            elif offered_availability_check:
                greeting_rule = (
                    "The customer confirmed they want availability. Call search_products and "
                    "show what is in stock with prices. Do NOT ask which branch."
                )
            else:
                # A bare "yes" is an answer to the question the bot just asked, so the
                # model continues from its own last message. This used to be a canned
                # "Which branch would you like to check?" even when the bot had just
                # offered to add a product.
                greeting_rule = (
                    "The customer said yes. Read YOUR previous message and carry out what "
                    "you offered there (add the product they agreed to, or continue the "
                    "step you asked about). Do NOT ask which branch and do NOT change the "
                    "subject."
                )
        elif medication_context:
            greeting_rule = (
                "The customer is asking about medications. Show the quotation from the context below."
            )
        elif selected_branch and history:
            # User selected a branch - check if previous message was asking about a product
            # Look for product inquiry in recent history (check more messages)
            logger.info("Checking history for product inquiry, history has %d messages", len(history))
            recent_product_inquiry = None
            for msg in reversed(history[-8:] if history else []):  # Check last 8 messages
                msg_content = (msg.get("content") or "").lower()
                logger.info("History msg role=%s, content='%s'", msg.get("role"), msg_content[:50] if msg_content else "")
                if msg.get("role") == "user":
                    # Check if this was a product inquiry
                    if any(kw in msg_content for kw in ["nivea", "q10", "do you have", "looking for", "vaseline", "cream", "lotion"]):
                        recent_product_inquiry = msg_content
                        logger.info("Found product inquiry: '%s'", recent_product_inquiry[:50])
                        break

            if recent_product_inquiry:
                # Customer selected branch after asking about product - now show prices
                # Search for products in the selected branch
                search_term = None
                for kw in ["nivea", "q10", "vaseline", "olay", "cream", "lotion", "shampoo"]:
                    if kw in recent_product_inquiry:
                        search_term = kw
                        break

                if search_term:
                    branch_products = _search_products_by_keyword(db, store, search_term, limit=20, branch=selected_branch)
                    if branch_products:
                        product_list = "\n".join([f"- {p['name']}: {p['price']}" for p in branch_products[:10]])
                        greeting_rule = (
                            f"The customer selected {selected_branch} branch after asking about products. "
                            f"Show them the products with prices:\n\n"
                            f"Here are the matching products at our {selected_branch} branch:\n{product_list}\n\n"
                            f"Ask if they'd like to order any of these."
                        )
                    else:
                        greeting_rule = (
                            f"The customer selected {selected_branch} branch but we couldn't find matching products. "
                            f"Apologize and offer to help with something else."
                        )
                else:
                    greeting_rule = (
                        f"The customer selected the {selected_branch} branch. Show them the main menu:\n"
                        f"'How can I help you today?\n1. Prescriptions\n2. Cosmetics & Personal Care'"
                    )
            else:
                # Branch selection without prior product inquiry - show main menu
                greeting_rule = (
                    f"The customer selected the {selected_branch} branch. Respond with:\n"
                    f"'Great! You've selected our {selected_branch} branch.\n\n"
                    f"How can I help you today?\n"
                    f"1. Prescriptions\n"
                    f"2. Cosmetics & Personal Care'"
                )
        elif invalid_branch_selection:
            # User typed an invalid number for branch selection
            greeting_rule = (
                f"The customer typed an invalid option '{user_lower}'. Politely let them know and show the valid options:\n"
                f"'Sorry, that's not a valid option. Please select from our available branches:\n\n"
                f"{branch_menu}'"
            )
        elif is_bare_greeting:
            if len(available_branches) > 1:
                # Ask for branch first
                greeting_rule = (
                    f"The customer sent a greeting. First ask which branch they want to shop from:\n"
                    f"'Hi, welcome to {name}! Which branch would you like to shop from?\n\n"
                    f"{branch_menu}'"
                )
            else:
                # Single branch or no branches, show regular menu
                greeting_rule = (
                    f"The customer sent a greeting. Respond with the main menu:\n"
                    f"'Hi, welcome to {name}! How can I help you today?\n\n"
                    f"Please select an option:\n"
                    f"1. Prescriptions\n"
                    f"2. Cosmetics & Personal Care'"
                )
        elif history:
            if is_bare_greeting:
                greeting_rule = (
                    "The customer is greeting you again. Reply with a short greeting that "
                    f"names the business, e.g. 'Hi, welcome back to {name}! How can "
                    f"I help you today?' Never greet without the business name."
                )
            else:
                greeting_rule = (
                    "You've already been talking with this customer - answer their query directly. "
                    "If they seem unsure, offer the menu options (1. Prescriptions, 2. Cosmetics & Personal Care)."
                )
        else:
            if len(available_branches) > 1:
                greeting_rule = (
                    f"Greet the customer and ask which branch they want to shop from:\n"
                    f"'Hi, welcome to {name}! Which branch would you like to shop from?\n\n"
                    f"{branch_menu}'"
                )
            else:
                greeting_rule = (
                    f'Greet the customer and present the main menu:\n'
                    f'"Hi, welcome to {name}! How can I help you today?\n\n'
                    f'Please select an option:\n'
                    f'1. Prescriptions\n'
                    f'2. Cosmetics & Personal Care"'
                )
    elif history:
        greeting_rule = (
            "You've already been talking with this customer (see the conversation "
            f"history below) - do NOT re-introduce yourself as {bot_name} or repeat a "
            f"welcome menu, just answer their new message directly, like a continuing "
            f"conversation. A greeting that names {name} (e.g. 'Welcome to {name}') is "
            "fine and expected when the customer greets you."
        )
    else:
        greeting_rule = (
            f'If this message is ONLY a bare greeting with no other content (just '
            f'"hi"/"hello"/"hey" and nothing else), reply with your name and the '
            f'business name together, once, in one short sentence (e.g. "Hi, I\'m '
            f'{bot_name} from {name}, how can I help you today?"). Any message that '
            f'also asks a question, expresses interest, or requests information - '
            f'even if it starts with "Hi" (this includes messages like "Hi, I\'d '
            f'like to know more about {name}", which is what tapping a Click-to-'
            f'WhatsApp ad pre-fills, NOT a bare greeting) - is NOT just a greeting: '
            f'answer the actual request directly and specifically using the '
            f'business info/FAQ below, with at most a brief greeting as a lead-in. '
            f'Never reply with only a generic greeting/"how can I help" to a '
            f'message that already states what the customer wants.'
        )
    if use_openclaw_agent:
        greeting_rule = (
            "Answer the customer's current message directly. Do not greet or "
            "re-introduce yourself unless they greeted you. Use the pharmacy "
            "tools for the request and follow the tool-first rules below."
        )
        unknown_rule = (
            "TOOL-FIRST RULE - FOLLOW EXACTLY:\n"
            "You are connected to the shopivell-pharmacy tools. For every question "
            "about a product, price, stock, branch, cart, order, delivery or payment, "
            "call the appropriate tool and answer from its result in this turn. "
            "Never say an item is unavailable until search_products has returned "
            "NOT FOUND in this turn. Never invent prices, stock, order numbers or "
            "payment references. Before adding an item to the cart, read "
            "active_branch in the tool context: use that branch when it is set, "
            "and ask the customer which branch they want when it says (none "
            "selected). Never guess a branch. After add_to_cart succeeds, do not "
            "search for that item again - the add result is the confirmation. If "
            "add_to_cart returns an error, stop and ask the customer instead of "
            "retrying the whole list. The business info and FAQ are only for "
            "opening hours, location, policies and other business details. If no "
            "tool can answer a non-product question, say a team member will follow "
            "up.\n\n"
        )
        knowledge_rule = (
            "Use the business info and FAQ below for business details (hours, "
            "location, policies), and the pharmacy tools for products, stock, "
            "prices, carts, orders, delivery and payment. "
        )
    else:
        unknown_rule = (
            "CRITICAL RULE - FOLLOW EXACTLY:\n"
            "If the answer to the customer's question is not directly contained in the "
            "BUSINESS INFO or FAQ below, you MUST reply with EXACTLY this one word and "
            'nothing else, no punctuation, no apology, no explanation: NO_KNOWLEDGE_MATCH\n'
            "Do NOT write a natural-language \"I don't have that information\" style "
            "reply. Do NOT guess, approximate, or use general knowledge to answer. Do "
            "NOT offer to connect them with the team yourself - the system handles "
            "that automatically (silently, and alerts the business owner to reply "
            "personally) whenever you return NO_KNOWLEDGE_MATCH. Never invent prices "
            "or stock. It is always better to return NO_KNOWLEDGE_MATCH than to make "
            "something up or answer vaguely.\n\n"
        )
        knowledge_rule = (
            "Use ONLY the business info and FAQ below - check the FAQ for specific "
            "questions like location, hours, or policies. "
        )
    system = (
        f"You are {bot_name}, a customer-service assistant replying on WhatsApp on "
        f"behalf of {name}, a real business (you work for the business - never "
        f'claim to literally BE the business, i.e. never say "I\'m {name}"). Naming the '
        f"business in a greeting (\"Welcome to {name}\") is expected and is not a claim "
        "to be it. "
        "Answer warmly and concisely (WhatsApp-length, 1-3 short sentences, no "
        f"markdown). {greeting_rule} {knowledge_rule}"
        "When the customer expresses interest in the business, its products/"
        "services, or signing up, and a Store link is given in the business info "
        "below, include that link in your reply so they can act on it "
        "immediately.\n\n"
        f"{unknown_rule}"
        "MEDICATION, PRESCRIPTIONS AND HEALTH - NEVER ANSWER:\n"
        "You are not a clinician, so you must never give medical advice. Do not "
        "answer questions about dosages, how many to take, how often, side "
        "effects, interactions (alcohol, other medicines), use in pregnancy or "
        "for babies/children, or what a symptom might be. Do not recommend, "
        "compare or choose a medicine for a symptom, do not say a prescription "
        "is valid or safe, and do not interpret one. The system hands those "
        "questions to a pharmacist before you are called; if one still reaches "
        "you, reply only that a pharmacist will answer shortly and that they "
        "should not start, stop or change any medication before that.\n\n"
        "=== BUSINESS INFO ===\n" + context
    )
    if custom_rules:
        # Owner-set behavior rules (Settings > WhatsApp Business > Bot Rules).
        # Applied on top of, never instead of, the core constraints above - they
        # can't be used to make the bot invent prices/stock or lie about the
        # business, only to steer tone/behavior within those limits.
        system += (
            "\n\n=== ADDITIONAL RULES FROM THE BUSINESS OWNER ===\n"
            f"{custom_rules}\n"
            "Follow these rules whenever they don't conflict with the core "
            "instructions above (never invent prices/stock, never claim to be "
            "the business itself, only use the business info/FAQ provided)."
        )
    # Add image context to system prompt when images are present
    if image_urls:
        if is_pharmacy_store:
            # A prescription is pharmacist work, so the bot is told - before it
            # looks at the photo - not to read, price or interpret one. Product
            # photos (cream, soap, drink) are still identified as normal.
            system += (
                "\n\nIMAGE HANDLING (PHARMACY):\n"
                "The customer has sent an image.\n\n"
                "IF IT IS A PRESCRIPTION, DOCTOR'S NOTE, MEDICATION BOX OR LABEL, OR\n"
                "ANY MEDICAL DOCUMENT: do not read it. Do not name, match, price or\n"
                "quote any medication from it, do not comment on the dose, and do not\n"
                "interpret it. Reply with exactly this text and nothing else:\n"
                f"---\n{PHARMACIST_QUESTION_MESSAGE}\n---\n\n"
                "IF IT IS A PRODUCT PHOTO (cream, soap, drink, cosmetic, grocery):\n"
                "identify the brand and list the matching products with their prices.\n"
                "IF UNCLEAR: ask what they need help with."
            )
        else:
            system += (
                "\n\nIMAGE HANDLING: The customer has sent an image/photo. Analyze what you "
                "see in it and respond helpfully. If the image shows a product:\n"
                "1. Identify the product/brand in the image\n"
                "2. If we have that product or similar products from the same brand, list them as options\n"
                "3. NEVER say 'unable to confirm' if you can identify the brand - instead list available products from that brand\n"
                "4. Always ask which branch they want to check prices for\n"
                "If you cannot determine what the image shows, politely ask for clarification."
            )

    # Pharmacy-specific conversation flow
    if is_pharmacy_store:
        system += (
            "\n\n=== HOW TO RUN THIS CONVERSATION ===\n"
            "You are the shop assistant. The tools are your only source of truth: every\n"
            "product, price, branch, stock level, cart total and order number you give the\n"
            "customer MUST come from a tool result in this conversation.\n\n"
            "BRANCHES AVAILABLE: "
            + (", ".join(available_branches) if available_branches else "none configured")
            + "\n\n"
            "GROUNDING - NEVER BREAK THESE\n"
            "1. Never name a product, price, branch or stock level a tool did not return.\n"
            "   If you have not searched yet, call search_products first - never answer a\n"
            "   product or price question from memory.\n"
            "2. Use the EXACT name and price from the tool result. Prices are whole\n"
            "   numbers: if the data says 9.75 say $10, if it says 16.01 say $16.\n"
            "3. If a result starts with NOT FOUND or DID_YOU_MEAN, say exactly that and\n"
            "   offer the suggested spelling. Never claim stock the search did not find.\n"
            "4. Never invent an order number, order status, payment reference or delivery\n"
            "   time. Those come only from confirm_order and get_order_status.\n"
            "4b. Questions about the customer's own orders ('what's my order number',\n"
            "   'where is my order', 'my orders') and about the branches are ALWAYS\n"
            "   answerable: call get_order_status or list_branches and answer from the\n"
            "   result. Never return NO_KNOWLEDGE_MATCH for those.\n"
            "5. If a tool result is INCOMPLETE or INVALID, ask the customer for the missing\n"
            "   detail. Never fill the gap with a guess.\n"
            "6. Never write a cart summary, subtotal or total from memory - call view_cart\n"
            "   (or use the cart numbers a tool just returned) and copy them. If the cart\n"
            "   is empty, say it is empty. Never ask the customer to supply a price.\n\n"
            "CART\n"
            "7. One product per add_to_cart call. If the customer wants several products,\n"
            "   call add_to_cart once for each one - never drop one.\n"
            "8. When the customer names a product they want ('i want X', 'also add X',\n"
            "   'give me X'), that IS the confirmation: call add_to_cart in the same turn\n"
            "   with the exact name and price from the product data. Do not ask 'would you\n"
            "   like to add it?', 'shall I add it?' or which branch. If the search lists\n"
            "   several products they might mean, ask which ONE - then add that one.\n"
            "9. If the customer says remove, delete, clear or 'take out', call\n"
            "   remove_from_cart (or update_cart with quantity=0). NEVER add_to_cart when\n"
            "   they asked to remove something. If that product is not in the cart, say\n"
            "   so and show what IS in the cart - never answer a removal by offering to\n"
            "   add the product.\n"
            "10. A brand or category is not one product ('i want nivea', 'any lotion'). Show\n"
            "   the matching products and ask which one - NEVER add several products just\n"
            "   because they share a brand.\n"
            "11. A search without a request to buy only shows what we have; it does not add\n"
            "   anything. 'Do you have X?' / 'how much is X?' -> search and answer.\n"
            "12. NEVER ask which branch before searching. search_products covers every\n"
            "   branch and the result says where the product is; only narrow to a branch\n"
            "   when the customer names one.\n"
            "12b. When the customer answers a branch menu with a number or a branch name,\n"
            "   call set_branch with that branch - do not search for the number as a\n"
            "   product and do not ask which branch again.\n"
            "12c. When the customer replies with a number to a numbered list you sent,\n"
            "   read it against THAT list from the conversation history. A collection\n"
            "   menu number calls set_collection_method, a payment menu number calls\n"
            "   set_payment_method, and a product number calls add_to_cart with the\n"
            "   exact name and price shown. Never search for the number as a product.\n"
            "13. Change a quantity with update_cart (it sets the new total quantity). Remove\n"
            "   a line with remove_from_cart, or empty the cart with remove_from_cart\n"
            "   product_name='all'. Never say something was added, changed or removed\n"
            "   unless the tool result confirms it.\n"
            "13b. 'Add another one', 'one more', 'add one' means ONE extra unit: pass\n"
            "   quantity=1, or update_cart with the current quantity + 1. It is never\n"
            "   'double what is there' - 2 units plus 'another one' is 3, not 4.\n"
            "14. After every cart change, say what changed and give the new contents and\n"
            "   total from the tool result.\n"
            "15. When the customer refers to a product by number ('the 3rd one', 'number\n"
            "   2'), use the list YOU showed them and its exact name and price. If it is not\n"
            "   obvious which item they mean, ask instead of guessing.\n\n"
            "ASK BEFORE YOU ACT\n"
            "16. If the request is ambiguous - which product, which size, how many - ask\n"
            "   ONE short question and wait. Never call add_to_cart or update_cart on a\n"
            "   guess.\n"
            "17. Before confirming an order, show the full summary (items, quantities,\n"
            "   total, collection, payment) and wait for an explicit yes.\n"
            "18. A 'yes' only confirms the question you just asked. If you asked something\n"
            "   else, ask again.\n\n"
            "CHECKOUT - LET THE TOOLS DRIVE IT\n"
            "19. Only start checkout when the customer says they are done ('checkout',\n"
            "   'that's all', 'done', 'finish', 'proceed'). Begin by calling view_cart.\n"
            "20. Ask how they want to collect it, then call set_collection_method. The tool\n"
            "   says which step comes next; ask only for what it asks for.\n"
            "20a. The newest answer wins. If the customer changes collection or payment,\n"
            "   call the tool again with the new choice even if one is already stored.\n"
            "20b. DELIVERY vs WALK-IN collection:\n"
            "   - DELIVERY: requires name, phone AND a full delivery address.\n"
            "   - WALK-IN: no address needed - customer picks up at the branch.\n"
            "   If the customer doesn't want to give an address, offer to switch to walk-in.\n"
            "20c. When asking for delivery address, ALWAYS give an example:\n"
            "   'Please provide your full delivery address (street, suburb, city), e.g.\n"
            "   670 Ushewekunze Street, Mabelreign, Harare.'\n"
            "20d. Validate address has: a number or house name, street/road name, area/suburb.\n"
            "   If incomplete, ask for the missing part (e.g. 'Which suburb is that in?').\n"
            "20e. At the name/phone/address steps the message is a delivery detail, NEVER a\n"
            "   product search. Save it with update_delivery_name, update_delivery_phone or\n"
            "   update_delivery_address. If name and phone arrive together, save BOTH.\n"
            "   Never ask for a detail already shown in CURRENT ORDER STATE.\n"
            "21. Ask how they want to pay, then call set_payment_method. Only Cash, EcoCash,\n"
            "   OneMoney and InnBucks exist - never offer Medical Aid, card or bank\n"
            "   transfer.\n"
            "22. Call confirm_order only after the customer has seen the summary and said\n"
            "   yes. Quote the order number exactly as the tool returned it.\n"
            "22a. confirm_order sends the mobile-money prompt for EcoCash, OneMoney and\n"
            "   InnBucks. If its result says the payment request was sent, tell the\n"
            "   customer the amount, the number and the exact instructions, and ask them\n"
            "   to approve the prompt on their phone. If it says PAYMENT NOT SENT, say the\n"
            "   order is saved but the prompt failed, and offer to retry or pay cash.\n"
            "   Never say payment succeeded just because the order was created.\n"
            "22b. If you asked 'shall I add X?' and the customer says yes, call add_to_cart\n"
            "   with that exact X and the price you just quoted. That yes is never a new\n"
            "   product search and never a reason to drop the item.\n\n"
            "PHARMACY SAFETY\n"
            "23. If the customer is unsure, or describes a symptom and asks what to take,\n"
            "   do NOT suggest or name any medication or product. Say the request is with\n"
            "   the pharmacist and stop there.\n"
            "24. If the customer names a MEDICINE they want (something you swallow, e.g.\n"
            "   Panadol, Benylin, antibiotics), ask once: 'Just to confirm - are you really\n"
            "   sure you want *<product>*?' and add it only after they say yes. Cosmetics,\n"
            "   toiletries, baby care and supplements are ordinary products - never\n"
            "   double-check those.\n\n"
            "STYLE\n"
            "25. Short WhatsApp messages, warm and plain. One question per message. Prices\n"
            "   as $X. Never dump the whole catalogue at once.\n"
            "26. If the customer says 'my name is X', 'change my name to X' or 'call me X',\n"
            "   save it with update_delivery_name and confirm the new name. If they ask\n"
            "   'what is my name?', call show_delivery_details and answer from the result.\n"
            "   Never save a correction that names no new name (e.g. 'my name is not X').\n"
            "27. A plain name at the delivery-name step is a name, never a product search.\n"
            "   A name plus a phone number is both details - save both in one turn.\n"
        )
        # Add medication quotation if any
        if medication_context:
            system += medication_context
        # Add product search results if any
        if product_context:
            system += product_context
        # Add current order state (cart, branch, etc.)
        if order_state_context:
            system += order_state_context

    messages = [{"role": "system", "content": system}]
    for m in (history or [])[-12:]:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # Build user message with images if present (vision model format)
    # WhatsApp media URLs require auth, so download and convert to base64 first
    if image_urls:
        user_content = [{"type": "text", "text": user_text or "What is this?"}]
        import base64
        # Try with Zernio auth header for WhatsApp media URLs
        headers = {"Authorization": f"Bearer {ZERNIO_API_KEY}"} if ZERNIO_API_KEY else {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            for url in image_urls[:4]:  # Limit to 4 images
                try:
                    # Download image (WhatsApp URLs need auth via Zernio)
                    # Try with auth first, then without if it fails
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 401 or resp.status_code == 403:
                        # Try without auth header (might be a public URL)
                        resp = await client.get(url)
                    if resp.status_code == 200:
                        content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
                        img_base64 = base64.b64encode(resp.content).decode("utf-8")
                        data_url = f"data:{content_type};base64,{img_base64}"
                        user_content.append({
                            "type": "image_url",
                            "image_url": {"url": data_url, "detail": "auto"}
                        })
                        logger.info("Successfully converted image to base64 (%d bytes)", len(resp.content))
                    else:
                        logger.warning("Failed to download image %s: status %d", url[:100], resp.status_code)
                except Exception as e:
                    logger.warning("Failed to fetch image %s: %s", url[:100], e)
        # Only use vision model if we successfully got at least one image
        if len(user_content) > 1:
            messages.append({"role": "user", "content": user_content})
            model = os.getenv("WHATSAPP_BOT_VISION_MODEL", "gpt-4o")
        else:
            # Fallback to text-only if image download failed
            messages.append({"role": "user", "content": user_text or "Hi"})
            model = os.getenv("WHATSAPP_BOT_MODEL", "gpt-4o-mini")
    else:
        messages.append({"role": "user", "content": user_text or "Hi"})
        model = os.getenv("WHATSAPP_BOT_MODEL", "gpt-4o-mini")

    # REAL OPENCLAW BRAIN: hand the turn to the agent on the gateway. The agent
    # calls the pharmacy MCP tools itself and keeps the conversation memory; the
    # Python code keeps the transport, the deterministic guards above and the
    # store state that is injected into the system prompt. Any gateway failure
    # falls through to the Python agent path below instead of dropping the reply.
    if OPENCLAW_BRAIN_ENABLED and is_pharmacy_store and customer_phone and not image_urls:
        try:
            agent_reply = await _openclaw_agent_reply(
                system
                + _recent_conversation_block(history)
                + _openclaw_context_block(
                    store, customer_phone,
                    active_branch=(pharmacy_state.get("selected_branch")
                                   if is_pharmacy_store else None),
                ),
                user_text,
                f"pharmacy:{store.id}:{customer_phone}",
            )
            if agent_reply:
                logger.info("[OpenClaw] agent answered a turn for %s", customer_phone)
                return agent_reply
            logger.warning("[OpenClaw] agent returned an empty reply; using the Python path")
        except Exception as e:
            logger.error("[OpenClaw] agent turn failed, falling back to the Python path: %s", e)

    try:
        # Confirmed live: this called an undefined _openai(), which meant every bot
        # reply silently fell back to the canned "Thanks for reaching out" string
        # instead of a real AI response. _llm() is this file's actual OpenAI-direct
        # (falls back to OpenRouter) helper, already used everywhere else here.
        # Increase max_tokens when listing products/medications or processing prescription images
        # A customer who pastes a whole list makes the model emit one
        # add_to_cart call per line; at 800 tokens the batch was cut off
        # mid-argument (a call arrived with product_name=None) and the last
        # items were silently dropped from the order.
        if is_pharmacy_store:
            max_tokens = 2000
        elif product_context or medication_context or image_urls:
            max_tokens = 800
        else:
            max_tokens = 300

        # Build request payload
        request_payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.5,
        }

        # Pharmacy tools for function calling
        # Build session key for OpenClaw conversation isolation
        session_key = None
        if is_pharmacy_store and customer_phone:
            request_payload["tools"] = PHARMACY_TOOLS

            # The model decides which tool (if any) to call. Keyword-forced
            # tool_choice used to fire on words like "cash" or "delivery" inside
            # unrelated sentences, which made the bot act without understanding.
            request_payload["tool_choice"] = "auto"

            # Session key for OpenClaw Gateway (isolates conversations per customer)
            session_key = f"pharmacy:{store.id}:{customer_phone}"

        res = await _llm("/chat/completions", request_payload, timeout=30.0, session_key=session_key)

        # Handle tool calls if present (function calling)
        message = res["choices"][0]["message"]
        tool_calls = message.get("tool_calls")

        if is_pharmacy_store and customer_phone:
            if tool_calls:
                # Execute each tool call and collect results
                messages.append(message)  # Add assistant message with tool_calls

                for tool_call in tool_calls:
                    tool_name = tool_call["function"]["name"]
                    try:
                        import json
                        tool_args = json.loads(tool_call["function"]["arguments"])
                    except:
                        tool_args = {}

                    logger.info("Executing tool: %s with args: %s", tool_name, tool_args)

                    # Execute the tool. One tool that raises must not cost the
                    # customer the whole reply: the model gets the failure as
                    # the tool result and answers from what did work.
                    try:
                        tool_result = await _execute_pharmacy_tool(
                            db, store, customer_phone, tool_name, tool_args, user_text
                        )
                    except Exception as tool_error:  # noqa: BLE001
                        logger.error("pharmacy tool %s failed: %s", tool_name, tool_error)
                        tool_result = (f"TOOL ERROR in {tool_name}: the action did not "
                                       f"complete. Do not say it happened - tell the "
                                       f"customer something went wrong and, where it "
                                       f"makes sense, try the step again.")

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": tool_result
                    })

                # Make another LLM call to generate the final response with tool results
                final_payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.5,
                }

                final_res = await _llm("/chat/completions", final_payload, timeout=30.0, session_key=session_key)
                final_text = (final_res["choices"][0]["message"]["content"] or "").strip()
            else:
                final_text = (message.get("content") or "").strip()

            # The cart is the source of truth: never let the reply describe a
            # change that did not happen.
            final_text = await _repair_cart_claim(
                db, store, customer_phone, messages, final_text, cart_before,
                model, max_tokens)
            return final_text or f"Thanks for messaging {name}! How can we help you today?"

        return (message.get("content") or "").strip() or \
            f"Thanks for messaging {name}! How can we help you today?"
    except Exception as e:  # never fail the webhook on the AI call
        import traceback
        logger.error("bot reply generation failed: %s\n%s", e, traceback.format_exc())
        # Do not pretend this was a greeting - the customer asked something and
        # we failed to answer it, so say so instead of changing the subject.
        return ("Sorry - I hit a temporary problem and couldn't finish that. "
                "Please send your message again in a moment.")


SANDBOX_NUMBER_DISPLAY = "+1 202 908 7457"
SANDBOX_NUMBER_DIGITS = "12029087457"
ZERNIO_SANDBOX_ACCOUNT_ID = os.getenv("ZERNIO_SANDBOX_ACCOUNT_ID", "6a180a034c7f364ffded3c9c")


def sandbox_send_text_sync(to_phone: str, body: str, account_id: Optional[str] = None) -> str:
    """Send a WhatsApp text via Zernio from a sync context (used by the UI send-text
    endpoint). Replies into the recipient's open conversation.

    account_id should be the caller's own resolved Zernio account (see
    _zernio_account_id_for_wa) - defaults to the shared sandbox account only for
    legacy sandbox rows. Always scoping /inbox/conversations by accountId matters:
    without it, this searches every tenant's conversations on the shared Zernio API
    key, and could match (and reply into) a different store's conversation with a
    customer who happens to share the same phone number."""
    import asyncio
    account_id = account_id or ZERNIO_SANDBOX_ACCOUNT_ID

    async def _go():
        convs = await _zernio("GET", "/inbox/conversations",
                              params={"platform": "whatsapp", "limit": 50, "accountId": account_id})
        target = (to_phone or "").lstrip("+").replace(" ", "")
        conv = next(
            (c for c in (convs.get("data") or [])
             if str(c.get("participantId") or c.get("participantUsername") or "").lstrip("+").replace(" ", "") == target),
            None,
        )
        if not conv:
            raise HTTPException(status_code=400, detail=(
                "No open WhatsApp conversation with this number — the customer must "
                "message this number first."))
        r = await _zernio(
            "POST", f"/inbox/conversations/{conv['id']}/messages",
            json_body={"accountId": account_id, "message": body},
        )
        return ((r or {}).get("data") or {}).get("messageId")

    return asyncio.run(_go())


def _ensure_sandbox_wa_account(db: Session, store, account: Optional[dict] = None):
    """Get/create the Shopivell WhatsAppAccount row for a Zernio-routed number, bound
    to `store`, so the WhatsApp inbox UI can show the conversation.

    When `account` (the Zernio account object from an inbound webhook, or a
    /accounts lookup) is given, this represents that number's REAL identity
    (waba_id/phone_number_id/display number) - correct for any tenant's own
    connected number, not just the one shared test number. Falls back to the
    synthetic "zernio-sandbox-{store_id}" marker only when no real account data
    is available (e.g. Zernio's shared test number, which isn't a real WABA)."""
    if not store:
        return None
    from modules.whatsapp.models import WhatsAppAccount
    from modules.business.models import FacebookBusinessAccount

    md = (account or {}).get("metadata") or {}
    real_waba_id = md.get("wabaId")
    real_phone_number_id = md.get("phoneNumberId")
    is_real = bool(real_waba_id and real_phone_number_id)

    marker = real_phone_number_id if is_real else f"zernio-sandbox-{store.id}"
    # A WABA can contain several numbers, potentially used by different stores.
    # Only the phone-number ID identifies this connection.
    wa = db.query(WhatsAppAccount).filter(WhatsAppAccount.phone_number_id == marker).first()
    if wa:
        if wa.store_id and wa.store_id != store.id:
            raise ValueError('WhatsApp phone number is already connected to another store')
        if not wa.store_id:
            wa.store_id = store.id
        if is_real:
            wa.waba_id = real_waba_id
            wa.phone_number = md.get("displayPhoneNumber") or wa.phone_number
            wa.is_enabled = True
        return wa

    fba = db.query(FacebookBusinessAccount).filter(
        FacebookBusinessAccount.business_account_id == "zernio-sandbox"
    ).first()
    if not fba:
        fba = FacebookBusinessAccount(
            business_account_id="zernio-sandbox",
            business_name="Zernio Sandbox",
            access_token="zernio-sandbox",
            user_id="zernio",
        )
        db.add(fba)
        db.flush()

    display_name = md.get("verifiedName") or ("Zernio Sandbox" if not is_real else "WhatsApp (via Zernio)")
    wa = WhatsAppAccount(
        business_account_id=fba.id,
        waba_id=real_waba_id if is_real else marker,
        phone_number_id=marker,
        phone_number=md.get("displayPhoneNumber") or SANDBOX_NUMBER_DISPLAY,
        display_name=display_name,
        verified_name=md.get("verifiedName") or display_name,
        is_enabled=True,
        store_id=store.id,
    )
    db.add(wa)
    db.flush()
    return wa


async def _zernio_account_id_for_wa(wa) -> str:
    """Resolve the exact phone-number connection within the store profile."""
    if str(wa.waba_id or '').startswith('zernio-sandbox-'):
        return ZERNIO_SANDBOX_ACCOUNT_ID
    db = SessionLocal()
    try:
        store = db.query(Store).filter(Store.id == wa.store_id).first() if wa.store_id else None
        if not store or not store.zernio_profile_id:
            raise RuntimeError('Store WhatsApp connection is not configured')
        res = await _zernio("GET", "/accounts", params={"profileId": store.zernio_profile_id})
        for account in (res.get("accounts") or []):
            if (account.get("platform") == "whatsapp" and
                    (account.get("metadata") or {}).get("phoneNumberId") == wa.phone_number_id):
                account_id = account.get("_id") or account.get("id")
                if account_id:
                    return account_id
        raise RuntimeError('Store WhatsApp phone number was not found in Zernio')
    finally:
        db.close()


def _persist_sandbox_message(db: Session, wa, other_phone: str, customer_name: str,
                             direction: str, text: str, msg_id: str, ts=None,
                             media_urls: Optional[List[str]] = None):
    """Upsert a conversation + insert one message into Shopivell's WhatsApp tables
    so the sandbox chat shows in the inbox UI. Deduped by message_id.
    
    If media_urls is provided, stores the first URL in media_url field and sets
    message_type appropriately (image/document based on URL extension).
    """
    from modules.whatsapp.models import WhatsAppMessage, WhatsAppConversation
    ts = ts or datetime.utcnow()
    other = (other_phone or "").lstrip("+")
    if not other:
        return
    if msg_id and db.query(WhatsAppMessage).filter(
        WhatsAppMessage.whatsapp_account_id == wa.id,
        WhatsAppMessage.message_id == msg_id,
    ).first():
        return
    conv = db.query(WhatsAppConversation).filter(
        WhatsAppConversation.whatsapp_account_id == wa.id,
        WhatsAppConversation.phone_number == other,
    ).first()
    if not conv:
        conv = WhatsAppConversation(
            whatsapp_account_id=wa.id, store_id=wa.store_id,
            phone_number=other, customer_name=customer_name, status="active",
        )
        db.add(conv)
        db.flush()
    if customer_name and not conv.customer_name:
        conv.customer_name = customer_name
    if not conv.last_message_at or ts > conv.last_message_at:
        conv.last_message_at = ts

    # Determine message type based on content
    msg_type = "text"
    media_url = None
    if media_urls:
        media_url = media_urls[0]  # Store first media URL
        # Detect media type from URL extension
        lower_url = media_url.lower()
        if any(ext in lower_url for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
            msg_type = "image"
        elif any(ext in lower_url for ext in ['.pdf', '.doc', '.docx']):
            msg_type = "document"
        elif any(ext in lower_url for ext in ['.mp4', '.mov', '.avi']):
            msg_type = "video"
        elif any(ext in lower_url for ext in ['.mp3', '.wav', '.ogg']):
            msg_type = "audio"
        else:
            msg_type = "image"  # Default to image for unknown media
    
    business_phone = re.sub(r'\D', '', wa.phone_number or '') or SANDBOX_NUMBER_DIGITS
    db.add(WhatsAppMessage(
        whatsapp_account_id=wa.id,
        message_id=msg_id or f"zernio-{ts.timestamp()}",
        from_number=("+" + other) if direction == "inbound" else ("+" + business_phone),
        to_number=("+" + business_phone) if direction == "inbound" else ("+" + other),
        message_type=msg_type,
        direction=direction,
        status="delivered",
        message_text=text,
        media_url=media_url,
        timestamp=ts,
    ))


async def _handle_inbound_whatsapp(payload: dict):
    """Background task: read an inbound message and reply via Zernio."""
    try:
        msg = payload.get("message") or {}

        # Deduplicate webhook messages to prevent processing the same message twice
        # (Zernio may retry on slow responses)
        msg_id = msg.get("platformMessageId") or msg.get("id") or ""
        if _is_message_duplicate(msg_id):
            logger.info("Skipping duplicate message: %s", msg_id)
            return

        # Log incoming message structure for debugging media/caption handling
        logger.info("Inbound WhatsApp message keys: %s", list(msg.keys()))
        if msg.get("mediaUrl") or msg.get("media_url") or msg.get("attachments") or msg.get("media"):
            logger.info("Media message details - text: %r, caption: %r, mediaUrl: %r, attachments: %r",
                       msg.get("text"), msg.get("caption"),
                       msg.get("mediaUrl") or msg.get("media_url"),
                       msg.get("attachments") or msg.get("media"))
        # Zernio uses "incoming"/"outgoing"; only reply to customer messages so we
        # don't loop on our own outbound echoes.
        if msg.get("direction") in ("outgoing", "out", "outbound"):
            return
        if (msg.get("platform") or "").lower() not in ("whatsapp", ""):
            return
        conv_id = msg.get("conversationId") or (payload.get("conversation") or {}).get("id")
        account = payload.get("account") or {}
        account_id = account.get("id") or account.get("_id")
        # Extract text - check both 'text' and 'caption' (WhatsApp sends image captions separately)
        user_text = msg.get("text") or msg.get("caption") or ""

        # Handle interactive replies (button clicks, list selections)
        metadata = msg.get("metadata") or msg.get("meta") or {}
        interactive_type = metadata.get("interactiveType") or metadata.get("interactive_type") or ""
        interactive_id = metadata.get("interactiveId") or metadata.get("interactive_id") or ""

        # Map interactive button clicks to text for the AI
        if interactive_type in ("button_reply", "list_reply") and interactive_id:
            interactive_map = {
                # Add to cart confirmation
                "checkout_yes": "yes",
                "checkout_no": "no",
                "answer_yes": "yes",
                "answer_no": "no",
                "confirm_add_yes": "yes",
                "confirm_add_no": "no, don't add it",
                # Collection method
                "collection_walkin": "walk-in",
                "collection_delivery": "delivery",
                # Payment method
                "pay_cash": "cash",
                "pay_ecocash": "ecocash",
                "pay_onemoney": "onemoney",
                "pay_innbucks": "innbucks",
                # Order confirmation
                "confirm_yes": "yes",
                "confirm_no": "cancel order",
            }
            mapped_text = interactive_map.get(interactive_id)
            if mapped_text:
                user_text = mapped_text
                logger.info("Mapped interactive button '%s' to text: '%s'", interactive_id, user_text)
            elif not user_text:
                # Use the button title if no mapping
                user_text = metadata.get("interactiveTitle") or interactive_id

        # Extract media URLs from message (images, documents, etc.)
        media_urls = []
        media_url = msg.get("mediaUrl") or msg.get("media_url") or msg.get("imageUrl") or msg.get("image_url")
        if media_url:
            media_urls.append(media_url)
        # Some platforms send multiple attachments
        attachments = msg.get("attachments") or msg.get("media") or []
        for att in attachments:
            if isinstance(att, dict):
                url = att.get("url") or att.get("mediaUrl") or att.get("link")
                if url:
                    media_urls.append(url)
                # Also check for caption in attachment objects
                if not user_text:
                    user_text = att.get("caption") or ""
            elif isinstance(att, str) and att.startswith("http"):
                media_urls.append(att)
        # If no text but has media, set a default text
        if not user_text and media_urls:
            user_text = "What is this?"
        sender = msg.get("sender") or {}
        sender_phone = (sender.get("phoneNumber") or msg.get("senderPhoneNumber")
                        or (payload.get("conversation") or {}).get("participantId")
                        or sender.get("id") or "")
        sender_name = sender.get("name") or ""
        in_msg_id = msg.get("platformMessageId") or msg.get("id")
        if not conv_id or not account_id:
            logger.warning("inbound webhook missing conversationId/accountId: %s", payload)
            return

        db = SessionLocal()
        try:
            store = _resolve_bot_store(db, account)

            # The webhook's account object omits metadata (wabaId/phoneNumberId) - only
            # the /accounts list endpoint has it. Fetch it so the local mirror represents
            # this number's real identity, for any tenant's own number, not just the
            # shared sandbox one. Resolved up front (moved ahead of reply generation)
            # so we can look up this customer's prior message history below.
            full_account = account
            profile_id = account.get("profileId")
            if profile_id:
                try:
                    accts_res = await _zernio("GET", "/accounts", params={"profileId": profile_id})
                    full_account = next(
                        (a for a in (accts_res.get("accounts") or [])
                         if (a.get("_id") or a.get("id")) == account_id),
                        account,
                    )
                except Exception as e:
                    logger.warning("Could not enrich account metadata for %s: %s", account_id, e)

            wa = None
            history: list = []
            try:
                wa = _ensure_sandbox_wa_account(db, store, full_account)
                if wa:
                    from sqlalchemy import or_
                    from modules.whatsapp.models import WhatsAppMessage
                    other = (sender_phone or "").lstrip("+")
                    history_rows = (
                        db.query(WhatsAppMessage)
                        .filter(
                            WhatsAppMessage.whatsapp_account_id == wa.id,
                            or_(WhatsAppMessage.from_number == f"+{other}",
                                WhatsAppMessage.to_number == f"+{other}"),
                        )
                        .order_by(WhatsAppMessage.timestamp.desc())
                        .limit(20)
                        .all()
                    )
                    # Only count this as "the same conversation" (suppress the
                    # welcome/self-introduction) if the most recent prior message
                    # was within the last 24 hours - WhatsApp's own customer-
                    # service-window convention. A longer gap reads as a fresh
                    # conversation to the customer even though this phone number
                    # has talked to the bot before at some point in the past.
                    if history_rows and (datetime.utcnow() - history_rows[0].timestamp) <= timedelta(hours=24):
                        history = [
                            {"role": "user" if m.direction == "inbound" else "assistant",
                             "content": m.message_text or ""}
                            for m in reversed(history_rows)
                        ]
            except Exception as we:
                logger.warning("Could not resolve WhatsApp account/history before reply: %s", we)

            # Keep service notices visible without treating them as customer requests.
            from modules.whatsapp.system_contacts import is_whatsapp_service_number
            if is_whatsapp_service_number(sender_phone):
                if wa:
                    _persist_sandbox_message(db, wa, sender_phone, sender_name,
                                             "inbound", user_text, in_msg_id, media_urls=media_urls or None)
                    db.commit()
                logger.info("Skipping auto-response to WhatsApp service notification")
                return

            # If the customer is explicitly asking for a human (Settings > WhatsApp
            # Business > Handoff Keywords), skip the AI reply entirely and send the
            # configured handoff message instead.
            checkout_reply = None
            if _is_pharmacy_store(store) and not media_urls:
                action = {
                    "collection_walkin": ("set_collection_method", {"method": "walkin"}),
                    "collection_delivery": ("set_collection_method", {"method": "delivery"}),
                    "pay_cash": ("set_payment_method", {"method": "cash"}),
                    "pay_ecocash": ("set_payment_method", {"method": "ecocash"}),
                    "pay_onemoney": ("set_payment_method", {"method": "onemoney"}),
                    "pay_innbucks": ("set_payment_method", {"method": "innbucks"}),
                }.get(interactive_id)
                if action:
                    checkout_reply = await _execute_pharmacy_tool(
                        db, store, sender_phone, action[0], action[1], user_text)

            handoff_msg = _check_handoff(db, store, user_text)
            no_knowledge = False
            pharmacist_handoff = False
            if handoff_msg:
                reply = handoff_msg
            elif (interactive_id in ("checkout_yes", "checkout_no")
                  and (_get_order_state(db, str(store.id), sender_phone) or {}).get("current_state") == "awaiting_checkout"):
                reply = await _execute_pharmacy_tool(
                    db, store, sender_phone,
                    "start_checkout" if interactive_id == "checkout_yes" else "go_back_to_cart", {}, user_text)
            elif checkout_reply is not None:
                reply = checkout_reply
            else:
                # Pass in prior history so the model knows whether it's already spoken
                # to this customer - without it, every reply re-introduced the business
                # ("Hi, I'm X") because each call looked like a brand-new conversation.
                reply = await _generate_bot_reply(
                    db, user_text, store,
                    history=history,
                    image_urls=media_urls if media_urls else None,
                    customer_phone=sender_phone,
                    conv_id=conv_id,
                    account_id=account_id
                )
                # A clinical question is answered with the pharmacist handover,
                # so mark it as a real handoff (below) instead of leaving the
                # customer's question sitting in an unassigned chat.
                pharmacist_handoff = reply in (PHARMACIST_QUESTION_MESSAGE,
                                               HEALTH_QUESTION_MESSAGE)
                if "NO_KNOWLEDGE_MATCH" in reply.upper():
                    # Check if user is asking about products - provide helpful response instead of silence
                    user_lower = user_text.lower()
                    product_keywords = ["nivea", "vaseline", "lotion", "cream", "shampoo", "soap",
                                       "medicine", "tablet", "capsule", "syrup", "do you have",
                                       "looking for", "i want", "i need", "price", "how much",
                                       "available", "stock", "cheaper", "cheapest", "order", "buy"]
                    is_product_query = any(kw in user_lower for kw in product_keywords)

                    if is_product_query:
                        # Provide helpful response for product queries
                        reply = (
                            "I couldn't find an exact match for that product. "
                            "Could you please:\n\n"
                            "1. Check the spelling of the product name\n"
                            "2. Try a simpler search term (e.g., just 'Nivea' or 'Vaseline')\n"
                            "3. Or tell me what type of product you're looking for\n\n"
                            "I'll help you find what you need!"
                        )
                        no_knowledge = False
                    else:
                        # Non-product query we have no answer for. Never leave the
                        # customer on read: send a short, honest reply and still
                        # alert the owner (notify_unanswered_query further down),
                        # which is what the old silent path did instead.
                        no_knowledge = True
                        reply = _unanswered_query_reply(getattr(store, "store_name", None))

            # The model may emit internal artifact identifiers in currency lines.
            # At confirmation, reconstruct the summary from the saved cart instead.
            if reply and "openai-templates:artifact-template-" in reply:
                latest = _get_order_state(db, str(store.id), sender_phone) or {}
                if latest.get("current_state") == "confirm" and latest.get("cart_items"):
                    reply = await _resume_checkout(db, store, sender_phone, user_text)
                else:
                    reply = re.sub(r"openai-templates:artifact-template-[a-z0-9_-]+\s*", "", reply, flags=re.I)

            resp = None
            if reply is not None:
                # Check if this is an ordering step that should use interactive buttons
                interactive_sent = False
                reply_lower = reply.lower()
                saved_checkout = _get_order_state(db, str(store.id), sender_phone) or {}
                checkout_step = saved_checkout.get("current_state")

                if (checkout_step == "awaiting_checkout" and saved_checkout.get("cart_items")
                        and not extract_sure_check_item(reply)
                        and ("proceed to checkout" in reply_lower or re.search(r"\badded\b.*\bcart\b", reply_lower, re.S))):
                    try:
                        if "would you like to proceed to checkout?" not in reply_lower:
                            reply = reply.rstrip() + "\n\nWould you like to proceed to checkout?"
                        await _zernio("POST", f"/inbox/conversations/{conv_id}/messages", json_body={
                            "accountId": account_id, "message": reply,
                            "buttons": [
                                {"type": "postback", "title": "Yes", "payload": "checkout_yes"},
                                {"type": "postback", "title": "No", "payload": "checkout_no"},
                            ],
                        })
                        interactive_sent = True
                    except Exception as ie:
                        logger.warning("Failed to send checkout buttons, falling back to text: %s", ie)

                # Product Add Confirmation - send yes/no list
                if not interactive_sent and "just to confirm" in reply_lower and "to your cart" in reply_lower:
                    try:
                        # Extract product info for the list description
                        # Find ALL products in the message (could be multiple)
                        product_matches = re.findall(r'add\s+(.+?)\s*\(\$?([\d.]+)\)', reply, re.IGNORECASE)

                        # Also check for plural indicators in the message
                        plural_indicators = ["these items", "these products", "both items", "both products",
                                           "all items", "all products", " and ", "items to your cart",
                                           "products to your cart", "2 ", "3 ", "4 ", "5 "]
                        has_plural_indicator = any(ind in reply_lower for ind in plural_indicators)

                        if len(product_matches) > 1:
                            # Multiple products found by regex
                            product_desc = f"{len(product_matches)} products"
                            total_price = sum(round_price(m[1]) for m in product_matches)
                            price = format_price(total_price)
                            item_word = "these items"
                        elif len(product_matches) == 1 and not has_plural_indicator:
                            # Single product
                            product_desc = product_matches[0][0].strip()
                            price = f"${product_matches[0][1]}"
                            item_word = "this item"
                        elif has_plural_indicator:
                            # No regex match but message indicates multiple products
                            product_desc = "these products"
                            price = ""
                            item_word = "these items"
                        else:
                            # No match found, single product
                            product_desc = "this product"
                            price = ""
                            item_word = "this item"

                        action = build_list_action("Confirm", [{
                            "title": "Add to Cart?",
                            "rows": [
                                {"id": "confirm_add_yes", "title": "Yes, Add to Cart", "description": f"Add {product_desc[:50]} {price}"},
                                {"id": "confirm_add_no", "title": "No, Cancel", "description": f"Don't add {item_word}"}
                            ]
                        }])
                        await _send_interactive_message(
                            conv_id, account_id, "list",
                            reply,
                            action,
                            header="Confirm Add",
                            recipient_phone=sender_phone
                        )
                        interactive_sent = True
                        logger.info("Sent add-to-cart confirmation list to %s", conv_id)
                    except Exception as ie:
                        logger.warning("Failed to send add confirmation list, falling back to text: %s", ie)

                # Collection Method - send list (Zernio only supports list, not button)
                if (not interactive_sent
                        and not saved_checkout.get("collection_method")
                        and (checkout_step == "awaiting_collection"
                             or "collection method" in reply_lower)):
                    try:
                        action = build_list_action("Select Option", [{
                            "title": "Collection Options",
                            "rows": [
                                {"id": "collection_walkin", "title": "Walk-in", "description": "Pick up from our branch"},
                                {"id": "collection_delivery", "title": "Delivery", "description": "FREE within 10km, $0.40/km after"}
                            ]
                        }])
                        await _send_interactive_message(
                            conv_id, account_id, "list",
                            "How would you like to collect your order?",
                            action,
                            header="Collection Method",
                            recipient_phone=sender_phone
                        )
                        interactive_sent = True
                        logger.info("Sent collection method list to %s", conv_id)
                    except Exception as ie:
                        logger.warning("Failed to send interactive list, falling back to text: %s", ie)

                # Payment Method - send list
                elif (not interactive_sent and checkout_step == "payment"
                      and ("payment method" in reply_lower
                           or re.search(r'\b(?:how|which way)\b.{0,40}\bpay\b', reply_lower))
                      and not re.search(r'\b(?:number|phone)\b', reply_lower)):
                    try:
                        action = build_list_action("Select Payment", [{
                            "title": "Payment Options",
                            "rows": [
                                {"id": "pay_cash", "title": "Cash", "description": "Pay on delivery/collection"},
                                {"id": "pay_ecocash", "title": "EcoCash", "description": "Pay via EcoCash mobile money"},
                                {"id": "pay_onemoney", "title": "OneMoney", "description": "Pay via OneMoney"},
                                {"id": "pay_innbucks", "title": "InnBucks", "description": "Pay via InnBucks"}
                            ]
                        }])
                        await _send_interactive_message(
                            conv_id, account_id, "list",
                            reply,
                            action,
                            header="Payment Method",
                            recipient_phone=sender_phone
                        )
                        interactive_sent = True
                        logger.info("Sent payment method list to %s", conv_id)
                    except Exception as ie:
                        logger.warning("Failed to send interactive list, falling back to text: %s", ie)

                # Order Confirmation - send list
                elif not interactive_sent and ("reply *yes* to confirm" in reply_lower or "reply yes to confirm" in reply_lower):
                    try:
                        action = build_list_action("Confirm", [{
                            "title": "Confirm Order",
                            "rows": [
                                {"id": "confirm_yes", "title": "Yes, Confirm", "description": "Place this order"},
                                {"id": "confirm_no", "title": "Cancel", "description": "Cancel this order"}
                            ]
                        }])
                        # Send the order summary as text first, then list
                        await _zernio(
                            "POST",
                            f"/inbox/conversations/{conv_id}/messages",
                            json_body={"accountId": account_id, "message": reply.replace("Reply *YES* to confirm your order", "").strip()},
                        )
                        await _send_interactive_message(
                            conv_id, account_id, "list",
                            "Please confirm your order",
                            action,
                            header="Confirm Order",
                            recipient_phone=sender_phone
                        )
                        interactive_sent = True
                        logger.info("Sent order confirmation list to %s", conv_id)
                    except Exception as ie:
                        logger.warning("Failed to send interactive list, falling back to text: %s", ie)

                # Use WhatsApp's single-select list for explicit yes/no questions.
                if not interactive_sent and (
                    re.search(r'\byes\s*(?:/|or)\s*no\b', reply_lower)
                    or re.search(r'(?:^|\n)\s*(?:would you like|do you want|is everything (?:correct|right))\b[^?\n]*\?', reply_lower)
                ):
                    try:
                        action = build_list_action("Choose", [{"title": "Your answer", "rows": [
                            {"id": "answer_yes", "title": "Yes"},
                            {"id": "answer_no", "title": "No"},
                        ]}])
                        await _send_interactive_message(conv_id, account_id, "list", reply, action,
                                                        recipient_phone=sender_phone)
                        interactive_sent = True
                    except Exception as ie:
                        logger.warning("Failed to send yes/no options, falling back to text: %s", ie)

                # Fall back to regular text message if no interactive was sent
                if not interactive_sent:
                    resp = await _zernio(
                        "POST",
                        f"/inbox/conversations/{conv_id}/messages",
                        json_body={"accountId": account_id, "message": reply},
                    )
                logger.info("Replied to WhatsApp conversation %s", conv_id)
            else:
                logger.info("Staying silent on conversation %s (no knowledge match)", conv_id)

            # Mirror the exchange into Shopivell's WhatsApp tables so the inbox UI
            # shows it (best-effort; never fail the reply on a persistence error).
            # When staying silent, only the inbound message is mirrored - there's
            # no outbound reply to show.
            try:
                if wa:
                    _persist_sandbox_message(db, wa, sender_phone, sender_name,
                                             "inbound", user_text, in_msg_id,
                                             media_urls=media_urls if media_urls else None)
                    if reply is not None:
                        out_id = ((resp or {}).get("data") or {}).get("messageId")
                        _persist_sandbox_message(db, wa, sender_phone, sender_name,
                                                 "outbound", reply, out_id)
                    db.commit()
            except Exception as pe:
                db.rollback()
                logger.warning("Failed to mirror sandbox message to UI tables: %s", pe)

            # Score this lead off the exchange. Best-effort: never block the
            # reply that already went out. Human handoffs still alert the owner.
            try:
                if wa:
                    from sqlalchemy import or_
                    from modules.whatsapp.models import WhatsAppMessage
                    from modules.whatsapp.lead_scorer import EnhancedLeadScorer
                    from modules.whatsapp.crm_service import CRMService

                    other = (sender_phone or "").lstrip("+")
                    crm = CRMService(store.id, db)
                    lead = crm.get_or_create_lead(other, wa.id)
                    conv = crm.get_or_create_conversation(other, wa.id)

                    if handoff_msg or pharmacist_handoff:
                        reason = ("Medication/prescription question for a pharmacist"
                                  if pharmacist_handoff else
                                  "Customer requested human assistance")
                        crm.request_handoff(conv, reason)
                        await crm.notify_handoff(conv, reason, query_text=user_text)
                    elif no_knowledge:
                        await crm.notify_unanswered_query(other, user_text, conversation_id=conv.id)

                    history_rows = (
                        db.query(WhatsAppMessage)
                        .filter(
                            WhatsAppMessage.whatsapp_account_id == wa.id,
                            or_(WhatsAppMessage.from_number == f"+{other}",
                                WhatsAppMessage.to_number == f"+{other}"),
                        )
                        .order_by(WhatsAppMessage.timestamp.desc())
                        .limit(10)
                        .all()
                    )
                    history = [
                        {"role": "user" if m.direction == "inbound" else "assistant",
                         "content": m.message_text or ""}
                        for m in reversed(history_rows)
                    ]

                    scorer = EnhancedLeadScorer(store_type=store.business_type or "general")
                    result = scorer.score_lead(
                        conversation_history=history,
                        last_message=user_text,
                        current_score=lead.lead_score or 0,
                    )
                    crm.update_lead_score(lead, result["score"], result.get("recommended_action"))
                    if result.get("interests"):
                        crm.update_lead_interests(lead, result["interests"])
                    # Report hot leads to Meta via Zernio's Conversions API, so ad
                    # delivery can learn from them. No-op (422, logged at info) until
                    # the tenant provisions a dataset (Settings > WhatsApp Business >
                    # Conversion Tracking) and only fires for conversations Zernio can
                    # attribute back to a Click-to-WhatsApp ad click - both expected,
                    # not failures. eventId is stable per lead so repeat hot-lead
                    # messages dedupe on Meta's side instead of over-reporting.
                    hot_threshold = 80
                    try:
                        from modules.whatsapp.models import StoreBotConfig
                        bot_config = db.query(StoreBotConfig).filter(
                            StoreBotConfig.store_id == store.id
                        ).first()
                        if bot_config and bot_config.hot_lead_threshold:
                            hot_threshold = bot_config.hot_lead_threshold
                    except Exception:
                        pass
                    if result["score"] >= hot_threshold:
                        try:
                            await _zernio("POST", "/whatsapp/conversions", json_body={
                                "accountId": account_id,
                                "eventName": "LeadSubmitted",
                                "eventId": f"lead-{lead.id}",
                                "conversationId": conv_id,
                            })
                        except HTTPException as ze:
                            logger.info("Zernio conversion not sent for lead %s (%s): %s",
                                        lead.id, ze.status_code, ze.detail)
                        except Exception as ze:
                            logger.warning("Zernio conversion send failed for lead %s: %s", lead.id, ze)
            except Exception as le:
                db.rollback()
                logger.warning("Lead scoring failed for %s: %s", sender_phone, le)
        finally:
            db.close()
    except Exception as e:
        logger.exception("Failed to handle inbound WhatsApp webhook: %s", e)


@router.post("/zernio-webhook")
async def zernio_webhook(request: Request, background_tasks: BackgroundTasks):
    """Public receiver for Zernio webhooks (no auth; verified via signature)."""
    raw = await request.body()
    sig = request.headers.get("X-Zernio-Signature", "")
    if not _verify_zernio_signature(raw, sig):
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        payload = _safe_json(raw.decode("utf-8"))
    except Exception:
        payload = {}
    event = payload.get("event") or request.headers.get("X-Zernio-Event", "")
    if event == "message.received":
        background_tasks.add_task(_handle_inbound_whatsapp, payload)
    # Always 200 quickly so Zernio doesn't retry/disable the webhook.
    return {"ok": True, "event": event}


# Maximum customer messages accepted in one scripted test conversation.
MAX_TEST_TURNS = 10


def _may_write_real_order_state(store, current_user: Optional[CurrentUser]) -> bool:
    """Only the store's own account (or an admin) may write real carts/orders."""
    if current_user is None:
        return False
    if (current_user.role or "").lower() in ("admin", "superadmin", "super_admin"):
        return True
    return bool(current_user.store_id) and str(store.id) == str(current_user.store_id)


@router.post("/test-bot-reply")
async def test_bot_reply(
    store_id: str = Query(..., description="Store ID"),
    message: str = Query("", description="Test message"),
    image_url: str = Query(None, description="Optional image URL to test vision"),
    phone: str = Query(None, description="Optional customer phone number. Supplying one turns on the full flow (tools, cart, checkout, phone validation)."),
    messages: str = Query(None, description="Optional scripted conversation - one customer message per line, run in order with the cart carried between turns."),
    dry_run: bool = Query(True, description="Keep carts and orders in memory instead of the database. Pass false to exercise real order storage, which requires a token for the store's owner."),
    reset: bool = Query(False, description="Clear any earlier dry-run cart for this phone before running the messages."),
    db: Session = Depends(get_db),
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """Test endpoint to verify bot reply generation (no auth needed unless writing real orders).

    With no `phone` this behaves as before: one stateless reply.

    With a `phone` the real Platinum Pharmacy flow runs - product search,
    spelling suggestions, the pharmacist safety gate and the cart/checkout state
    machine - so a conversation can be replayed against a live store. Either
    send the whole conversation in `messages` (one customer message per line) or
    step through it one request at a time with the same phone; both the dry-run
    cart and the conversation history are carried between requests for 30
    minutes, and `reset=true` starts clean. History matters: answers like "yes"
    and "no" only mean anything next to the question that preceded them.

    By default it runs dry: the cart and any orders stay in memory, nothing is
    written and no payment prompt is sent. The live cart, the current flow state
    and any order numbers come back in the response. Pass `dry_run=false` with a
    token for the store's owner to exercise the real order tables instead.
    """
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    script = [line.strip() for line in (messages or "").splitlines() if line.strip()]
    if not script:
        script = [message or "hi"]
    if len(script) > MAX_TEST_TURNS:
        raise HTTPException(
            status_code=400,
            detail=f"A scripted test conversation is limited to {MAX_TEST_TURNS} customer messages."
        )

    if not dry_run and not _may_write_real_order_state(store, current_user):
        raise HTTPException(
            status_code=403,
            detail="Testing against real order storage requires a token for the store's owner."
        )

    is_pharmacy_store = _is_pharmacy_store(store)

    try:
        image_urls = [image_url] if image_url else None
        active_dry_run = bool(dry_run and phone)
        session = _dry_run_session(store_id, phone, reset=reset) if active_dry_run else None
        scope = dry_run_order_state(session) if active_dry_run else None
        dry_store = scope.__enter__() if scope else None
        turns = []
        # Continue the stored conversation when the caller steps through a test
        # one message at a time - a bare "yes"/"no" is meaningless without it.
        history = list((dry_store or {}).get("history") or []) or None
        try:
            for index, text in enumerate(script):
                reply = await _generate_bot_reply(
                    db, text, store,
                    history=history,
                    image_urls=image_urls if index == 0 else None,
                    customer_phone=phone,
                )
                # The webhook turns this marker into a real reply; a test run
                # must show what the customer would actually receive.
                if "NO_KNOWLEDGE_MATCH" in (reply or "").upper():
                    reply = _unanswered_query_reply(store.store_name)
                history = (history or []) + [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": reply},
                ]
                turns.append({"user": text, "reply": reply})
        finally:
            if dry_store is not None:
                dry_store["history"] = history or []
            if scope:
                scope.__exit__(None, None, None)

        result = {
            "store_name": store.store_name,
            "user_message": script[-1],
            "image_url": image_url,
            "bot_reply": turns[-1]["reply"],
            # Kept for clients that read the old key; both mean "pharmacy flow on".
            "is_pharmacy_store": is_pharmacy_store,
            "is_platinum_pharmacy": is_pharmacy_store,
            "phone": phone,
            "dry_run": active_dry_run,
            "turns": turns,
            "history_length": len(history or []),
        }
        if dry_store is not None:
            state = dry_store["states"].get(phone) or {}
            result["cart"] = state.get("cart_items", [])
            result["current_state"] = state.get("current_state")
            result["orders"] = [o["order_number"] for o in dry_store["orders"]]
        return result
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@router.post("/stores/{store_id}/sync-whatsapp-inbox")
async def sync_whatsapp_inbox(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Backfill existing Zernio WhatsApp conversations for this store into
    Shopivell's WhatsApp tables so they appear in the inbox UI.

    Resolves this store's OWN connected Zernio WhatsApp account (via its
    zernio_profile_id) rather than assuming the one shared sandbox number, and
    scopes the conversation list to that account - without an accountId filter,
    /inbox/conversations returns every conversation on the shared Zernio API key
    across every tenant, which would leak other stores' conversations in here."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    from modules.whatsapp.router import _authorize_message_store
    _authorize_message_store(db, current_user, store.id)

    account = None
    if store.zernio_profile_id:
        try:
            accts_res = await _zernio("GET", "/accounts", params={"profileId": store.zernio_profile_id})
            account = next((a for a in (accts_res.get("accounts") or []) if a.get("platform") == "whatsapp"), None)
        except Exception as e:
            logger.warning("Could not look up Zernio WhatsApp account for store %s: %s", store_id, e)
    account_id = (account or {}).get("_id") or (account or {}).get("id")
    metadata = (account or {}).get("metadata") or {}
    if not account_id or not metadata.get("wabaId") or not metadata.get("phoneNumberId"):
        raise HTTPException(status_code=400, detail="No connected WhatsApp phone number found for this store")

    wa = _ensure_sandbox_wa_account(db, store, account)
    if not wa:
        raise HTTPException(status_code=400, detail="Could not create WhatsApp account record.")

    convs_res = await _zernio("GET", "/inbox/conversations",
                              params={"platform": "whatsapp", "limit": 50, "accountId": account_id})
    conversations = convs_res.get("data") or []
    imported = 0
    for c in conversations:
        cid = c.get("id")
        phone = c.get("participantId") or c.get("participantUsername") or ""
        name = c.get("participantName") or ""
        if not cid:
            continue
        try:
            msgs_res = await _zernio("GET", f"/inbox/conversations/{cid}/messages", params={"limit": 200, "accountId": account_id})
        except HTTPException:
            continue
        msgs = msgs_res.get("data") or msgs_res.get("messages") or []
        for m in msgs:
            direction = "inbound" if m.get("direction") in ("incoming", "in", "inbound") else "outbound"
            text = m.get("message") or m.get("text") or ""
            mid = m.get("id") or m.get("platformMessageId")
            sent = m.get("createdAt") or m.get("sentAt")
            ts = None
            if sent:
                try:
                    ts = datetime.fromisoformat(str(sent).replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    ts = None
            _persist_sandbox_message(db, wa, phone, name, direction, text, mid, ts)
            imported += 1
    db.commit()
    return {"account_id": str(wa.id), "conversations": len(conversations), "messages_imported": imported}


async def _resolve_store_whatsapp_account_id(db: Session, store) -> Optional[str]:
    """This store's connected Zernio WhatsApp account id, or None if it hasn't
    connected a number yet. Same resolution pattern as sync_whatsapp_inbox."""
    if not store or not store.zernio_profile_id:
        return None
    try:
        accts_res = await _zernio("GET", "/accounts", params={"profileId": store.zernio_profile_id})
        account = next((a for a in (accts_res.get("accounts") or []) if a.get("platform") == "whatsapp"), None)
        return (account or {}).get("_id") or (account or {}).get("id")
    except Exception as e:
        logger.warning("Could not look up Zernio WhatsApp account for store %s: %s", store.id, e)
        return None


@router.get("/stores/{store_id}/whatsapp-conversions/status")
async def whatsapp_conversions_status(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Whether Meta Conversions API tracking (via Zernio) is provisioned for this
    store's WhatsApp number - i.e. whether a CTWA conversions dataset is linked."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    account_id = await _resolve_store_whatsapp_account_id(db, store)
    if not account_id:
        return {"connected": False, "dataset_id": None}
    res = await _zernio("GET", "/whatsapp/dataset", params={"accountId": account_id})
    return {"connected": True, "dataset_id": res.get("datasetId")}


@router.post("/stores/{store_id}/whatsapp-conversions/enable")
async def enable_whatsapp_conversions(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Provision Meta Conversions API tracking for this store's WhatsApp number,
    via Zernio (no Meta token pasting needed - it reuses the already-connected
    WhatsApp account's permissions). Hot-lead conversion events then get reported
    automatically from _handle_inbound_whatsapp's lead-scoring step."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    account_id = await _resolve_store_whatsapp_account_id(db, store)
    if not account_id:
        raise HTTPException(status_code=400, detail="Connect a WhatsApp number first.")
    res = await _zernio("POST", "/whatsapp/dataset", json_body={"accountId": account_id})
    return {"dataset_id": res.get("datasetId"), "created": res.get("created", False)}


# ============ Custom Audiences (Zernio) ============
# Uploads the store's own customer list (email/phone from checkout, plus
# WhatsApp lead phone numbers) as a Meta Custom Audience via Zernio - for
# retargeting or as a lookalike seed. Zernio SHA256-hashes everything
# server-side before it reaches Meta; Shopivell never hashes or stores a
# hashed copy itself.

@router.get("/stores/{store_id}/audiences")
async def list_audiences(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    targets = await resolve_meta_targets(store)
    res = await _zernio("GET", "/ads/audiences", params={
        "accountId": targets["account_id"],
        "adAccountId": targets["ad_account_id"],
    })
    return {"audiences": res.get("audiences") or []}


@router.post("/stores/{store_id}/audiences/sync-customers")
async def sync_customers_to_audience(
    store_id: str,
    segment_id: Optional[str] = Query(None, description="Export only this Customer Segment, instead of every customer."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create (or reuse) a customer_list Custom Audience for this store and
    upload customers with an email or phone on file - either everyone
    (Customers table + WhatsApp leads, deduped) or, when segment_id is
    given, just that Customer Segment's members. This is what Customers >
    Segments > Export calls; there's deliberately no separate "sync all
    customers" entry point in Settings, so audience export lives in one
    place."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    targets = await resolve_meta_targets(store)

    from modules.customers.models import Customer, CustomerSegment, CustomerSegmentMembership

    seen = set()
    users: List[Dict[str, str]] = []
    segment = None

    if segment_id:
        segment = db.query(CustomerSegment).filter(CustomerSegment.id == segment_id).first()
        if not segment:
            raise HTTPException(status_code=404, detail="Segment not found")
        customers = (
            db.query(Customer)
            .join(CustomerSegmentMembership, CustomerSegmentMembership.customer_id == Customer.id)
            .filter(CustomerSegmentMembership.segment_id == segment_id, Customer.store_id == store.id)
            .all()
        )
        for c in customers:
            if not c.email:
                continue
            key = ("e", c.email.strip().lower())
            if key in seen:
                continue
            seen.add(key)
            entry = {"email": c.email.strip()}
            if c.phone:
                entry["phone"] = c.phone.strip()
            users.append(entry)
    else:
        from modules.whatsapp.models import WhatsAppLead, WhatsAppAccount

        for c in db.query(Customer).filter(Customer.store_id == store.id).all():
            if not c.email:
                continue
            key = ("e", c.email.strip().lower())
            if key in seen:
                continue
            seen.add(key)
            entry = {"email": c.email.strip()}
            if c.phone:
                entry["phone"] = c.phone.strip()
            users.append(entry)

        wa_ids = [w.id for w in db.query(WhatsAppAccount).filter(WhatsAppAccount.store_id == store.id).all()]
        if wa_ids:
            for lead in db.query(WhatsAppLead).filter(WhatsAppLead.whatsapp_account_id.in_(wa_ids)).all():
                if not lead.phone_number:
                    continue
                key = ("p", lead.phone_number.strip())
                if key in seen:
                    continue
                seen.add(key)
                users.append({"phone": lead.phone_number.strip()})

    if not users:
        detail = (f"No customers with an email on file in segment '{segment.name}' for this store."
                   if segment else "No customers with an email or phone number found for this store yet.")
        raise HTTPException(status_code=400, detail=detail)

    audience_name = f"{store.store_name} - {segment.name}" if segment else f"{store.store_name} - Shopivell Customers"
    listing = await _zernio("GET", "/ads/audiences", params={
        "accountId": targets["account_id"],
        "adAccountId": targets["ad_account_id"],
    })
    existing = next(
        (a for a in (listing.get("audiences") or []) if a.get("name") == audience_name and a.get("type") == "customer_list"),
        None,
    )
    if existing and existing.get("id"):
        audience_id = existing["id"]
        created_new = False
    else:
        created = await _zernio("POST", "/ads/audiences", json_body={
            "accountId": targets["account_id"],
            "adAccountId": targets["ad_account_id"],
            "name": audience_name,
            "type": "customer_list",
        })
        audience_id = created.get("id")
        created_new = True
        if not audience_id:
            raise HTTPException(status_code=502, detail="Zernio did not return an audience id.")

    total_received = 0
    total_invalid = 0
    for i in range(0, len(users), 10000):
        chunk = users[i:i + 10000]
        res = await _zernio("POST", f"/ads/audiences/{audience_id}/users", json_body={"users": chunk})
        total_received += res.get("numReceived", 0) or 0
        total_invalid += res.get("numInvalid", 0) or 0

    return {
        "success": True,
        "audience_id": audience_id,
        "audience_name": audience_name,
        "created_new_audience": created_new,
        "customers_synced": len(users),
        "num_received": total_received,
        "num_invalid": total_invalid,
    }


# ============ Product Catalog (Zernio) ============
# The same Meta Commerce catalog powers dynamic product ads, Instagram/
# Facebook Shops, and WhatsApp in-chat product browsing. Sync pushes the
# store's active Products; linking it to WhatsApp is a separate, best-effort
# step since it needs catalog_management on the connected Meta login (not
# every store's connection will have that scope granted).

def _product_storefront_url(store, product_id) -> str:
    storefront_url = os.getenv("STOREFRONT_URL", "https://shopivell.com")
    return f"{storefront_url}/store/{store.id}/product/{product_id}"


@router.get("/stores/{store_id}/catalog/status")
async def get_catalog_status(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    targets = await resolve_meta_targets(store)
    listing = await _zernio("GET", "/ads/catalogs", params={"accountId": targets["account_id"]})
    catalog_name = f"{store.store_name} - Shopivell Catalog"
    catalog = next((c for c in (listing.get("catalogs") or []) if c.get("name") == catalog_name), None)

    linked_to_whatsapp = False
    if catalog:
        wa_account_id = await _resolve_store_whatsapp_account_id(db, store)
        if wa_account_id:
            try:
                wa_catalogs = await _zernio("GET", "/whatsapp/catalogs", params={"accountId": wa_account_id})
                linked_to_whatsapp = any(
                    c.get("id") == catalog.get("id") for c in (wa_catalogs.get("catalogs") or [])
                )
            except Exception:
                pass

    return {
        "catalog": catalog,
        "linked_to_whatsapp": linked_to_whatsapp,
    }


@router.post("/stores/{store_id}/catalog/sync")
async def sync_product_catalog(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create (or reuse) this store's Meta catalog and push every active
    product into it, then best-effort link the catalog to the store's
    WhatsApp number so customers can browse it in-chat."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    targets = await resolve_meta_targets(store)

    from modules.products.models import Product

    products = db.query(Product).filter(
        Product.store_id == store.id,
        Product.status == "Active",
    ).all()
    if not products:
        raise HTTPException(status_code=400, detail="No active products found for this store yet.")

    catalog_name = f"{store.store_name} - Shopivell Catalog"
    listing = await _zernio("GET", "/ads/catalogs", params={"accountId": targets["account_id"]})
    existing = next((c for c in (listing.get("catalogs") or []) if c.get("name") == catalog_name), None)
    if existing and existing.get("id"):
        catalog_id = existing["id"]
        created_new = False
    else:
        created = await _zernio("POST", "/ads/catalogs", json_body={
            "accountId": targets["account_id"],
            "adAccountId": targets["ad_account_id"],
            "name": catalog_name,
            "vertical": "commerce",
        })
        catalog_id = created.get("id")
        created_new = True
        if not catalog_id:
            raise HTTPException(status_code=502, detail="Zernio did not return a catalog id.")

    currency = (store.currency or "USD").upper()
    requests_payload = []
    for p in products:
        available = (p.available if p.available else p.on_hand) or 0
        requests_payload.append({
            "method": "CREATE",
            "product": {
                "retailerId": str(p.id),
                "name": p.title[:200],
                "description": (p.description or p.title)[:9999],
                "url": _product_storefront_url(store, p.id),
                "imageUrl": p.image_url or "",
                "price": float(p.price or 0),
                "currency": currency,
                "availability": "in stock" if (available > 0 or p.sell_when_out_of_stock) else "out of stock",
                "condition": "new",
                "brand": p.vendor or store.store_name,
                "category": p.category or None,
                "inventory": int(available),
            },
        })

    # Meta processes catalog batches asynchronously - this counts items
    # submitted, not confirmed-processed. Per-item errors would need polling
    # GET /ads/catalogs/{catalog_id}/batches/{handle}, not done here.
    total_created = 0
    for i in range(0, len(requests_payload), 5000):
        chunk = requests_payload[i:i + 5000]
        await _zernio("POST", f"/ads/catalogs/{catalog_id}/products/batch", json_body={
            "accountId": targets["account_id"],
            "requests": chunk,
        })
        total_created += len(chunk)

    linked_to_whatsapp = False
    whatsapp_link_error = None
    wa_account_id = await _resolve_store_whatsapp_account_id(db, store)
    if wa_account_id:
        try:
            await _zernio("POST", "/whatsapp/catalogs", json_body={
                "accountId": wa_account_id,
                "catalogAccountId": targets["account_id"],
                "catalogId": catalog_id,
            })
            linked_to_whatsapp = True
        except Exception as e:
            whatsapp_link_error = str(e)
            logger.info("Could not link catalog to WhatsApp for store %s: %s", store.id, e)

    return {
        "success": True,
        "catalog_id": catalog_id,
        "catalog_name": catalog_name,
        "created_new_catalog": created_new,
        "products_synced": total_created,
        "linked_to_whatsapp": linked_to_whatsapp,
        "whatsapp_link_error": whatsapp_link_error,
    }


# Export router
openclaw_router = router


async def resolve_meta_targets(store) -> Dict[str, Any]:
    """The Zernio account, Meta ad account (act_...) and Facebook Page for a store.

    The Page matters: Meta rejects a creative with no page ("Failed to parse URL"), and
    Zernio only fills it in automatically for some goals.
    """
    profile_id = str(store.zernio_profile_id or "")

    def _profile_of(account):
        p = account.get("profileId") or account.get("profile")
        return str(p.get("_id") if isinstance(p, dict) else (p or ""))

    # No cross-store fallback here (confirmed live: it leaked one tenant's real
    # connection into another's publish calls) - only this store's own profile.
    listing = await _zernio("GET", "/accounts")
    accounts = listing.get("accounts", []) if isinstance(listing, dict) else (listing or [])
    meta_accounts = [a for a in accounts if a.get("platform") in ("facebook", "metaads")]
    account = next((a for a in meta_accounts if _profile_of(a) == profile_id), None)
    if not account:
        raise HTTPException(status_code=400, detail="No Meta (Facebook) account is connected to this store.")
    account_id = account.get("_id") or account.get("id")

    ads = await _zernio("GET", "/ads/accounts", params={"accountId": account_id})
    ad_accounts = ads.get("accounts", []) if isinstance(ads, dict) else (ads or [])
    if not ad_accounts:
        raise HTTPException(status_code=400, detail="No Meta ad account is available on the connected account.")

    # platformUserId is "<user id>:page:<page id>" (confirmed live: e.g.
    # "1039651675735589:page:557578300779245") - the Facebook Page id Meta wants is
    # only the last segment. Sending the whole composite string 400s at Zernio's own
    # validation ("pageId must be a Facebook Page id") before it even reaches Meta.
    page_id = None
    raw = str(account.get("platformUserId") or "")
    if ":page:" in raw:
        page_id = raw.rsplit(":page:", 1)[-1]
    elif raw.isdigit():
        page_id = raw

    try:  # a Page already used by an existing ad on this account is the safest choice
        tree = await _zernio("GET", "/ads/tree", params={"accountId": account_id})
        for campaign in (tree.get("campaigns") or []):
            for ad_set in (campaign.get("adSets") or []):
                for ad in (ad_set.get("ads") or []):
                    existing = (ad.get("creative") or {}).get("pageId")
                    if existing and str(existing).isdigit():
                        page_id = str(existing)
                        break
    except Exception as e:
        logger.warning("could not read existing ads for a page id: %s", e)

    if not page_id:
        raise HTTPException(status_code=400,
                            detail="Could not determine the Facebook Page id for this connected account.")
    return {"account_id": account_id,
            "ad_account_id": ad_accounts[0].get("id") or ad_accounts[0].get("accountId"),
            "page_id": page_id}
