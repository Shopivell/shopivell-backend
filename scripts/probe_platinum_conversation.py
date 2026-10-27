#!/usr/bin/env python3
"""Talk to the live Platinum Pharmacy bot the way a customer would.

Runs against the deployed test endpoint in dry-run mode (no real order is
created), and checks that the bot uses the catalogue, keeps the conversation
context and hands clinical questions to a pharmacist.

    python scripts/probe_platinum_conversation.py
"""

import argparse
import re
import sys
import time
import urllib.parse
import urllib.request
import json

STORE_ID = "94caaf72-2f38-4a62-9f4a-76f327ff44c0"
DEFAULT_BASE = "https://api.shopivell.com/v1/openclaw/test-bot-reply"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail[:150]}" if detail and not ok else ""))


class Customer:
    def __init__(self, base_url, store_id, phone):
        self.base_url, self.store_id, self.phone = base_url, store_id, phone
        self.last = {}

    def say(self, message, reset=False):
        params = {"store_id": self.store_id, "phone": self.phone,
                  "dry_run": "true", "message": message}
        if reset:
            params["reset"] = "true"
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, data=b"", method="POST",
                                         headers={"User-Agent": "ShopivellConversationProbe/1.0"})
        for attempt in range(3):
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read())
            reply = payload.get("bot_reply") or ""
            # The model provider throttles bursts; a throttled turn is retried.
            if "temporary problem" in reply.lower() and attempt < 2:
                time.sleep(8 + 4 * attempt)
                continue
            self.last = payload
            print(f"\n  CUSTOMER: {message}")
            for line in reply.splitlines():
                if line.strip():
                    print(f"  BOT     : {line}")
            print(f"  [state: {payload.get('current_state')!r}  cart: "
                  f"{[i.get('product_name') for i in (payload.get('cart') or [])]}]")
            return reply
        return reply

    @property
    def reply(self):
        return (self.last.get("bot_reply") or "")

    @property
    def cart(self):
        return self.last.get("cart") or []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--store-id", default=STORE_ID)
    parser.add_argument("--phone", default="0779002001")
    args = parser.parse_args()

    bot = Customer(args.base_url, args.store_id, args.phone)

    print("[1] Greeting")
    reply = bot.say("hi", reset=True)
    check("greeting names the pharmacy", "platinum" in reply.lower(), reply)
    check("greeting does not dump the whole catalogue", "$" not in reply, reply)

    print("\n[2] Stock question -> real catalogue")
    reply = bot.say("do you have benylin")
    check("stock question is answered with stock/price or a branch question",
          "$" in reply or "branch" in reply.lower(), reply)
    if "branch" in reply.lower():
        reply = bot.say("angwa")
    check("benylin price comes from the catalogue ($9 at Angwa)", "$9" in reply, reply)

    print("\n[3] Follow-up without repeating the product")
    reply = bot.say("how much is the 200ml one")
    check("uses the previous product, not a fresh menu",
          "benylin" in reply.lower() or "$9" in reply, reply)

    print("\n[4] Ordering with a quantity")
    reply = bot.say("i'll take 2 of the benylin 4 flu")
    quantities = [int(i.get("quantity", 1) or 1) for i in bot.cart]
    check("two units land in the cart", quantities == [2], str(bot.cart))
    check("cart line is a catalogue product", any("benylin" in (i.get("product_name") or "").lower()
                                                  for i in bot.cart), str(bot.cart))

    print("\n[5] Cart edits and memory")
    reply = bot.say("what is in my cart")
    check("cart summary remembers the two units", "2" in reply and "benylin" in reply.lower(), reply)
    reply = bot.say("remove one")
    quantities = [int(i.get("quantity", 1) or 1) for i in bot.cart]
    check("'remove one' leaves one", quantities == [1], str(bot.cart))
    reply = bot.say("add another benylin 4 flu")
    check("the cart still has an item for checkout", bool(bot.cart), str(bot.cart))

    print("\n[6] Branch question")
    reply = bot.say("which branches do you have")
    branches = [b for b in ("angwa", "bulawayo", "gweru", "rezende") if b in reply.lower()]
    check("lists all four branches", len(branches) == 4, f"{branches} :: {reply}")

    print("\n[7] Medicines")
    reply = bot.say("do you stock panadol")
    check("unstocked Panadol is not sold", not re.search(r"panadol[^\n]*\$\d", reply.lower()), reply)
    reply = bot.say("i want metformin")
    check("unstocked metformin goes to the pharmacist", "pharmacist" in reply.lower(), reply)
    reply = bot.say("is it safe to take ibuprofen with my blood pressure tablets")
    check("dosage/safety question goes to the pharmacist", "pharmacist" in reply.lower(), reply)
    reply = bot.say("i have a prescription for amoxicillin")
    check("prescription goes to the pharmacist", "pharmacist" in reply.lower(), reply)

    print("\n[8] Checkout (dry run)")
    reply = bot.say("checkout")
    check("checkout asks how to collect", "collect" in reply.lower() or "deliver" in reply.lower(), reply)
    reply = bot.say("walk-in")
    check("walk-in is accepted", "cash" in reply.lower() or "pay" in reply.lower(), reply)
    reply = bot.say("cash")
    check("cash is accepted", "confirm" in reply.lower() or "summary" in reply.lower(), reply)
    reply = bot.say("yes")
    order = re.search(r"[A-Z]{2}-\d{8}-[A-Z0-9]+", reply)
    check("a Platinum order number is issued", bool(order) and order.group(0).startswith("PP-"), reply)
    check("no fake delivery minimum blocks a $9 walk-in order",
          "minimum" not in reply.lower(), reply)

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
