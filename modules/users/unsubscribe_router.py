"""
Email subscription / unsubscribe endpoints for Shopivell account owners.

Public (no-login) token-based pages let recipients unsubscribe straight from an
email link, and support mail-client one-click unsubscribe (RFC 8058) via a POST
to the same URL. Authenticated endpoints let the account settings UI read and
toggle the preference.
"""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from modules.users.models import User
from utils.jwt_auth import jwt_auth, get_current_user, CurrentUser
from utils.email_templates import build_unsubscribe_url

unsubscribe_router = APIRouter(tags=["email-preferences"])


# ----------------------------- HTML page helper -----------------------------

def _page(title: str, message: str, action_html: str = "") -> HTMLResponse:
    """Render a small, neutral, self-contained status page."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} · Shopivell</title>
</head>
<body style="margin:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1a1a1a;">
  <div style="max-width:480px;margin:64px auto;padding:0 20px;">
    <div style="background:#fff;border-radius:12px;padding:40px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
      <div style="font-size:22px;font-weight:700;margin-bottom:24px;">Shopivell</div>
      <h1 style="font-size:20px;font-weight:600;margin:0 0 12px;">{title}</h1>
      <p style="font-size:15px;color:#555;line-height:1.6;margin:0 0 24px;">{message}</p>
      {action_html}
    </div>
    <p style="text-align:center;font-size:12px;color:#999;margin-top:20px;">&copy; Shopivell</p>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


def _button(label: str, action: str, token: str) -> str:
    return f"""<form method="post" action="{action}?token={token}" style="margin:0;">
      <button type="submit" style="background:#1a1a1a;color:#fff;border:none;border-radius:8px;padding:12px 24px;font-size:15px;font-weight:600;cursor:pointer;">{label}</button>
    </form>"""


def _resolve_user(token: str, db: Session):
    payload = jwt_auth.verify_unsubscribe_token(token)
    if not payload:
        return None, None
    user = db.query(User).filter(User.id == payload.get("sub")).first()
    return user, payload


# ----------------------------- Public pages -----------------------------

@unsubscribe_router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(token: str = Query(...), db: Session = Depends(get_db)):
    """Confirmation page reached from an email link."""
    user, _ = _resolve_user(token, db)
    if not user:
        return _page("Link expired", "This unsubscribe link is invalid or has expired.")
    if not user.marketing_emails_subscribed:
        return _page(
            "Already unsubscribed",
            f"<strong>{user.email}</strong> is not receiving Shopivell marketing emails.",
            _button("Resubscribe", "/v1/resubscribe", token),
        )
    return _page(
        "Unsubscribe from Shopivell emails",
        f"Click below to stop receiving Shopivell marketing emails at <strong>{user.email}</strong>. "
        f"You will still get important account emails such as verification and password resets.",
        _button("Unsubscribe", "/v1/unsubscribe", token),
    )


@unsubscribe_router.post("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_action(token: str = Query(...), db: Session = Depends(get_db)):
    """Perform the unsubscribe. Also handles mail-client one-click POSTs."""
    user, _ = _resolve_user(token, db)
    if not user:
        return _page("Link expired", "This unsubscribe link is invalid or has expired.")
    if user.marketing_emails_subscribed:
        user.marketing_emails_subscribed = False
        db.commit()
    return _page(
        "You're unsubscribed",
        f"<strong>{user.email}</strong> will no longer receive Shopivell marketing emails. "
        f"Changed your mind?",
        _button("Resubscribe", "/v1/resubscribe", token),
    )


@unsubscribe_router.post("/resubscribe", response_class=HTMLResponse)
def resubscribe_action(token: str = Query(...), db: Session = Depends(get_db)):
    user, _ = _resolve_user(token, db)
    if not user:
        return _page("Link expired", "This link is invalid or has expired.")
    if not user.marketing_emails_subscribed:
        user.marketing_emails_subscribed = True
        db.commit()
    return _page(
        "You're subscribed",
        f"<strong>{user.email}</strong> will now receive Shopivell marketing emails again.",
    )


# ----------------------------- Authenticated preference API -----------------------------

class EmailPreference(BaseModel):
    marketing_emails_subscribed: bool


@unsubscribe_router.get("/me/email-preferences", response_model=EmailPreference)
def get_email_preferences(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == current_user.id).first()
    subscribed = bool(user.marketing_emails_subscribed) if user else True
    return EmailPreference(marketing_emails_subscribed=subscribed)


@unsubscribe_router.put("/me/email-preferences", response_model=EmailPreference)
def update_email_preferences(
    pref: EmailPreference,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == current_user.id).first()
    if user:
        user.marketing_emails_subscribed = pref.marketing_emails_subscribed
        db.commit()
    return EmailPreference(marketing_emails_subscribed=pref.marketing_emails_subscribed)
