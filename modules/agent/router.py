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
    return {
        "tool": req.tool,
        "status": status,
        "data_part": _data_part(req.tool, result) if result is not None and req.tool in tool_registry.BY_NAME else None,
        "result": result,
        "cost": cost,
        "balance": new_balance,
    }


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
