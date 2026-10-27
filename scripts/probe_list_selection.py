#!/usr/bin/env python3
"""Replay the first-aid list complaint against the live Platinum Pharmacy bot.

The customer was shown a numbered list of First Aid products, pasted it back
with "add these to the cart", and only one line (the medication-gated PLASTER OF
PARIS 50MM) ended up in the cart - and the bot never asked which branch. This
walks the same turns through the deployed bot in dry-run mode and checks the cart
against what the customer asked for.

    python scripts/probe_list_selection.py
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

STORE_ID = "94caaf72-2f38-4a62-9f4a-76f327ff44c0"      # Platinum Pharmacy
DEFAULT_BASE = "https://api.shopivell.com/v1/openclaw/test-bot-reply"

# What the customer pasted back, exactly as the bot had listed it.
FIRST_AID_LIST = "\n".join([
    "1. CUTICURA ANTISEPTIC OINTMENT 10G - $6",
    "2. CAR FIRST AID KIT - $30",
    "3. CREPE BANDAGE 100MMX4M - $1",
    "4. CREPE BANDAGE 150MM X4.5M - $2",
    "5. CREPE BANDAGE 75MMX4.5M 1S - $1",
    "6. FIRST AID BOX (MEDIUM) - $53",
    "7. FIRST AID DRESSING NO 2 - $1",
    "8. PLASTER OF PARIS 100MM - $1",
    "9. PLASTER OF PARIS 50MM - $1",
    "10. PLASTER OF PARIS 75MM - $1",
])

FAILURES = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}"
          + (f"  -> {detail[:200]}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(f"{label} {detail[:200]}")


class Customer:
    def __init__(self, base_url, store_id, phone):
        self.base_url, self.store_id, self.phone = base_url, store_id, phone
        self.last, self.reply = {}, ""

    def say(self, message, reset=False):
        params = {"store_id": self.store_id, "phone": self.phone,
                  "dry_run": "true", "message": message}
        if reset:
            params["reset"] = "true"
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, data=b"", method="POST",
                                         headers={"User-Agent": "ShopivellListProbe/1.0"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    payload = json.loads(response.read())
            except Exception as exc:  # noqa: BLE001 - reported, never hidden
                payload = {"error": f"{type(exc).__name__}: {exc}"}
            self.reply = payload.get("bot_reply") or ""
            if self.reply and "temporary problem" not in self.reply.lower():
                break
            print("  [retry] the bot failed or was throttled; asking again in a moment")
            time.sleep(10 + 5 * attempt)
        self.last = payload
        print(f"\n  CUSTOMER: {message[:200]}")
        for line in self.reply.splitlines():
            if line.strip():
                print(f"  BOT     : {line[:200]}")
        print(f"  [state: {payload.get('current_state')!r}  cart: "
              f"{[(i.get('product_name'), i.get('quantity')) for i in (payload.get('cart') or [])]}]")
        return self.reply

    @property
    def cart(self):
        return self.last.get("cart") or []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--store-id", default=STORE_ID)
    parser.add_argument("--phone", default="0781276999")
    args = parser.parse_args()

    customer = Customer(args.base_url, args.store_id, args.phone)

    # 1. A fresh chat: branches are offered, and picking one must stick.
    customer.say("hi", reset=True)
    customer.say("1")

    # 2. The customer asks for a shelf, not a brand.
    reply = customer.say("first aid products")
    listed_reply = reply
    check("a category request is answered with a numbered list",
          len(re.findall(r"^\s*\d+\.", reply, re.M)) >= 5, reply)
    check("a category request is never answered with 'did you mean'",
          "did you mean" not in reply.lower(), reply)
    check("a category request is not answered with a branch question",
          "which branch" not in reply.lower(), reply)

    # The bot's own list is the order the customer is answering: every product
    # it showed for the branch has to reach the cart.
    listed = [name.upper() for name in
              re.findall(r"^\s*\d+\.\s*(.+?)\s*-\s*\$\d", listed_reply, re.M)]
    check("the category reply lists products with prices", len(listed) >= 5, listed_reply)

    # 3. The customer pastes the list back and asks for all of it.
    customer.say(FIRST_AID_LIST + "\nadd these to the cart")
    if re.search(r"reply yes|really sure|are you sure", customer.reply, re.I):
        customer.say("yes")

    cart = {str(i.get("product_name") or "").upper() for i in customer.cart}
    missing = [name for name in listed if name not in cart]
    check(f"every product the bot listed reaches the cart ({len(cart)} added)",
          not missing, f"missing: {missing}")
    # A requested line the branch does not stock must be said, not dropped.
    unstocked = [line.split(". ", 1)[1].split(" - $")[0]
                 for line in FIRST_AID_LIST.splitlines()
                 if line.split(". ", 1)[1].split(" - $")[0].upper() not in cart]
    for name in unstocked:
        check(f"'{name}' is either added or explained",
              name.split()[0].lower() in customer.reply.lower(), customer.reply)
    check("the cart holds no duplicate lines",
          len(cart) == len(customer.cart), str([i.get("product_name") for i in customer.cart]))
    check("no turn fell back to 'temporary problem'",
          "temporary problem" not in customer.reply.lower(), customer.reply)

    print()
    if FAILURES:
        print(f"LIST PROBE: {len(FAILURES)} CHECK(S) FAILED")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("LIST PROBE: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
