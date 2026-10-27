/**
 * Planner Agent
 * Takes goals from Goal Agent and creates executable task plans
 * Decomposes high-level goals into specific skill actions
 */

import Anthropic from '@anthropic-ai/sdk';
import {
  AgentIdentity,
  AgentMessage,
  Goal,
  Task,
  TaskType,
  ExecutionPlan,
  SuccessCriteria
} from './types';

const anthropic = new Anthropic();

// ============ Planner Agent Identity ============

export const PLANNER_AGENT: AgentIdentity = {
  id: 'planner-agent-001',
  role: 'planner',
  name: 'Strategic Planner'
};

// ============ Available Skills & Actions ============

const AVAILABLE_SKILLS = {
  'ad-creator': {
    description: 'AI-powered ad creation and market research',
    actions: {
      'research_market': {
        description: 'Analyze market and competitors',
        parameters: ['product_name', 'product_description', 'niche', 'target_country']
      },
      'analyze_product': {
        description: 'Extract marketing info from product',
        parameters: ['product_data']
      },
      'generate_angles': {
        description: 'Generate creative angles for campaign',
        parameters: ['product_data', 'market_data', 'campaign_goal', 'brand_voice']
      },
      'generate_ad_copy': {
        description: 'Generate ad copy variations',
        parameters: ['angle', 'product_data', 'format', 'variations']
      },
      'generate_image': {
        description: 'Generate ad image with GPT-Image-2.5',
        parameters: ['product_name', 'product_description', 'style', 'dimensions', 'brand_colors']
      },
      'generate_full_campaign': {
        description: 'One-click full campaign generation',
        parameters: ['product_name', 'product_description', 'store_name', 'campaign_goal', 'budget']
      }
    }
  },
  'zernio-ads': {
    description: 'Meta Ads management via Zernio API',
    actions: {
      'create_campaign': {
        description: 'Create Meta ad campaign',
        parameters: ['profile_id', 'ad_account_id', 'name', 'goal', 'budget_amount', 'targeting', 'creative']
      },
      'create_ctwa_campaign': {
        description: 'Create Click-to-WhatsApp campaign',
        parameters: ['profile_id', 'whatsapp_number', 'budget_amount', 'targeting', 'creative']
      },
      'get_insights': {
        description: 'Get performance metrics',
        parameters: ['ad_id', 'date_preset', 'breakdowns']
      },
      'get_all_store_insights': {
        description: 'Get all campaign performance',
        parameters: ['profile_id', 'date_preset']
      },
      'pause_ad': {
        description: 'Pause underperforming ad',
        parameters: ['ad_id', 'reason']
      },
      'scale_budget': {
        description: 'Increase budget for winners',
        parameters: ['ad_id', 'percentage', 'max_budget']
      },
      'create_lookalike_audience': {
        description: 'Create lookalike from seed audience',
        parameters: ['profile_id', 'source_audience_id', 'country', 'ratio']
      },
      'send_lead_event': {
        description: 'Send lead scoring event to Meta',
        parameters: ['profile_id', 'pixel_id', 'phone', 'lead_score', 'lead_quality']
      }
    }
  },
  'optimizer': {
    description: '24/7 autonomous campaign monitoring',
    actions: {
      'run_optimization_cycle': {
        description: 'Run one optimization cycle',
        parameters: ['store_id']
      },
      'check_creative_fatigue': {
        description: 'Check for creative fatigue signals',
        parameters: ['campaign_id']
      },
      'get_recommendations': {
        description: 'Get AI recommendations for campaigns',
        parameters: ['store_id']
      }
    }
  }
};

// ============ System Prompt ============

const PLANNER_PROMPT = `You are a Strategic Advertising Planner that creates detailed execution plans to achieve advertising goals.

## Your Role
Given a goal (e.g., "maximize ROAS to 3x"), decompose it into specific tasks that use available skills.

## Available Skills
${JSON.stringify(AVAILABLE_SKILLS, null, 2)}

## Task Types You Can Create
- research_market: Understand the market before creating campaigns
- analyze_competitors: Study competitor ads and positioning
- generate_campaign: Create a new ad campaign
- create_ad_variations: Create A/B test variations
- launch_campaign: Push campaign to Meta
- pause_campaign: Stop underperforming campaign
- scale_budget: Increase budget on winners
- kill_underperformer: Cut budget or pause losers
- refresh_creative: Create new creative for fatigued ads
- adjust_targeting: Modify audience targeting
- create_lookalike: Build lookalike audience
- send_conversion_event: Track conversions for optimization
- generate_report: Create performance report
- wait_and_monitor: Wait for data before next action

## Output Format
Return JSON with this structure:
{
  "description": "Brief plan description",
  "tasks": [
    {
      "type": "task_type",
      "description": "What this task does",
      "skill": "skill_name",
      "action": "action_name",
      "parameters": { ... },
      "dependencies": ["task_id_1"],  // Tasks that must complete first
      "retry_count": 0,
      "max_retries": 3
    }
  ],
  "parallel_groups": [["task_1", "task_2"], ["task_3"]],  // Groups that can run in parallel
  "estimated_duration_hours": 24,
  "estimated_cost": 50,
  "success_criteria": [
    { "metric": "roas", "operator": "gte", "value": 3, "weight": 1 }
  ],
  "fallback_strategy": "If primary approach fails, try..."
}

## Planning Rules
1. Start with research/analysis before creating campaigns
2. Create multiple ad variations for testing
3. Include monitoring tasks to evaluate performance
4. Plan for iteration (refresh, scale, kill decisions)
5. Consider budget constraints
6. Include checkpoints to evaluate and adjust
7. Maximum 15 tasks per plan (break into phases if needed)
`;

// ============ Plan Generation ============

export interface PlanGenerationInput {
  goal: Goal;
  available_budget: number;
  existing_campaigns?: any[];
  previous_results?: any[];
}

export async function generatePlan(input: PlanGenerationInput): Promise<ExecutionPlan> {
  const prompt = buildPlanPrompt(input);

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 8192,
    system: PLANNER_PROMPT,
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
  const jsonMatch = content.text.match(/\{[\s\S]*\}/);
  if (!jsonMatch) {
    throw new Error('Failed to parse plan from response');
  }

  const planData = JSON.parse(jsonMatch[0]);

  // Transform to ExecutionPlan
  const plan: ExecutionPlan = {
    id: `plan-${Date.now()}`,
    goal_id: input.goal.id,
    description: planData.description,
    tasks: planData.tasks.map((t: any, index: number) => ({
      id: `task-${Date.now()}-${index}`,
      type: t.type as TaskType,
      description: t.description,
      skill: t.skill,
      action: t.action,
      parameters: t.parameters || {},
      dependencies: t.dependencies || [],
      status: 'pending',
      retry_count: 0,
      max_retries: t.max_retries || 3
    })),
    parallel_groups: planData.parallel_groups || [],
    estimated_duration_hours: planData.estimated_duration_hours || 24,
    estimated_cost: planData.estimated_cost || input.available_budget * 0.5,
    success_criteria: planData.success_criteria?.map((c: any) => ({
      metric: c.metric,
      operator: c.operator,
      value: c.value,
      weight: c.weight || 1
    })) || [],
    fallback_strategy: planData.fallback_strategy,
    created_at: new Date().toISOString()
  };

  // Fix task dependencies to use actual task IDs
  const taskIdMap: Record<string, string> = {};
  planData.tasks.forEach((t: any, index: number) => {
    taskIdMap[`task_${index}`] = plan.tasks[index].id;
    taskIdMap[t.id || `task_${index}`] = plan.tasks[index].id;
  });

  plan.tasks.forEach(task => {
    task.dependencies = task.dependencies.map(dep => taskIdMap[dep] || dep);
  });

  // Fix parallel groups to use actual task IDs
  plan.parallel_groups = plan.parallel_groups.map(group =>
    group.map(taskRef => taskIdMap[taskRef] || taskRef)
  );

  return plan;
}

function buildPlanPrompt(input: PlanGenerationInput): string {
  let prompt = `## Goal to Achieve\n`;
  prompt += `- Type: ${input.goal.type}\n`;
  prompt += `- Description: ${input.goal.description}\n`;
  prompt += `- Target: ${input.goal.target_metric} = ${input.goal.target_value}\n`;
  prompt += `- Current: ${input.goal.current_value || 'Unknown'}\n`;
  prompt += `- Priority: ${input.goal.priority}\n`;
  if (input.goal.deadline) {
    prompt += `- Deadline: ${input.goal.deadline}\n`;
  }
  prompt += '\n';

  prompt += `## Constraints\n`;
  prompt += `- Available Budget: $${input.available_budget}\n`;
  if (input.goal.constraints.max_daily_spend) {
    prompt += `- Max Daily Spend: $${input.goal.constraints.max_daily_spend}\n`;
  }
  if (input.goal.constraints.min_roas) {
    prompt += `- Min ROAS: ${input.goal.constraints.min_roas}x\n`;
  }
  if (input.goal.constraints.max_cpa) {
    prompt += `- Max CPA: $${input.goal.constraints.max_cpa}\n`;
  }
  prompt += '\n';

  prompt += `## Context\n`;
  prompt += `- Store ID: ${input.goal.context.store_id}\n`;
  if (input.goal.context.store_name) {
    prompt += `- Store Name: ${input.goal.context.store_name}\n`;
  }
  if (input.goal.context.current_performance) {
    const perf = input.goal.context.current_performance;
    prompt += `- Current ROAS: ${perf.roas}x\n`;
    prompt += `- Current CPA: $${perf.cpa}\n`;
    prompt += `- Active Campaigns: ${perf.active_campaigns}\n`;
  }
  prompt += '\n';

  if (input.existing_campaigns?.length) {
    prompt += `## Existing Campaigns\n`;
    for (const campaign of input.existing_campaigns) {
      prompt += `- ${campaign.name}: ${campaign.status} (ROAS: ${campaign.roas}x)\n`;
    }
    prompt += '\n';
  }

  if (input.previous_results?.length) {
    prompt += `## Previous Attempts\n`;
    for (const result of input.previous_results) {
      prompt += `- ${result.description}: ${result.outcome}\n`;
    }
    prompt += '\n';
  }

  prompt += `Create a detailed execution plan to achieve this goal. `;
  prompt += `Include research, campaign creation, monitoring, and optimization tasks.`;

  return prompt;
}

// ============ Plan Adjustment ============

export async function adjustPlan(
  plan: ExecutionPlan,
  feedback: string,
  completedTasks: Task[],
  failedTasks: Task[]
): Promise<ExecutionPlan> {
  const prompt = `
## Current Plan
${JSON.stringify(plan, null, 2)}

## Completed Tasks
${completedTasks.map(t => `- ${t.description}: ${JSON.stringify(t.result)}`).join('\n')}

## Failed Tasks
${failedTasks.map(t => `- ${t.description}: ${t.error}`).join('\n')}

## Feedback
${feedback}

Adjust the plan based on this feedback. You can:
1. Remove tasks that are no longer needed
2. Add new tasks based on learnings
3. Modify parameters of remaining tasks
4. Change task order or dependencies

Return the updated plan in the same JSON format.
`;

  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 8192,
    system: PLANNER_PROMPT,
    messages: [
      {
        role: 'user',
        content: prompt
      }
    ]
  });

  const content = response.content[0];
  if (content.type !== 'text') {
    throw new Error('Unexpected response type');
  }

  const jsonMatch = content.text.match(/\{[\s\S]*\}/);
  if (!jsonMatch) {
    throw new Error('Failed to parse adjusted plan');
  }

  const adjustedData = JSON.parse(jsonMatch[0]);

  return {
    ...plan,
    description: adjustedData.description || plan.description,
    tasks: adjustedData.tasks.map((t: any, index: number) => ({
      id: t.id || `task-${Date.now()}-${index}`,
      type: t.type as TaskType,
      description: t.description,
      skill: t.skill,
      action: t.action,
      parameters: t.parameters || {},
      dependencies: t.dependencies || [],
      status: t.status || 'pending',
      retry_count: t.retry_count || 0,
      max_retries: t.max_retries || 3
    })),
    parallel_groups: adjustedData.parallel_groups || plan.parallel_groups,
    fallback_strategy: adjustedData.fallback_strategy || plan.fallback_strategy
  };
}

// ============ Task Prioritization ============

export function getNextTasks(plan: ExecutionPlan): Task[] {
  const completedIds = new Set(
    plan.tasks.filter(t => t.status === 'completed').map(t => t.id)
  );

  const pendingTasks = plan.tasks.filter(t => t.status === 'pending');
  const readyTasks: Task[] = [];

  for (const task of pendingTasks) {
    const allDependenciesMet = task.dependencies.every(dep => completedIds.has(dep));
    if (allDependenciesMet) {
      readyTasks.push(task);
    }
  }

  // Check for parallel groups
  for (const group of plan.parallel_groups) {
    const groupTasks = readyTasks.filter(t => group.includes(t.id));
    if (groupTasks.length > 0) {
      return groupTasks; // Return all tasks in this parallel group
    }
  }

  // If no parallel group, return first ready task
  return readyTasks.slice(0, 1);
}

// ============ Message Handlers ============

export function createPlanMessage(
  plan: ExecutionPlan,
  correlationId?: string
): AgentMessage {
  return {
    id: `msg-${Date.now()}`,
    type: 'plan_response',
    from: PLANNER_AGENT,
    to: 'executor',
    timestamp: new Date().toISOString(),
    payload: { plan },
    correlation_id: correlationId
  };
}

export async function handlePlanRequest(
  message: AgentMessage
): Promise<AgentMessage> {
  const { goal, available_budget, existing_campaigns, previous_results } = message.payload;

  try {
    const plan = await generatePlan({
      goal,
      available_budget,
      existing_campaigns,
      previous_results
    });

    return createPlanMessage(plan, message.id);
  } catch (error) {
    return {
      id: `msg-${Date.now()}`,
      type: 'error',
      from: PLANNER_AGENT,
      to: message.from.role,
      timestamp: new Date().toISOString(),
      payload: { error: (error as Error).message },
      correlation_id: message.id
    };
  }
}
