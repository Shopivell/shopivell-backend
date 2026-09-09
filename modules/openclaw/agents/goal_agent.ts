/**
 * Goal Agent
 * Analyzes store performance, market conditions, and business context
 * to autonomously set and prioritize advertising goals
 */

import Anthropic from '@anthropic-ai/sdk';
import {
  AgentIdentity,
  AgentMessage,
  Goal,
  GoalType,
  GoalPriority,
  GoalContext,
  GoalConstraints,
  PerformanceSnapshot,
  MarketConditions
} from './types';

const anthropic = new Anthropic();

// ============ Goal Agent Identity ============

export const GOAL_AGENT: AgentIdentity = {
  id: 'goal-agent-001',
  role: 'goal_setter',
  name: 'Strategic Goal Setter'
};

// ============ System Prompt ============

const GOAL_AGENT_PROMPT = `You are a Strategic Advertising Goal Setter for e-commerce businesses.

Your role is to analyze business performance data and market conditions to set clear, achievable advertising goals.

## Your Capabilities:
1. Analyze current ad performance metrics (ROAS, CPA, CTR, etc.)
2. Identify performance gaps and opportunities
3. Set SMART goals (Specific, Measurable, Achievable, Relevant, Time-bound)
4. Prioritize goals based on business impact
5. Adjust goals based on constraints (budget, time, resources)

## Goal Types You Can Set:
- maximize_roas: Improve return on ad spend
- minimize_cpa: Reduce cost per acquisition
- increase_conversions: Drive more sales/leads
- grow_audience: Expand reach and awareness
- reduce_cac: Lower customer acquisition cost
- improve_lead_quality: Better quality leads from ads
- scale_revenue: Increase total revenue from ads
- brand_awareness: Increase brand visibility

## Output Format:
Return a JSON array of goals, ordered by priority. Each goal should have:
- type: One of the goal types above
- description: Clear description of what to achieve
- target_metric: The specific metric to optimize
- target_value: The target number to achieve
- deadline: When to achieve by (ISO date string)
- priority: critical | high | medium | low
- reasoning: Why this goal matters for the business

## Important Rules:
1. Set realistic targets based on current performance (don't expect 10x overnight)
2. Consider budget constraints when setting goals
3. Balance short-term wins with long-term growth
4. Maximum 5 active goals at a time to maintain focus
5. At least one goal should be achievable within 7 days for quick wins
`;

// ============ Goal Generation ============

export interface GoalGenerationInput {
  store_id: string;
  store_name: string;
  performance: PerformanceSnapshot;
  market_conditions?: MarketConditions;
  constraints: GoalConstraints;
  business_context?: string;
  previous_goals?: Goal[];
}

export async function generateGoals(input: GoalGenerationInput): Promise<Goal[]> {
  const prompt = buildGoalPrompt(input);

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 4096,
    system: GOAL_AGENT_PROMPT,
    messages: [
      {
        role: 'user',
        content: prompt
      }
    ]
  });

  const content = response.content[0];
  if (content.type !== 'text') {
    throw new Error('Unexpected response type from Claude');
  }

  // Parse the JSON response
  const jsonMatch = content.text.match(/\[[\s\S]*\]/);
  if (!jsonMatch) {
    throw new Error('Failed to parse goals from response');
  }

  const goalsData = JSON.parse(jsonMatch[0]);

  // Transform to Goal objects
  const goals: Goal[] = goalsData.map((g: any, index: number) => ({
    id: `goal-${Date.now()}-${index}`,
    type: g.type as GoalType,
    description: g.description,
    target_metric: g.target_metric,
    target_value: g.target_value,
    current_value: getCurrentValue(g.target_metric, input.performance),
    deadline: g.deadline,
    priority: g.priority as GoalPriority,
    status: 'pending',
    constraints: input.constraints,
    context: {
      store_id: input.store_id,
      store_name: input.store_name,
      current_performance: input.performance,
      market_conditions: input.market_conditions
    },
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  }));

  return goals;
}

function buildGoalPrompt(input: GoalGenerationInput): string {
  let prompt = `## Current Store Performance\n`;
  prompt += `Store: ${input.store_name} (ID: ${input.store_id})\n\n`;

  prompt += `### Metrics (${input.performance.date_range})\n`;
  prompt += `- ROAS: ${input.performance.roas.toFixed(2)}x\n`;
  prompt += `- CPA: $${input.performance.cpa.toFixed(2)}\n`;
  prompt += `- CTR: ${(input.performance.ctr * 100).toFixed(2)}%\n`;
  prompt += `- Conversion Rate: ${(input.performance.conversion_rate * 100).toFixed(2)}%\n`;
  prompt += `- Total Spend: $${input.performance.total_spend.toFixed(2)}\n`;
  prompt += `- Total Revenue: $${input.performance.total_revenue.toFixed(2)}\n`;
  prompt += `- Active Campaigns: ${input.performance.active_campaigns}\n\n`;

  if (input.market_conditions) {
    prompt += `### Market Conditions\n`;
    prompt += `- Seasonality: ${input.market_conditions.seasonality}\n`;
    prompt += `- Competition: ${input.market_conditions.competition_level}\n`;
    prompt += `- Estimated CPM: $${input.market_conditions.estimated_cpm.toFixed(2)}\n`;
    if (input.market_conditions.trending_topics?.length) {
      prompt += `- Trending: ${input.market_conditions.trending_topics.join(', ')}\n`;
    }
    prompt += '\n';
  }

  prompt += `### Constraints\n`;
  if (input.constraints.max_budget) {
    prompt += `- Max Budget: $${input.constraints.max_budget}\n`;
  }
  if (input.constraints.max_daily_spend) {
    prompt += `- Max Daily Spend: $${input.constraints.max_daily_spend}\n`;
  }
  if (input.constraints.min_roas) {
    prompt += `- Minimum ROAS: ${input.constraints.min_roas}x\n`;
  }
  if (input.constraints.max_cpa) {
    prompt += `- Maximum CPA: $${input.constraints.max_cpa}\n`;
  }
  if (input.constraints.time_limit_days) {
    prompt += `- Time Limit: ${input.constraints.time_limit_days} days\n`;
  }
  prompt += '\n';

  if (input.business_context) {
    prompt += `### Business Context\n${input.business_context}\n\n`;
  }

  if (input.previous_goals?.length) {
    prompt += `### Previous Goals\n`;
    for (const goal of input.previous_goals) {
      prompt += `- ${goal.type}: ${goal.description} (Status: ${goal.status})\n`;
    }
    prompt += '\n';
  }

  prompt += `Based on this data, generate strategic advertising goals for this store. `;
  prompt += `Focus on the biggest opportunities for improvement while respecting constraints.`;

  return prompt;
}

function getCurrentValue(metric: string, performance: PerformanceSnapshot): number {
  const metricMap: Record<string, number> = {
    'roas': performance.roas,
    'cpa': performance.cpa,
    'ctr': performance.ctr,
    'conversion_rate': performance.conversion_rate,
    'revenue': performance.total_revenue,
    'spend': performance.total_spend
  };
  return metricMap[metric.toLowerCase()] || 0;
}

// ============ Goal Evaluation ============

export interface GoalProgress {
  goal: Goal;
  current_value: number;
  progress_percentage: number;
  trend: 'improving' | 'stable' | 'declining';
  on_track: boolean;
  days_remaining?: number;
  projected_completion?: string;
}

export async function evaluateGoalProgress(
  goal: Goal,
  currentPerformance: PerformanceSnapshot
): Promise<GoalProgress> {
  const currentValue = getCurrentValue(goal.target_metric, currentPerformance);
  const startValue = goal.current_value || currentValue;
  const targetValue = goal.target_value;

  // Calculate progress (handle both increase and decrease targets)
  let progressPercentage: number;
  if (targetValue > startValue) {
    // Increasing metric (e.g., ROAS from 2 to 3)
    progressPercentage = ((currentValue - startValue) / (targetValue - startValue)) * 100;
  } else {
    // Decreasing metric (e.g., CPA from 50 to 30)
    progressPercentage = ((startValue - currentValue) / (startValue - targetValue)) * 100;
  }
  progressPercentage = Math.max(0, Math.min(100, progressPercentage));

  // Determine trend (would need historical data for real implementation)
  const trend: 'improving' | 'stable' | 'declining' =
    progressPercentage > 50 ? 'improving' :
    progressPercentage > 25 ? 'stable' : 'declining';

  // Calculate days remaining
  let daysRemaining: number | undefined;
  if (goal.deadline) {
    const deadlineDate = new Date(goal.deadline);
    const now = new Date();
    daysRemaining = Math.ceil((deadlineDate.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
  }

  // Determine if on track
  const onTrack = progressPercentage >= 50 || (daysRemaining && daysRemaining > 7 && progressPercentage > 20);

  return {
    goal,
    current_value: currentValue,
    progress_percentage: progressPercentage,
    trend,
    on_track: onTrack,
    days_remaining: daysRemaining
  };
}

// ============ Goal Adjustment ============

export async function suggestGoalAdjustments(
  goal: Goal,
  progress: GoalProgress,
  constraints: GoalConstraints
): Promise<{
  should_adjust: boolean;
  new_target?: number;
  new_deadline?: string;
  reasoning: string;
}> {
  if (progress.on_track) {
    return {
      should_adjust: false,
      reasoning: 'Goal is on track, no adjustment needed'
    };
  }

  const prompt = `
A goal is off track and may need adjustment.

## Goal
- Type: ${goal.type}
- Description: ${goal.description}
- Target: ${goal.target_metric} = ${goal.target_value}
- Current: ${progress.current_value}
- Progress: ${progress.progress_percentage.toFixed(1)}%
- Trend: ${progress.trend}
- Days Remaining: ${progress.days_remaining || 'No deadline'}

## Constraints
${JSON.stringify(constraints, null, 2)}

Should this goal be:
1. Kept as-is (push harder)
2. Target adjusted (make more achievable)
3. Deadline extended
4. Abandoned (focus elsewhere)

Return JSON with: { should_adjust: boolean, new_target?: number, new_deadline?: string, reasoning: string }
`;

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 1024,
    messages: [{ role: 'user', content: prompt }]
  });

  const content = response.content[0];
  if (content.type !== 'text') {
    return { should_adjust: false, reasoning: 'Failed to get adjustment recommendation' };
  }

  const jsonMatch = content.text.match(/\{[\s\S]*\}/);
  if (!jsonMatch) {
    return { should_adjust: false, reasoning: 'Failed to parse adjustment recommendation' };
  }

  return JSON.parse(jsonMatch[0]);
}

// ============ Message Handlers ============

export function createGoalMessage(
  goals: Goal[],
  correlationId?: string
): AgentMessage {
  return {
    id: `msg-${Date.now()}`,
    type: 'goal_response',
    from: GOAL_AGENT,
    to: 'planner',
    timestamp: new Date().toISOString(),
    payload: { goals },
    correlation_id: correlationId
  };
}

export async function handleGoalRequest(
  message: AgentMessage
): Promise<AgentMessage> {
  const { store_id, store_name, performance, market_conditions, constraints, business_context } = message.payload;

  try {
    const goals = await generateGoals({
      store_id,
      store_name,
      performance,
      market_conditions,
      constraints,
      business_context
    });

    return createGoalMessage(goals, message.id);
  } catch (error) {
    return {
      id: `msg-${Date.now()}`,
      type: 'error',
      from: GOAL_AGENT,
      to: message.from.role,
      timestamp: new Date().toISOString(),
      payload: { error: (error as Error).message },
      correlation_id: message.id
    };
  }
}
