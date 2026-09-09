# OpenClaw Multi-Agent System

Autonomous goal-driven advertising management using cooperating AI agents.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Autonomous Loop                              │
│                                                                   │
│  ┌──────────────┐    goals    ┌──────────────┐                  │
│  │  Goal Agent  │ ─────────► │ Planner Agent │                  │
│  │              │             │               │                  │
│  │ • Analyzes   │             │ • Decomposes  │                  │
│  │   performance│             │   goals       │                  │
│  │ • Sets goals │             │ • Creates     │                  │
│  │ • Prioritizes│             │   task plans  │                  │
│  └──────────────┘             └───────┬───────┘                  │
│         ▲                             │ plan                     │
│         │                             ▼                          │
│         │ feedback          ┌──────────────┐                     │
│         │                   │Executor Agent│                     │
│  ┌──────┴───────┐           │              │                     │
│  │  Evaluator   │◄──────────│ • Runs tasks │                     │
│  │              │  results  │ • Calls skills│                     │
│  │ • Assesses   │           │ • Handles     │                     │
│  │   progress   │           │   retries     │                     │
│  │ • Recommends │           └──────┬───────┘                     │
│  │   adjustments│                  │                             │
│  └──────────────┘                  ▼                             │
│                            ┌──────────────┐                      │
│                            │    Skills    │                      │
│                            │              │                      │
│                            │ • ad-creator │                      │
│                            │ • zernio-ads │                      │
│                            │ • optimizer  │                      │
│                            └──────────────┘                      │
└─────────────────────────────────────────────────────────────────┘
```

## Agents

### Goal Agent
**Role:** Strategic goal setter

Analyzes store performance and market conditions to set advertising goals.

**Inputs:**
- Current performance metrics (ROAS, CPA, CTR, etc.)
- Market conditions (seasonality, competition)
- Business constraints (budget, timeline)

**Outputs:**
- Prioritized goals with targets and deadlines
- Goal types: maximize_roas, minimize_cpa, increase_conversions, grow_audience, etc.

**Example:**
```typescript
const goals = await generateGoals({
  store_id: 'store_123',
  store_name: 'Fashion Store',
  performance: {
    roas: 2.1,
    cpa: 15,
    ctr: 1.8,
    conversion_rate: 0.03,
    total_spend: 500,
    total_revenue: 1050,
    active_campaigns: 3
  },
  constraints: {
    max_budget: 1000,
    min_roas: 2.5
  }
});
// Returns: [{ type: 'maximize_roas', target_value: 3, ... }]
```

### Planner Agent
**Role:** Task decomposition

Takes goals and creates detailed execution plans with ordered tasks.

**Inputs:**
- Goal from Goal Agent
- Available budget
- Existing campaigns
- Previous results

**Outputs:**
- Execution plan with tasks
- Task dependencies and parallel groups
- Success criteria
- Fallback strategies

**Example:**
```typescript
const plan = await generatePlan({
  goal: { type: 'maximize_roas', target_value: 3, ... },
  available_budget: 500
});
// Returns: {
//   tasks: [
//     { type: 'research_market', skill: 'ad-creator', ... },
//     { type: 'generate_campaign', skill: 'ad-creator', ... },
//     { type: 'launch_campaign', skill: 'zernio-ads', ... },
//     { type: 'wait_and_monitor', ... },
//     { type: 'scale_budget', skill: 'zernio-ads', ... }
//   ],
//   parallel_groups: [['task_1', 'task_2']],
//   success_criteria: [{ metric: 'roas', operator: 'gte', value: 3 }]
// }
```

### Executor Agent
**Role:** Task execution

Executes tasks by calling the appropriate skills with retry logic.

**Features:**
- Skill registry for available actions
- Retry with exponential backoff
- Parallel and sequential execution
- Progress tracking

**Example:**
```typescript
const result = await executeTask({
  type: 'generate_campaign',
  skill: 'ad-creator',
  action: 'generate_full_campaign',
  parameters: {
    product_name: 'Summer Dress',
    budget: 50
  }
});
// Returns: { success: true, result: {...}, duration_ms: 3000 }
```

### Evaluator (Built into Loop)
**Role:** Progress assessment

Evaluates goal progress and recommends adjustments.

**Assessments:**
- `achieved`: Goal reached
- `on_track`: Good progress
- `at_risk`: May not reach goal
- `off_track`: Significantly behind
- `failed`: Cannot achieve

**Recommendations:**
- `scale`: Increase budget/effort
- `reduce`: Cut spending
- `pivot`: Change strategy
- `pause`: Wait for more data
- `continue`: Keep going
- `abandon`: Give up on goal

## Message Protocol

Agents communicate via typed messages:

```typescript
interface AgentMessage {
  id: string;
  type: MessageType;  // goal_request, plan_response, task_result, etc.
  from: AgentIdentity;
  to: AgentRole | 'broadcast';
  timestamp: string;
  payload: any;
  correlation_id?: string;
}
```

## Starting an Autonomous Session

```typescript
import { startAutonomousSession } from './agents';

const session = await startAutonomousSession(
  {
    store_id: 'store_123',
    auto_generate_goals: true,
    evaluation_interval_minutes: 60,
    max_concurrent_tasks: 3,
    budget_limit: 500,
    pause_on_error: true
  },
  currentPerformance,
  {
    onGoalsGenerated: (goals) => console.log('Goals:', goals),
    onPlanCreated: (goal, plan) => console.log('Plan:', plan),
    onTaskCompleted: (result) => console.log('Task done:', result),
    onGoalAchieved: (goal) => console.log('Goal achieved!', goal),
    onError: (error) => console.error('Error:', error)
  }
);
```

## Continuous Monitoring Mode

For 24/7 autonomous operation:

```typescript
import { startContinuousMonitoring } from './agents';

const sessionId = await startContinuousMonitoring(
  {
    store_id: 'store_123',
    auto_generate_goals: true,
    evaluation_interval_minutes: 60,
    budget_limit: 1000
  },
  async () => {
    // Fetch current performance from Zernio
    return await getStorePerformance('store_123');
  }
);

// Later: pause, resume, or stop
pauseSession(sessionId);
resumeSession(sessionId);
stopSession(sessionId);
```

## Goal Types

| Type | Target Metric | Example Target |
|------|---------------|----------------|
| `maximize_roas` | ROAS | 3.0x |
| `minimize_cpa` | CPA | $10 |
| `increase_conversions` | Conversions | 100/week |
| `grow_audience` | Reach | 50,000 |
| `reduce_cac` | CAC | $25 |
| `improve_lead_quality` | Lead Score | 70+ |
| `scale_revenue` | Revenue | $5,000/week |
| `brand_awareness` | Impressions | 100,000 |

## Task Types

| Type | Skill | Action |
|------|-------|--------|
| `research_market` | ad-creator | research_market |
| `generate_campaign` | ad-creator | generate_full_campaign |
| `launch_campaign` | zernio-ads | create_campaign |
| `pause_campaign` | zernio-ads | pause_ad |
| `scale_budget` | zernio-ads | scale_budget |
| `refresh_creative` | ad-creator | generate_image + generate_ad_copy |
| `create_lookalike` | zernio-ads | create_lookalike_audience |
| `wait_and_monitor` | - | Sleep then check metrics |

## Integration with Router

The autonomous system is exposed via REST API:

```
POST /api/openclaw/autonomous/start
POST /api/openclaw/autonomous/{session_id}/pause
POST /api/openclaw/autonomous/{session_id}/resume
POST /api/openclaw/autonomous/{session_id}/stop
GET  /api/openclaw/autonomous/{session_id}/status
GET  /api/openclaw/autonomous/sessions
```

## Environment Variables

- `ANTHROPIC_API_KEY`: For Claude (goal/plan generation)
- `OPENAI_API_KEY`: For GPT-Image-2.5 (ad images)
- `ZERNIO_API_KEY`: For Meta Ads API

## Best Practices

1. **Start with specific goals**: Rather than "improve everything", set "achieve 3x ROAS"
2. **Set realistic constraints**: Budget limits prevent runaway spending
3. **Monitor callbacks**: Use callbacks to log and alert on key events
4. **Use evaluation intervals**: 60 minutes is good for most campaigns
5. **Enable pause_on_error**: Prevents cascading failures
