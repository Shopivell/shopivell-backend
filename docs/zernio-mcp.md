# Zernio Ads MCP over Streamable HTTP

Shopivell exposes its Zernio ads integration as an MCP JSON-RPC endpoint:

```text
https://api.shopivell.com/v1/openclaw/mcp/zernio
```

This is a Shopivell gateway to the Zernio REST API. It is not an endpoint hosted
by Zernio, and the Zernio API key is never sent to MCP clients. The gateway uses
the backend's `ZERNIO_API_KEY` and requires a separate `MCP_ZERNIO_TOKEN` from
every caller.

## Configure authentication

Set a high entropy `MCP_ZERNIO_TOKEN` in the backend production environment and
restart/redeploy the backend. Keep it in the trusted MCP client's secret store;
never place it in browser code or a public URL. Requests may use either:

```http
Authorization: Bearer <MCP_ZERNIO_TOKEN>
```

or `X-MCP-Token: <MCP_ZERNIO_TOKEN>`. The endpoint fails closed with `503` if
the server token is not configured and rejects missing or invalid caller tokens
with `401`. A Meta or Pipeboard token is not a substitute for this Shopivell
gateway token.

## Protocol

The server is stateless and accepts MCP JSON-RPC 2.0 POST requests. It supports
`initialize`, `ping`, `tools/list`, and `tools/call`, returning JSON responses.
It also acknowledges notifications with `202 Accepted` and no response body.
Send `Accept: application/json, text/event-stream` and
`Content-Type: application/json` as shown below.

```bash
curl -X POST https://api.shopivell.com/v1/openclaw/mcp/zernio \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Authorization: Bearer <MCP_ZERNIO_TOKEN>' \
  -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"my-client","version":"1.0.0"}}}'
```

List tools:

```bash
curl -X POST https://api.shopivell.com/v1/openclaw/mcp/zernio \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Authorization: Bearer <MCP_ZERNIO_TOKEN>' \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":2}'
```

Call a tool (replace the store UUID with a store that has Meta Ads connected):

```bash
curl -X POST https://api.shopivell.com/v1/openclaw/mcp/zernio \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Authorization: Bearer <MCP_ZERNIO_TOKEN>' \
  -d '{"jsonrpc":"2.0","method":"tools/call","id":3,"params":{"name":"list_campaigns","arguments":{"store_id":"<store-uuid>"}}}'
```

## Tools

- `list_campaigns`: list campaigns for the store's connected ad account.
- `get_insights`: fetch account scoped campaign/ad insights and a supported date preset.
- `get_conversion_stats`: fetch account scoped conversion and lead fields.
- `create_campaign`: create a campaign, paused by default. Requires creative copy,
  destination URL, image URL, goal, and budget.
- `pause_campaign`: pause a campaign after confirming that its ID exists in that
  store's connected ad account.

Every call requires `store_id`. Account, ad account, and Facebook Page identifiers
are resolved by the server from that store's own Zernio profile. Callers cannot
override the target with identifiers from another store. Writes still act on the
store's live Meta Ads account; campaign creation defaults to paused to avoid
starting spend unexpectedly.

## Security and deployment

- Keep the API behind HTTPS and an authenticating network perimeter; do not expose
  an internal backend port directly to the public internet.
- Use a dedicated strong `MCP_ZERNIO_TOKEN`, rotate it if exposed, and configure
  it only in trusted clients.
- Keep `ZERNIO_API_KEY` server side. Do not send it as a caller token.
- The endpoint uses Shopivell's shared gateway token, so protect it as a
  privileged credential. Store-specific account targeting is enforced in code.
- CORS is enabled for protocol compatibility, but the token must only be used by
  trusted server-side clients. CORS is not authentication.

The gateway's Zernio API key must also be configured as `ZERNIO_API_KEY` in the
backend environment. Zernio availability, plan limits, and Meta permissions are
controlled by the connected Zernio/Meta accounts.
