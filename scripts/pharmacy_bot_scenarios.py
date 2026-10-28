#!/usr/bin/env python3
"""
Scenario runner for the Platinum Pharmacy WhatsApp bot.

Drives the REAL bot code (modules/openclaw/router.py) through full WhatsApp
conversations, exactly the way the Zernio webhook does, but without touching
WhatsApp or paying for LLM calls:

  * a scripted stand-in model emits the tool calls a real model would emit
  * the order-state tables are replaced with an in-memory store (the prod
    tables are Postgres jsonb, this runner runs on a throwaway sqlite DB)

Scenarios covered:
  1. Greeting / first contact
  2. Misspelled products -> "did you mean" (benylin 4 flu, benylin for flu, benilyn, nivia)
  3. Prices always rounded to the nearest whole number
  4. Only active + in-stock products are offered
  5. Multi-item ordering - nothing gets skipped, second/third product added
  6. Confirming a multi-product confirmation adds EVERY product
  7. 10-digit phone number validation (delivery + payment)
 12. Real 263788836724 conversation replay (name correction, address query,
     complaint-as-address, and confirming a delivery order without an address)
  8. Unsure customer -> pharmacist handover (never a suggestion)
  9. Sure customer -> "are you really sure?" then continues
 10. Normal product questions are NOT interrupted by the medication gate

Run:  python scripts/pharmacy_bot_scenarios.py
"""

import asyncio
import json
import os
import re
import sys
import tempfile
import time
import types
from pathlib import Path

# Windows consoles default to cp1252 and crash on the bot's emoji
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.openclaw.pharmacy_rules import (  # noqa: E402
    extract_name_correction,
    is_affirmative,
    is_medication_related,
    looks_like_address,
    looks_like_person_name,
    normalize_phone,
    sure_confirmation_message,
)

STORE_ID = "ad8f40bf-8926-47e9-8830-72a1c6e89d5c"

# --------------------------------------------------------------------------
# Throwaway sqlite DB seeded like Platinum Pharmacy's catalogue
# --------------------------------------------------------------------------

CATALOGUE = [
    # name, price, branch, extra content line, products-table stock fields
    ("NIVEA CREAM 100ML", 6.00, "Angwa", "", {}),
    ("NIVEA BODY LOTION 400ML", 9.75, "Angwa", "", {}),
    ("NIVEA SOFT MOISTURISER 200ML", 12.40, "Bulawayo", "", {}),
    ("DOVE SOAP 100G", 4.40, "Angwa", "", {}),
    ("DOVE BODY WASH 250ML", 7.20, "Angwa", "", {}),
    ("BENYLIN 4 FLU & COUGH SYRUP 100ML", 8.20, "Angwa", "", {}),
    ("PANADOL EXTRA 500MG (20 TABLETS)", 3.50, "Angwa", "", {}),
    ("ZARON MATTE LIPSTICK RED", 16.01, "Angwa", "", {}),
    # out of stock, flagged in the knowledge entry itself
    ("COLGATE TOOTHPASTE 100ML", 2.30, "Angwa", "In Stock: No", {"available": 0, "on_hand": 0}),
    # out of stock only via the products table (no stock text in the entry)
    ("SORBET FACIAL WASH 150ML", 8.60, "Angwa", "", {"available": 0, "on_hand": 0}),
    # zero stock but the store sells out-of-stock items -> still offered
    ("REXONA DEODORANT 150ML", 5.30, "Angwa", "",
     {"available": 0, "on_hand": 0, "sell_when_out_of_stock": 1}),
    # stock not tracked -> we cannot judge, so still offered
    ("SIMPLE FACIAL WASH 150ML", 9.10, "Angwa", "",
     {"available": 0, "on_hand": 0, "inventory_tracked": 0}),
]


def build_db():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    db_path = Path(tempfile.gettempdir()) / "pharmacy_scenarios.db"
    if db_path.exists():
        db_path.unlink()
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE company_knowledge (
                id TEXT PRIMARY KEY, store_id TEXT, branch TEXT, title TEXT,
                content TEXT, category TEXT, content_type TEXT, source_id TEXT,
                is_active INTEGER DEFAULT 1)
        """))
        conn.execute(text("""
            CREATE TABLE products (
                id TEXT PRIMARY KEY, store_id TEXT, title TEXT, status TEXT,
                available INTEGER, on_hand INTEGER,
                sell_when_out_of_stock INTEGER DEFAULT 0,
                inventory_tracked INTEGER DEFAULT 1)
        """))
        for i, (name, price, branch, extra, stock) in enumerate(CATALOGUE, 1):
            content = f"Product: {name}\nPrice: ${price:.2f}\n"
            if extra:
                content += f"{extra}\n"
            content += "\nAvailable at Platinum Pharmacy."
            conn.execute(text("""
                INSERT INTO company_knowledge (id, store_id, branch, title, content,
                    category, content_type, source_id, is_active)
                VALUES (:id, :store_id, :branch, :title, :content, 'product', 'product', NULL, 1)
            """), {"id": f"ck{i}", "store_id": STORE_ID, "branch": branch,
                   "title": f"Product: {name}", "content": content})
            conn.execute(text("""
                INSERT INTO products (id, store_id, title, status, available, on_hand,
                                      sell_when_out_of_stock, inventory_tracked)
                VALUES (:id, :store_id, :title, 'Active', :available, :on_hand, :sell_oos, :tracked)
            """), {"id": f"p{i}", "store_id": STORE_ID, "title": name,
                   "available": stock.get("available", 12),
                   "on_hand": stock.get("on_hand", 12),
                   "sell_oos": stock.get("sell_when_out_of_stock", 0),
                   "tracked": stock.get("inventory_tracked", 1)})
    Session = sessionmaker(bind=engine)
    return Session(), db_path, engine


STORE = types.SimpleNamespace(
    id=STORE_ID, store_name="Platinum Pharmacy", store_category="Pharmacy",
    business_type="pharmacy", store_description="Your trusted community pharmacy.",
    store_voice="friendly", products_or_services=None, store_address="Angwa Street",
    store_city="Harare", store_country="Zimbabwe", currency="USD",
    store_phone="0771234567", store_email="hello@platinum.co.zw",
    operating_hours=None, store_link="https://shopivell.com/store/platinum", store_tone="warm",
)


# --------------------------------------------------------------------------
# In-memory order state (mirrors the Postgres helpers in the router)
# --------------------------------------------------------------------------

_ORDER_STATES = {}
_CREATED_ORDERS = []


def _mem_get_order_state(db, store_id, customer_phone):
    state = _ORDER_STATES.get((store_id, customer_phone))
    if not state:
        return None
    return {"cart_items": [dict(i) for i in state.get("cart_items", [])],
            **{k: v for k, v in state.items() if k != "cart_items"}}


def _mem_update_order_state(db, store_id, customer_phone, **updates):
    state = _ORDER_STATES.setdefault((store_id, customer_phone), {"cart_items": []})
    state.update(updates)
    return True


def _mem_create_order(db, store_id, customer_phone, order_data):
    number = f"PP-20261016-S{len(_CREATED_ORDERS) + 1:02d}"
    _CREATED_ORDERS.append({"order_number": number, "store_id": store_id,
                            "customer_phone": customer_phone, "status": "pending",
                            "created_at": "2026-10-16 10:00", **order_data})
    _ORDER_STATES[(store_id, customer_phone)] = {"cart_items": [], "current_state": "idle"}
    return number


def _mem_get_order_history(db, store_id, customer_phone, limit=5):
    mine = [o for o in _CREATED_ORDERS
            if o.get("store_id") == store_id and o.get("customer_phone") == customer_phone]
    return list(reversed(mine))[:limit]


# --------------------------------------------------------------------------
# Scripted stand-in for the OpenAI-compatible model
# --------------------------------------------------------------------------

class FakeModel:
    """A deterministic stand-in for a real, state-aware tool-calling model.

    The bot no longer answers menus and checkout answers in Python before the
    model sees them. This fake reads the same system-prompt state a real model
    reads (FLOW STATE, ACTIVE BRANCH, the last assistant message) and emits the
    tool calls a real model is expected to make.
    """

    def __init__(self):
        self.payloads = []
        self.pending_note = ""

    async def __call__(self, path, payload, timeout=60.0, session_key=None):
        # `session_key` is the real _llm signature: it routes to the OpenClaw
        # gateway when the brain flag is on. The scripted model ignores it.
        self.payloads.append(payload)
        messages = payload.get("messages", [])
        if any(m.get("role") == "tool" for m in messages):
            tool_text = "\n".join(m["content"] for m in messages if m.get("role") == "tool")
            note = self.pending_note
            self.pending_note = ""
            return _text_msg((tool_text + ("\n\n" + note if note else "")).strip())

        user_msg = next((m["content"] for m in reversed(messages)
                         if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
        result = self._decide(payload, user_msg)
        if isinstance(result, str):
            return _text_msg(result)
        if result:
            return _tool_msg(result)
        return _text_msg("Sure - tell me what you need and I'll check for you.")

    # -- context helpers ---------------------------------------------------
    @staticmethod
    def _last_assistant(messages):
        return next((m.get("content") or "" for m in reversed(messages)
                     if m.get("role") == "assistant"
                     and isinstance(m.get("content"), str)), "")

    @staticmethod
    def _system_text(messages):
        return next((m.get("content") or "" for m in messages
                     if m.get("role") == "system"
                     and isinstance(m.get("content"), str)), "")

    @staticmethod
    def _flow_state(system):
        match = re.search(r"FLOW STATE:\s*([a-z_]+)", system, re.IGNORECASE)
        return match.group(1).lower() if match else "cart"

    @staticmethod
    def _active_branch(system):
        match = re.search(r"ACTIVE BRANCH:\s*([^*\n\r]+)", system, re.IGNORECASE)
        return match.group(1).strip() if match else "Angwa"

    @staticmethod
    def _available_branches(system):
        match = re.search(r"BRANCHES AVAILABLE:\s*([^\n\r]+)", system, re.IGNORECASE)
        if match:
            names = [b.strip(" *") for b in match.group(1).split(",") if b.strip(" *")]
            if names and "none configured" not in names[0].lower():
                return names
        seen = []
        for _name, _price, branch, _extra, _stock in CATALOGUE:
            if branch and branch not in seen:
                seen.append(branch)
        return seen

    @staticmethod
    def _previous_user(messages):
        users = [m.get("content") for m in messages
                 if m.get("role") == "user" and isinstance(m.get("content"), str)]
        return users[-2] if len(users) >= 2 else ""

    @staticmethod
    def _phone_match(text):
        return re.search(r"(?:\+263|00263|0)\s?\d(?:[\s-]?\d){8}\b", str(text or ""))

    def _phone(self, text):
        match = self._phone_match(text)
        if not match:
            return None
        phone, _ = normalize_phone(re.sub(r"[\s-]", "", match.group(0)))
        return phone

    def _without_phone(self, text):
        match = self._phone_match(text)
        raw = str(text or "")
        if not match:
            return raw.strip()
        cleaned = raw[:match.start()] + " " + raw[match.end():]
        return re.sub(r"[\s,;|/]+", " ", cleaned).strip(" .,;:-")

    # -- menu helpers ------------------------------------------------------
    @staticmethod
    def _items(text):
        """Numbered lines from a bot message: {number, label, price}."""
        items = []
        for line in str(text or "").splitlines():
            match = re.match(r"^\s*(\d{1,2})[.)]\s+(.+?)\s*$", line)
            if not match:
                continue
            rest = match.group(2).strip()
            price = None
            price_match = re.search(r"(?:[-–—:]\s*)?\$\s*(\d+(?:\.\d{1,2})?)\s*$", rest)
            if not price_match:
                price_match = re.search(r"\s[-–—]\s*(\d+(?:\.\d{1,2})?)\s*$", rest)
            if price_match:
                price = float(price_match.group(1))
                rest = rest[:price_match.start()].rstrip(" -–—:(")
            label = rest.strip("* ").strip()
            if " - " in label:
                label = label.split(" - ")[0].strip("* ").strip()
            if label:
                items.append({"number": int(match.group(1)), "label": label,
                              "price": price})
        return items

    def _find_menu(self, messages, last_bot):
        """The last numbered product list, even if a branch question came after it."""
        items = self._items(last_bot)
        if any(item["price"] is not None for item in items):
            return items
        for message in reversed(messages):
            if message.get("role") != "assistant":
                continue
            text = message.get("content") or ""
            low = text.lower()
            if "your cart" in low or "subtotal" in low:
                continue
            candidate = self._items(text)
            if len(candidate) >= 2 and any(i["price"] is not None for i in candidate):
                return candidate
        return items

    @staticmethod
    def _numbers(text, count):
        words = re.sub(r"[^a-z0-9\s]", " ", str(text or "").lower()).split()
        if not words or len(words) > 14:
            return []
        noise = {"add", "and", "the", "these", "to", "cart", "please", "i",
                 "want", "take", "get", "item", "items", "number", "numbers",
                 "option", "options", "all", "of", "them"}
        numbers = []
        for word in words:
            if word.isdigit():
                numbers.append(int(word))
            elif word not in noise:
                return []
        return [n for n in numbers if 1 <= n <= count]

    @staticmethod
    def _selects_all(text):
        low = str(text or "").lower()
        return ("add" in low or "cart" in low) and any(
            phrase in low for phrase in
            ("all of them", "all these", "these", "everything", "whole list", "all"))

    @staticmethod
    def _payment_method(text):
        low = str(text or "").lower()
        if "ecocash" in low or "eco cash" in low:
            return "ecocash"
        if "onemoney" in low or "one money" in low:
            return "onemoney"
        if "innbucks" in low or "inn bucks" in low:
            return "innbucks"
        if "cash" in low or "cod" in low or "pay on" in low:
            return "cash"
        return None

    def _menu_payment_method(self, text, items):
        for item in items:
            label = item["label"].lower()
            if any(word in label for word in
                   ("ecocash", "eco cash", "onemoney", "one money",
                    "innbucks", "inn bucks", "cash")):
                picked = self._numbers(text, len(items))
                if picked and picked[0] == item["number"]:
                    return self._payment_method(label)
        return None

    def _pick_payment(self, text, items):
        direct = self._payment_method(text)
        if direct:
            return direct
        return self._menu_payment_method(text, items)

    def _pick_collection(self, text, items):
        low = str(text or "").lower()
        if "walk" in low or "pick" in low or "collect" in low or "pickup" in low:
            return "walkin"
        if "deliver" in low:
            return "delivery"
        picked = self._numbers(text, len(items))
        if picked:
            label = items[picked[0] - 1]["label"].lower()
            if "walk" in label or "pick" in label or "collect" in label:
                return "walkin"
            if "deliver" in label:
                return "delivery"
        value = low.strip()
        if value == "1":
            return "walkin"
        if value == "2":
            return "delivery"
        return None

    @staticmethod
    def _looks_like_collection_menu(text, items):
        low = str(text or "").lower()
        return ("collect" in low or "how would you like" in low) and any(
            "walk" in item["label"].lower() or "deliver" in item["label"].lower()
            for item in items)

    @staticmethod
    def _looks_like_payment_menu(text, items):
        low = str(text or "").lower()
        return ("pay" in low or "payment" in low) and any(
            any(word in item["label"].lower() for word in
                ("cash", "ecocash", "onemoney", "innbucks"))
            for item in items)

    @staticmethod
    def _products_in_text(text):
        found = re.findall(r"\*([^*\n]+?)\*\s*\(\s*\$?(\d+(?:\.\d{1,2})?)\s*\)",
                           str(text or ""))
        return [(name.strip(), float(price)) for name, price in found
                if name.strip()]

    def _catalogue_price(self, name, branch=None):
        wanted = str(name or "").lower().strip()
        if not wanted:
            return None, None
        for product, price, product_branch, _extra, _stock in CATALOGUE:
            product_low = product.lower()
            if (wanted == product_low or wanted in product_low
                    or product_low in wanted):
                if branch and product_branch.lower() != branch.lower():
                    continue
                return price, product_branch
        return None, None

    def _add_items(self, items, branch):
        calls = []
        medicines = []
        for item in items:
            if item["price"] is None:
                continue
            price, product_branch = self._catalogue_price(item["label"], branch)
            if price is None:
                continue
            if is_medication_related(item["label"]):
                medicines.append(item["label"])
                continue
            calls.append(_tool("add_to_cart", {
                "product_name": item["label"],
                "price": price,
                "quantity": 1,
                "branch": product_branch or branch,
            }))
        if medicines:
            self.pending_note = sure_confirmation_message(medicines[0])
        if calls:
            return calls
        if medicines:
            return sure_confirmation_message(medicines[0])
        return []

    # -- decision ----------------------------------------------------------
    def _decide(self, payload, user_msg):
        lower = user_msg.lower()
        choice = payload.get("tool_choice")
        forced = choice.get("function", {}).get("name") if isinstance(choice, dict) else None

        if forced == "search_products":
            return [_tool("search_products", {"query": _clean_query(user_msg)})]
        if forced == "set_collection_method":
            return [_tool("set_collection_method",
                          {"method": "delivery" if "deliver" in lower else "walkin"})]
        if forced == "set_payment_method":
            method = next((m for m in ["ecocash", "onemoney", "innbucks", "cash"] if m in lower), "cash")
            digits = re.search(r"0\d{9}", user_msg)
            args = {"method": method}
            if method != "cash" and digits:
                args["mobile_number"] = digits.group(0)
            return [_tool("set_payment_method", args)]

        messages = payload.get("messages", [])
        system = self._system_text(messages)
        flow = self._flow_state(system)
        branch = self._active_branch(system)
        last_bot = self._last_assistant(messages)
        last_low = last_bot.lower()
        last_items = self._items(last_bot)

        # A yes to "are you really sure..." (the medicine double-check).
        sure_match = re.search(r"really sure you want \*([^*]+)\*", last_bot, re.IGNORECASE)
        if sure_match and is_affirmative(user_msg):
            item = sure_match.group(1).strip()
            price, product_branch = self._catalogue_price(item, branch)
            if price is not None:
                return [_tool("add_to_cart", {
                    "product_name": item, "price": price, "quantity": 1,
                    "branch": product_branch or branch})]

        # A yes to "shall I add X ($price) and Y ($price)?" adds every quoted
        # product, not just the first. The order summary is not a product list.
        if (is_affirmative(user_msg) and flow not in ("confirm", "payment")
                and "order summary" not in last_low):
            confirmed = self._products_in_text(last_bot)
            if confirmed and ("confirm" in last_low or "add" in last_low):
                calls = []
                for name, _price in confirmed:
                    real_price, product_branch = self._catalogue_price(name, branch)
                    if real_price is None:
                        continue
                    calls.append(_tool("add_to_cart", {
                        "product_name": name, "price": real_price, "quantity": 1,
                        "branch": product_branch or branch}))
                if calls:
                    return calls

        # "What details do you have?" / "I gave you my address already" asks
        # for the saved details, not for a product or a new address.
        if (("address" in lower or "details" in lower or "my info" in lower)
                and any(word in lower for word in
                        ("what", "whats", "already", "show", "tell", "gave"))
                or ("address" in lower and "?" in user_msg)):
            if not re.search(r"\b(my|the)\s+(delivery\s+)?address\s+is\b", lower):
                return [_tool("show_delivery_details", {})]

        # Branch menu: save the branch, then show the product they asked about
        # before the branch question if there was one.
        branch_menu = any(marker in last_low for marker in
                          ("which branch", "select a branch", "choose a branch"))
        if branch_menu:
            branches = self._available_branches(system)
            picked = self._numbers(user_msg, len(last_items))
            chosen = None
            if picked:
                chosen = last_items[picked[0] - 1]["label"]
            elif lower.strip() in (b.lower() for b in branches):
                chosen = user_msg.strip()
            elif lower.strip().isdigit() and not last_items:
                index = int(lower.strip()) - 1
                if 0 <= index < len(branches):
                    chosen = branches[index]
            if chosen:
                calls = [_tool("set_branch", {"branch": chosen})]
                previous = self._previous_user(messages)
                if previous and any(word in previous.lower() for word in
                                    ("do you have", "looking for", "how much",
                                     "show me", "i want", "i need")):
                    calls.append(_tool("search_products", {
                        "query": _clean_query(previous), "branch": chosen}))
                return calls

        # Collection / payment menus can be in history even when the stored
        # flow state is stale (the live "2" failure).
        if self._looks_like_collection_menu(last_bot, last_items):
            method = self._pick_collection(user_msg, last_items)
            if method:
                return [_tool("set_collection_method", {"method": method})]
        if self._looks_like_payment_menu(last_bot, last_items):
            method = self._pick_payment(user_msg, last_items)
            if method:
                args = {"method": method}
                phone = self._phone(user_msg)
                if phone and method != "cash":
                    args["mobile_number"] = phone
                return [_tool("set_payment_method", args)]

        # Checkout details are details, never product searches.
        if flow == "delivery_step_name":
            cleaned = self._without_phone(user_msg)
            candidate = extract_name_correction(user_msg) or cleaned
            if self._phone(user_msg) and not looks_like_person_name(cleaned) \
                    and not extract_name_correction(user_msg):
                return [_tool("update_delivery_phone", {"phone": user_msg})]
            if looks_like_person_name(candidate):
                return [_tool("update_delivery_name", {"name": user_msg})]
            if "my name" in lower and "?" in user_msg:
                return [_tool("show_delivery_details", {})]
            return []

        if flow == "delivery_step_phone":
            correction = extract_name_correction(user_msg)
            if correction and looks_like_person_name(correction):
                return [_tool("update_delivery_name", {"name": user_msg})]
            if "address" in lower and ("what" in lower or "my" in lower):
                return [_tool("show_delivery_details", {})]
            return [_tool("update_delivery_phone", {"phone": user_msg})]

        if flow == "delivery_step_address":
            if "address" in lower and ("what" in lower or "my" in lower
                                       or "which" in lower):
                return [_tool("show_delivery_details", {})]
            if looks_like_address(user_msg):
                return [_tool("update_delivery_address", {"address": user_msg})]
            return []

        if flow == "payment":
            if (looks_like_address(user_msg)
                    and not self._payment_method(user_msg)):
                return [_tool("update_delivery_address", {"address": user_msg})]
            method = self._pick_payment(user_msg, last_items)
            if method:
                args = {"method": method}
                phone = self._phone(user_msg)
                if phone and method != "cash":
                    args["mobile_number"] = phone
                return [_tool("set_payment_method", args)]
            correction = extract_name_correction(user_msg)
            if correction and looks_like_person_name(correction):
                return [_tool("update_delivery_name", {"name": user_msg})]
            return []

        if flow == "confirm":
            if is_affirmative(user_msg):
                return [_tool("confirm_order", {})]
            if looks_like_address(user_msg):
                return [_tool("update_delivery_address", {"address": user_msg})]
            method = self._pick_payment(user_msg, last_items)
            if method:
                return [_tool("set_payment_method", {"method": method})]
            return []

        if flow == "awaiting_collection":
            method = self._pick_collection(user_msg, last_items)
            if method:
                return [_tool("set_collection_method", {"method": method})]
            return []

        # Name changes and name questions outside the checkout flow.
        correction = extract_name_correction(user_msg)
        if correction and looks_like_person_name(correction):
            return [_tool("update_delivery_name", {"name": user_msg})]
        if "what is my name" in lower or "what's my name" in lower:
            return [_tool("show_delivery_details", {})]

        menu = self._find_menu(messages, last_bot)
        if menu and self._selects_all(user_msg):
            return self._add_items(menu, branch)

        if re.search(r"\b(checkout|check out|thats all|that's all|done|finish)\b", lower):
            return [_tool("view_cart", {}), _tool("start_checkout", {})]
        if "cart" in lower:
            return [_tool("view_cart", {})]

        # A numbered reply belongs to the last numbered menu. Even a branch
        # question in between does not turn "3 and 4" into product names.
        picked = self._numbers(user_msg, len(menu))
        if picked:
            chosen = [menu[n - 1] for n in picked]
            priced = [item for item in chosen if item["price"] is not None]
            if priced:
                return self._add_items(chosen, branch)
            calls = []
            for item in chosen:
                term = re.sub(r"\s*\(.*?\)", "", item["label"]).strip()
                calls.append(_tool("search_products", {"query": term, "branch": branch}))
            if calls:
                return calls
        if re.fullmatch(r"[\d\s,and]+", lower.strip()) and not any(
                item["price"] is not None for item in menu):
            return ("I can't tell which item you mean - those numbers aren't on a list "
                    "I've just sent you.\n\nSend me the product name, or tell me the kind "
                    "of product (e.g. 'body lotions') and I'll list them with numbers you "
                    "can reply with.")

        if re.search(r"\b(add|i want|i'd like|i will take|i'll take|order|buy|take|give me)\b", lower):
            calls = []
            for part in re.split(r"\s+and\s+|\s+also\s+|\s+plus\s+", user_msg):
                if not part.strip():
                    continue
                call = self._add_call(part, lower)
                if call:
                    calls.append(call)
            return calls
        if re.search(r"(do you have|have you got|how much|price|show me|looking for)", lower):
            return [_tool("search_products", {"query": _clean_query(user_msg)})]
        if is_affirmative(user_msg):
            return [_tool("confirm_order", {})]
        return []

    def _add_call(self, part, lower):
        part_lower = part.lower()
        # Honour an explicit "2 x <product>" quantity the way a real model would
        qty_match = re.search(r"\b(\d{1,2})\s*x\s+", part_lower)
        quantity = int(qty_match.group(1)) if qty_match else 1
        # Catalogue product? A real model searches first, so a drug word the
        # customer typed ("panadol") picks that catalogue row.
        best, best_score = None, 0
        tokens = set(re.findall(r"[a-z0-9]+", part_lower))
        for name, price, branch, _extra, _stock in CATALOGUE:
            name_tokens = set(re.findall(r"[a-z0-9]+", name.lower()))
            score = len(tokens & name_tokens) / max(1, len(name_tokens))
            if score < 0.5 and any(len(t) > 3 and t in name_tokens for t in tokens):
                score = 0.5
            if score > best_score:
                best, best_score = (name, price, branch), score
        if best and best_score >= 0.5:
            name, price, branch = best
            return _tool("add_to_cart", {"product_name": name, "price": price,
                                         "quantity": quantity, "branch": branch})
        # Unknown product - pass the words through with no price (realistic:
        # the tool must refuse instead of inventing a price)
        cleaned = re.sub(r"^(add|i want|i'd like|i will take|i'll take|order|buy|take|give me)\s+",
                         "", part.strip(), flags=re.IGNORECASE)
        return _tool("add_to_cart", {"product_name": cleaned.title(), "price": 0,
                                     "quantity": quantity, "branch": "Angwa"})


def _clean_query(text):
    cleaned = re.sub(r"^(do you have|have you got|how much is|how much for|show me|"
                     r"looking for|i need|i want|is there|are there|any)\s+", "",
                     text.strip(), flags=re.IGNORECASE)
    return cleaned.strip(" ?!.").strip()


def _tool(name, args):
    return {"id": f"call_{abs(hash((name, json.dumps(args, sort_keys=True)))) % 10**8}",
            "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _tool_msg(calls):
    return {"choices": [{"message": {"content": "", "tool_calls": calls}}]}


def _text_msg(text):
    return {"choices": [{"message": {"content": text}}]}


# --------------------------------------------------------------------------
# Conversation driver (mirrors _handle_inbound_whatsapp)
# --------------------------------------------------------------------------

class Bot:
    def __init__(self, db):
        self.db = db
        self.history = []
        self.phone = "263771234567"
        from modules.openclaw import router
        self.router = router

    async def say(self, text):
        reply = await self.router._generate_bot_reply(
            self.db, text, STORE, history=list(self.history),
            customer_phone=self.phone, conv_id="conv-test", account_id="acc-test")
        self.history.append({"role": "user", "content": text})
        self.history.append({"role": "assistant", "content": reply or ""})
        return reply or ""

    async def say_image(self, caption, image_url="https://example.test/photo.jpg"):
        """Same turn, but with a photo attached (a script, a product, a rash)."""
        reply = await self.router._generate_bot_reply(
            self.db, caption, STORE, history=list(self.history),
            image_urls=[image_url],
            customer_phone=self.phone, conv_id="conv-test", account_id="acc-test")
        self.history.append({"role": "user", "content": caption})
        self.history.append({"role": "assistant", "content": reply or ""})
        return reply or ""


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

FAILURES = []


def check(scenario, label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"    [{status}] {label}" + (f"  -> {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(f"{scenario}: {label} {detail}")


def transcript(title, user_msg, reply):
    print(f"\n  --- {title} ---")
    print(f"  CUSTOMER: {user_msg}")
    for line in (reply or "").splitlines():
        print(f"  BOT     : {line}")


async def run():
    from modules.openclaw import router

    db, db_path, engine = build_db()

    # Patch only the infrastructure the scenario runner can't provide
    router._get_order_state = _mem_get_order_state
    router._update_order_state = _mem_update_order_state
    router._create_order = _mem_create_order
    router._get_order_history = _mem_get_order_history
    fake = FakeModel()
    router._llm = fake

    bot = Bot(db)

    # ---------------------------------------------------------------- 1
    print("\n[1] First contact / greeting")
    reply = await bot.say("hi")
    transcript("greeting", "hi", reply)
    check("1", "bot replies", bool(reply.strip()))
    check("1", "greeting names the business",
          "welcome to platinum pharmacy" in reply.lower(), reply[:240])
    check("1", "greeting asks how it can help",
          "how can i help you today" in reply.lower(), reply[:240])
    check("1", "greeting lists every branch the store sells from",
          "angwa" in reply.lower() and "bulawayo" in reply.lower(), reply[:240])
    check("1", "greeting asks which branch to shop from",
          "which branch" in reply.lower(), reply[:240])

    # A finished order leaves an "idle" state row behind. That must not make
    # the next "hi" skip the branded greeting and fall through to the model.
    bot.history.clear()
    bot.phone = "263771234568"
    _ORDER_STATES[(STORE_ID, bot.phone)] = {
        "cart_items": [], "current_state": "idle", "selected_branch": "Angwa",
    }
    reply = await bot.say("hi")
    transcript("greeting with a stale idle order state", "hi", reply)
    check("1", "an idle state still gets the branded welcome",
          "welcome to platinum pharmacy" in reply.lower(), reply[:240])
    check("1", "...and still sees all the branches",
          "angwa" in reply.lower() and "bulawayo" in reply.lower(), reply[:240])

    # Restore the main test number for the product scenarios below.
    bot.history.clear()
    bot.phone = "263771234567"
    _ORDER_STATES.pop((STORE_ID, "263771234568"), None)

    # ---------------------------------------------------------------- 2
    print("\n[2] Misspelled products -> did-you-mean")
    for typed, expected in [("benylin 4 flu", "BENYLIN"),
                            ("benylin for flu", "BENYLIN"),
                            ("benilyn", "BENYLIN"),
                            ("nivia", "NIVEA"),
                            ("nivea", "NIVEA")]:
        result = await router._execute_pharmacy_tool(
            db, STORE, bot.phone, "search_products", {"query": typed})
        transcript(f"tool search '{typed}'", typed, result)
        check("2", f"'{typed}' resolves to {expected}",
              expected in result.upper(), result[:160])
        check("2", f"'{typed}' is a suggestion or a real hit",
              "DID_YOU_MEAN" in result or "FOUND" in result, result[:160])

    # A random string that happens to contain a product word is not a typo for
    # it: "zzzznothing" contains "thin" and used to be suggested as ALWAYS pads.
    from modules.openclaw.pharmacy_rules import suggest_product_names
    check("2", "a nonsense query gets no lookalike suggestion",
          not suggest_product_names("zzzznothing", ["ALWAYS ULTRA THIN 10S"]), "")

    # ---------------------------------------------------------------- 3
    print("\n[3] Prices are rounded to the nearest whole number")
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "search_products", {"query": "nivea", "branch": "Angwa"})
    transcript("search nivea (Angwa)", "nivea", result)
    check("3", "$9.75 is shown as $10", "$10" in result, result[:200])
    check("3", "no cents anywhere in the product list",
          not re.search(r"\$\d+\.\d\d", result), result[:200])
    check("3", "$6.00 stays $6", "$6\n" in result or "$6 " in result or result.endswith("$6"), result[:200])

    # ---------------------------------------------------------------- 4
    print("\n[4] Only active + in-stock products are offered")
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "search_products", {"query": "colgate", "branch": "Angwa"})
    transcript("search colgate (out of stock)", "colgate", result)
    check("4", "out-of-stock product is NOT offered",
          result.startswith("NOT FOUND") and "$" not in result and "DID_YOU_MEAN" not in result,
          result[:200])

    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "search_products", {"query": "sorbet facial wash", "branch": "Angwa"})
    transcript("search sorbet (out of stock via the products table)", "sorbet facial wash", result)
    check("4", "hidden when only the products row says out of stock",
          result.startswith("NOT FOUND") and "$" not in result, result[:200])

    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "search_products", {"query": "rexona deodorant", "branch": "Angwa"})
    transcript("search rexona (zero stock, sells when out of stock)", "rexona deodorant", result)
    check("4", "zero stock but sell_when_out_of_stock is still offered",
          "REXONA" in result.upper() and "$5" in result, result[:200])

    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "search_products", {"query": "simple facial wash", "branch": "Angwa"})
    transcript("search simple (inventory not tracked)", "simple facial wash", result)
    check("4", "untracked inventory is not treated as out of stock",
          "SIMPLE" in result.upper() and "$9" in result, result[:200])

    # ---------------------------------------------------------------- 5
    print("\n[5] Multi-item ordering - nothing gets skipped")
    _ORDER_STATES.clear()
    _CREATED_ORDERS.clear()
    bot.history.clear()
    bot.phone = "26377111111"

    fake.payloads.clear()
    reply = await bot.say("i want nivea cream and dove soap")
    transcript("ask for two products", "i want nivea cream and dove soap", reply)
    last_payload = fake.payloads[-1] if fake.payloads else {}
    check("5", "model was NOT forced into a product search for a multi-add",
          not (isinstance(last_payload.get("tool_choice"), dict)
               and last_payload["tool_choice"].get("function", {}).get("name") == "search_products"),
          str(last_payload.get("tool_choice")))
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    names = [i["product_name"] for i in state.get("cart_items", [])]
    check("5", "both products landed in the cart (2 items)", len(names) == 2, str(names))
    check("5", "nivea kept in the cart", any("NIVEA" in n.upper() for n in names), str(names))
    check("5", "dove kept in the cart", any("DOVE" in n.upper() for n in names), str(names))

    reply = await bot.say("also add zaron lipstick")
    transcript("add a third product", "also add zaron lipstick", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    names = [i["product_name"] for i in state.get("cart_items", [])]
    check("5", "third product added without dropping the others (3 items)", len(names) == 3, str(names))
    check("5", "earlier items still in the cart",
          any("NIVEA" in n.upper() for n in names) and any("DOVE" in n.upper() for n in names), str(names))

    reply = await bot.say("checkout")
    transcript("checkout", "checkout", reply)
    check("5", "collection method asked", "walk" in reply.lower(), reply[:160])
    reply = await bot.say("1")
    transcript("walk-in", "1", reply)
    check("5", "payment method asked", "payment" in reply.lower() or "ecocash" in reply.lower(), reply[:160])
    reply = await bot.say("cash")
    transcript("cash", "cash", reply)
    check("5", "order summary shows whole-number total",
          re.search(r"\*(?:Total|TOTAL)\D*\$\d+\b", reply) and not re.search(r"\$\d+\.\d\d", reply),
          reply[:300])
    reply = await bot.say("yes")
    transcript("confirm order", "yes", reply)
    check("5", "order created with whole-number total",
          len(_CREATED_ORDERS) == 1 and float(_CREATED_ORDERS[0]["total_amount"]) ==
          int(_CREATED_ORDERS[0]["total_amount"]), str(_CREATED_ORDERS[:1]))
    check("5", "order confirmation mentions an order number", "PP-" in reply, reply[:200])

    # ---------------------------------------------------------------- 6
    print("\n[6] A single confirmation covering SEVERAL products adds all of them")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377122222"
    bot.history.append({"role": "user", "content": "add nivea cream and dove soap"})
    bot.history.append({"role": "assistant",
                        "content": "Just to confirm, you want to add *NIVEA CREAM 100ML* ($6) "
                                   "and *DOVE SOAP 100G* ($4) to your cart from Angwa branch?"})
    reply = await bot.say("yes")
    transcript("confirm both at once", "yes", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    names = [i["product_name"].upper() for i in state.get("cart_items", [])]
    check("6", "BOTH confirmed products were added", len(names) == 2, str(names))
    check("6", "cart summary shows a whole-number subtotal",
          not re.search(r"\$\d+\.\d\d", reply), reply[:200])

    # ---------------------------------------------------------------- 7
    print("\n[7] 10-digit phone validation")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377133333"
    await bot.say("i want dove soap")
    _mem_update_order_state(db, STORE_ID, bot.phone, current_state="delivery_step_name",
                            collection_method="delivery", cart_items=[{"product_name": "DOVE SOAP 100G",
                                                                       "price": 4, "quantity": 1,
                                                                       "branch": "Angwa"}])
    reply = await bot.say("Tendai Moyo")
    transcript("delivery step 1", "Tendai Moyo", reply)
    check("7", "asks for phone number", "phone number" in reply.lower(), reply[:160])

    for bad in ["0771", "77123456", "0771234567890", "abc"]:
        reply = await bot.say(bad)
        transcript(f"invalid phone '{bad}'", bad, reply)
        check("7", f"'{bad}' rejected as not a 10-digit number",
              "10-digit" in reply, reply[:200])

    for raw, expected in [("077 123 4567", "0771234567"),
                          ("+263771234567", "0771234567"),
                          ("0771234567", "0771234567")]:
        _mem_update_order_state(db, STORE_ID, bot.phone, current_state="delivery_step_phone")
        reply = await bot.say(raw)
        transcript(f"phone '{raw}'", raw, reply)
        state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
        check("7", f"'{raw}' normalised to {expected}",
              state.get("customer_phone_delivery") == expected, str(state))
        check("7", f"'{raw}' is not also stored as the delivery address",
              not (state.get("customer_address") or "").strip(), str(state.get("customer_address")))
        check("7", f"'{raw}' moves on to the address step",
              state.get("current_state") == "delivery_step_address",
              str(state.get("current_state")))
        _mem_update_order_state(db, STORE_ID, bot.phone, current_state="delivery_step_name",
                                customer_address=None)

    _mem_update_order_state(db, STORE_ID, bot.phone, customer_address="12 Samora Machel Ave, Harare")
    # mobile money number via the tool
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "set_payment_method", {"method": "ecocash", "mobile_number": "0771"})
    check("7", "tool rejects a short EcoCash number", "10-digit" in result, result[:160])
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "set_payment_method", {"method": "ecocash", "mobile_number": "0771234567"})
    check("7", "tool accepts a valid EcoCash number", "ORDER SUMMARY" in result, result[:160])

    # ---------------------------------------------------------------- 7b
    print("\n[7b] A messy customer: hedges are not a name, a city is not an address")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377166666"
    cart = [{"product_name": "DOVE SOAP 100G", "price": 4, "quantity": 1, "branch": "Angwa"}]
    _mem_update_order_state(db, STORE_ID, bot.phone, current_state="delivery_step_name",
                            collection_method="delivery", cart_items=cart)
    for hedge in ["not sure", "i dont know", "maybe later", "cash"]:
        reply = await bot.say(hedge)
        transcript(f"not a name '{hedge}'", hedge, reply)
        state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
        check("7b", f"{hedge!r} is not saved as the customer's name",
              not (state.get("customer_name") or "").strip(),
              str(state.get("customer_name")))
        check("7b", f"{hedge!r} leaves the flow on the name step",
              state.get("current_state") == "delivery_step_name",
              str(state.get("current_state")))

    # A stale name prompt must not swallow a shopping request as the name.
    check("7b", "'add them to the cart' is not a person's name",
          not router.looks_like_person_name("add them to the cart"),
          str(router.looks_like_person_name("add them to the cart")))

    # Delivery details must not be saved or advanced when the cart is empty.
    empty_phone = "26377177777"
    _ORDER_STATES[(STORE_ID, empty_phone)] = {
        "cart_items": [], "current_state": "delivery_step_name",
    }
    for tool, args in [
        ("update_delivery_name", {"name": "Tendai Moyo"}),
        ("update_delivery_phone", {"phone": "0771234567"}),
        ("update_delivery_address", {"address": "12 Samora Machel Avenue, Harare CBD, Harare"}),
        ("set_delivery_details", {"customer_name": "Tendai Moyo",
                                  "phone": "0771234567",
                                  "address": "12 Samora Machel Avenue, Harare CBD, Harare"}),
    ]:
        result = await router._execute_pharmacy_tool(
            db, STORE, empty_phone, tool, args)
        transcript(f"{tool} with an empty cart", tool, result)
        check("7b", f"{tool} refuses an empty cart",
              "cart is empty" in result.lower(), result[:200])
    empty_state = _mem_get_order_state(db, STORE_ID, empty_phone) or {}
    check("7b", "...and saves none of the details",
          not any(empty_state.get(key) for key in
                  ("customer_name", "customer_phone_delivery", "customer_address")),
          str(empty_state))

    reply = await bot.say("tendai moyo")
    transcript("real name", "tendai moyo", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("7b", "a real name is saved", state.get("customer_name") == "tendai moyo",
          str(state.get("customer_name")))

    _mem_update_order_state(db, STORE_ID, bot.phone, current_state="delivery_step_address",
                            customer_address=None)
    for vague in ["harare", "bulawayo", "gweru"]:
        reply = await bot.say(vague)
        transcript(f"not an address '{vague}'", vague, reply)
        state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
        check("7b", f"{vague!r} on its own is not saved as the address",
              not (state.get("customer_address") or "").strip(),
              str(state.get("customer_address")))
        check("7b", f"{vague!r} leaves the flow on the address step",
              state.get("current_state") == "delivery_step_address",
              str(state.get("current_state")))

    _mem_update_order_state(db, STORE_ID, bot.phone, customer_phone_delivery="0771234567")
    reply = await bot.say("12 samora machel ave, harare")
    transcript("real address", "12 samora machel ave, harare", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("7b", "a real address is saved and payment is offered",
          "payment" in reply.lower() and state.get("current_state") == "payment",
          str(state.get("current_state")))

    reply = await bot.say("no wait cash")
    transcript("payment change in a sentence", "no wait cash", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("7b", "a payment method named in a sentence is honoured",
          state.get("payment_method") in ("cash", "cod"),
          str(state.get("payment_method")))
    check("7b", "the summary shows the method that was saved",
          "cash" in reply.lower(), reply[:200])

    # An address sent at the payment step is a correction, not a dead end.
    reply = await bot.say("actually 5 second street, harare")
    transcript("address correction", "actually 5 second street, harare", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("7b", "a corrected address is saved at the payment step",
          "second street" in (state.get("customer_address") or "").lower(),
          str(state.get("customer_address")))

    # ---------------------------------------------------------------- 7c
    print("\n[7c] Cart arithmetic taken from the customer's words")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377177777"

    def units_in_cart():
        state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
        return sum(int(i.get("quantity", 1) or 1) for i in state.get("cart_items") or [])

    # The model read "add another one" as "double it" and sent quantity=2.
    # The customer's words win: another one is ONE more unit.
    await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "add_to_cart",
        {"product_name": "DOVE SOAP 100G", "price": 4, "quantity": 1, "branch": "Angwa"},
        "add dove soap")
    check("7c", "one add leaves one unit", units_in_cart() == 1, str(units_in_cart()))
    await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "add_to_cart",
        {"product_name": "DOVE SOAP 100G", "price": 4, "quantity": 2, "branch": "Angwa"},
        "add anothr one")
    check("7c", "'add anothr one' adds exactly one unit, never double",
          units_in_cart() == 2, str(units_in_cart()))
    await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "add_to_cart",
        {"product_name": "DOVE SOAP 100G", "price": 4, "quantity": 2, "branch": "Angwa"},
        "add two more please")
    check("7c", "'two more' still adds two units", units_in_cart() == 4, str(units_in_cart()))
    await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "remove_from_cart",
        {"product_name": "DOVE SOAP 100G", "quantity": 1}, "take one out")
    check("7c", "'take one out' removes a single unit", units_in_cart() == 3, str(units_in_cart()))

    # ---------------------------------------------------------------- 8
    print("\n[8] Unsure customer -> pharmacist handover (never a suggestion)")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377144444"
    # Both pharmacist handovers are deterministic and fixed - any other reply
    # here means the model got to answer a clinical question.
    handovers = {router.PHARMACIST_REVIEW_MESSAGE.strip(),
                 router.PHARMACIST_QUESTION_MESSAGE.strip()}
    for msg in ["i'm not sure what i need",
                "what should i take for a headache",
                "can you recommend something, i dont know what to take",
                "i have a fever, what works for that"]:
        reply = await bot.say(msg)
        transcript("unsure customer", msg, reply)
        check("8", f"'{msg}' goes to the pharmacist",
              reply.strip() in handovers, reply[:200])
        check("8", f"'{msg}' does NOT suggest a product",
              not re.search(r"\$\d", reply), reply[:200])

    # ---------------------------------------------------------------- 9
    print("\n[9] Sure customer -> 'are you really sure?' then continues")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377155555"
    reply = await bot.say("i want panadol")
    transcript("sure customer", "i want panadol", reply)
    check("9", "asks for a double-check", "are you really sure" in reply.lower(), reply[:200])
    check("9", "names the product the customer asked for", "PANADOL" in reply.upper(), reply[:200])
    check("9", "no price/suggestion before confirmation", not re.search(r"\$\d", reply), reply[:200])

    reply = await bot.say("yes")
    transcript("confirmed", "yes", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    names = [i["product_name"].upper() for i in state.get("cart_items", [])]
    check("9", "after confirming, the order continues (item in cart)",
          any("PANADOL" in n for n in names), str(names))

    reply = await bot.say("also add panadol")
    transcript("medication added while shopping", "also add panadol", reply)
    check("9", "'also add panadol' is double-checked too",
          "are you really sure" in reply.lower(), reply[:200])
    def _units():
        items = (_mem_get_order_state(db, STORE_ID, bot.phone) or {}).get("cart_items", [])
        return sum(int(i.get("quantity", 1) or 1) for i in items), items

    before_units, before_items = _units()
    reply = await bot.say("yes")
    after_units, after_items = _units()
    check("9", "confirming an existing medication does not add another",
          after_units == before_units and bool(before_items),
          f"{before_units}->{after_units} {[i['product_name'] for i in after_items]}")

    _ORDER_STATES.clear()
    bot.history.clear()
    reply = await bot.say("i want panadol")
    reply = await bot.say("no")
    transcript("declined", "no", reply)
    check("9", "declining hands over to the pharmacist",
          "under review by our pharmacist" in reply.lower(), reply[:200])

    # ---------------------------------------------------------------- 10
    print("\n[10] Normal (non-medication) questions are not interrupted")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377166666"
    reply = await bot.say("do you have nivea")
    transcript("product question", "do you have nivea", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("10", "product question reaches the tools (no gate)",
          "are you really sure" not in reply.lower(), reply[:200])
    check("10", "search actually ran", bool(fake.payloads), "")

    # ---------------------------------------------------------------- 11
    print("\n[11] Edge cases")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377177777"

    # quantity requested explicitly
    reply = await bot.say("add 2 x nivea body lotion")
    transcript("explicit quantity", "add 2 x nivea body lotion", reply)
    items = (_mem_get_order_state(db, STORE_ID, bot.phone) or {}).get("cart_items", [])
    total_qty = sum(int(i.get("quantity", 1) or 1) for i in items)
    check("11", "quantity of 2 is stored", total_qty == 2, str(items))
    check("11", "subtotal counts the quantity ($10 x 2 = $20)", "$20" in reply, reply[:200])

    # adding the same product again grows the quantity instead of duplicating
    reply = await bot.say("add 1 x nivea body lotion")
    items = (_mem_get_order_state(db, STORE_ID, bot.phone) or {}).get("cart_items", [])
    check("11", "re-adding the same product merges into one line",
          len(items) == 1 and int(items[0].get("quantity", 1)) == 3, str(items))

    # checkout with an empty cart must not create an order
    _ORDER_STATES.clear()
    bot.history.clear()
    before_orders = len(_CREATED_ORDERS)
    reply = await bot.say("checkout")
    transcript("checkout with nothing in the cart", "checkout", reply)
    check("11", "empty-cart checkout says the cart is empty",
          "empty" in reply.lower(), reply[:200])
    check("11", "no order was created", len(_CREATED_ORDERS) == before_orders, str(len(_CREATED_ORDERS)))

    # a stray "yes" with nothing pending must not invent an order either
    reply = await bot.say("yes")
    transcript("stray yes", "yes", reply)
    check("11", "stray 'yes' does not create an order",
          len(_CREATED_ORDERS) == before_orders and "PP-" not in reply, reply[:200])

    # a product nobody stocks
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "search_products", {"query": "zzqx nonexistent brand", "branch": "Angwa"})
    check("11", "unknown product reports NOT FOUND instead of inventing one",
          result.startswith("NOT FOUND"), result[:160])

    # adding an unknown product without a price must be refused
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "add_to_cart",
        {"product_name": "Something Random", "price": 0, "quantity": 1, "branch": "Angwa"})
    check("11", "add_to_cart refuses a price-less product",
          "price is missing" in result.lower(), result[:160])

    # phone with letters mixed in, and a 9-digit number
    for bad in ["077ABC4567", "123456789"]:
        phone_clean, err = __import__("modules.openclaw.pharmacy_rules", fromlist=["x"]).normalize_phone(bad)
        check("11", f"'{bad}' rejected", phone_clean is None and "10-digit" in err, str(phone_clean))

    # ---------------------------------------------------------------- 12
    print("\n[12] Real conversation replay (263788836724, 17 Oct) - name/phone/address")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "263788836724"
    _mem_update_order_state(db, STORE_ID, bot.phone,
                            current_state="delivery_step_name",
                            collection_method="delivery",
                            cart_items=[{"product_name": "BENYLIN 4 FLU 200MLS", "price": 36,
                                         "quantity": 4, "branch": "Rezende"}])

    reply = await bot.say("farai rato")
    transcript("step 1 - name", "farai rato", reply)
    check("12", "first name accepted, phone requested",
          "phone number" in reply.lower(), reply[:160])

    # The real failure: a typo'd correction ("sorr", not "sorry") was answered
    # with the hardcoded phone error and the name change was lost.
    reply = await bot.say("sorr my real name is farai emmanuel rato")
    transcript("typo'd name correction at the phone step",
               "sorr my real name is farai emmanuel rato", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("12", "typo'd correction is NOT rejected as a phone number",
          "couldn't read" not in reply.lower(), reply[:200])
    check("12", "name updated from the correction",
          state.get("customer_name") == "farai emmanuel rato",
          str(state.get("customer_name")))
    check("12", "still asks for the phone number",
          "phone number" in reply.lower(), reply[:160])

    reply = await bot.say("0783434")
    transcript("short number", "0783434", reply)
    check("12", "short number rejected and echoed back",
          "10-digit" in reply and "0783434" in reply, reply[:200])

    reply = await bot.say("0781276999")
    transcript("valid phone", "0781276999", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("12", "phone saved",
          state.get("customer_phone_delivery") == "0781276999",
          str(state.get("customer_phone_delivery")))
    check("12", "asks for the address", "address" in reply.lower(), reply[:160])

    # Asking about the address must be answered, not stored as the address.
    reply = await bot.say("whats my delivery address")
    transcript("asking for the address before giving one", "whats my delivery address", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("12", "question is not stored as the address",
          not (state.get("customer_address") or "").strip(),
          str(state.get("customer_address")))

    reply = await bot.say("670 ushewekunze")
    transcript("real address", "670 ushewekunze", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("12", "real address saved",
          state.get("customer_address") == "670 ushewekunze",
          str(state.get("customer_address")))

    # The complaint that used to become the delivery address.
    reply = await bot.say("i gave you my address already")
    transcript("complaint instead of an address", "i gave you my address already", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("12", "complaint does NOT overwrite the saved address",
          state.get("customer_address") == "670 ushewekunze",
          str(state.get("customer_address")))
    check("12", "bot shows the address it already has",
          "670 ushewekunze" in reply, reply[:200])

    # A delivery order with no address must be refused, not confirmed.
    _ORDER_STATES.clear()
    _mem_update_order_state(db, STORE_ID, "263788836799",
                            collection_method="delivery", payment_method="cod",
                            customer_name="Test Customer", customer_phone_delivery="0771234567",
                            cart_items=[{"product_name": "DOVE SOAP 100G", "price": 4,
                                         "quantity": 1, "branch": "Angwa"}])
    before_orders = len(_CREATED_ORDERS)
    result = await router._execute_pharmacy_tool(db, STORE, "263788836799", "confirm_order", {})
    transcript("confirm with no address", "yes", result)
    check("12", "confirm refuses a delivery order with no address",
          "ADDRESS" in result.upper() and len(_CREATED_ORDERS) == before_orders, result[:200])

    # The tool path must not accept a sentence as the address either.
    _ORDER_STATES[(STORE_ID, "263788836798")] = {
        "cart_items": [{"product_name": "DOVE SOAP 100G", "price": 4,
                        "quantity": 1, "branch": "Angwa"}],
        "selected_branch": "Angwa",
    }
    result = await router._execute_pharmacy_tool(
        db, STORE, "263788836798", "set_delivery_details",
        {"customer_name": "Farai Rato", "phone": "0781276999",
         "address": "i gave you my address already"})
    check("12", "set_delivery_details rejects a sentence as the address",
          "INCOMPLETE" in result.upper(), result[:200])

    # ---------------------------------------------------------------- 12b
    print("\n[12b] Mobile-money confirmation sends the PayNow prompt")

    calls = []
    original_mobile_payment = router._initiate_mobile_payment

    def fake_mobile_payment(db_, order_number, phone):
        calls.append((order_number, phone))
        return {"success": True,
                "instructions": "Dial *151*2# on your EcoCash phone and approve.",
                "reference": "PNW-SCENARIO"}

    router._initiate_mobile_payment = fake_mobile_payment
    try:
        mobile_phone = "263788836797"
        _ORDER_STATES[(STORE_ID, mobile_phone)] = {
            "cart_items": [{"product_name": "DOVE SOAP 100G", "price": 4,
                            "quantity": 1, "branch": "Angwa"}],
            "selected_branch": "Angwa",
            "collection_method": "walkin",
            "payment_method": "mobile_money",
            "payment_provider": "ecocash",
            "payment_phone": "0771234567",
        }
        result = await router._execute_pharmacy_tool(
            db, STORE, mobile_phone, "confirm_order", {})
        transcript("confirm an EcoCash order", "yes", result)
        check("12b", "confirm_order actually initiates the mobile payment",
              len(calls) == 1, str(calls))
        check("12b", "...with the saved wallet number",
              calls and calls[0][1] == "0771234567", str(calls))
        check("12b", "the customer is told to approve the prompt",
              "payment request sent" in result.lower()
              and "dial *151*2#" in result.lower()
              and "approve the prompt" in result.lower(), result[:300])

        # Cash must never trigger a PayNow prompt.
        calls.clear()
        cash_phone = "263788836796"
        _ORDER_STATES[(STORE_ID, cash_phone)] = {
            "cart_items": [{"product_name": "DOVE SOAP 100G", "price": 4,
                            "quantity": 1, "branch": "Angwa"}],
            "selected_branch": "Angwa",
            "collection_method": "walkin",
            "payment_method": "cash",
        }
        result = await router._execute_pharmacy_tool(
            db, STORE, cash_phone, "confirm_order", {})
        check("12b", "a cash order does not call PayNow", not calls, str(calls))
        check("12b", "a cash order is confirmed normally",
              "order confirmed" in result.lower(), result[:200])

        # A failed prompt must not look like a successful payment.
        calls.clear()

        def failing_mobile_payment(db_, order_number, phone):
            calls.append((order_number, phone))
            return {"error": "PayNow is temporarily unavailable"}

        router._initiate_mobile_payment = failing_mobile_payment
        failed_phone = "263788836795"
        _ORDER_STATES[(STORE_ID, failed_phone)] = {
            "cart_items": [{"product_name": "DOVE SOAP 100G", "price": 4,
                            "quantity": 1, "branch": "Angwa"}],
            "selected_branch": "Angwa",
            "collection_method": "walkin",
            "payment_method": "mobile_money",
            "payment_provider": "onemoney",
            "payment_phone": "0771234567",
        }
        result = await router._execute_pharmacy_tool(
            db, STORE, failed_phone, "confirm_order", {})
        transcript("confirm with PayNow down", "yes", result)
        check("12b", "a failed prompt is reported, not hidden",
              "payment not sent" in result.lower()
              and "temporarily unavailable" in result.lower(), result[:300])
    finally:
        router._initiate_mobile_payment = original_mobile_payment

    # ---------------------------------------------------------------- 13
    print("\n[13] Cart editing: update_cart / remove_from_cart / get_order_status / list_branches")
    _ORDER_STATES.clear()
    _CREATED_ORDERS.clear()
    bot.history.clear()
    bot.phone = "26377188888"

    await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "add_to_cart",
        {"product_name": "NIVEA CREAM 100ML", "price": 6, "quantity": 1, "branch": "Angwa"})
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "update_cart",
        {"product_name": "nivea cream", "quantity": 3})
    transcript("change quantity to 3", "make the nivea 3", result)
    items = (_mem_get_order_state(db, STORE_ID, bot.phone) or {}).get("cart_items", [])
    check("13", "update_cart sets the ABSOLUTE quantity",
          len(items) == 1 and int(items[0]["quantity"]) == 3, str(items))
    check("13", "update reports the new quantity", "x3" in result, result[:160])
    check("13", "subtotal follows the new quantity ($18)", "$18" in result, result[:200])

    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "update_cart",
        {"product_name": "nivea cream", "quantity": 2})
    items = (_mem_get_order_state(db, STORE_ID, bot.phone) or {}).get("cart_items", [])
    check("13", "second edit replaces the quantity, not stacks it",
          int(items[0]["quantity"]) == 2, str(items))

    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "update_cart",
        {"product_name": "dove soap", "quantity": 2})
    check("13", "editing an item not in the cart is refused with the real contents",
          "not in the cart" in result.lower() and "NIVEA" in result.upper(), result[:200])

    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "update_cart",
        {"product_name": "nivea cream", "quantity": 0})
    items = (_mem_get_order_state(db, STORE_ID, bot.phone) or {}).get("cart_items", [])
    check("13", "quantity 0 deletes the line instead of erroring", items == [], str(items))
    await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "add_to_cart",
        {"product_name": "NIVEA CREAM 100ML", "price": 6, "quantity": 1, "branch": "Angwa"})

    # swapping the product must take the catalogue price, never the model's
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "update_cart",
        {"product_name": "nivea cream", "quantity": 1,
         "new_product_name": "DOVE SOAP 100G"})
    items = (_mem_get_order_state(db, STORE_ID, bot.phone) or {}).get("cart_items", [])
    check("13", "swapping an item uses the catalogue price",
          items and "DOVE" in items[0]["product_name"].upper()
          and round(float(items[0]["price"])) == 4, str(items))

    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "remove_from_cart", {"product_name": "dove"})
    items = (_mem_get_order_state(db, STORE_ID, bot.phone) or {}).get("cart_items", [])
    check("13", "remove_from_cart empties the line", items == [], str(items))

    result = await router._execute_pharmacy_tool(db, STORE, bot.phone, "get_order_status", {})
    check("13", "get_order_status says so (and invents nothing) when there is no order",
          "no orders found" in result.lower() and "PP-" not in result, result[:200])

    _mem_create_order(db, STORE_ID, bot.phone, {
        "items": [{"product_name": "DOVE SOAP 100G", "price": 4, "quantity": 1,
                   "branch": "Angwa"}],
        "total_amount": 4, "subtotal": 4, "payment_method": "cod"})
    result = await router._execute_pharmacy_tool(db, STORE, bot.phone, "get_order_status", {})
    transcript("what is my order number", "whats my order number", result)
    order_number = _CREATED_ORDERS[-1]["order_number"]
    check("13", "get_order_status returns the real order number",
          order_number in result, result[:200])
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "get_order_status", {"order_number": "PP-NOPE"})
    check("13", "an unknown order number is refused, not invented",
          "no order" in result.lower(), result[:200])

    result = await router._execute_pharmacy_tool(db, STORE, bot.phone, "list_branches", {})
    transcript("which branches exist", "which branches do you have", result)
    check("13", "list_branches returns the catalogue branches",
          "Angwa" in result and "Bulawayo" in result, result[:200])

    # the product lookup must not score the request words against the catalogue
    check("13", "the buy verb is stripped before the fuzzy product search",
          router._clean_product_query("also add dove soap") == "dove soap",
          router._clean_product_query("also add dove soap"))
    check("13", "question wording is stripped too",
          router._clean_product_query("do you have nivea cream") == "nivea cream",
          router._clean_product_query("do you have nivea cream"))

    # the model must choose its own tools - no keyword-forced tool_choice
    fake.payloads.clear()
    await bot.say("do you have cash soap for delivery")
    payload = fake.payloads[0] if fake.payloads else {}
    check("13", "no tool is forced from keywords",
          payload.get("tool_choice") == "auto", str(payload.get("tool_choice")))

    # ---------------------------------------------------------------- 14
    print("\n[14] Medication/prescription questions are NEVER answered by the model")
    _ORDER_STATES.clear()
    _CREATED_ORDERS.clear()
    bot.history.clear()
    bot.phone = "26377199999"

    clinical = [
        "can i take panadol with antibiotics",
        "how many panadol can i take at once",
        "what's the dose for a 5 year old",
        "is it safe to take ibuprofen while pregnant",
        "i have a fever and a headache",
        "what can i take for a cough",
        "do you have something for a cough",
        "can i drink alcohol with flagyl",
        "my doctor prescribed amoxicillin, how often do i take it",
        "is my prescription ready",
        "can i get a refill on my script",
        "i took too much panadol, what do i do",
        "any side effects of tramadol",
        "which is stronger, panadol or ibuprofen",
        "is panadol safe for my baby",
        "my back hurts",
        # No product named, still clinical: the bot must not guess either.
        "can i drink alcohol with this",
        "can i take these two together",
        "i'm allergic to penicillin, what can i take",
        "is this ok for kids",
        "can my daughter take this",
        "i want something to help me sleep",
        "i need my medication",
        "i have been feeling dizzy",
        # A question about a drug is a pharmacist question too.
        "is amoxicillin an antibiotic",
        "does benylin make you sleepy",
        "can i stop taking my tablets",
    ]
    for msg in clinical:
        fake.payloads.clear()
        reply = await bot.say(msg)
        transcript("clinical question", msg, reply)
        check("14", f"'{msg}' -> pharmacist handover",
              reply.strip() == router.PHARMACIST_QUESTION_MESSAGE.strip(), reply[:160])
        check("14", f"'{msg}' never reached the model",
              not fake.payloads, f"{len(fake.payloads)} model call(s)")
        check("14", f"'{msg}' contains no price and no medicine advice",
              not re.search(r"\$\d", reply) and "panadol" not in reply.lower(), reply[:160])

    check("14", "no clinical question touched the cart",
          not ((_mem_get_order_state(db, STORE_ID, bot.phone) or {}).get("cart_items")), "")

    # A photo must not become a back door: a script caption is handed over too,
    # and the pharmacy image prompt tells the model not to read a prescription.
    fake.payloads.clear()
    reply = await bot.say_image("here is my script")
    transcript("prescription photo", "here is my script", reply)
    check("14", "a prescription photo caption is handed to the pharmacist",
          reply.strip() == router.PHARMACIST_QUESTION_MESSAGE.strip(), reply[:200])
    check("14", "the model never saw the prescription photo",
          not fake.payloads, f"{len(fake.payloads)} model call(s)")

    fake.payloads.clear()
    reply = await bot.say_image("is this the nivea cream you sell")
    system_prompt = "\n".join(str(m.get("content")) for m in
                               (fake.payloads[0].get("messages", []) if fake.payloads else [])
                               if m.get("role") == "system")
    check("14", "a product photo still reaches the model", bool(fake.payloads), "")
    check("14", "the image prompt forbids reading a prescription",
          "do not read it" in system_prompt.lower(),
          system_prompt[:200])
    check("14", "the image prompt no longer asks for a prescription quotation",
          "read all medication names" not in system_prompt.lower(), "")

    # shopping questions must still reach the tools - the guard is narrow
    fake.payloads.clear()
    reply = await bot.say("do you have panadol")
    transcript("stock question still reaches the tools", "do you have panadol", reply)
    check("14", "'do you have panadol' still reaches the model/tools", bool(fake.payloads), "")
    fake.payloads.clear()
    reply = await bot.say("how much is benylin")
    check("14", "'how much is benylin' still reaches the model/tools", bool(fake.payloads), "")

    fake.payloads.clear()
    reply = await bot.say("amoxicillin 500mg")
    check("14", "a drug name on its own is still a product search",
          bool(fake.payloads), "")

    fake.payloads.clear()
    reply = await bot.say("add dove soap")
    check("14", "adding a non-medication product still works",
          "$" in reply and "dove" in reply.lower(), reply[:200])

    # Buying wording must reach the catalogue even when a medicine or a symptom
    # is named: "can i get panadol" is an order, not a request for advice.
    for msg in ("can i get panadol", "do you have painkillers",
                "i need a box of panadol"):
        fake.payloads.clear()
        reply = await bot.say(msg)
        transcript("buying wording reaches the catalogue", msg, reply)
        check("14", f"'{msg}' is not sent to the pharmacist",
              reply.strip() != router.PHARMACIST_QUESTION_MESSAGE.strip(), reply[:200])
        # Either the sure-check or a catalogue answer - both mean the order side
        # of the flow handled it instead of the clinical gate.
        check("14", f"'{msg}' continues as a product request",
              "are you really sure" in reply.lower() or bool(fake.payloads), reply[:200])

    # A medicine the branch price list does not stock is never sold: the bot
    # must not invent a pack or a price for it (metformin/ibuprofen are not in
    # this test catalogue), so it goes to the pharmacist instead.
    for msg in ("can i get metformin", "i need a box of ibuprofen"):
        fake.payloads.clear()
        reply = await bot.say(msg)
        transcript("unstocked medicine", msg, reply)
        check("14", f"'{msg}' (not stocked) goes to the pharmacist",
              reply.strip() == router.PHARMACIST_REVIEW_MESSAGE.strip(), reply[:200])
        check("14", f"'{msg}' quotes no invented price",
              not re.search(r"\$\d", reply), reply[:200])

    # ...but naming no product at all is still pharmacist work.
    fake.payloads.clear()
    reply = await bot.say("i need medication")
    transcript("vague medication request", "i need medication", reply)
    check("14", "'i need medication' still goes to the pharmacist",
          reply.strip() == router.PHARMACIST_QUESTION_MESSAGE.strip(), reply[:200])
    check("14", "'i need medication' never reached the model",
          not fake.payloads, f"{len(fake.payloads)} model call(s)")

    # A store without a pharmacist still never answers - it just must not promise
    # a pharmacist it does not have.
    hardware = types.SimpleNamespace(**{**vars(STORE), "store_name": "Rato Hardware",
                                       "store_category": "Hardware",
                                       "business_type": "retail",
                                       "store_description": "Tools and building supplies."})
    fake.payloads.clear()
    reply = await router._generate_bot_reply(
        db, "can i take panadol with antibiotics", hardware,
        history=[], customer_phone="26377199998")
    transcript("non-pharmacy store asked a clinical question",
               "can i take panadol with antibiotics", reply)
    check("14", "a non-pharmacy store still refuses to answer",
          reply.strip() == router.HEALTH_QUESTION_MESSAGE.strip(), reply[:200])
    check("14", "...without claiming a pharmacist it does not have",
          "pharmacist" not in reply.lower(), reply[:200])
    check("14", "the non-pharmacy clinical question never reached the model",
          not fake.payloads, f"{len(fake.payloads)} model call(s)")

    # ---------------------------------------------------------------- 15
    print("\n[15] Asking to change the name actually changes it")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377100000"
    name_phone = bot.phone
    # A delivery flow only exists when there is something to deliver. Seeding a
    # cart keeps these name tests on the real path now that delivery tools
    # refuse to advance an empty cart.
    _ORDER_STATES[(STORE_ID, name_phone)] = {
        "cart_items": [{"product_name": "DOVE SOAP 100G", "price": 4,
                        "quantity": 1, "branch": "Angwa"}],
        "selected_branch": "Angwa",
    }

    def name_saved():
        return ((_mem_get_order_state(db, STORE_ID, name_phone) or {})
                .get("customer_name"))

    # Inside the delivery flow, step 1 used to answer "Your name is *Old Name*"
    # and drop the new name without saving it.
    for msg in ["my name is Farai Rato",
                "my real name is Farai Emmanuel Rato",
                "call me Farai Rato"]:
        _mem_update_order_state(db, STORE_ID, name_phone,
                                current_state="delivery_step_name",
                                customer_name="Old Name")
        reply = await bot.say(msg)
        transcript("name during the delivery step", msg, reply)
        check("15", f"'{msg}' is saved as the name", name_saved() != "Old Name", str(name_saved()))
        check("15", f"'{msg}' does not answer with the old name",
              "old name" not in reply.lower(), reply[:160])
        check("15", f"'{msg}' moves on to the phone number",
              "phone number" in reply.lower(), reply[:160])

    # Outside the flow the request was answered "Sure - tell me what you need".
    for msg, expected in [("change my name to Tendai Moyo", "Tendai Moyo"),
                          ("update my name to Tendai", "Tendai"),
                          ("my name is Tendai Moyo", "Tendai Moyo")]:
        _mem_update_order_state(db, STORE_ID, name_phone,
                                current_state="idle", customer_name="Old Name")
        reply = await bot.say(msg)
        transcript("name outside the flow", msg, reply)
        check("15", f"'{msg}' updates the saved name", name_saved() == expected, str(name_saved()))
        check("15", f"'{msg}' confirms the new name back", expected in reply, reply[:160])

    reply = await bot.say("what is my name")
    transcript("asking for the name", "what is my name", reply)
    check("15", "asking for the name answers with the saved one",
          "Tendai Moyo" in reply, reply[:160])
    check("15", "...without changing it", name_saved() == "Tendai Moyo", str(name_saved()))

    reply = await bot.say("what is the name of this product")
    transcript("product-name question", "what is the name of this product", reply)
    check("15", "a question about a product's name is not answered as the customer's",
          "tendai" not in reply.lower(), reply[:160])

    reply = await bot.say("my name is not Farai")
    transcript("correction with no new name", "my name is not Farai", reply)
    check("15", "a correction naming no new name leaves the saved one alone",
          name_saved() == "Tendai Moyo", str(name_saved()))

    # ---------------------------------------------------------------- 16
    print("\n[16] Answering \"which branch?\" is not a product search")
    _ORDER_STATES.clear()
    branch_menu = ("Hi! Welcome to Platinum Pharmacy! Which branch would you like to shop from?\n\n"
                   "1. Angwa\n2. Bulawayo")

    bot.history.clear()
    bot.phone = "26377100001"
    bot.history.extend([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": branch_menu},
    ])
    fake.payloads.clear()
    reply = await bot.say("1")
    transcript("branch answer", "1", reply)
    check("16", "'1' is read as the Angwa branch", "angwa" in reply.lower(), reply[:200])
    check("16", "...without asking for the branch again",
          "which branch" not in reply.lower(), reply[:200])
    check("16", "...and without inventing a NIVEA catalogue",
          "nivea" not in reply.lower(), reply[:200])
    check("16", "...and the model handled the branch answer", bool(fake.payloads),
          f"{len(fake.payloads)} model call(s)")
    saved = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("16", "the chosen branch is remembered",
          str(saved.get("selected_branch", "")).lower() == "angwa", str(saved.get("selected_branch")))

    # The customer asked for a product, the bot asked which branch, they answered.
    bot.history.clear()
    bot.history.extend([
        {"role": "user", "content": "do you have nivea soft moisturiser"},
        {"role": "assistant", "content": "We have Nivea products. Which branch would you like to check prices for?"},
    ])
    _ORDER_STATES[(STORE_ID, bot.phone)] = {"cart_items": []}
    fake.payloads.clear()
    reply = await bot.say("2")
    transcript("branch answer after a product question", "2", reply)
    check("16", "the product they asked about is shown at the chosen branch",
          "nivea soft" in reply.lower() and "$12" in reply, reply[:240])
    check("16", "...and the model handles branch replies", bool(fake.payloads), f"{len(fake.payloads)} model call(s)")
    check("16", "...and it does not ask for the branch again",
          "which branch" not in reply.lower(), reply[:200])

    # A stray number must never turn into the skincare catalogue.
    fake.payloads.clear()
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "search_products", {"query": "1"})
    transcript("stray '1' in a product search", "1", result)
    check("16", "a bare '1' does not return skincare products as if they were the answer",
          "$" not in result, result[:200])
    check("16", "...it asks what they are looking for instead",
          "what type of product" in result.lower(), result[:200])

    # ---------------------------------------------------------------- 17
    print("\n[17] A numbered list can be answered with its numbers")
    _ORDER_STATES.clear()
    bot.phone = "26377100002"
    bot.history.clear()
    _ORDER_STATES[(STORE_ID, bot.phone)] = {"cart_items": [], "selected_branch": "Angwa"}
    product_menu = ("Here are the body lotions at the Angwa branch:\n\n"
                    "1. NIVEA CREAM 100ML - $6\n2. NIVEA BODY LOTION 400ML - $10")
    bot.history.extend([
        {"role": "user", "content": "body lotions"},
        {"role": "assistant", "content": product_menu},
    ])

    fake.payloads.clear()
    reply = await bot.say("add 2")
    transcript("'add 2' against a product list", "add 2", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    names = [i.get("product_name") for i in state.get("cart_items") or []]
    check("17", "'add 2' adds the second product on the list",
          "NIVEA BODY LOTION 400ML" in names, str(names))
    check("17", "...at the list's branch and a whole-number price",
          any(i.get("price") == 10 and i.get("branch") == "Angwa"
              for i in state.get("cart_items") or []), str(state.get("cart_items")))
    check("17", "...the model handles the menu reply", bool(fake.payloads),
          f"{len(fake.payloads)} model call(s)")

    bot.history.clear()
    bot.history.extend([
        {"role": "user", "content": "body lotions"},
        {"role": "assistant", "content": product_menu},
    ])
    fake.payloads.clear()
    reply = await bot.say("1, and 2")
    transcript("'1, and 2' against a product list", "1, and 2", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    names = [i.get("product_name") for i in state.get("cart_items") or []]
    check("17", "both numbers are added, not just the first",
          "NIVEA CREAM 100ML" in names and "NIVEA BODY LOTION 400ML" in names, str(names))
    check("17", "...the model handles the menu reply", bool(fake.payloads),
          f"{len(fake.payloads)} model call(s)")

    # A number past the end of the list is not an order for anything.
    before = list(names)
    bot.history.clear()
    bot.history.extend([
        {"role": "user", "content": "body lotions"},
        {"role": "assistant", "content": product_menu},
    ])
    await bot.say("6")
    after = [i.get("product_name") for i in
             (_mem_get_order_state(db, STORE_ID, bot.phone) or {}).get("cart_items") or []]
    check("17", "a number past the end of the list adds nothing", after == before, str(after))

    # Collection menu: "2" must mean Delivery and must be saved.
    collection_menu = ("Your cart total: *$16*\n\n*How would you like to collect your order?*\n\n"
                       "1. *Walk-in* - Pick up from our branch\n2. *Delivery* - We deliver to you")
    bot.history.clear()
    bot.history.extend([
        {"role": "user", "content": "checkout"},
        {"role": "assistant", "content": collection_menu},
    ])
    fake.payloads.clear()
    reply = await bot.say("2")
    transcript("'2' against the collection menu", "2", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("17", "'2' on the collection menu is saved as delivery",
          str(state.get("collection_method", "")).lower() == "delivery", str(state.get("collection_method")))
    check("17", "...and does not add the second cart item again",
          len(state.get("cart_items") or []) == 2, str(state.get("cart_items")))
    check("17", "...the collection choice is saved without a model call", not fake.payloads,
          f"{len(fake.payloads)} model call(s)")

    # Payment menu: "2" must mean EcoCash and must be saved.
    payment_menu = ("How would you like to pay?\n\n1. *Cash* - pay on collection\n"
                    "2. *EcoCash* - mobile money")
    bot.history.clear()
    bot.history.extend([
        {"role": "user", "content": "delivery"},
        {"role": "assistant", "content": payment_menu},
    ])
    fake.payloads.clear()
    reply = await bot.say("2")
    transcript("'2' against the payment menu", "2", reply)
    check("17", "a mobile-money choice asks for the number, not for internal instructions",
          "10-digit" in reply and "call set_payment_method" not in reply, reply[:200])
    check("17", "...the model handles the menu reply", bool(fake.payloads),
          f"{len(fake.payloads)} model call(s)")

    # With the number in the same breath the method is saved.
    bot.history.clear()
    bot.history.extend([
        {"role": "user", "content": "delivery"},
        {"role": "assistant", "content": payment_menu},
    ])
    fake.payloads.clear()
    reply = await bot.say("2 0771234567")
    transcript("'2' plus a number against the payment menu", "2 0771234567", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("17", "'2 0771234567' is saved as EcoCash",
          str(state.get("payment_provider", "")).lower() == "ecocash",
          str(state.get("payment_provider") or state.get("payment_method")))
    check("17", "...with the number kept",
          "0771234567" in str(state.get("payment_phone") or ""), str(state.get("payment_phone")))

    # ---------------------------------------------------------------- 18
    print("\n[18] Category phrases list that category, and 'all' is not a branch")
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "search_products", {"query": "personal care products"})
    transcript("tool search 'personal care products'", "personal care products", result)
    check("18", "'personal care products' lists personal-care items",
          result.startswith("FOUND") and ("NIVEA" in result or "DOVE" in result), result[:200])
    check("18", "...instead of a did-you-mean", "DID_YOU_MEAN" not in result, result[:200])

    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "search_products", {"query": "toiletries"})
    check("18", "'toiletries' lists soap/deodorant",
          result.startswith("FOUND") and ("DOVE" in result or "REXONA" in result), result[:200])

    # A customer can type the whole product name. The catalogue uses "&" and
    # the customer writes a space, so the exact LIKE search misses it. The token
    # fallback must find the row instead of telling them it is out of stock.
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "search_products",
        {"query": "benylin 4 flu cough syrup 100ml", "branch": "Angwa"})
    transcript("full name with '&' in the catalogue", "benylin 4 flu cough syrup", result)
    check("18", "a full product name with '&' finds the catalogue row",
          "BENYLIN 4 FLU & COUGH SYRUP 100ML" in result, result[:240])
    check("18", "...without a did-you-mean detour", "DID_YOU_MEAN" not in result, result[:200])

    # "body lotion" used to be rewritten to "lotion", which made this exact
    # product miss even though its catalogue title contains both words.
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "search_products",
        {"query": "nivea body lotion 400ml", "branch": "Angwa"})
    transcript("full name with a qualifier", "nivea body lotion 400ml", result)
    check("18", "'body lotion' is not discarded from the search",
          "NIVEA BODY LOTION 400ML" in result, result[:240])

    # The model often includes the quantity in the query: "add 2 nivea...".
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "search_products",
        {"query": "2 nivea body lotion 400ml", "branch": "Angwa"})
    transcript("full name with a quantity", "2 nivea body lotion 400ml", result)
    check("18", "a leading quantity does not hide the named product",
          "NIVEA BODY LOTION 400ML" in result, result[:240])

    # The live WhatsApp conversation had branch='all' rejected as a branch.
    _ORDER_STATES.clear()
    bot.phone = "26377100003"
    _ORDER_STATES[(STORE_ID, bot.phone)] = {"cart_items": [], "selected_branch": "Angwa"}
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "add_to_cart",
        {"product_name": "NIVEA CREAM 100ML", "price": 6, "quantity": 1, "branch": "all"})
    transcript("add with branch='all'", "branch=all", result)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    names = [i.get("product_name") for i in state.get("cart_items") or []]
    check("18", "branch='all' uses the active branch and does not block the add",
          "NIVEA CREAM 100ML" in names, result[:200])
    check("18", "...the item still gets a real branch",
          all(i.get("branch") for i in state.get("cart_items") or []), str(state.get("cart_items")))

    # A customer who has not chosen a branch must be asked, not guessed at.
    _ORDER_STATES.clear()
    bot.phone = "26377100005"
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "add_to_cart",
        {"product_name": "NIVEA CREAM 100ML", "price": 6, "quantity": 1})
    transcript("add with no branch", "no branch", result)
    check("18", "an add with no branch asks which branch",
          result.startswith("BRANCH_REQUIRED"), result[:200])

    # A branch that conflicts with the existing cart must be rejected.
    _ORDER_STATES[(STORE_ID, bot.phone)] = {"cart_items": [], "selected_branch": "Angwa"}
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "add_to_cart",
        {"product_name": "NIVEA CREAM 100ML", "price": 6, "quantity": 1, "branch": "Bulawayo"})
    transcript("add from a conflicting branch", "branch=Bulawayo", result)
    check("18", "a conflicting branch is rejected before the price lookup",
          "already set to Angwa" in result, result[:240])

    # ---------------------------------------------------------------- 19
    print("\n[19] A category phrase in the bot itself, not just the tool")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377100004"
    fake.payloads.clear()
    reply = await bot.say("personal care products")
    transcript("personal care products", "personal care products", reply)
    check("19", "the customer gets personal-care products",
          ("NIVEA" in reply or "DOVE" in reply) and "$" in reply, reply[:240])
    check("19", "...not a spelling question", "did you mean" not in reply.lower(), reply[:160])
    check("19", "...without calling the model", not fake.payloads,
          f"{len(fake.payloads)} model call(s)")

    reply = await bot.say("1")
    transcript("answering that list", "1", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    names = [i.get("product_name") for i in state.get("cart_items") or []]
    check("19", "'1' adds the first product in the list", bool(names), str(names))

    _ORDER_STATES.clear()
    bot.history.clear()
    fake.payloads.clear()
    reply = await bot.say("skincare and cosmetics")
    transcript("two categories at once", "skincare and cosmetics", reply)
    check("19", "two categories are answered together, not one at a time",
          "did you mean" not in reply.lower() and "reply with the numbers" in reply.lower(),
          reply[:240])

    # ---------------------------------------------------------------- 20
    print("\n[20] Numbers still point at the list when a question came in between")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377100005"
    _ORDER_STATES[(STORE_ID, bot.phone)] = {"cart_items": [], "selected_branch": "Angwa"}
    earlier_list = ("Here are the body lotions at the Angwa branch:\n\n"
                    "1. NIVEA CREAM 100ML - $6\n"
                    "2. NIVEA BODY LOTION 400ML - $10\n"
                    "3. DOVE SOAP 100G - $4\n"
                    "4. DOVE BODY WASH 250ML - $7")
    bot.history.extend([
        {"role": "user", "content": "body lotions"},
        {"role": "assistant", "content": earlier_list},
        {"role": "user", "content": "add 3 and 4"},
        {"role": "assistant", "content": "Which branch would you like to shop from: Angwa, Bulawayo, Gweru, or Rezende?"},
    ])
    fake.payloads.clear()
    reply = await bot.say("add 3 and 4")
    transcript("numbers after a branch question", "add 3 and 4", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    names = [i.get("product_name") for i in state.get("cart_items") or []]
    check("20", "the numbers resolve against the earlier list",
          "DOVE SOAP 100G" in names and "DOVE BODY WASH 250ML" in names, str(names))
    check("20", "...the model resolves numbers against the earlier list", bool(fake.payloads),
          f"{len(fake.payloads)} model call(s)")

    # A number with no list at all used to be fuzzy-matched into a wound dressing.
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377100006"
    fake.payloads.clear()
    reply = await bot.say("add 6 and 7, 13, 14")
    transcript("numbers with no list", "add 6 and 7, 13, 14", reply)
    check("20", "a stray number is not answered with a product guess",
          "3/0" not in reply and "did you mean" not in reply.lower(), reply[:200])
    check("20", "...it asks for the product name instead",
          "product name" in reply.lower() or "kind of product" in reply.lower(), reply[:200])

    # ---------------------------------------------------------------- 21
    print("\n[21] \"add these to the cart\" adds the whole list, medicine last")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377100007"
    _ORDER_STATES[(STORE_ID, bot.phone)] = {"cart_items": [], "selected_branch": "Angwa"}
    first_aid = ("Here are the first aid products:\n\n*First Aid*\n"
                 "1. NIVEA CREAM 100ML - $6\n"
                 "2. DOVE SOAP 100G - $4\n"
                 "3. PANADOL EXTRA 500MG (20 TABLETS) - $4")
    bot.history.extend([
        {"role": "user", "content": "first aid"},
        {"role": "assistant", "content": first_aid},
    ])
    fake.payloads.clear()
    reply = await bot.say("add these to the cart")
    transcript("'add these to the cart'", "add these to the cart", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    names = [i.get("product_name") for i in state.get("cart_items") or []]
    check("21", "every product on the list is added",
          "NIVEA CREAM 100ML" in names and "DOVE SOAP 100G" in names, str(names))
    check("21", "the medicine is NOT added without the double-check",
          not any("PANADOL" in (n or "").upper() for n in names), str(names))
    check("21", "...the pharmacist double-check is asked instead",
          "sure" in reply.lower() and "PANADOL" in reply.upper(), reply[-260:])

    reply = await bot.say("yes")
    transcript("confirming the medicine", "yes", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    panadol = [i for i in state.get("cart_items") or []
               if "PANADOL" in (i.get("product_name") or "").upper()]
    check("21", "confirming adds exactly one", bool(panadol) and panadol[0].get("quantity") == 1,
          str(panadol))

    # A pasted price list must not turn "150MM X4.5M" into a quantity of 4.
    from modules.openclaw.router import _requested_quantity
    check("21", "pack sizes do not become quantities",
          _requested_quantity("CREPE BANDAGE 150MM X4.5M - $2") == 1,
          str(_requested_quantity("CREPE BANDAGE 150MM X4.5M - $2")))
    check("21", "a stated quantity still counts",
          _requested_quantity("i want 2 of the dove soap") == 2,
          str(_requested_quantity("i want 2 of the dove soap")))

    # ---------------------------------------------------------------- 22
    print("\n[22] A name typed at the delivery step is a name")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377100008"
    _ORDER_STATES[(STORE_ID, bot.phone)] = {
        "cart_items": [{"product_name": "NIVEA CREAM 100ML", "price": 6,
                        "quantity": 1, "branch": "Angwa"}],
        "selected_branch": "Angwa", "current_state": "delivery_step_name",
        "collection_method": "delivery",
    }
    bot.history.extend([
        {"role": "user", "content": "2"},
        {"role": "assistant", "content": "Great! I'll need a few details for delivery.\n\n*Step 1 of 3*\nWhat is your *full name*?"},
    ])
    fake.payloads.clear()
    reply = await bot.say("farai rato")
    transcript("a name at the name step", "farai rato", reply)
    state = _mem_get_order_state(db, STORE_ID, bot.phone) or {}
    check("22", "the name is saved", str(state.get("customer_name") or "").lower() == "farai rato",
          str(state.get("customer_name")))
    check("22", "...the phone number is asked for next",
          "phone number" in reply.lower() and "did you mean" not in reply.lower(), reply[:200])
    check("22", "...the name is saved without a model call", not fake.payloads,
          f"{len(fake.payloads)} model call(s)")

    # Full names, repeated confirmations and explicit checkout choices.
    _ORDER_STATES[(STORE_ID, bot.phone)]["current_state"] = "delivery_step_name"
    await bot.say("Tinotenda Cosmas Nyaruwanga")
    state = _mem_get_order_state(db, STORE_ID, bot.phone)
    check("22", "all parts of a delivery name are saved",
          state.get("customer_name") == "Tinotenda Cosmas Nyaruwanga", str(state.get("customer_name")))
    _ORDER_STATES[(STORE_ID, bot.phone)]["current_state"] = "awaiting_checkout"
    bot.history[:] = [{"role": "assistant", "content": "Added to your cart. Would you like to proceed to checkout?"}]
    before = list(_ORDER_STATES[(STORE_ID, bot.phone)]["cart_items"])
    reply = await bot.say("yes")
    check("22", "yes starts checkout with the existing cart",
          (_mem_get_order_state(db, STORE_ID, bot.phone) or {}).get("cart_items") == before
          and "phone" in reply.lower(), reply[:180])
    _ORDER_STATES[(STORE_ID, bot.phone)]["current_state"] = "awaiting_checkout"
    _ORDER_STATES[(STORE_ID, bot.phone)]["collection_method"] = None
    bot.history[:] = [{"role": "assistant", "content": "Would you like to proceed to checkout?"}]
    await bot.say("no")
    check("22", "no continues shopping", _mem_get_order_state(db, STORE_ID, bot.phone).get("current_state") == "cart")
    result = await router._execute_pharmacy_tool(db, STORE, bot.phone, "add_to_cart",
        {"product_name":"NIVEA CREAM 100ML", "price":6, "branch":"Angwa"}, "yes")
    check("22", "repeated confirmation keeps the quantity", _mem_get_order_state(db, STORE_ID, bot.phone)["cart_items"][0]["quantity"] == 1, result)
    result = await router._execute_pharmacy_tool(db, STORE, bot.phone, "add_to_cart",
        {"product_name":"NIVEA CREAM 100ML", "price":6, "branch":"Angwa"}, "add one more")
    check("22", "an explicit extra unit is added", _mem_get_order_state(db, STORE_ID, bot.phone)["cart_items"][0]["quantity"] == 2, result)

    # ---------------------------------------------------------------- 23
    print("\n[23] A NULL collection method cannot break the payment summary")
    _ORDER_STATES.clear()
    bot.history.clear()
    bot.phone = "26377100009"
    # Exactly what production held when the customer sent their EcoCash number:
    # the key is present with a NULL value, which .get(key, "delivery") does not
    # cover - the summary then crashed and the customer got "temporary problem".
    _ORDER_STATES[(STORE_ID, bot.phone)] = {
        "cart_items": [{"product_name": "NIVEA CREAM 100ML", "price": 6,
                        "quantity": 2, "branch": "Angwa"}],
        "selected_branch": "Angwa", "current_state": "payment",
        "collection_method": None, "customer_name": "farai rato",
    }
    result = await router._execute_pharmacy_tool(
        db, STORE, bot.phone, "set_payment_method",
        {"method": "ecocash", "mobile_number": "0781276999"})
    transcript("EcoCash number arrives with no stored collection method",
               "0781276999", result)
    check("23", "the payment summary is returned", "ORDER SUMMARY" in result.upper(), result[:200])
    check("23", "...with a collection line, not a crash",
          "Collection:" in result and "None" not in result.split("Collection:")[-1][:20], result)

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"SCENARIOS: {len(FAILURES)} CHECK(S) FAILED")
        for f in FAILURES:
            print(f"  - {f}")
    else:
        print("SCENARIOS: ALL CHECKS PASSED")
    print("=" * 70)

    # Release the sqlite file handle before deleting it (on Windows an open
    # handle makes unlink fail, so retry briefly rather than leaking the file).
    db.close()
    engine.dispose()
    for _ in range(5):
        try:
            db_path.unlink()
            break
        except OSError:
            time.sleep(0.3)
    if db_path.exists():
        print(f"note: could not remove the temporary scenario DB at {db_path}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
