# OpenClaw model and pharmacy verification

Status: **verified 2026-10-22**. The gateway has a working model and the real
Platinum Pharmacy agent answers through the production MCP tools.

## Environment

| Item | Value |
|------|-------|
| Host | your own Docker host (see [deployment](#deployment)) |
| OpenClaw container | `openclaw` |
| Image | `openclaw/openclaw:2026.10.5` |
| Agent model | `openai/gpt-5.4-mini` |
| Gateway | `http://openclaw:18789` |
| Chat completions | enabled |
| MCP endpoint | `https://api.shopivell.com/v1/openclaw/mcp/pharmacy` |
| MCP server name | `shopivell-pharmacy` |
| MCP tools | 18 |
| Backend store | a single seeded pharmacy store |
| WhatsApp transport | Zernio (bot number configured per deployment) |

Secrets are held only in the deployed environment and
`/home/node/.openclaw/openclaw.json`. They are not recorded here.

The gateway token in the container environment returned 401; the token in
`gateway.auth.token` in the OpenClaw config works. The backend uses that value.

## Verification results

### Gateway

- Backend-to-gateway `POST /v1/chat/completions` returns **200**.
- A real agent turn answered a Panado query, then "which branch has it?" using
  its session memory and the catalogue tools.
- Production logs show `[OpenClaw] agent answered a turn` and MCP tool calls.

### MCP

- Authenticated `openclaw mcp probe shopivell-pharmacy` reports
  **18 tools, Codex approval auto**.
- Unauthenticated POST to the MCP endpoint returns **401**.
- The MCP config sends `Authorization: Bearer <MCP_PHARMACY_TOKEN>`.

### Branch behaviour

| Test | Result |
|------|--------|
| No active branch, "add them" | Bot asked which branch and which items; no cart row was created. |
| Active Angwa, add a known Angwa item | Item added at Angwa with the catalogue price. |
| Cart at Angwa, add explicitly from Bulawayo | No add; customer offered another branch. |
| `branch='all'` with an active branch | Uses the active branch; "all" is not treated as a branch. |

### Product search

- `nivea body lotion aloe hydration 400ml` at Angwa returns
  `NIVEA BODY LOTION ALOE&HYDRATION 400ML - $6`.
- A leading quantity (`2 nivea body lotion aloe hydration 400ml`) returns the
  same product; the quantity is a tool argument, not part of the name.
- `nivea body lotion 400ml` returns the 400 ml variants without a did-you-mean
  detour.
- Category phrases still browse the shelf; brand/product phrases do not.

### Greeting

- A bare `hi` is answered from code, without a model or product search:
  `Welcome to Platinum Pharmacy. How can I help you today?`
- The greeting lists every branch in the store's catalogue and asks which one
  the customer wants.
- A finished order leaves an `idle` (or empty `cart`) state row behind. That
  state no longer suppresses the branded greeting; only a cart with items or a
  real checkout step (`delivery_step_*`, `payment`, `confirm`, etc.) continues
  the flow.
- A returning customer with a saved branch sees the full list with that branch
  marked `(current)`.

### Checkout

Full checkout on test phone `263771999022`, branch Angwa:

1. add 2 x NIVEA BODY LOTION ALOE&HYDRATION 400ML ($12);
2. `checkout` -> collection choice;
3. `delivery` -> name, phone, address;
4. `cash` -> summary with $12 total;
5. `yes` -> order confirmed, order number issued.

The test order and all test order states were deleted afterwards. The real
customer thread `+263781276999` was not modified.

### Mobile-money payment

`confirm_order` now calls `_initiate_mobile_payment` after creating an
EcoCash/OneMoney/InnBucks order. It validates the 10-digit wallet number before
creating the order, sends the PayNow mobile prompt, and returns the exact
instructions to the customer. If PayNow fails, the tool returns `PAYMENT NOT
SENT` with the error instead of leaving an unpaid order that looks confirmed.
Cash orders never call PayNow.

This was the cause of the live "EcoCash but no OTP" report: the order was
created and the state cleared, but no `send_mobile` call was made.

### Medication safety

- "I want to buy panado syrup 100ml" triggers the explicit
  "are you really sure" double-check.
- A request for advice ("it is for my child") hands over to the pharmacist and
  does not give medical advice.
- A later explicit "yes please add it" adds the catalogue item after the
  double-check, as covered by the scenario suite.

### Delivery-detail safety

- With an empty cart, `update_delivery_name`, `update_delivery_phone`,
  `update_delivery_address` and `set_delivery_details` all return
  "Your cart is empty" and save nothing.
- With a cart, the same name update saves the name and advances to the phone
  step normally.
- `looks_like_person_name("add them to the cart")` is false, so a stale name
  prompt cannot swallow a shopping request as the customer's name.

## Reproduce

Offline checks:

```powershell
python scripts/pharmacy_bot_scenarios.py
```

MCP probe and auth check on the server:

```bash
docker exec openclaw openclaw mcp probe shopivell-pharmacy
curl -s -o /dev/null -w '%{http_code}' -X POST \
  https://api.shopivell.com/v1/openclaw/mcp/pharmacy \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

Expected: `18 tools` and `401`.

## Notes

- OpenClaw keeps a session per `pharmacy:<store_id>:<phone>`. The backend also
  sends a capped recent-thread block because Python-generated category lists are
  not in the agent's session memory.
- The agent's MCP search is the source of truth when OpenClaw is active; Python
  does not inject a competing product result into the prompt.
- The model is selected with `OPENCLAW_AGENT_MODEL=openclaw`; the provider/model
  behind that selector is `openai/gpt-5.4-mini`.
