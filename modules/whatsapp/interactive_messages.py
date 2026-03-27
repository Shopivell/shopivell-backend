"""
WhatsApp Interactive Message Builders.

Helpers for constructing WhatsApp Business API interactive message payloads
(list messages, reply buttons, text messages).
"""

from typing import List, Dict, Any, Optional


def build_text_message(text: str) -> Dict[str, Any]:
    """Build a simple text message payload."""
    return {
        "type": "text",
        "data": {"text": {"body": text, "preview_url": False}},
    }


def build_button_message(
    body: str,
    buttons: List[Dict[str, str]],
    header: Optional[str] = None,
    footer: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build an interactive reply-button message (max 3 buttons).

    buttons: [{"id": "btn_id", "title": "Button Label"}, ...]
    """
    action_buttons = [
        {"type": "reply", "reply": {"id": btn["id"], "title": btn["title"][:20]}}
        for btn in buttons[:3]
    ]

    interactive: Dict[str, Any] = {
        "type": "button",
        "body": {"text": body},
        "action": {"buttons": action_buttons},
    }

    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}

    return {
        "type": "interactive",
        "data": {"interactive": interactive},
    }


def build_list_message(
    body: str,
    button_text: str,
    sections: List[Dict[str, Any]],
    header: Optional[str] = None,
    footer: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build an interactive list message.

    sections: [
        {
            "title": "Section Title",
            "rows": [
                {"id": "row_id", "title": "Row Title (24 chars)", "description": "72 chars max"},
                ...
            ]
        }
    ]
    Max 10 rows per section, max 10 sections.
    """
    interactive: Dict[str, Any] = {
        "type": "list",
        "body": {"text": body},
        "action": {"button": button_text[:20], "sections": sections},
    }

    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}

    return {
        "type": "interactive",
        "data": {"interactive": interactive},
    }


def build_flow_message(
    flow_id: str,
    flow_token: str,
    flow_cta: str = "Place Order",
    header: str = "Order Now",
    body: str = "Browse our products and place your order right here in WhatsApp!",
    footer: Optional[str] = "Powered by Shopivell",
    first_screen: str = "PRODUCT_BROWSE",
) -> Dict[str, Any]:
    """
    Build a WhatsApp Flow interactive message.

    Sends a message with a CTA button that opens the Flow UI.
    """
    interactive: Dict[str, Any] = {
        "type": "flow",
        "body": {"text": body},
        "action": {
            "name": "flow",
            "parameters": {
                "flow_message_version": "3",
                "flow_id": flow_id,
                "flow_token": flow_token,
                "flow_cta": flow_cta[:20],
                "flow_action": "data_exchange",
                "flow_action_payload": {
                    "screen": first_screen,
                },
            },
        },
    }

    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}

    return {
        "type": "interactive",
        "data": {"interactive": interactive},
    }
