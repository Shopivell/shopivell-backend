# Advertising agents on the real OpenClaw gateway

Status: **implemented, verified against a stub gateway; needs the six gateway
agents configured on the host before production use.**

The advertising agents no longer reason inside the backend. Goal setting, plan
creation, progress evaluation, optimizer target calibration, market research
judgement and image art direction are six dedicated agents on the OpenClaw
gateway. The backend sends each one a strict JSON contract, validates the
answer, and raises an error when there is no real answer. There is no
direct-OpenAI reasoning path for these agents and no local fallback.

The pharmacy WhatsApp agent is unchanged and documented separately in
[openclaw-migration.md](./openclaw-migration.md).

## Architecture

```
POST /openclaw/stores/{id}/autonomous/start
        |
        v
FastAPI autonomous loop (modules/openclaw/router.py)
        |  measured performance, business profile, connected accounts
        v
OpenClaw gateway /v1/chat/completions      one agent + session key per role
        |  openclaw/ads-goal
        |  openclaw/ads-planner
        |  openclaw/ads-evaluator
        |  openclaw/ads-calibrator
        |  openclaw/ads-research    (market research judgement)
        |  openclaw/ads-image       (image art direction, photo choice)
        v
Structured JSON  -> validated in modules/openclaw/agent_service.py
        |
        v
Deterministic executor (_run_executor_task -> _dispatch_ad_creator / _dispatch_zernio)
        |
        v
Zernio / Meta Ads, OpenAI ad copy, image rendering, Serper/Tavily data (tools, not agents)
```

## Roles

| Role | Agent model selector (default) | Session key | Returns |
|------|-------------------------------|-------------|---------|
| Goal | `openclaw/ads-goal` | `ads-goal:<store_id>` | JSON array of 1-5 typed, numeric goals |
| Planner | `openclaw/ads-planner` | `ads-planner:<store_id>` | JSON plan whose tasks only use executable skills/actions |
| Evaluator | `openclaw/ads-evaluator` | `ads-evaluator:<store_id>` | assessment, progress, recommendations, `should_continue` |
| Calibrator | `openclaw/ads-calibrator` | `ads-calibrator:<store_id>` | target ROAS/CPA and optimizer rule overrides |
| Researcher | `openclaw/ads-research` | `ads-research:<task>:<market-hash>` | keep-lists for competitors/keywords/trends, structured website profile |
| Art director | `openclaw/ads-image` | `ads-image:<store_id>` | image prompts per creative, plus which real photos to copy |

Each role has its own session key so one agent's memory cannot leak into
another. Every key is scoped to one store, except the researcher's, which is
scoped to the business+market being researched (its four tasks are one-shot
judgements, so a stable per-market key keeps one store's history out of another's
without creating a session per request). The gateway keeps the memory; the
backend does not replay history.

`openclaw/<agentId>` selects a dedicated agent on the gateway. A bare
`openclaw` uses the gateway's default agent, which is useful as a stopgap until
the dedicated agents exist.

## What the backend validates

- **Goals** - type must be one of the eight goal types and `target_value` must
  be numeric; invalid entries are dropped and an answer with no valid goal is a
  **502**. No fallback goal is invented.
- **Plans** - a task must name a `skill`/`action` pair the executor can actually
  run (`SKILL_ACTIONS` in `agent_service.py`); anything else is dropped, and a
  plan with no executable task is a **502**. `estimated_cost` is never guessed
  locally.
- **Assessments** - `assessment` must be one of `on_track`, `at_risk`,
  `off_track`, `achieved`, `failed`; `should_continue` must be a boolean;
  unknown recommendation types are dropped. The metrics recorded with the
  assessment are the ones the backend measured, never model output.
- **Calibration** - rule bounds in `modules/optimizer/calibration.py` still
  clamp every proposed number; the model proposes, the code enforces limits.
- **Research judgement** - every keep-list index must be an integer inside the
  candidate rows; unknown indices are dropped and a section the agent wiped
  entirely falls back to the candidate list rather than inventing entries. Dead
  data sources (Serper/Tavily/Keywords Everywhere) return empty lists so one
  provider cannot fail a report; the agent is required, so its failure is a
  **503/502**, not an empty report.
- **Image art direction** - the prompt must be a real paragraph (an empty or
  stub prompt is a **502**), and only reference numbers that exist for that
  request are attached. In a campaign, every copy variation must come back with
  its own prompt or the whole call fails - a silently missing creative is worse
  than a visible error.

## Optional Hermes backend

The same six roles can run on a Hermes Agent gateway instead of OpenClaw. On the
Contabo host the profiles and one multiplexed gateway are already provisioned:

| Role | Hermes profile | Endpoint |
|------|----------------|----------|
| Goal | `ads-goal` | `http://hermes:8642/p/ads-goal/v1/chat/completions` |
| Planner | `ads-planner` | `http://hermes:8642/p/ads-planner/v1/chat/completions` |
| Evaluator | `ads-evaluator` | `http://hermes:8642/p/ads-evaluator/v1/chat/completions` |
| Calibrator | `ads-calibrator` | `http://hermes:8642/p/ads-calibrator/v1/chat/completions` |
| Researcher | `ads-research` | `http://hermes:8642/p/ads-research/v1/chat/completions` |
| Art director | `ads-image` | `http://hermes:8642/p/ads-image/v1/chat/completions` |

Each profile's `SOUL.md` carries the same instructions and JSON contract as the
prompt constants in this repo, so the backend's validators keep working
unchanged. One gateway process serves all six (Hermes multiplexing), so six roles
cost one process, not six.

Switch the ad roles over with two variables; leave everything else alone:

| Variable | Purpose |
|----------|---------|
| `HERMES_GATEWAY_URL` | e.g. `http://hermes:8642`. When set, the six ad roles go to their profile endpoints |
| `HERMES_GATEWAY_TOKEN` | Hermes `API_SERVER_KEY`; falls back to `OPENCLAW_GATEWAY_TOKEN` |

The model id sent to Hermes is the bare profile name (`ads-goal`), not
`openclaw/ads-goal`. The pharmacy WhatsApp agent is unaffected: it always uses
`OPENCLAW_GATEWAY_URL`. Unset `HERMES_GATEWAY_URL` to roll back to OpenClaw.

## Market research

The split in `modules/market_research/service.py` is deliberate:

- **Tools (code)** - Serper organic + Maps, Google autocomplete,
  Keywords Everywhere volume, Tavily extraction. These are API calls and cheap
  regex pre-filters; they return data.
- **Judgement (agent)** - which result is really a competitor and what its brand
  name is, which keywords this business's customers in this market would type,
  which reports are about this industry, and what a website actually sells
  (`competitors`, `keywords`, `trends`, `website` tasks).

The agent is asked for `{"keep": [...]}` (or the website profile object) and the
service applies that to the rows it gathered. It never sees a made-up row, and
it cannot add one: indices outside the candidate list are discarded.

## Image generation

A language model cannot render an image, so the division is:

- **Agent (`ads-image`)** - decides what the picture is: scene, composition,
  lighting, mood, whether text is rendered and exactly which words, and which of
  the business's real photos the creative must copy. One turn per image, or one
  turn for a whole campaign's variations.
- **Tool (backend)** - sends that prompt to the image model (`/images/edits`
  with the chosen real photos, `/images/generations`, or the OpenRouter image
  model when no OpenAI key is set) and stores the result.

The paths that use it: the `ad-creator` `generate_image` action (and therefore
`generate_full_campaign`), `POST /api/assets/generate`, and campaign creative
building (`generate_campaign_images`). Which website photos a campaign creative
uses is the same agent's call, made from thumbnails it can see - the old vision
picker and the fixed prompt template are gone.

## Failure behaviour

| Situation | Result |
|-----------|--------|
| `OPENCLAW_GATEWAY_URL` / `OPENCLAW_GATEWAY_TOKEN` missing | 503 naming the variable; no session is created |
| Gateway unreachable / timeout | 503 |
| Gateway returns 4xx/5xx | 502 with the upstream code and body excerpt |
| Empty or non-JSON completion | 502 "unusable answer" |
| Autonomous goal/plan/evaluation fails | session `state` becomes `failed` with an `error` message; it never reports success |
| Research agent fails | the research endpoint/task raises 503/502; no unfiltered list is returned as if it had been judged |
| Image agent fails | image generation raises 503/502; no generic template prompt is used instead |

Because failures are loud, `POST /autonomous/start` and the resume/add-goal
endpoints check the gateway configuration before doing any work.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENCLAW_GATEWAY_URL` | `http://openclaw:18789` | Gateway base URL (must be set explicitly; there is no default in code) |
| `OPENCLAW_GATEWAY_TOKEN` | - | Bearer token; must match `gateway.auth.token` |
| `OPENCLAW_GOAL_AGENT_MODEL` | `openclaw/ads-goal` | Goal agent selector |
| `OPENCLAW_PLANNER_AGENT_MODEL` | `openclaw/ads-planner` | Planner agent selector |
| `OPENCLAW_EVALUATOR_AGENT_MODEL` | `openclaw/ads-evaluator` | Evaluator agent selector |
| `OPENCLAW_CALIBRATOR_AGENT_MODEL` | `openclaw/ads-calibrator` | Optimizer calibration selector |
| `OPENCLAW_RESEARCH_AGENT_MODEL` | `openclaw/ads-research` | Market research judgement selector |
| `OPENCLAW_IMAGE_AGENT_MODEL` | `openclaw/ads-image` | Image art direction / photo choice selector |

`OPENCLAW_BRAIN_ENABLED` only controls the pharmacy WhatsApp path; the
advertising agents always run on the gateway.

## Host setup

Create the six agents in the OpenClaw configuration
(`/home/node/.openclaw/openclaw.json`) with those ids, then make sure the
gateway exposes `/v1/chat/completions` and the token in `gateway.auth.token`
matches the backend environment. Restart the gateway container and restart the
backend.

If the host cannot define separate agents yet, point the variables at an
existing agent (for example `OPENCLAW_GOAL_AGENT_MODEL=openclaw`). The roles
still get separate session keys and contracts; only the underlying agent is
shared.

The image and research agents work from text alone. When the gateway agent's
model has vision, the backend also attaches the business's real photos as
`image_url` parts of the user turn (campaign creative choice, and the numbered
reference list), so photo selection is made by looking at them; with a
text-only model the agent picks from their descriptions instead and nothing
breaks.

Any web-search capability the goal or calibrator agents should have is
configured on the gateway agent itself. The backend does not send OpenAI-style
`tools` requests - the agent decides what it does.

## Removed

- `agent_service._openai()` and the direct `responses.create` calls.
- The fallback goal that was invented when goal parsing failed.
- `estimated_cost = available_budget * 0.5` when the planner omitted it.
- The unconditional "session completed" ending - the evaluator now decides
  whether a goal is achieved, failed or still active.
- `conversion_rate: 0.03` and `cpa = spend / max(conversions, 1)` in the
  performance snapshot; a metric with no data is `None`, not zero.
- The `resume` stub ("would need to resume from checkpoint") and the
  `add-goal` endpoint that appended a goal without ever running it.
- The direct OpenAI/OpenRouter prompts that filtered competitors, keywords,
  trends and website profiles in `modules/market_research/service.py`.
- The hardcoded image-prompt templates in the ad-creator skill, in
  `AssetService.generate_ad_image` and in the campaign creative builder
  (`_IMAGE_STYLES`, layout/text/anatomy rules), plus the `pick_reference_photos`
  vision call that picked photos before the prompt was written.

## Verification

Run against a stub gateway (the checks used while implementing):

1. goals: per-role model id, `Bearer` token, session key, invalid goal dropped,
   unknown metric absent from the prompt;
2. planner: unexecutable task dropped, real ids preserved, no fabricated cost;
3. evaluator: assessment/recommendation validation, measured metrics attached;
4. calibrator: sync path used by the optimizer loop, rule overrides clamped;
5. non-JSON answer -> 502, nothing invented;
6. unreachable gateway -> 503, missing token -> 503;
7. loop: goal -> plan -> execute -> evaluator marks the goal achieved;
   evaluator `pause` pauses the session; resume runs only goals that still need
   work; adding a goal executes it; a gateway failure fails the session;
8. research: each of the four tasks sends its own session key and gets the
   keep-list applied (unknown indices dropped, other-market rows removed);
   gateway down -> 503 and the endpoint does not answer with raw rows;
9. image: the agent's prompt and chosen reference numbers are the ones used for
   rendering, a thin/empty prompt is a 502, and a campaign batch missing one
   variation fails instead of generating a creative-less ad.

On the host, confirm all six agents exist and answer:

```bash
docker exec openclaw openclaw agents list
```

Then start a session with a small budget cap and check
`GET /openclaw/autonomous/{session_id}/status` for `evaluations`,
`goals_achieved` and `error`.

## Not done in this pass

- `modules/openclaw/agents/*.ts`, `skills/*.ts` and `plugins/optimizer/*.ts`
  are not executed by the backend and were deliberately left untouched. They
  contain their own prompts and mock skill implementations; nothing in the
  running system imports them. Remove or port them separately.
- `GET /openclaw/stores/{id}/lead-stats` still returns zeroed counters.
- Autonomous sessions are still stored in memory (`_autonomous_sessions`), so a
  deploy loses them.
