#!/usr/bin/env python3
"""Exercise every pharmacy MCP tool against a live deployment, in order.

This is a black-box probe: it speaks the same JSON-RPC the OpenClaw gateway
does, so it proves the tools work through the interface a model actually uses
(not by importing the app).

    python scripts/probe_pharmacy_mcp_tools.py
    python scripts/probe_pharmacy_mcp_tools.py --base-url https://api.shopivell.com \
        --store-id 94caaf72-... --branch Angwa --phone 0779000001

It leaves order state for the test phone; clean it up with
scripts/probe_pharmacy_cleanup.sql (or delete by phone) after the run.
"""

import argparse
import json
import re
import sys
import urllib.request

STORE_ID = "94caaf72-2f38-4a62-9f4a-76f327ff44c0"   # Platinum Pharmacy
DEFAULT_BASE = "https://api.shopivell.com/v1/openclaw/mcp/pharmacy"
DEFAULT_PHONE = "0779000001"
DEFAULT_BRANCH = "Angwa"

results = []


def rpc(url, method, params=None, request_id=1):
    body = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 # Cloudflare rejects the default urllib agent on this host.
                 "User-Agent": "ShopivellPharmacyProbe/1.0"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = response.read().decode()
    # Streamable HTTP may answer as SSE; take the last JSON data line.
    if raw.lstrip().startswith("event:") or "\ndata:" in raw:
        payload = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
        raw = payload[-1] if payload else raw
    return json.loads(raw)


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail[:180]}" if detail else ""))


def call(url, tool, args, request_id):
    response = rpc(url, "tools/call", {"name": tool, "arguments": args}, request_id)
    if "error" in response:
        return f"ERROR {response['error']}"
    content = response.get("result", {}).get("content") or []
    return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))


def money(text):
    match = re.search(r"\$(\d+(?:\.\d+)?)", text or "")
    return float(match.group(1)) if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--store-id", default=STORE_ID)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--phone", default=DEFAULT_PHONE)
    args = parser.parse_args()

    url, store, phone, branch = args.base_url, args.store_id, args.phone, args.branch
    ctx = {"store_id": store, "customer_phone": phone}
    step = [0]

    def tool(tool_name, **kwargs):
        step[0] += 1
        return call(url, tool_name, {**kwargs, **ctx}, step[0])

    init = rpc(url, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "shopivell-probe", "version": "1"}}, 0)
    check("initialize negotiates", "result" in init, json.dumps(init)[:160])

    listed = rpc(url, "tools/list", {}, 0)
    tools = [t["name"] for t in (listed.get("result", {}).get("tools") or [])]
    check(f"tools/list returns the pharmacy tools ({len(tools)})", len(tools) >= 17, ", ".join(tools))

    print("\n[branches]")
    out = tool("list_branches")
    check("list_branches names the catalogue branches",
          branch.lower() in out.lower() and "rezende" in out.lower(), out)

    print("\n[search]")
    out = tool("search_products", query="nivea")
    check("search_products finds a brand in several branches",
          "FOUND" in out.upper() or "available at" in out.lower(), out)
    out = tool("search_products", query="nivea", branch=branch)
    check("search_products honours a branch", branch.lower() in out.lower(), out)
    prices = re.findall(r"^\s*\d+\.\s*(.+?)\s+-\s+\$([\d.]+)", out, re.MULTILINE)
    check("search_products returns priced rows for the branch", bool(prices), str(prices[:2]))
    product_name, product_price = (prices[0] if prices else ("NIVEA 3IN1 WIPES", "5.00"))

    out = tool("search_products", query="benilyn")
    check("search_products suggests a spelling fix", "DID_YOU_MEAN" in out.upper(), out)
    out = tool("search_products", query="panadol")
    check("search_products offers the closest stocked item, not a sale",
          "DID_YOU_MEAN" in out.upper() and "PANADO" in out.upper(), out)
    out = tool("search_products", query="zzzznothing")
    check("search_products says not found for nonsense", "NOT FOUND" in out.upper(), out)

    print("\n[cart]")
    out = tool("add_to_cart", product_name=product_name, price=float(product_price),
               branch=branch, quantity=1)
    check("add_to_cart adds a catalogue product", "Added" in out, out)
    out = tool("add_to_cart", product_name="FAKE PRODUCT XYZ", price=9, branch=branch)
    check("add_to_cart refuses a product outside the catalogue",
          "not in this store's catalogue" in out, out)
    out = tool("view_cart")
    check("view_cart shows the line", product_name.split()[0].lower() in out.lower(), out)
    out = tool("update_cart", product_name=product_name, quantity=2)
    check("update_cart changes the quantity", "x2" in out or "2" in out, out)
    out = tool("remove_from_cart", product_name=product_name)
    check("remove_from_cart removes the line", "Removed" in out or "removed" in out, out)
    out = tool("add_to_cart", product_name=product_name, price=float(product_price),
               branch=branch, quantity=1)
    check("add_to_cart works again for checkout", "Added" in out, out)

    print("\n[checkout]")
    out = tool("start_checkout")
    check("start_checkout asks how to collect", "collect" in out.lower() or "delivery" in out.lower(), out)
    out = tool("go_back_to_cart")
    check("go_back_to_cart returns to the cart", "cart" in out.lower(), out)
    out = tool("start_checkout")
    out = tool("set_collection_method", method="walkin")
    check("set_collection_method walk-in", "walk" in out.lower() or "collect" in out.lower(), out)
    out = tool("set_delivery_details", customer_name="Test Customer", phone=phone,
               address="1 Test Street, Harare")
    check("set_delivery_details saves the details", "aved" in out or "Test Customer" in out, out)
    out = tool("show_delivery_details")
    check("show_delivery_details echoes them", "Test Customer" in out, out)
    out = tool("update_delivery_name", name="Test Customer Two")
    check("update_delivery_name updates", "Test Customer Two" in out, out)
    out = tool("update_delivery_phone", phone="0771234567")
    check("update_delivery_phone updates", "0771234567" in out, out)
    out = tool("update_delivery_address", address="2 Test Avenue, Harare")
    check("update_delivery_address updates", "2 Test Avenue" in out, out)
    out = tool("set_payment_method", method="cash")
    check("set_payment_method cash", "cash" in out.lower(), out)

    out = tool("confirm_order")
    order_number = (re.search(r"[A-Z]{2}-\d{8}-[A-Z0-9]+", out) or [None])[0]
    check("confirm_order creates an order", bool(order_number), out)

    if order_number:
        print("\n[order]")
        out = tool("get_order_status", order_number=order_number)
        check("get_order_status finds the order", order_number in out, out)

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
        return 1
    print(f"\nTest order number: {order_number}  (phone {phone})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
