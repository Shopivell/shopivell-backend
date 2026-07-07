"""
Shared Shopivell email templates and the marketing-email sender.

- render_marketing_email() wraps arbitrary HTML body content in the branded
  Shopivell layout (inline logo header + unsubscribe footer).
- send_marketing_email() respects the recipient's marketing_emails_subscribed
  preference, builds a signed unsubscribe link, and sets the List-Unsubscribe
  header so mail clients can offer a native one-click unsubscribe.

Transactional emails (verification codes, password resets) do NOT go through
here — they are always delivered regardless of marketing preferences.
"""
import os

from utils.Verification_Codes_Services import VerificationCodeService
from utils.jwt_auth import jwt_auth


def public_api_url() -> str:
    """Base URL of the backend that serves the unsubscribe pages."""
    return os.getenv("PUBLIC_API_URL", "https://api.shopivell.com").rstrip("/")


def build_unsubscribe_url(user_id: str, email: str) -> str:
    """Signed, no-login unsubscribe link for a given account owner."""
    token = jwt_auth.create_unsubscribe_token(str(user_id), email)
    return f"{public_api_url()}/v1/unsubscribe?token={token}"


def render_marketing_email(title: str, body_html: str, unsubscribe_url: str) -> str:
    """Wrap body_html in the branded Shopivell layout with an unsubscribe footer."""
    logo = VerificationCodeService._logo_img_tag(height=56)
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background-color:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f5f5;padding:40px 20px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:12px;overflow:hidden;">
        <tr><td style="padding:32px 40px 0;">{logo}</td></tr>
        <tr><td style="padding:24px 40px 32px;">
          <h1 style="font-size:22px;font-weight:600;color:#1a1a1a;margin:0 0 16px;">{title}</h1>
          <div style="font-size:15px;color:#444;line-height:1.6;">{body_html}</div>
        </td></tr>
        <tr><td style="padding:0 40px 32px;">
          <hr style="border:none;border-top:1px solid #eee;margin:0 0 16px;">
          <p style="font-size:12px;color:#999;line-height:1.5;margin:0;">
            You are receiving this email because you have a Shopivell account.<br>
            <a href="{unsubscribe_url}" style="color:#666;text-decoration:underline;">Unsubscribe</a> from Shopivell marketing emails at any time.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_marketing_email(user, subject: str, title: str, body_html: str) -> bool:
    """Send a branded marketing email to a User, honoring their subscription.

    `user` is a User ORM object (needs .id, .email and .marketing_emails_subscribed).
    Returns False (and sends nothing) if the user has unsubscribed.
    """
    if not getattr(user, "marketing_emails_subscribed", True):
        print(f"[Marketing] Skipped (unsubscribed): {user.email}")
        return False

    unsubscribe_url = build_unsubscribe_url(user.id, user.email)
    html = render_marketing_email(title, body_html, unsubscribe_url)
    headers = {
        "List-Unsubscribe": f"<{unsubscribe_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    return VerificationCodeService.send_email(
        user.email, subject, html, content_type="html", extra_headers=headers
    )
