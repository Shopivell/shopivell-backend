# Hermes Agent deployment (Contabo host)

Status: **provisioned and running; no model provider has credit, so turns fail at
the provider.** Nothing else is missing — fund a key and the six agents answer.

## What runs where

| Item | Value |
|------|-------|
| Host | your own Docker host (any host with the Dokploy network works) |
| Image | `nousresearch/hermes-agent:latest` (v0.22.5) |
| Container | `hermes`, `--init`, restart `unless-stopped` |
| Network | `dokploy-network` (no published ports) |
| Memory cap | 1 GB (`--memory 1g --memory-swap 1g`) |
| State volume | `hermes-data` → `/var/lib/docker/volumes/hermes-data/_data` |
| API port | `8642`, inside the Docker network only |
| Dashboard | disabled (no `HERMES_DASHBOARD`) |

One multiplexed gateway process serves every profile. A `docker rm` + recreate
must pass the same env again:

```bash
docker run -d --name hermes --restart unless-stopped \
  --network dokploy-network --init \
  --memory 1g --memory-swap 1g \
  -v hermes-data:/opt/data \
  -e API_SERVER_ENABLED=true -e API_SERVER_HOST=0.0.0.0 \
  nousresearch/hermes-agent gateway run
```

## The six agents

| Agent | Profile | Endpoint |
|-------|---------|----------|
| Goal | `ads-goal` | `http://hermes:8642/p/ads-goal/v1` |
| Planner | `ads-planner` | `http://hermes:8642/p/ads-planner/v1` |
| Evaluator | `ads-evaluator` | `http://hermes:8642/p/ads-evaluator/v1` |
| Calibrator | `ads-calibrator` | `http://hermes:8642/p/ads-calibrator/v1` |
| Researcher | `ads-research` | `http://hermes:8642/p/ads-research/v1` |
| Art director | `ads-image` | `http://hermes:8642/p/ads-image/v1` |

Each profile lives at `profiles/<name>/` in the volume with its own `config.yaml`,
`.env`, `SOUL.md`, `state.db`, sessions and memory. `SOUL.md` is generated from
the prompt constants in `modules/openclaw/agent_service.py`,
`modules/market_research/service.py` and `modules/optimizer/calibration.py` —
if those prompts change, copy them into the matching `SOUL.md` again.

```bash
docker exec hermes /opt/hermes/.venv/bin/hermes gateway status   # served profiles
docker exec hermes /opt/hermes/.venv/bin/hermes profile list
```

## Authentication

`API_SERVER_KEY` is set in the root profile's `.env` and copied into each of the
six profiles, so one bearer token works on every `/p/<profile>/v1` endpoint.
`/health` needs no auth; `/v1/*` returns 401 without the token.

Read it on the host (never commit it):

```bash
grep '^API_SERVER_KEY=' /var/lib/docker/volumes/hermes-data/_data/.env
```

Rotate it by updating all seven `.env` files and restarting the container.

## Finishing after funding a provider

Every profile is currently `provider: openrouter`, `model: openai/gpt-4o-mini`
(OpenRouter had ~334 tokens of credit; OpenAI and Anthropic are at zero and the
Gemini key is suspended).

```bash
H='docker run --rm -v hermes-data:/opt/data --entrypoint /opt/hermes/.venv/bin/hermes nousresearch/hermes-agent'
$H -p ads-goal config set model.default openai/gpt-5.6-terra   # or openai/gpt-5.4-mini on OpenAI
docker restart hermes
```

If the funded key belongs to a provider that is not in the profile `.env`, add it
there (`profiles/<name>/.env`) or set it as a container env var.

Smoke test from the backend container:

```bash
docker exec <backend> sh -c 'curl -s -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"ads-goal\",\"messages\":[{\"role\":\"user\",\"content\":\"Return {}.\"}]}" \
  http://hermes:8642/p/ads-goal/v1/chat/completions'
```

## Pointing the backend at Hermes

The backend defaults to OpenClaw. Two variables switch the six ad roles:

| Variable | Value |
|----------|-------|
| `HERMES_GATEWAY_URL` | `http://hermes:8642` |
| `HERMES_GATEWAY_TOKEN` | the `API_SERVER_KEY` above |

`modules/openclaw/gateway.py` then calls `/p/<agent>/v1/chat/completions` with the
bare profile name as the model. The pharmacy WhatsApp agent keeps using
`OPENCLAW_GATEWAY_URL`. Unset `HERMES_GATEWAY_URL` to roll back.

## Constraints on this host

- **Memory**: 11 GB total, ~0.5 GB available, no swap. The gateway idles at
  ~280 MB; Hermes logs "system memory pressure is critical" and throttles worker
  spawning. A swapfile would make this safe.
- **Disk**: 93% used (~15 GB free). Docker reports ~30 GB of unused images and
  ~20 GB of build cache as reclaimable.
- **Sandboxing**: the API server logs that it is network-accessible with
  `terminal.backend: local`, so a caller holding `API_SERVER_KEY` gets an
  unsandboxed shell as the container user. The port is unpublished but reachable
  from every other container on the shared network; keep the key private and consider
  `terminal.backend: docker` before real use.
