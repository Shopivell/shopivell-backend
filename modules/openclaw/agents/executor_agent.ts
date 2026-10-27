/**
 * Executor Agent
 * Executes tasks from plans by calling the appropriate skills
 * Handles retries, errors, and reports results back
 */

import {
  AgentIdentity,
  AgentMessage,
  Task,
  TaskStatus,
  ExecutionPlan
} from './types';

// ============ Executor Agent Identity ============

export const EXECUTOR_AGENT: AgentIdentity = {
  id: 'executor-agent-001',
  role: 'executor',
  name: 'Task Executor'
};

// ============ Skill Registry ============

type SkillAction = (params: Record<string, any>) => Promise<any>;

interface SkillRegistry {
  [skillName: string]: {
    [actionName: string]: SkillAction;
  };
}

// This will be populated at runtime with actual skill implementations
let skillRegistry: SkillRegistry = {};

export function registerSkill(skillName: string, actions: Record<string, SkillAction>) {
  skillRegistry[skillName] = actions;
}

export function getRegisteredSkills(): string[] {
  return Object.keys(skillRegistry);
}

// ============ Task Execution ============

export interface TaskExecutionResult {
  task: Task;
  success: boolean;
  result?: any;
  error?: string;
  duration_ms: number;
  retried: boolean;
}

export async function executeTask(task: Task): Promise<TaskExecutionResult> {
  const startTime = Date.now();
  let retried = false;

  // Mark task as in progress
  task.status = 'in_progress';
  task.started_at = new Date().toISOString();

  try {
    // Get the skill and action
    const skill = skillRegistry[task.skill];
    if (!skill) {
      throw new Error(`Skill not found: ${task.skill}`);
    }

    const action = skill[task.action];
    if (!action) {
      throw new Error(`Action not found: ${task.skill}.${task.action}`);
    }

    // Execute with retry logic
    let lastError: Error | null = null;
    let result: any;

    while (task.retry_count <= task.max_retries) {
      try {
        result = await action(task.parameters);
        break; // Success, exit retry loop
      } catch (error) {
        lastError = error as Error;
        task.retry_count++;
        retried = task.retry_count > 1;

        if (task.retry_count > task.max_retries) {
          throw lastError;
        }

        // Exponential backoff
        const backoffMs = Math.min(1000 * Math.pow(2, task.retry_count), 30000);
        await sleep(backoffMs);
      }
    }

    // Success
    task.status = 'completed';
    task.completed_at = new Date().toISOString();
    task.result = result;

    return {
      task,
      success: true,
      result,
      duration_ms: Date.now() - startTime,
      retried
    };

  } catch (error) {
    // Failure
    task.status = 'failed';
    task.completed_at = new Date().toISOString();
    task.error = (error as Error).message;

    return {
      task,
      success: false,
      error: (error as Error).message,
      duration_ms: Date.now() - startTime,
      retried
    };
  }
}

// ============ Batch Execution ============

export interface BatchExecutionResult {
  results: TaskExecutionResult[];
  all_success: boolean;
  total_duration_ms: number;
}

/**
 * Execute multiple tasks in parallel
 */
export async function executeTasksParallel(tasks: Task[]): Promise<BatchExecutionResult> {
  const startTime = Date.now();

  const results = await Promise.all(
    tasks.map(task => executeTask(task))
  );

  return {
    results,
    all_success: results.every(r => r.success),
    total_duration_ms: Date.now() - startTime
  };
}

/**
 * Execute tasks sequentially
 */
export async function executeTasksSequential(tasks: Task[]): Promise<BatchExecutionResult> {
  const startTime = Date.now();
  const results: TaskExecutionResult[] = [];

  for (const task of tasks) {
    const result = await executeTask(task);
    results.push(result);

    // Stop on failure if task is critical
    if (!result.success && !task.parameters.continue_on_failure) {
      break;
    }
  }

  return {
    results,
    all_success: results.every(r => r.success),
    total_duration_ms: Date.now() - startTime
  };
}

// ============ Plan Execution ============

export interface PlanExecutionState {
  plan: ExecutionPlan;
  completed_tasks: TaskExecutionResult[];
  failed_tasks: TaskExecutionResult[];
  current_tasks: Task[];
  status: 'running' | 'paused' | 'completed' | 'failed';
  started_at: string;
  last_update: string;
  total_spend: number;
}

export async function executePlan(
  plan: ExecutionPlan,
  onTaskComplete?: (result: TaskExecutionResult) => void,
  onPlanProgress?: (state: PlanExecutionState) => void,
  shouldPause?: () => boolean
): Promise<PlanExecutionState> {
  const state: PlanExecutionState = {
    plan,
    completed_tasks: [],
    failed_tasks: [],
    current_tasks: [],
    status: 'running',
    started_at: new Date().toISOString(),
    last_update: new Date().toISOString(),
    total_spend: 0
  };

  while (state.status === 'running') {
    // Check if we should pause
    if (shouldPause?.()) {
      state.status = 'paused';
      break;
    }

    // Get next tasks that are ready to execute
    const nextTasks = getReadyTasks(plan, state.completed_tasks.map(r => r.task));

    if (nextTasks.length === 0) {
      // Check if all tasks are done
      const allCompleted = plan.tasks.every(
        t => t.status === 'completed' || t.status === 'skipped'
      );
      const anyFailed = plan.tasks.some(t => t.status === 'failed');

      if (allCompleted) {
        state.status = 'completed';
      } else if (anyFailed) {
        state.status = 'failed';
      }
      break;
    }

    state.current_tasks = nextTasks;
    state.last_update = new Date().toISOString();
    onPlanProgress?.(state);

    // Check if tasks are in a parallel group
    const inParallelGroup = plan.parallel_groups.some(
      group => nextTasks.some(t => group.includes(t.id))
    );

    // Execute tasks
    const batchResult = inParallelGroup
      ? await executeTasksParallel(nextTasks)
      : await executeTasksSequential(nextTasks);

    // Process results
    for (const result of batchResult.results) {
      if (result.success) {
        state.completed_tasks.push(result);

        // Track spend if result includes it
        if (result.result?.spend) {
          state.total_spend += result.result.spend;
        }
      } else {
        state.failed_tasks.push(result);
      }

      onTaskComplete?.(result);
    }

    state.current_tasks = [];
    state.last_update = new Date().toISOString();
    onPlanProgress?.(state);

    // If critical task failed, stop execution
    if (!batchResult.all_success) {
      const criticalFailed = batchResult.results.some(
        r => !r.success && r.task.parameters.critical
      );
      if (criticalFailed) {
        state.status = 'failed';
        break;
      }
    }
  }

  return state;
}

function getReadyTasks(plan: ExecutionPlan, completedTasks: Task[]): Task[] {
  const completedIds = new Set(completedTasks.map(t => t.id));

  return plan.tasks.filter(task => {
    // Skip already completed or failed tasks
    if (task.status !== 'pending') {
      return false;
    }

    // Check all dependencies are met
    return task.dependencies.every(dep => completedIds.has(dep));
  });
}

// ============ Message Handlers ============

export function createTaskResultMessage(
  result: TaskExecutionResult,
  correlationId?: string
): AgentMessage {
  return {
    id: `msg-${Date.now()}`,
    type: 'task_result',
    from: EXECUTOR_AGENT,
    to: 'evaluator',
    timestamp: new Date().toISOString(),
    payload: {
      task_id: result.task.id,
      success: result.success,
      result: result.result,
      error: result.error,
      duration_ms: result.duration_ms
    },
    correlation_id: correlationId
  };
}

export async function handleTaskAssignment(
  message: AgentMessage
): Promise<AgentMessage> {
  const { task } = message.payload;

  const result = await executeTask(task);

  return createTaskResultMessage(result, message.id);
}

// ============ Utilities ============

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ============ Mock Skills for Testing ============

export function registerMockSkills() {
  registerSkill('ad-creator', {
    research_market: async (params) => {
      await sleep(1000);
      return {
        market_size: '$1.5B',
        competitors: ['Competitor A', 'Competitor B'],
        trending_topics: ['Summer sales', 'Back to school'],
        recommended_angles: ['Value for money', 'Premium quality']
      };
    },
    analyze_product: async (params) => {
      await sleep(500);
      return {
        unique_selling_points: ['Fast delivery', 'Quality materials'],
        target_audience: 'Young professionals 25-34',
        pain_points_addressed: ['Time savings', 'Convenience']
      };
    },
    generate_angles: async (params) => {
      await sleep(800);
      return {
        angles: [
          { name: 'Value', hook: 'Save more today', target_emotion: 'relief' },
          { name: 'Premium', hook: 'You deserve the best', target_emotion: 'aspiration' }
        ]
      };
    },
    generate_ad_copy: async (params) => {
      await sleep(700);
      return {
        variations: [
          { headline: 'Shop Now & Save', primary_text: 'Limited time offer...' },
          { headline: 'Premium Quality', primary_text: 'Experience luxury...' }
        ]
      };
    },
    generate_image: async (params) => {
      await sleep(2000);
      return {
        image_url: 'https://example.com/generated-image.jpg',
        prompt_used: 'Professional product photo...'
      };
    },
    generate_full_campaign: async (params) => {
      await sleep(3000);
      return {
        product_analysis: {},
        market_research: {},
        angles: [],
        ad_set: { name: 'Generated Campaign', ads: [], recommended_budget: 50 },
        ready_for_launch: true
      };
    }
  });

  registerSkill('zernio-ads', {
    create_campaign: async (params) => {
      await sleep(1500);
      return {
        campaign_id: `campaign_${Date.now()}`,
        adset_id: `adset_${Date.now()}`,
        ad_id: `ad_${Date.now()}`,
        status: 'ACTIVE'
      };
    },
    get_insights: async (params) => {
      await sleep(500);
      return {
        spend: 50,
        impressions: 10000,
        clicks: 250,
        ctr: 2.5,
        conversions: 10,
        roas: 2.5,
        cpa: 5
      };
    },
    get_all_store_insights: async (params) => {
      await sleep(800);
      return {
        campaigns: [
          { id: 'camp1', name: 'Campaign 1', spend: 100, roas: 3 },
          { id: 'camp2', name: 'Campaign 2', spend: 50, roas: 2 }
        ]
      };
    },
    pause_ad: async (params) => {
      await sleep(300);
      return { success: true };
    },
    scale_budget: async (params) => {
      await sleep(300);
      return { success: true, old_budget: 50, new_budget: 60 };
    },
    create_lookalike_audience: async (params) => {
      await sleep(1000);
      return { audience_id: `audience_${Date.now()}` };
    },
    send_lead_event: async (params) => {
      await sleep(200);
      return { events_received: 1, fbtrace_id: 'trace123' };
    }
  });

  registerSkill('optimizer', {
    run_optimization_cycle: async (params) => {
      await sleep(2000);
      return {
        actions_taken: [
          { campaign: 'Campaign 1', action: 'scale_up', details: '+20% budget' }
        ]
      };
    },
    check_creative_fatigue: async (params) => {
      await sleep(500);
      return { fatigued: false, frequency: 2.1 };
    },
    get_recommendations: async (params) => {
      await sleep(1000);
      return {
        recommendations: [
          { type: 'scale', campaign: 'Campaign 1', reason: 'High ROAS' },
          { type: 'refresh', campaign: 'Campaign 2', reason: 'Creative fatigue' }
        ]
      };
    }
  });
}
