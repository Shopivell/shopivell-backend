# OpenClaw - AI Ad Management System

> **Shopivell's autonomous advertising platform using OpenClaw + Zernio**

## Quick Summary

Meta rejected our App Review for `ads_management` permission. Solution:
- **Zernio** = Meta Marketing Partner (provides API access without App Review)
- **OpenClaw** = AI agent platform (replaces our Python agents)

```
Frontend → Shopivell Backend → OpenClaw → Zernio → Meta Ads API
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend                                 │
│                    openclawService.ts                           │
└─────────────────────────┬───────────────────────────────────────┘
                          │ /api/openclaw/*
┌─────────────────────────▼───────────────────────────────────────┐
│                    Shopivell Backend                             │
│                 modules/openclaw/router.py                       │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│                        OpenClaw                                  │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ Skills (TypeScript)                                     │     │
│  │  • ad-creator/    → AI campaign generation              │     │
│  │  • zernio-ads/    → Meta Ads via Zernio API             │     │
│  └────────────────────────────────────────────────────────┘     │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ Plugins                                                 │     │
│  │  • optimizer/     → 24/7 autonomous monitoring          │     │
│  └────────────────────────────────────────────────────────┘     │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ Agents (Multi-Agent System)                             │     │
│  │  • Goal Agent     → Sets strategic goals                │     │
│  │  • Planner Agent  → Creates execution plans             │     │
│  │  • Executor Agent → Runs tasks using skills             │     │
│  └────────────────────────────────────────────────────────┘     │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│                      Zernio API                                  │
│              (Meta Marketing Partner)                            │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│                     Meta Ads API                                 │
│            (Facebook, Instagram, WhatsApp)                       │
└─────────────────────────────────────────────────────────────────┘
```

## File Structure

```
modules/openclaw/
├── router.py                    # FastAPI endpoints (Python)
├── README.md                    # This file
│
├── skills/
│   ├── ad-creator/
│   │   ├── SKILL.md            # Skill documentation
│   │   └── index.ts            # AI ad generation (GPT-Image-2.5)
│   │
│   └── zernio-ads/
│       ├── SKILL.md            # Skill documentation
│       └── index.ts            # Meta Ads via Zernio
│
├── plugins/
│   └── optimizer/
│       ├── PLUGIN.md           # Plugin documentation
│       └── index.ts            # 24/7 monitoring rules
│
└── agents/
    ├── AGENTS.md               # Agent system documentation
    ├── types.ts                # Shared types & message protocol
    ├── goal_agent.ts           # Goal generation & evaluation
    ├── planner_agent.ts        # Task planning & decomposition
    ├── executor_agent.ts       # Task execution with retries
    ├── autonomous_loop.ts      # Main orchestration loop
    └── index.ts                # Exports
```

## Key Concepts

### 1. Skills (What the system can DO)

| Skill | Purpose | Key Actions |
|-------|---------|-------------|
| `ad-creator` | AI ad generation | `generate_full_campaign()`, `generate_image()`, `generate_ad_copy()` |
| `zernio-ads` | Meta Ads management | `create_campaign()`, `get_insights()`, `scale_budget()`, `pause_ad()` |

### 2. Plugins (Background automation)

| Plugin | Purpose | Rules |
|--------|---------|-------|
| `optimizer` | 24/7 monitoring | `scale_winner`, `kill_loser`, `creative_fatigue`, `ctwa_quality` |

### 3. Agents (Goal-driven autonomy)

| Agent | Role | Input → Output |
|-------|------|----------------|
| Goal Agent | Sets goals | Performance data → Goals (e.g., "achieve 3x ROAS") |
| Planner Agent | Creates plans | Goal → Task list (research, create, launch, monitor) |
| Executor Agent | Runs tasks | Task → Result (calls skills) |

## API Endpoints

### Campaign Management
```
GET  /api/openclaw/stores/{id}/campaigns
GET  /api/openclaw/campaigns/{id}/insights
POST /api/openclaw/campaigns/{id}/pause
POST /api/openclaw/campaigns/{id}/resume
POST /api/openclaw/campaigns/{id}/scale
```

### AI Generation
```
POST /api/openclaw/stores/{id}/generate-campaign
POST /api/openclaw/stores/{id}/generate-ctwa-campaign
POST /api/openclaw/generate-image
POST /api/openclaw/generate-copy
```

### Autonomous System
```
POST /api/openclaw/stores/{id}/autonomous/start
GET  /api/openclaw/stores/{id}/autonomous/sessions
GET  /api/openclaw/autonomous/{session_id}/status
POST /api/openclaw/autonomous/{session_id}/pause
POST /api/openclaw/autonomous/{session_id}/resume
POST /api/openclaw/autonomous/{session_id}/stop
POST /api/openclaw/autonomous/{session_id}/add-goal
```

### Reporting
```
GET  /api/openclaw/stores/{id}/report/weekly
GET  /api/openclaw/stores/{id}/report/demographics
GET  /api/openclaw/stores/{id}/lead-stats
GET  /api/openclaw/stores/{id}/conversion-stats
```

## How Autonomous Mode Works

```
User: "Maximize my ROAS"
         │
         ▼
┌─────────────────┐
│   Goal Agent    │  Analyzes performance, sets goal: "Achieve 3x ROAS in 14 days"
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Planner Agent   │  Creates plan:
└────────┬────────┘  1. Research market
         │           2. Generate 3 campaign variations
         │           3. Launch with $50/day budget
         │           4. Monitor for 3 days
         │           5. Scale winners, kill losers
         │           6. Repeat until goal achieved
         ▼
┌─────────────────┐
│ Executor Agent  │  Runs each task by calling skills:
└────────┬────────┘  - ad-creator.research_market()
         │           - ad-creator.generate_full_campaign()
         │           - zernio-ads.create_campaign()
         │           - zernio-ads.get_insights()
         │           - zernio-ads.scale_budget()
         ▼
┌─────────────────┐
│   Evaluator     │  Checks progress:
└────────┬────────┘  - ROAS now 2.5x (83% to goal)
         │           - Trend: improving
         │           - Recommendation: continue, scale top performer
         │
         ▼
    Loop continues until goal achieved or budget exhausted
```

## Frontend Integration

```typescript
import { openclawService } from '@/services/openclawService'

// Start autonomous session
const { session_id } = await openclawService.startAutonomousSession('store_123', {
  auto_generate_goals: true,  // Let AI set goals
  budget_limit: 500,          // Max spend
  evaluation_interval_minutes: 60
})

// Or with specific goals
const { session_id } = await openclawService.startAutonomousSession('store_123', {
  budget_limit: 500,
  initial_goals: [{
    type: 'maximize_roas',
    description: 'Achieve 3x ROAS',
    target_metric: 'roas',
    target_value: 3,
    priority: 'high'
  }]
})

// Monitor progress
const status = await openclawService.getAutonomousSessionStatus(session_id)
// { state: 'running', goals: [...], completed_tasks: 5, total_spend: 150 }

// Control session
await openclawService.pauseAutonomousSession(session_id)
await openclawService.resumeAutonomousSession(session_id)
await openclawService.stopAutonomousSession(session_id)
```

## Environment Variables

```bash
# Required
ZERNIO_API_KEY=xxx           # Zernio API access
ANTHROPIC_API_KEY=xxx        # Claude (goal/plan generation)
OPENAI_API_KEY=xxx           # GPT-Image-2.5 (ad images)

# Optional
OPENCLAW_GATEWAY_URL=http://openclaw:18789
```

## What Was Replaced

| Old (Python) | New (OpenClaw) |
|--------------|----------------|
| `modules/agents/` | `openclaw/agents/` + `openclaw/skills/ad-creator/` |
| `modules/ad_generator/` | `openclaw/skills/ad-creator/` |
| `modules/marketing/` | `openclaw/skills/zernio-ads/` |
| `modules/micro_strategy/` | `openclaw/plugins/optimizer/` |
| `modules/brand_intelligence/` | `openclaw/skills/ad-creator/research_market()` |

Legacy code backed up to: `shopivell-legacy-agents` repo

## Testing

### 1. Test Campaign Generation
```bash
curl -X POST http://localhost:8000/api/openclaw/stores/{store_id}/generate-campaign \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "Summer Dress",
    "product_description": "Light cotton dress perfect for summer",
    "campaign_goal": "conversions",
    "brand_voice": "casual",
    "budget": 50
  }'
```

### 2. Test Autonomous Session
```bash
curl -X POST http://localhost:8000/api/openclaw/stores/{store_id}/autonomous/start \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "auto_generate_goals": true,
    "budget_limit": 100,
    "evaluation_interval_minutes": 60
  }'
```

### 3. Check Session Status
```bash
curl http://localhost:8000/api/openclaw/autonomous/{session_id}/status \
  -H "Authorization: Bearer {token}"
```

## Common Issues

### "Store must be connected to Zernio first"
Store needs OAuth flow completed:
1. Call `POST /stores/{id}/connect-zernio`
2. Redirect user to `auth_url`
3. Handle callback at `/settings/ads/callback`

### "No ad account connected"
User hasn't connected their Meta ad account through Zernio OAuth.

### Session stuck in "initializing"
Check OpenClaw gateway is running and `OPENCLAW_GATEWAY_URL` is correct.

## Quick Links

- [Ad Creator Skill](./skills/ad-creator/SKILL.md)
- [Zernio Ads Skill](./skills/zernio-ads/SKILL.md)
- [Optimizer Plugin](./plugins/optimizer/PLUGIN.md)
- [Agent System](./agents/AGENTS.md)
