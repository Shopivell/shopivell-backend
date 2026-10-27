# Contributing to Shopivell

Thanks for taking a look. This is a production backend, so the bar for a change is
"does it keep the live paths safe", not "does it add the most code".

## Getting it running

```bash
git clone https://github.com/Shopivell/shopivell-backend.git
cd shopivell-backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload
```

`USE_SQLITE=true` is the default, so there is no database to install: the app
creates a local SQLite file on first boot. API reference lives at `/docs`.

The install is large because `requirements.txt` carries optional vision
dependencies (torch, mediapipe, playwright). If you are working on a single
module, it is fine to install just what it imports and skip the rest.

## Repository conventions

- **One package per domain.** Each module under `modules/` is
  `router.py` (HTTP) → `service.py` (logic) → `models.py` (SQLAlchemy) →
  `schemas.py` (Pydantic). Keep HTTP concerns in the router and business logic in
  the service; a change that needs a new domain should be a new package, not a
  bigger existing one.
- **Register routers explicitly.** A new router must be added in `main.py`. Some
  modules are deliberately left unregistered while they stabilise — do not
  "clean up" those commented lines, they are decisions.
- **Store scoping is not optional.** Multi-tenancy is enforced by filtering on
  `store_id`. Any query that reads or writes tenant data must be scoped, and the
  store must come from the authenticated principal, never from a request body.
- **Secrets never enter the repo.** `.env` is git-ignored; add new settings to
  `.env.example` with an empty or safe default.
- **Be honest in code comments.** Existing comments mark removed subsystems and
  known rough edges — keep that habit.

## Agent changes

The agents are the part most likely to break silently, so the rules are stricter:

- The model is given a bounded context and must answer with a **strict JSON
  contract**. Parse and validate it; never trust a shape.
- Never let a model value reach a budget, bid or price without clamping it in the
  service layer.
- Fail loudly. If a response is invalid, raise — do not fall back to a fabricated
  default.
- Contract or prompt changes belong in `docs/openclaw-ad-agents.md` as well, since
  the gateway profiles are generated from those prompt constants.

## Before you open a pull request

There is no pytest suite yet (see below), so verify by hand and say what you ran:

```bash
python -m compileall -q .            # syntax across the tree
uvicorn main:app --reload            # boots, /health returns healthy
python scripts/pharmacy_bot_scenarios.py   # conversational scenarios, if you touched WhatsApp
```

Then in the PR description: what changed, why, which endpoints or agents it
touches, and the commands you used to check it. Small, focused PRs get reviewed
fast; a large refactor is better raised as an issue first.

## Good first contributions

1. **A test suite.** The highest-value thing in this repo. `pytest` with
   `httpx.ASGITransport` against a SQLite fixture, covering the agent JSON
   contracts and the store-scoping rules first.
2. **Typing and lint config** (`pyproject.toml`, ruff) that the code already
   passes — not a reformat of the whole tree.
3. **Docs for a module** that has none: a short page in `docs/` beats a comment.
4. **Provider adapters** for the agent gateway, as long as they keep the same JSON
   contracts and fail loudly.

## License

Contributions are accepted under the [MIT license](LICENSE).
