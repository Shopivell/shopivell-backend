#!/usr/bin/env python3
"""
Live-model acceptance check for the Platinum Pharmacy WhatsApp bot.

Unlike pharmacy_bot_scenarios.py (which swaps in a scripted stand-in model),
this drives the REAL model that production uses, so the answers are the ones
customers would actually get:

  * OPENROUTER_API_KEY  - the key the backend container uses
  * WHATSAPP_BOT_MODEL  - leave unset to use the production default

It still avoids WhatsApp and real data: the order-state tables are an
in-memory store and the catalogue is a throwaway sqlite DB.

Covers the six things a customer must be able to rely on:
  1. a phone number must be exactly 10 digits (delivery + mobile money)
  2. prices are rounded to the nearest whole number
  3. only active / in-stock products are offered
  4. misspellings and related names are corrected
     (nivia -> Nivea, benyln/benilyn -> Benylin, "benylin 4 flu" ~ "benylin for flu")
  5. unsure customer -> pharmacist handover, never a suggestion;
     sure customer -> "are you really sure?" and then the order continues
  6. adding a second product must not silently drop the first
  7. changing your mind - add, remove, re-add and clear the cart
  8. editing the cart - change a quantity, and ask instead of guessing when
     the request is ambiguous
  9. order questions - the order number comes from the tool, never invented;
     branches come from the branch list

Run (needs the production key):

    OPENROUTER_API_KEY=... python scripts/pharmacy_live_llm_check.py

Exit code is 0 only when every check passes.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pharmacy_bot_scenarios as H  # noqa: E402  (reuses the seeded catalogue)
from modules.openclaw import router  # noqa: E402

FAILURES = []


def check(scenario, label, ok, detail=""):
    print(f"    [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILURES.append(f"{scenario}: {label} -> {detail}")


def show(customer, reply):
    print(f"  CUSTOMER: {customer}")
    for line in (reply or "").splitlines():
        print(f"  BOT     : {line}")


async def say(bot, message, answer_branch=True):
    """One customer turn. Answers the bot's follow-up the way a person would."""
    reply = await bot.say(message)
    show(message, reply)
    if answer_branch and "?" in reply:
        low = reply.lower()
        if "which branch" in low:
            reply = await bot.say("Angwa")
            show("Angwa", reply)
        elif "are you really sure" not in low and (
                "just to confirm" in low or "shall i add" in low
                or "would you like to order" in low):
            # A confirm-to-add prompt needs a yes, not a branch name. The
            # "are you really sure" gate is answered explicitly by each scenario.
            reply = await bot.say("yes")
            show("yes", reply)
    print()
    return reply


async def fresh(db, phone):
    H._ORDER_STATES.clear()
    H._CREATED_ORDERS.clear()
    bot = H.Bot(db)
    bot.phone = phone
    return bot


def state(phone):
    return H._mem_get_order_state(db_ref, H.STORE_ID, phone) or {}


db_ref = None


async def main():
    global db_ref
    if not os.getenv("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY is not set - this check must use the real model.")
        return 2

    print(f"MODEL: {os.getenv('WHATSAPP_BOT_MODEL') or '(production default)'}")

    db, _db_path, engine = H.build_db()
    db_ref = db
    router._get_order_state = H._mem_get_order_state
    router._update_order_state = H._mem_update_order_state
    router._create_order = H._mem_create_order
    router._get_order_history = H._mem_get_order_history
    # router._llm is deliberately NOT patched: these are real model answers.

    # ---------------------------------------------------------------- 1
    print("\n[1] Phone number must be exactly 10 digits")
    bot = await fresh(db, "263770000001")
    H._mem_update_order_state(db, H.STORE_ID, bot.phone,
                              current_state="delivery_step_name",
                              collection_method="delivery",
                              cart_items=[{"product_name": "NIVEA CREAM 100ML",
                                           "price": 6, "quantity": 2, "branch": "Angwa"}])
    await say(bot, "Farai Rato", answer_branch=False)
    for bad in ["0771", "0771234567890", "abc"]:
        reply = await say(bot, bad, answer_branch=False)
        check("1", f"'{bad}' is rejected", "10-digit" in reply, reply[:160])
        check("1", f"'{bad}' did not get saved",
              state(bot.phone).get("customer_phone_delivery") is None,
              str(state(bot.phone).get("customer_phone_delivery")))
    reply = await say(bot, "0771234567", answer_branch=False)
    check("1", "valid number is saved",
          state(bot.phone).get("customer_phone_delivery") == "0771234567",
          str(state(bot.phone).get("customer_phone_delivery")))
    check("1", "address is requested next", "address" in reply.lower(), reply[:160])

    result = await router._execute_pharmacy_tool(
        db, H.STORE, bot.phone, "set_payment_method",
        {"method": "ecocash", "mobile_number": "0771"})
    check("1", "mobile-money number is validated too", "10-digit" in result, result[:160])

    # ---------------------------------------------------------------- 2
    print("\n[2] Prices are rounded to the nearest whole number")
    bot = await fresh(db, "263770000002")
    reply = await say(bot, "how much is nivea body lotion")
    check("2", "$9.75 shows as $10", "$10" in reply, reply[:200])
    check("2", "no cents anywhere", not re.search(r"\$\d+\.\d\d", reply), reply[:200])
    result = await router._execute_pharmacy_tool(
        db, H.STORE, bot.phone, "search_products", {"query": "nivea body lotion"})
    check("2", "tool output has no cents",
          not re.search(r"\$\d+\.\d\d", result), result[:200])

    # ---------------------------------------------------------------- 3
    print("\n[3] Only active / in-stock products are offered")
    bot = await fresh(db, "263770000003")
    for stock_query in ["colgate toothpaste", "sorbet facial wash"]:
        reply = await say(bot, f"do you have {stock_query}")
        check("3", f"out-of-stock '{stock_query}' is not offered a price",
              not re.search(r"\$\d", reply), reply[:200])
    result = await router._execute_pharmacy_tool(
        db, H.STORE, bot.phone, "search_products",
        {"query": "colgate", "branch": "Angwa"})
    check("3", "out-of-stock product hidden by the tool",
          result.startswith("NOT FOUND"), result[:160])

    # ---------------------------------------------------------------- 4
    print("\n[4] Spelling and related-name correction")
    for typed, expected in [("nivia", "NIVEA"),
                            ("benyln", "BENYLIN"),
                            ("benilyn", "BENYLIN"),
                            ("benylin 4 flu", "BENYLIN"),
                            ("benylin for flu", "BENYLIN")]:
        result = await router._execute_pharmacy_tool(
            db, H.STORE, bot.phone, "search_products", {"query": typed})
        check("4", f"'{typed}' resolves to {expected}",
              expected in result.upper(), result[:160])
    bot = await fresh(db, "263770000004")
    reply = await say(bot, "do you have benylin 4 flu")
    check("4", "customer-facing answer names Benylin", "BENYLIN" in reply.upper(), reply[:200])

    # ---------------------------------------------------------------- 5
    print("\n[5] Unsure -> pharmacist; sure -> 'are you really sure?'")
    bot = await fresh(db, "263770000005")
    for unsure in ["i have a back pain what do you recommend",
                   "i have sores on my throat what do you recommend",
                   "i'm not sure what i need"]:
        reply = await say(bot, unsure)
        check("5", f"'{unsure[:28]}...' handed to the pharmacist",
              "review" in reply.lower() or "pharmacist" in reply.lower(), reply[:200])
        check("5", "no product suggested", not re.search(r"\$\d", reply), reply[:200])

    bot = await fresh(db, "263770000006")
    reply = await say(bot, "i want panadol")
    check("5", "sure customer is double-checked",
          "are you really sure" in reply.lower(), reply[:200])
    reply = await say(bot, "yes")
    items = state(bot.phone).get("cart_items", [])
    check("5", "order continues after confirming",
          any("PANADOL" in i["product_name"].upper() for i in items), str(items))

    # ---------------------------------------------------------------- 6
    print("\n[6] A second product must not be dropped")
    bot = await fresh(db, "263770000007")
    await say(bot, "i want nivea cream")
    await say(bot, "also add dove soap")
    items = state(bot.phone).get("cart_items", [])
    names = [i["product_name"].upper() for i in items]
    check("6", "both products are in the cart", len(names) >= 2, str(names))
    check("6", "the first product survived",
          any("NIVEA" in n for n in names), str(names))
    check("6", "the second product was added",
          any("DOVE" in n for n in names), str(names))
    reply = await say(bot, "checkout")
    total = re.search(r"\$(\d+)", reply)
    check("6", "checkout shows a whole-number total", bool(total), reply[:200])

    # ---------------------------------------------------------------- 7
    print("\n[7] Changing your mind: add, remove, re-add, clear")
    bot = await fresh(db, "263770000008")
    await say(bot, "i want nivea cream")
    await say(bot, "also add dove soap")
    names = [i["product_name"].upper() for i in state(bot.phone).get("cart_items", [])]
    check("7", "two products in the cart", len(names) == 2, str(names))

    reply = await say(bot, "actually remove the dove soap")
    items = state(bot.phone).get("cart_items", [])
    names = [i["product_name"].upper() for i in items]
    check("7", "dove was removed", not any("DOVE" in n for n in names), str(names))
    check("7", "nivea survived the removal", any("NIVEA" in n for n in names), str(names))

    await say(bot, "add dove soap again")
    names = [i["product_name"].upper() for i in state(bot.phone).get("cart_items", [])]
    check("7", "the removed product can be re-added", len(names) == 2, str(names))

    result = await router._execute_pharmacy_tool(
        db, H.STORE, bot.phone, "remove_from_cart", {"product_name": "all"})
    check("7", "the cart can be cleared",
          not state(bot.phone).get("cart_items"), result[:120])
    result = await router._execute_pharmacy_tool(
        db, H.STORE, bot.phone, "remove_from_cart", {"product_name": "nivea"})
    check("7", "removing from an empty cart is handled",
          "empty" in result.lower(), result[:120])

    # ---------------------------------------------------------------- 8
    print("\n[8] Editing the cart: change a quantity, ask when it is ambiguous")
    bot = await fresh(db, "263770000009")
    await say(bot, "i want nivea cream")
    reply = await say(bot, "actually make it 3")
    items = state(bot.phone).get("cart_items", [])
    qty = sum(int(i.get("quantity", 1) or 1) for i in items) if items else 0
    check("8", "'make it 3' sets the quantity to 3", qty == 3, str(items))
    check("8", "the reply shows the new total ($18)", "$18" in reply, reply[:200])
    check("8", "no cents in the reply",
          not re.search(r"\$\d+\.\d\d", reply), reply[:200])

    reply = await say(bot, "change the nivea to 2", answer_branch=False)
    items = state(bot.phone).get("cart_items", [])
    qty = sum(int(i.get("quantity", 1) or 1) for i in items) if items else 0
    check("8", "a second edit replaces the quantity instead of stacking",
          qty == 2, str(items))

    bot = await fresh(db, "263770000010")
    reply = await say(bot, "i want nivea", answer_branch=False)
    items = state(bot.phone).get("cart_items", [])
    check("8", "an ambiguous 'i want nivea' does not add a guess",
          not items and "?" in reply, f"{items} | {reply[:160]}")
    check("8", "it asks which Nivea product instead",
          "which" in reply.lower() or "nivea" in reply.lower(), reply[:200])

    # ---------------------------------------------------------------- 9
    print("\n[9] Order questions: real order number, real branches")
    bot = await fresh(db, "263770000011")
    reply = await say(bot, "whats my order number", answer_branch=False)
    check("9", "no order number is invented when there is no order",
          not re.search(r"PP-\d", reply), reply[:200])

    H._mem_create_order(db, H.STORE_ID, bot.phone, {
        "items": [{"product_name": "DOVE SOAP 100G", "price": 4, "quantity": 1,
                   "branch": "Angwa"}],
        "total_amount": 4, "subtotal": 4, "payment_method": "cod"})
    real_number = H._CREATED_ORDERS[-1]["order_number"]
    reply = await say(bot, "whats my order number", answer_branch=False)
    check("9", "the real order number is quoted", real_number in reply, reply[:200])

    reply = await say(bot, "which branches do you have", answer_branch=False)
    check("9", "branches come from the branch list (Angwa)", "angwa" in reply.lower(), reply[:200])
    check("9", "branches come from the branch list (Bulawayo)",
          "bulawayo" in reply.lower(), reply[:200])

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"LIVE MODEL: {len(FAILURES)} CHECK(S) FAILED")
        for f in FAILURES:
            print("  -", f)
    else:
        print("LIVE MODEL: ALL CHECKS PASSED")
    print("=" * 70)

    db.close()
    engine.dispose()
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
