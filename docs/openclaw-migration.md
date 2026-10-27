# Platinum Pharmacy: OpenClaw conversation layer

Status: **deployed and verified on 2026-10-22**. The pharmacy conversation is
model-driven through the real OpenClaw gateway. Zernio remains the WhatsApp
transport and Python remains the source of truth for catalogue, cart, orders
and safety.

## Architecture

```
WhatsApp customer
      |  Zernio Cloud API
      v
FastAPI /v1/openclaw/zernio-webhook        transport, history, hard guards
      |  gateway /v1/chat/completions, session key per conversation
      v
OpenClaw gateway (openclaw:18789)          conversation, tool choice, branch dialogue
      |  MCP over HTTP
      v
FastAPI /v1/openclaw/mcp/pharmacy          18 pharmacy tools
      |  catalogue, cart, orders, payments
      v
PostgreSQL
```

The OpenClaw WhatsApp channel is deliberately **not** used. It runs WhatsApp Web
(Baileys), which cannot share the business number with the official Cloud API and
would add ban risk. Zernio stays.

## Division of responsibility

**Python / FastAPI**
- Zernio webhook, reply delivery, WhatsApp history.
- MCP tool server: `search_products`, `add_to_cart`, `view_cart`, checkout,
  delivery details, payment, `confirm_order`, pharmacist handover, and the rest.
- Hard guards that must not depend on model behaviour:
  - medication double-check and pharmacist handover;
  - human handoff;
  - catalogue-only products and prices;
  - branch consistency with the existing cart;
  - order confirmation only after the customer explicitly confirms;
  - delivery details are not accepted or advanced while the cart is empty;
  - a shopping request ("add them to the cart") is never saved as a customer
    name, even if the conversation state is stuck on the name step.
- Deterministic category shelf browse (`_is_pure_category_request`) and the
  branded greeting. The greeting names the business, lists every catalogue
  branch and asks which one the customer wants. An `idle`/empty-cart state row
  from a finished order does not suppress it; an active cart or checkout step
  still continues the flow.
- `confirm_order` sends the PayNow mobile prompt for EcoCash, OneMoney and
  InnBucks and returns the approval instructions. A failed prompt is reported
  as `PAYMENT NOT SENT`; it is never presented as a successful payment.

**OpenClaw**
- Reads the customer's intent and the recent WhatsApp thread.
- Chooses which MCP tools to call and in what order.
- Asks which branch the customer wants when no branch is active.
- Handles natural product names, follow-ups ("add them", "the first one"),
  checkout dialogue and the final summary.
- Does not invent products, prices, stock, order numbers or payment references.

## Configuration

Production values live in the Dokploy application environment and the deployed
container `.env`. Secrets are not recorded in this repository.

| Variable | Purpose |
|----------|---------|
| `OPENCLAW_BRAIN_ENABLED` | `true` routes pharmacy turns to OpenClaw; `false` is the rollback to the Python model path. |
| `OPENCLAW_GATEWAY_URL` | Internal gateway URL, `http://openclaw:18789`. |
| `OPENCLAW_GATEWAY_TOKEN` | Bearer token for the gateway. Must match `gateway.auth.token` in the OpenClaw config. |
| `OPENCLAW_AGENT_MODEL` | Agent model selector, currently `openclaw`. |
| `MCP_PHARMACY_TOKEN` | Shared secret for the MCP endpoint. OpenClaw sends `Authorization: Bearer <token>`. |

The gateway token in the container environment previously returned 401 while the
token in `/home/node/.openclaw/openclaw.json` worked. The deployed value is the
one from the OpenClaw config.

The MCP endpoint accepts either `Authorization: Bearer <token>` or
`X-MCP-Token: <token>`. An unauthenticated POST returns **401**.

## Branch rules

These rules were added after the live thread where the agent guessed Bulawayo,
tried seven adds, and told the customer nothing was available:

1. `active_branch` is included in the tool context for every OpenClaw turn.
2. If the cart already has a branch, `add_to_cart` uses it.
3. If there is no branch and the store has more than one, `add_to_cart` returns
   `BRANCH_REQUIRED` and the agent asks the customer.
4. A branch that conflicts with the cart is rejected **before** the price lookup.
5. A successful add is final: the agent does not search for the same item again.
6. The recent WhatsApp thread is included in the agent prompt so a Python-sent
   category list can be referenced by the next "add them" turn.

## Product search

`search_products` has three layers:

1. Exact/substring catalogue search, with spelling fixes for compact names
   (`tooth paste` -> `toothpaste`).
2. Token-normalised fallback for separators and size spacing:
   `nivea body lotion aloe hydration 400ml` matches
   `NIVEA BODY LOTION ALOE&HYDRATION 400ML`; `mild gentle` matches
   `MILD&GENTLE`. The branch is preserved.
3. Fuzzy "did you mean" only when the first two layers find nothing.

`body lotion` and `hand cream` are no longer collapsed to `lotion` and `cream`.
That rewrite made exact names miss the catalogue rows that contain both words.

Category browsing is only for **pure** shelf requests ("personal care products",
"skincare and cosmetics"). A brand or product word ("nivea body lotion") goes to
the catalogue search instead of listing the whole shelf.

## Verification

- `python scripts/pharmacy_bot_scenarios.py` -> `SCENARIOS: ALL CHECKS PASSED`.
- `openclaw mcp probe shopivell-pharmacy` -> **18 tools**.
- Unauthenticated MCP POST -> **401**.
- Real agent turns through Zernio-compatible history:
  - no branch -> "Which branch would you like, and which item numbers should I add?";
  - active Angwa -> item added at Angwa;
  - conflicting Bulawayo -> no add; customer offered another branch.
- Full checkout on a test phone: add 2 x NIVEA BODY LOTION ALOE&HYDRATION 400ML,
  delivery, name, phone, address, cash, confirmation -> order number issued.
- Mobile-money confirmation is covered offline: `confirm_order` calls the
  PayNow initiation with the saved wallet number, cash does not, and a PayNow
  failure is reported as `PAYMENT NOT SENT`.
- Greeting is covered offline: the welcome names Platinum Pharmacy, lists the
  catalogue branches and survives a stale `idle` state row.
- Medication path: explicit "are you really sure" double-check, then pharmacist
  handover for advice.
- Delivery-detail guards: an empty cart returns "cart is empty" for
  `update_delivery_name`, `update_delivery_phone`, `update_delivery_address` and
  `set_delivery_details`; "add them to the cart" is not a valid person name.
- All test order states and the test order were deleted after verification. The
  real customer thread `+263781276999` was not modified.

## Remaining work

- Consider extracting OpenClaw client, MCP tools and pharmacy guards out of the
  9,202-line `modules/openclaw/router.py` into smaller modules. The size is
  legacy platform code, not the agent.
- Watch agent latency on multi-item turns; a successful add no longer triggers a
  verification search, which removed the worst 55-second turn.
- Re-run the scenario suite after any prompt or tool change.

## Rollback

Set `OPENCLAW_BRAIN_ENABLED=false` and restart the service. The Python model path
is still present. No WhatsApp number change is involved.
