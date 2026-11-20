# modules/agent/router.py
"""Agent chat API: conversations + one chat endpoint that can run tools."""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, CurrentUser

from modules.agent.models import AgentConversation, AgentMessage
from modules.agent.credits import InsufficientTokens, get_balance, topup, history as credit_history
from modules.agent.service import AgentService
from modules.agent import tool_registry

agent_router = APIRouter(prefix="/api/agent", tags=["agent"])

# Token packages (demo top-up; swap for a payment provider webhook later).
TOKEN_PACKAGES = [
    {"id": "starter", "tokens": 50_000, "price_usd": 5, "label": "Starter"},
    {"id": "growth", "tokens": 250_000, "price_usd": 20, "label": "Growth"},
    {"id": "pro", "tokens": 1_000_000, "price_usd": 60, "label": "Pro"},
]


class ConversationOut(BaseModel):
    id: str
    title: str
    store_id: Optional[str] = None
    updated_at: Optional[str] = None
    message_count: int = 0


class MessageOut(BaseModel):
    id: str
    role: str
    content: Optional[str] = None
    parts: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[str] = None
    # Token-wallet fields (chat endpoint only)
    tokens_used: Optional[int] = None
    balance: Optional[int] = None
    went_negative: Optional[bool] = None
    low_balance: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    store_id: Optional[str] = None


class ImageGenerationRequest(BaseModel):
    prompt: str
    reference_image: Optional[str] = None
    store_id: Optional[uuid.UUID] = None


@agent_router.post("/generate-image")
def generate_image(request: ImageGenerationRequest,
                   current_user: CurrentUser = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Generate an image for the Create Image screen, with an optional image to edit."""
    import base64
    import json
    from modules.assets.service import generate_image_bytes

    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Enter an image prompt.")
    if len(prompt) > 4000:
        raise HTTPException(status_code=400, detail="Image prompt is too long.")
    reference = request.reference_image
    if reference and (not reference.startswith("data:image/") or len(reference) > 20_000_000):
        raise HTTPException(status_code=400, detail="Upload a valid image under 15 MB.")

    references = [reference] if reference else []
    if request.store_id:
        from modules.stores.models import Store
        from modules.openclaw.brand_context import build_visual_brand_contract, load_brand_context

        store = db.query(Store).filter(Store.id == request.store_id).first()
        if not store or str(store.owner_id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="Store access denied.")
        brand = load_brand_context(str(store.id))
        if not brand:
            brand = {"store_name": store.store_name, "business_type": store.business_type,
                     "brand_description": store.brand_description or store.store_description,
                     "color_theme": store.color_theme, "secondary_colors": store.secondary_colors or [],
                     "font_heading": store.font_heading, "font_body": store.font_body,
                     "logo_url": store.logo_url, "brand_dna": store.brand_dna or {}}
        contract = brand.get("visual_brand_contract") or build_visual_brand_contract(brand)
        prompt = (
            "Create an image that follows this store's visual identity. "
            "Use the saved palette, typography, style, and real product references consistently. "
            "Preserve the supplied logo and real products; do not invent a different brand. "
            f"Brand contract: {json.dumps(contract, ensure_ascii=False, default=str)[:6000]}. "
            f"User request: {prompt}"
        )
        for url in [brand.get("logo_url"), *(brand.get("real_asset_urls") or []),
                    brand.get("screenshot_url")]:
            if url and url not in references:
                references.append(url)
            if len(references) >= 4:
                break

    image_data, error = generate_image_bytes(
        prompt, references or None, require_reference=bool(reference)
    )
    if error or not image_data:
        raise HTTPException(status_code=502, detail=error or "The image model returned no image.")
    return {"image_url": "data:image/png;base64," + base64.b64encode(image_data).decode("ascii")}


class TopupRequest(BaseModel):
    package_id: str


class ToolCostOut(BaseModel):
    tool: str
    cost: int


class ToolCostsOut(BaseModel):
    costs: List[ToolCostOut]


class ConfirmActionRequest(BaseModel):
    tool: str
    args: Dict[str, Any] = {}
    conversation_id: Optional[str] = None
    proposal_message_id: Optional[str] = None
    proposal_index: Optional[int] = None


class CancelActionRequest(BaseModel):
    conversation_id: str
    proposal_message_id: str
    proposal_index: int


@agent_router.get("/conversations", response_model=List[ConversationOut])
async def list_conversations(scope: str = "me", current_user: CurrentUser = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    """scope=me: the user's own chats. scope=team: chats other people started in the same store."""
    q = db.query(AgentConversation)
    if scope == "team":
        if not current_user.store_id:
            return []
        q = q.filter(AgentConversation.store_id == uuid.UUID(str(current_user.store_id)),
                     AgentConversation.user_id != current_user.id)
    else:
        q = q.filter(AgentConversation.user_id == current_user.id)
    convs = q.order_by(AgentConversation.updated_at.desc()).limit(100).all()
    out = []
    for c in convs:
        count = db.query(AgentMessage).filter(AgentMessage.conversation_id == c.id).count()
        out.append(ConversationOut(
            id=str(c.id), title=c.title or "New chat",
            store_id=str(c.store_id) if c.store_id else None,
            updated_at=c.updated_at.isoformat() if c.updated_at else None,
            message_count=count))
    return out


@agent_router.post("/conversations", response_model=ConversationOut)
async def create_conversation(store_id: Optional[str] = None,
                              current_user: CurrentUser = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    sid = store_id or current_user.store_id
    conv = AgentConversation(user_id=current_user.id,
                             store_id=uuid.UUID(str(sid)) if sid else None)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return ConversationOut(id=str(conv.id), title=conv.title or "New chat",
                           store_id=str(conv.store_id) if conv.store_id else None,
                           updated_at=conv.updated_at.isoformat() if conv.updated_at else None,
                           message_count=0)


@agent_router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: uuid.UUID,
                              current_user: CurrentUser = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    conv = (db.query(AgentConversation)
            .filter(AgentConversation.id == conversation_id, AgentConversation.user_id == current_user.id)
            .first())
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conv)
    db.commit()
    return {"ok": True}


@agent_router.get("/conversations/{conversation_id}/messages", response_model=List[MessageOut])
async def get_messages(conversation_id: uuid.UUID,
                       current_user: CurrentUser = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    conv = (db.query(AgentConversation)
            .filter(AgentConversation.id == conversation_id, AgentConversation.user_id == current_user.id)
            .first())
    if not conv and current_user.store_id:   # teammates can read (not write) chats from their own store
        conv = (db.query(AgentConversation)
                .filter(AgentConversation.id == conversation_id,
                        AgentConversation.store_id == uuid.UUID(str(current_user.store_id))).first())
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = (db.query(AgentMessage)
            .filter(AgentMessage.conversation_id == conv.id)
            .order_by(AgentMessage.created_at.asc()).all())
    return [MessageOut(id=str(m.id), role=m.role, content=m.content, parts=m.parts,
                       created_at=m.created_at.isoformat() if m.created_at else None) for m in msgs]


@agent_router.get("/conversations/{conversation_id}/memory")
async def get_conversation_memory(conversation_id: uuid.UUID,
                                  current_user: CurrentUser = Depends(get_current_user),
                                  db: Session = Depends(get_db)):
    conv = db.query(AgentConversation).filter(
        AgentConversation.id == conversation_id,
        AgentConversation.user_id == current_user.id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    q = db.query(AgentMessage).filter(AgentMessage.conversation_id == conv.id)
    if conv.memory_cleared_at:
        q = q.filter(AgentMessage.created_at > conv.memory_cleared_at)
    messages = q.order_by(AgentMessage.created_at.desc()).limit(40).all()
    return {"messages": [{"role": m.role, "content": (m.content or "")[:500]}
                         for m in reversed(messages) if m.content],
            "cleared_at": conv.memory_cleared_at.isoformat() if conv.memory_cleared_at else None}


@agent_router.delete("/conversations/{conversation_id}/memory")
async def clear_conversation_memory(conversation_id: uuid.UUID,
                                    current_user: CurrentUser = Depends(get_current_user),
                                    db: Session = Depends(get_db)):
    from datetime import datetime
    conv = db.query(AgentConversation).filter(
        AgentConversation.id == conversation_id,
        AgentConversation.user_id == current_user.id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.memory_cleared_at = datetime.utcnow()
    db.commit()
    return {"messages": [], "cleared_at": conv.memory_cleared_at.isoformat()}


@agent_router.get("/credits")
async def get_credits(current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    balance = get_balance(db, current_user.id)
    return {"balance": balance, "packages": TOKEN_PACKAGES}


@agent_router.post("/credits/topup")
async def do_topup(req: TopupRequest, current_user: CurrentUser = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    pkg = next((p for p in TOKEN_PACKAGES if p["id"] == req.package_id), None)
    if not pkg:
        raise HTTPException(status_code=400, detail="Unknown package")
    balance = topup(db, current_user.id, pkg["tokens"], reason="topup",
                    detail=f"{pkg['label']} package (${pkg['price_usd']})")
    return {"balance": balance, "added": pkg["tokens"]}


@agent_router.get("/credits/history")
async def get_credit_history(current_user: CurrentUser = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    return {"balance": get_balance(db, current_user.id), "entries": credit_history(db, current_user.id, 50)}


@agent_router.get("/credits/usage-by-store")
async def get_usage_by_store(days: int = 30, current_user: CurrentUser = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    """Tokens spent per store over the last `days` (1 to 365), split by action. A user who runs
    many stores shows one row per store, so usage (and so billing) scales with the work done."""
    from modules.agent.credits import usage_by_store
    days = max(1, min(int(days), 365))
    return {"balance": get_balance(db, current_user.id), **usage_by_store(db, current_user.id, days)}


@agent_router.get("/action-costs")
async def action_costs():
    """The central price table: what each AI action costs, in tokens."""
    from modules.agent.credit_costs import ACTION_COSTS
    return {"costs": [{"action": a, "cost": c} for a, c in ACTION_COSTS.items()]}


@agent_router.get("/tool-costs", response_model=ToolCostsOut)
async def tool_costs():
    """Flat token prices for the agent's side-effect tools. The chat UI shows
    them on confirm cards so the user knows what an action costs before OKing it."""
    from modules.agent.service import TOOL_COSTS
    return {"costs": [{"tool": t, "cost": c} for t, c in TOOL_COSTS.items()]}


@agent_router.post("/actions/confirm")
async def confirm_action(req: ConfirmActionRequest, request: Request,
                         current_user: CurrentUser = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Run an expensive tool the user explicitly confirmed in the UI.

    The chat proposes actions (generate_image / create_campaign /
    show_ad_variations) as spec cards; this endpoint is the Confirm button.
    Runs the same tool the agent would run, charges the same token cost, and
    returns a result the UI can render directly.
    """
    from modules.agent.service import AgentService, TOOL_COSTS, _run_tool_standalone
    if req.tool not in TOOL_COSTS:
        raise HTTPException(status_code=400, detail=f"Unknown tool '{req.tool}'")
    proposal_msg = None
    proposal_parts = None
    if req.conversation_id and req.proposal_message_id is not None and req.proposal_index is not None:
        proposal_msg = (db.query(AgentMessage).join(AgentConversation)
                        .filter(AgentMessage.id == uuid.UUID(req.proposal_message_id),
                                AgentConversation.id == uuid.UUID(req.conversation_id),
                                AgentConversation.user_id == current_user.id).first())
        if not proposal_msg:
            raise HTTPException(status_code=404, detail="Action proposal not found")
        proposal_parts = list(proposal_msg.parts or [])
        if req.proposal_index < 0 or req.proposal_index >= len(proposal_parts):
            raise HTTPException(status_code=400, detail="Invalid action proposal")
        proposal = proposal_parts[req.proposal_index]
        if proposal.get("type") != "action_proposal" or proposal.get("tool") != req.tool or proposal.get("args") != req.args:
            raise HTTPException(status_code=400, detail="Action proposal has changed")
        if proposal.get("decision"):
            raise HTTPException(status_code=409, detail="Action already decided")
    cost = TOOL_COSTS.get(req.tool, 0)
    # Hard gate: confirmed actions are the expensive ones, and the user is on a
    # paid action. Chat stays open system-wide, but this needs real credit.
    from modules.agent.credits import get_balance, InsufficientTokens
    balance = get_balance(db, current_user.id)
    if cost > 0 and balance < cost:
        raise HTTPException(status_code=402, detail={
            "error": "insufficient_tokens",
            "message": f"That action costs {cost:,} tokens and your balance is {balance:,}. Top up to run it.",
            "balance": balance,
            "needed": cost,
            "packages": TOKEN_PACKAGES,
        })
    svc = AgentService(db, current_user.id, current_user.store_id, request.headers.get("authorization"))
    result, status = _run_tool_standalone(svc, req.tool, req.args or {})
    if not status.startswith("ok"):
        raise HTTPException(status_code=502, detail=f"Action failed: {status}")
    new_balance, _went_negative = (balance, False)
    if cost > 0:
        from modules.agent.credits import charge
        try:
            _sid = (req.args or {}).get("store_id")
            try:
                _sid = str(uuid.UUID(str(_sid))) if _sid else None
            except ValueError:
                _sid = None
            new_balance = charge(db, current_user.id, cost, f"tool:{req.tool}",
                                 detail=f"Confirmed {req.tool} from chat UI", store_id=_sid)
        except InsufficientTokens:
            raise HTTPException(status_code=402, detail={
                "error": "insufficient_tokens",
                "message": "You're out of AI tokens. Top up to keep going.",
                "balance": balance,
                "needed": cost,
                "packages": TOKEN_PACKAGES,
            })
    from modules.agent.service import _data_part
    data_part = _data_part(req.tool, result) if result is not None and req.tool in tool_registry.BY_NAME else None
    if proposal_msg is not None and proposal_parts is not None:
        result_parts = [{"type": "tool", "tool": req.tool, "status": status}]
        if req.tool == "generate_image" and isinstance(result, dict) and result.get("b64_png"):
            result_parts.append({"type": "image", "b64_png": result["b64_png"],
                                 "asset_id": result.get("asset_id"), "headline": result.get("headline")})
        elif req.tool == "show_ad_variations" and isinstance(result, list):
            result_parts.append({"type": "ad_variations", "variations": result,
                                 "summary": f"{len(result)} copy variations"})
        elif req.tool == "create_campaign" and isinstance(result, dict) and result.get("campaign_id"):
            result_parts.append({"type": "links", "links": [
                {"page": "Campaigns", "path": "/marketing/campaigns", "desc": "See your campaigns"}]})
        elif data_part:
            result_parts.append(data_part)
        proposal_parts[req.proposal_index] = {**proposal_parts[req.proposal_index],
                                               "decision": "confirmed", "result_parts": result_parts}
        proposal_msg.parts = proposal_parts
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(proposal_msg, "parts")
        db.commit()
    return {
        "tool": req.tool,
        "status": status,
        "data_part": data_part,
        "result": result,
        "cost": cost,
        "balance": new_balance,
    }


@agent_router.post("/actions/cancel")
async def cancel_action(req: CancelActionRequest,
                        current_user: CurrentUser = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    msg = (db.query(AgentMessage).join(AgentConversation)
           .filter(AgentMessage.id == uuid.UUID(req.proposal_message_id),
                   AgentConversation.id == uuid.UUID(req.conversation_id),
                   AgentConversation.user_id == current_user.id).first())
    if not msg:
        raise HTTPException(status_code=404, detail="Action proposal not found")
    parts = list(msg.parts or [])
    if req.proposal_index < 0 or req.proposal_index >= len(parts) or parts[req.proposal_index].get("type") != "action_proposal":
        raise HTTPException(status_code=400, detail="Invalid action proposal")
    if parts[req.proposal_index].get("decision"):
        raise HTTPException(status_code=409, detail="Action already decided")
    parts[req.proposal_index] = {**parts[req.proposal_index], "decision": "cancelled"}
    msg.parts = parts
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(msg, "parts")
    db.commit()
    return {"ok": True}


@agent_router.post("/conversations/{conversation_id}/chat", response_model=MessageOut)
async def chat(conversation_id: uuid.UUID, req: ChatRequest, request: Request,
               current_user: CurrentUser = Depends(get_current_user),
               db: Session = Depends(get_db)):
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Message is required")
    svc = AgentService(db, current_user.id, req.store_id or current_user.store_id, request.headers.get("authorization"))
    try:
        result = svc.chat(conversation_id, req.message.strip())
    except InsufficientTokens as e:
        # Kept for compatibility; the chat turn no longer hard-gates at zero.
        raise HTTPException(status_code=402, detail={
            "error": "insufficient_tokens",
            "message": f"You're out of AI tokens (balance: {e.balance}). Top up to keep going.",
            "balance": e.balance,
            "needed": e.needed,
            "packages": TOKEN_PACKAGES,
        })
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent turn failed: {e}")
    return MessageOut(id=result["message_id"], role="assistant", content=result["reply"],
                      parts=result["parts"], created_at=None,
                      tokens_used=result.get("tokens_used", 0),
                      balance=result.get("balance"),
                      went_negative=result.get("went_negative", False),
                      low_balance=result.get("low_balance_notice"))
