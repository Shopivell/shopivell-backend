#!/usr/bin/env python3
"""Replay a stored WhatsApp conversation through the live bot (dry run).

The transcript comes from the `whatsapp_messages` table, exported as
"timestamp|inbound|outbound|text" lines (see --help for the SQL). Only the
customer's (inbound) messages are sent; the bot's new replies are shown next to
what it actually replied at the time, so drift is visible.

    python scripts/replay_whatsapp_conversation.py --transcript wa.txt \
        --phone 0781276999 --since "2026-10-21 05:40"

Nothing is sent on WhatsApp: the test endpoint runs in dry-run mode, so no order
is created and no state is written for the real customer.
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

STORE_ID = "94caaf72-2f38-4a62-9f4a-76f327ff44c0"   # Platinum Pharmacy
DEFAULT_BASE = "https://api.shopivell.com/v1/openclaw/test-bot-reply"

# What the old replies leaked that a working bot must not repeat.
# The bot says this when it is answering from a clean slate. Production had
# cleared the conversation at those points (idle timeout), so the replay must
# reset there too or "hi" comes back as "welcome back" and the branch menu - and
# with it every "2" and "6" after it - never appears.
FRESH_GREETING = re.compile(r"^\s*hi,?\s+welcome\b", re.I)

PROBLEMS = {
    "did-you-mean on a category": re.compile(r"did you mean", re.I),
    "temporary problem": re.compile(r"temporary problem", re.I),
    "cannot add to cart": re.compile(r"unable to directly add|limitations in my current setup", re.I),
    "empty cart after checkout": re.compile(r"cart is empty|cart is currently empty", re.I),
    "handed to team": re.compile(r"passed your question to our team", re.I),
}


def parse_transcript(path, since):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("|", 2)
            if len(parts) < 3:
                continue
            stamp, direction, text = parts
            if since and stamp < since:
                continue
            # The SQL export keeps line breaks as a literal " \n ".
            text = text.replace(" \\n ", "\n").replace("\\n", "\n").strip()
            rows.append((stamp, direction, text))
    return rows


def send(base_url, store_id, phone, text, reset):
    params = {"store_id": store_id, "phone": phone, "dry_run": "true", "message": text}
    if reset:
        params["reset"] = "true"
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, data=b"", method="POST",
                                     headers={"User-Agent": "ShopivellReplay/1.0"})
    payload = {}
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                payload = json.loads(response.read())
        except Exception as exc:  # noqa: BLE001 - reported, never hidden
            payload = {"error": f"{type(exc).__name__}: {exc}"}
            time.sleep(5 + 5 * attempt)
            continue
        reply = payload.get("bot_reply") or ""
        if "temporary problem" in reply.lower() and attempt < 3:
            time.sleep(10 + 5 * attempt)
            continue
        return payload
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--store-id", default=STORE_ID)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--since", help="only replay messages at/after this timestamp")
    parser.add_argument("--until", help="stop at this timestamp")
    parser.add_argument("--no-split", action="store_true",
                        help="do not reset where the real bot greeted the customer afresh")
    args = parser.parse_args()

    rows = parse_transcript(args.transcript, args.since)
    if args.until:
        rows = [r for r in rows if r[0] <= args.until]
    if not rows:
        print("Nothing to replay.")
        return 1

    # Pair every inbound with the outbound that followed it.
    turns, pending = [], None
    for stamp, direction, text in rows:
        if direction == "inbound":
            pending = [stamp, text, None]
            turns.append(pending)
        elif direction == "outbound" and pending is not None and pending[2] is None:
            pending[2] = text
            pending = None

    print(f"Replaying {len(turns)} customer message(s) from {rows[0][0]} to {rows[-1][0]}\n")
    problems, answered, sessions = [], 0, 0
    last = {}
    for index, (stamp, text, recorded) in enumerate(turns, 1):
        starts_session = (index == 1
                          or (not args.no_split and recorded and FRESH_GREETING.match(recorded)))
        if starts_session:
            sessions += 1
            print(f"--- session {sessions} starts at {stamp} ---")
        last = send(args.base_url, args.store_id, args.phone, text, reset=starts_session)
        if last.get("error"):
            problems.append(f"#{index} request failed: {last['error']}")
        reply = last.get("bot_reply") or ""
        answered += 1
        print(f"[{index}] {stamp}  CUSTOMER: {text}")
        if recorded:
            print(f"    THEN: {recorded[:400]}")
        print(f"    NOW : {reply[:400]}")
        print(f"    [state={last.get('current_state')!r} cart={[i.get('product_name') for i in (last.get('cart') or [])]}]")
        for label, pattern in PROBLEMS.items():
            if pattern.search(reply):
                problems.append(f"#{index} {label}")
        print()

    final_cart = last.get("cart") or []
    placed = last.get("orders") or last.get("dry_run_orders") or []
    orders = [i.get("order_number") for i in placed if i.get("order_number")]
    print(f"Replayed {answered} turns across {sessions} session(s). "
          f"Final cart: {[i.get('product_name') for i in final_cart]}")
    print(f"Final state: {last.get('current_state')!r}  orders in dry run: {orders or 'none'}")
    if problems:
        print("Repeated problems: " + "; ".join(problems))
    return 0


if __name__ == "__main__":
    sys.exit(main())
