#!/usr/bin/env python3
"""Offline checks for the two things the app's "create FAQ with AI" depends on.

1. Which model provider the FAQ generator picks, and what it tells you when
   none of them answers (it used to require OPENAI_API_KEY only, so a
   deployment that runs on OpenRouter got "AI service not configured").
2. That a store's saved FAQs actually reach the bot's prompt - the FAQs added
   in scripts/seed_expresscare_faqs.sql are only useful if `_faq_context`
   hands them to the model.

No network, no database: the HTTP calls are stubbed and the FAQ rows are faked.

Run:  python scripts/faq_ai_check.py
Exit code is 0 only when every check passes.
"""

import asyncio
import json
import os
import sys
import types
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = []


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  -> {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(f"{label} {detail}".strip())


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def check_provider_choice():
    import requests
    from fastapi import HTTPException
    from modules.whatsapp import faq_router as fr

    calls = []
    provider_down = {}

    def fake_post(url, **kwargs):
        calls.append(url)
        if provider_down.get("openrouter") and "openrouter" in url:
            return _Resp(402, {"error": {"message": "insufficient credits"}})
        return _Resp(200, {"choices": [{"message": {
            "content": "```json\n[{\"question\":\"Q1\",\"answer\":\"A1\",\"category\":\"general\"}]\n```"}}]})

    original_post = requests.post
    requests.post = fake_post
    saved_keys = {k: os.environ.pop(k, None) for k in ("OPENAI_API_KEY", "OPENROUTER_API_KEY")}
    try:
        print("\n[1] Which provider the FAQ generator uses")

        check("no keys -> reported as not configured", fr._faq_llm_configured() is False)
        try:
            fr._generate_faqs_text("prompt")
            check("no keys -> clear error", False, "no exception")
        except HTTPException as e:
            check("no keys -> 503 naming both keys",
                  e.status_code == 503 and "OPENROUTER_API_KEY" in e.detail, str(e.detail))

        os.environ["OPENROUTER_API_KEY"] = "or-test-key"
        calls.clear()
        text = fr._generate_faqs_text("prompt")
        check("OPENROUTER_API_KEY alone counts as configured", fr._faq_llm_configured() is True)
        check("...and OpenRouter is called", bool(calls) and "openrouter.ai" in calls[0], str(calls))
        check("...and its answer is returned", "Q1" in text, text[:60])

        os.environ["OPENAI_API_KEY"] = "sk-test"
        calls.clear()
        fr._generate_faqs_text("prompt")
        check("an sk- OpenAI key is tried first", bool(calls) and "api.openai.com" in calls[0], str(calls))

        os.environ.pop("OPENAI_API_KEY")
        provider_down["openrouter"] = True
        try:
            fr._generate_faqs_text("prompt")
            check("provider failure surfaced", False, "no exception")
        except HTTPException as e:
            check("provider failure surfaced as 502 with its message",
                  e.status_code == 502 and "402" in e.detail, str(e.detail))
        provider_down.clear()

        parse = fr._parse_faqs_json
        check("fenced JSON array parses", len(parse("```json\n[{\"question\":\"q\"}]\n```")) == 1)
        check("prose around the array parses", len(parse("Here you go:\n[{\"question\":\"q\"}]\nThanks")) == 1)
        check("{\"faqs\": [...]} parses", len(parse('{"faqs":[{"question":"q"}]}')) == 1)
        try:
            parse("not json at all")
            check("garbage is rejected", False, "no exception")
        except HTTPException as e:
            check("garbage is rejected with 502", e.status_code == 502, str(e.detail))
    finally:
        requests.post = original_post
        for key, value in saved_keys.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value


FAQ_ROWS = [
    ("Where are your branches?",
     "Newlands: Shop 1 Mon Repos Building, Newlands Shopping Centre, Harare.", 1),
    ("Do you deliver?", "Yes, we deliver. Any delivery fee is shown before you confirm.", 2),
]


class _Row:
    def __init__(self, question, answer, order):
        self.question, self.answer, self.display_order = question, answer, order


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, model, *args, **kwargs):
        return _Query(self._rows)


async def check_faq_in_prompt():
    from modules.openclaw import router

    print("\n[2] Saved FAQs reach the bot's prompt")

    store = types.SimpleNamespace(
        id="76624a45-d935-4479-9706-2efcca8d1589", store_name="Express Care Pharmacy",
        store_category="Pharmacy", business_type="pharmacy",
        store_description="Community pharmacy group in Zimbabwe.",
        store_voice="Community pharmacy group since 2005.", products_or_services=None,
        store_address="Newlands, Harare", store_city="Harare", store_country="Zimbabwe",
        currency="USD", store_phone="+263 78 836 8390", store_email="admin@expresscare.co.zw",
        operating_hours=None, store_link="https://expresscare.co.zw/home", store_tone="warm")

    captured = {}

    async def fake_llm(path, payload, timeout=60.0):
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "We have four branches."}}]}

    original_llm = router._llm
    router._llm = fake_llm
    try:
        db = _FakeDB([_Row(*row) for row in FAQ_ROWS])
        reply = await router._generate_bot_reply(
            db, "where are your branches", store, history=[], customer_phone="263771234600")
    finally:
        router._llm = original_llm

    system = "\n".join(str(m.get("content", "")) for m in
                       captured.get("payload", {}).get("messages", [])
                       if m.get("role") == "system")
    check("a model call happened", bool(captured))
    check("the FAQ question is in the system prompt", "Where are your branches?" in system)
    check("the FAQ answer is in the system prompt", "Mon Repos Building" in system)
    check("the second FAQ is in the prompt too", "delivery fee is shown" in system)
    check("the store name is in the prompt", "Express Care Pharmacy" in system)
    check("the model's answer is returned", "four branches" in (reply or "").lower(), reply[:80])


def main():
    print("=" * 70)
    print("FAQ checks: AI generation provider, and FAQs reaching the bot")
    print("=" * 70)
    check_provider_choice()
    asyncio.run(check_faq_in_prompt())
    print("\n" + "=" * 70)
    if FAILURES:
        print(f"FAQ CHECKS: {len(FAILURES)} FAILED")
        for failure in FAILURES:
            print(f"  - {failure}")
    else:
        print("FAQ CHECKS: ALL PASSED")
    print("=" * 70)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
