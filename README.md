# Shopivell

**A multi-tenant commerce backend where LLM agents run the marketing, not just draft copy.**

Shopivell is the FastAPI backend behind a live retail platform: stores, catalogues, orders, payments, point-of-sale, delivery, accounting and a WhatsApp storefront. What makes it unusual is the growth loop on top — a set of long-running agents that read a store's real performance data, write the plan, generate the creative, launch the campaign, then evaluate and re-calibrate themselves against actual results.

[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116-009688)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Why this project exists

Most "AI marketing" features are a prompt in a route handler: send the model a store description, parse whatever comes back, hope. That breaks the moment a number matters, because the model will happily invent one.

Shopivell takes the opposite approach. The agents are **real processes behind an agent gateway** (OpenClaw, or a Hermes profile per role), and every hand-off between backend and model is a **strict JSON contract**:

- the backend never lets the model touch the database directly — it feeds the agent a bounded context and validates what comes back;
- every response is parsed, schema-checked, and clamped before it reaches a campaign, a budget or a bid;
- if the model returns something invalid, the request fails loudly instead of silently persisting a hallucinated budget;
- the numbers in a plan come from analytics queries; the model reasons over them, it does not invent them.

That constraint is what makes an autonomous ad loop safe to actually run.

## The agent loop

```
                    ┌─────────────────────────────────────────────┐
  store telemetry   │  analytics → goals → plan → creative → ads  │
  (orders, spend,   │                                             │
   revenue, ROAS)   └─────────────────────────────────────────────┘
        │                     │         │        │        │
        ▼                     ▼         ▼        ▼        ▼
   ┌─────────┐          ┌────────┐ ┌───────┐ ┌───────┐ ┌────────┐
   │  Goal   │─────────▶│Planner │▶│Executor│▶│Evaluator│▶│Calibrator│
   └─────────┘          └────────┘ └───────┘ └───────┘ └────────┘
        ▲                  research agent     │            │
        │                  (live web +       │  measured  │
        └────────────────── competitor data)  └── results ─┘
```

| Agent | Role |
|-------|------|
| **Goal** | Turns store performance into a small set of measurable goals |
| **Planner** | Breaks a goal into tasks, budgets and a schedule |
| **Researcher** | Live market/competitor research, keyword and trend extraction |
| **Executor** | Produces ad copy and creative briefs, then launches campaigns |
| **Evaluator** | Scores outcomes against the goal's own success criteria |
| **Calibrator** | Adjusts targeting, budgets and creative weights from measured results |
| **Art director** | Chooses and directs campaign imagery |

Each agent is a named role with its own identity prompt and its own session, keyed per store — so two stores on the same deployment never share agent memory or context.

## What else is in here

| Area | What it does |
|------|--------------|
| **Commerce core** | Products, variants, inventory, orders, customers, offers, procurement, returns, reviews |
| **Multi-tenancy** | Store-scoped models, per-store agent sessions, store-owned assets and analytics |
| **Payments** | Paynow (EcoCash, InnBucks, card), Stripe and PayPal, with generated PDF receipts |
| **WhatsApp storefront** | Embedded signup, conversational flows, FAQ, and a knowledge base the bot answers from |
| **WhatsApp agent** | A pharmacy assistant backed by 18 MCP tools that read live stock, prices and branches |
| **Market research** | Competitor, keyword and trend collection, plus page extraction |
| **Ad creative** | Copy and image generation with a shared brand-context layer |
| **Analytics** | Revenue, funnel and campaign performance feeds that the agents consume |
| **POS & accounting** | In-store sales, ledgers and stock movements |
| **Website builder** | Storefront pages generated per tenant |
| **Jobs** | A durable background queue with registered handlers |
| **AI usage accounting** | Per-store token and cost tracking across providers |

Roughly 650 route handlers across 40 modules.

## Architecture

```
FastAPI app (main.py)
  ├─ middleware/      request correlation, structured logs, Redis response cache
  ├─ modules/<area>/  router + service + models + schemas, one package per domain
  ├─ utils/           gateway clients, payment, mail, PDF, embeddings, cache
  └─ jobs/            durable queue + handlers

Data:      SQLite (local default) · PostgreSQL + pgvector (production)
Cache:     Redis (optional, graceful when absent)
Media:     S3/MinIO or Cloudinary
Agents:    OpenClaw gateway (or Hermes profiles) — HTTP, JSON contracts
Providers: OpenAI · OpenRouter · Anthropic · Gemini · Tavily
```

Every module follows the same shape — `router.py` (HTTP), `service.py` (logic), `models.py` (SQLAlchemy), `schemas.py` (Pydantic) — so a change stays inside one package.

## Quickstart

```bash
git clone https://github.com/Shopivell/shopivell-backend.git
cd shopivell-backend

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # works as-is for a local run
uvicorn main:app --reload
```

Open <http://127.0.0.1:8000/docs> for the generated API reference and
<http://127.0.0.1:8000/health> for a health check.

No database server is needed to boot: `USE_SQLITE` defaults to `true`, so a fresh
clone creates a local SQLite file and its tables on first start. Set
`USE_SQLITE=false` and fill in the `DB_*` variables to run against PostgreSQL —
which is what production uses, because several features rely on `pgvector`.

> The full `requirements.txt` is heavy: it includes optional vision dependencies
> (torch, mediapipe, playwright) used by the virtual try-on module. Expect a
> multi-gigabyte first install.

### Docker

```bash
docker build -t shopivell .
docker run -p 8000:8000 --env-file .env shopivell
```

## Configuration

Everything is read from the environment; see [.env.example](.env.example) for the
full annotated list. The ones that matter first:

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Signing key for JWTs — **set a real one** |
| `USE_SQLITE` | `true` for a local file DB, `false` for PostgreSQL |
| `DB_HOST` `DB_NAME` `DB_USERNAME` `DB_PASSWORD` `DB_PORT` | PostgreSQL connection |
| `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | Model providers for the agents |
| `OPENCLAW_GATEWAY_URL` / `OPENCLAW_GATEWAY_TOKEN` | Agent gateway (see below) |
| `PAYNOW_INTEGRATION_ID` / `PAYNOW_INTEGRATION_KEY` | Zimbabwe payments |
| `WHATSAPP_PERMANENT_TOKEN` / `META_APP_SECRET` | WhatsApp Business API |
| `TAVILY_API_KEY` | Market research search |

Nothing in this repository contains credentials. `.env` is git-ignored; every
provider is optional, and the API degrades with a clear error when one is missing.

## Running the agents

The backend is an agent *client*. It talks HTTP to a gateway that owns the model
sessions, so the agents can run as a separate container:

- **[docs/openclaw-ad-agents.md](docs/openclaw-ad-agents.md)** — the six roles, their
  JSON contracts, what the backend validates, and how to point it at a gateway.
- **[docs/openclaw-migration.md](docs/openclaw-migration.md)** — moving from the old
  in-process marketing module to the gateway.
- **[docs/hermes-deployment.md](docs/hermes-deployment.md)** — the same six agents as
  Hermes profiles, one endpoint per role.

Point `OPENCLAW_GATEWAY_URL` at your gateway and the WhatsApp pharmacy agent uses
it; set `HERMES_GATEWAY_URL` to route the six ad roles to Hermes instead. Both are
optional — without them, the commerce API runs fine on its own.

## Repository layout

```
main.py              app assembly, middleware, router registration
config.py            settings
database.py          engine, session, local SQLite fallback
modules/             one package per domain (40 total)
middleware/          cache + request context
utils/               gateway clients, payments, mail, PDF, embeddings
migrations/          data migrations and seeds
docs/                architecture and agent documentation
scripts/             operational and verification scripts
```

## Documentation

| Document | Contents |
|----------|----------|
| [docs/openclaw-ad-agents.md](docs/openclaw-ad-agents.md) | Agent roles, contracts, validation, failure modes |
| [docs/openclaw-model-verification.md](docs/openclaw-model-verification.md) | End-to-end verification of the WhatsApp pharmacy agent |
| [docs/hermes-deployment.md](docs/hermes-deployment.md) | Multi-profile Hermes deployment |
| [docs/AD_CREATIVE_SYSTEM.md](docs/AD_CREATIVE_SYSTEM.md) | How creative is generated and scored |
| [docs/AUTONOMOUS_AD_SYSTEM_PLAN.md](docs/AUTONOMOUS_AD_SYSTEM_PLAN.md) | The autonomous loop, end to end |
| [docs/DATA_COLLECTION_FRAMEWORK.md](docs/DATA_COLLECTION_FRAMEWORK.md) | What telemetry the agents read |

## Project status

This is the backend of a live product, open-sourced as it runs. It is honest about
that:

- **Mature:** commerce, payments, WhatsApp, analytics, the agent gateway client.
- **Working but unregistered:** a few modules (virtual try-on, coupons, returns)
  exist and are intentionally left out of `main.py` while they stabilise — the
  `# REMOVED` / commented lines there are a decision trail, not a bug.
- **Wanted:** a real test suite. There are verification scripts under `scripts/`,
  not pytest coverage. If you want a first contribution, that is the highest-value
  one — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing

Issues and pull requests are welcome. Start with
[CONTRIBUTING.md](CONTRIBUTING.md) for the local setup, the module conventions and
the kinds of changes that get merged quickly.

## Security

Please do not open a public issue for a vulnerability — see
[SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © Shopivell
