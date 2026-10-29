"""WhatsApp service senders are not customers and must not receive replies."""
import re

WHATSAPP_SERVICE_NUMBERS = frozenset({'16465894168'})


def is_whatsapp_service_number(number: str | None) -> bool:
    digits = re.sub(r'\D', '', number or '')
    if digits.startswith('00'):
        digits = digits[2:]
    return digits in WHATSAPP_SERVICE_NUMBERS
