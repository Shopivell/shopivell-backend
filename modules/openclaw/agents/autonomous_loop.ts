/**
 * Autonomous Loop
 * Orchestrates the multi-agent system for goal-driven ad management
 *
 * Flow:
 * 1. Goal Agent sets goals based on store performance
 * 2. Planner Agent creates execution plans for each goal
 * 3. Executor Agent runs tasks from plans
 * 4. Evaluator assesses progress and adjusts
 * 5. Loop continues until goals achieved or constraints hit
 */

import {
  AutonomousConfig,
  AutonomousSession,
  AgentState,
  AgentMessage,
  Goal,
  ExecutionPlan,
  Evaluation,
  PerformanceSnapshot,
  GoalConstraints
} from './types';

import {
  GOAL_AGENT,
  generateGoals,
  evaluateGoalProgress,
  GoalGenerationInput
} from './goal_agent';

import {
  PLANNER_AGENT,
  generatePlan,
  adjustPlan,
  getNextTasks
} from './planner_agent';

import {
  EXECUTOR_AGENT,
  executePlan,
  PlanExecutionState,
  TaskExecutionResult,
  registerMockSkills
} from './executor_agent';

import Anthropic from '@anthropic-ai/sdk';

const anthropic = new Anthropic();

// ============ Session Management ============

const activeSessions: Map<string, AutonomousSession> = new Map();

export function getSession(sessionId: string): AutonomousSession | undefined {
  return activeSessions.get(sessionId);
}

export function getAllSessions(): AutonomousSession[] {
  return Array.from(activeSessions.values());
}

// ============ Evaluator Agent ============

const EVALUATOR_AGENT = {
  id: 'evaluator-agent-001',
  role: 'evaluator' as const,
  name: 'Progress Evaluator'
};

async function evaluateProgress(
  goal: Goal,
  plan: ExecutionPlan,
  executionState: PlanExecutionState,
  currentPerformance: PerformanceSnapshot
): Promise<Evaluation> {
  const goalProgress = await evaluateGoalProgress(goal, currentPerformance);

  // Determine assessment
  let assessment: Evaluation['assessment'];
  if (goalProgress.progress_percentage >= 100) {
    assessment = 'achieved';
  } else if (goalProgress.progress_percentage >= 70 && goalProgress.on_track) {
    assessment = 'on_track';
  } else if (goalProgress.progress_percentage >= 30) {
    assessment = 'at_risk';
  } else if (executionState.failed_tasks.length > executionState.completed_tasks.length) {
    assessment = 'failed';
  } else {
    assessment = 'off_track';
  }

  // Get AI recommendations
  const recommendations = await getAIRecommendations(goal, goalProgress, executionState);

  return {
    id: `eval-${Date.now()}`,
    goal_id: goal.id,
    plan_id: plan.id,
    timestamp: new Date().toISOString(),
    progress_percentage: goalProgress.progress_percentage,
    metrics: {
      target_metric: goal.target_metric,
      target_value: goal.target_value,
      current_value: goalProgress.current_value,
      trend: goalProgress.trend,
      confidence: calculateConfidence(goalProgress, executionState),
      projected_achievement_date: goalProgress.on_track
        ? estimateCompletionDate(goalProgress)
        : undefined
    },
    assessment,
    recommendations,
    should_continue: assessment !== 'failed' && assessment !== 'achieved',
    should_adjust: assessment === 'off_track' || assessment === 'at_risk'
  };
}

async function getAIRecommendations(
  goal: Goal,
  progress: any,
  executionState: PlanExecutionState
): Promise<Evaluation['recommendations']> {
  const prompt = `
## Goal
${goal.description}
Target: ${goal.target_metric} = ${goal.target_value}
Current: ${progress.current_value}
Progress: ${progress.progress_percentage.toFixed(1)}%

## Execution State
- Completed tasks: ${executionState.completed_tasks.length}
- Failed tasks: ${executionState.failed_tasks.length}
- Total spend: $${executionState.total_spend}

## Recent Task Results
${executionState.completed_tasks.slice(-5).map(r =>
  `- ${r.task.description}: ${r.success ? 'Success' : 'Failed'}`
).join('\n')}

What should we do next? Return JSON array of recommendations:
[{ "type": "scale|reduce|pivot|pause|continue|abandon", "reason": "...", "priority": "critical|high|medium|low" }]
`;

  try {
    const response = await anthropic.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 1024,
      messages: [{ role: 'user', content: prompt }]
    });

    const content = response.content[0];
    if (content.type === 'text') {
      const jsonMatch = content.text.match(/\[[\s\S]*\]/);
      if (jsonMatch) {
        return JSON.parse(jsonMatch[0]);
      }
    }
  } catch (error) {
    console.error('Failed to get AI recommendations:', error);
  }

  // Default recommendation
  return [{
    type: 'continue',
    reason: 'Continue with current plan',
    priority: 'medium'
  }];
}

function calculateConfidence(progress: any, state: PlanExecutionState): number {
  let confidence = 0.5;

  // Adjust based on progress
  if (progress.progress_percentage > 50) confidence += 0.2;
  if (progress.trend === 'improving') confidence += 0.15;
  if (progress.trend === 'declining') confidence -= 0.2;

  // Adjust based on task success rate
  const totalTasks = state.completed_tasks.length + state.failed_tasks.length;
  if (totalTasks > 0) {
    const successRate = state.completed_tasks.length / totalTasks;
    confidence += (successRate - 0.5) * 0.3;
  }

  return Math.max(0, Math.min(1, confidence));
}

function estimateCompletionDate(progress: any): string {
  const daysRemaining = progress.days_remaining || 7;
  const progressPerDay = progress.progress_percentage / 7; // Assume 7 days of history
  const daysNeeded = (100 - progress.progress_percentage) / progressPerDay;

  const completionDate = new Date();
  completionDate.setDate(completionDate.getDate() + Math.ceil(daysNeeded));
  return completionDate.toISOString();
}

// ============ Main Autonomous Loop ============

export interface AutonomousLoopCallbacks {
  onGoalsGenerated?: (goals: Goal[]) => void;
  onPlanCreated?: (goal: Goal, plan: ExecutionPlan) => void;
  onTaskCompleted?: (result: TaskExecutionResult) => void;
  onEvaluation?: (evaluation: Evaluation) => void;
  onGoalAchieved?: (goal: Goal) => void;
  onGoalFailed?: (goal: Goal, reason: string) => void;
  onSessionComplete?: (session: AutonomousSession) => void;
  onError?: (error: Error) => void;
}

export async function startAutonomousSession(
  config: AutonomousConfig,
  performance: PerformanceSnapshot,
  callbacks?: AutonomousLoopCallbacks
): Promise<AutonomousSession> {
  // Initialize session
  const session: AutonomousSession = {
    id: `session-${Date.now()}`,
    config,
    state: 'initializing',
    agents: [
      { agent: GOAL_AGENT, active_goals: [], active_plans: [], pending_tasks: [], completed_tasks: [], message_history: [], started_at: new Date().toISOString(), last_activity: new Date().toISOString() },
      { agent: PLANNER_AGENT, active_goals: [], active_plans: [], pending_tasks: [], completed_tasks: [], message_history: [], started_at: new Date().toISOString(), last_activity: new Date().toISOString() },
      { agent: EXECUTOR_AGENT, active_goals: [], active_plans: [], pending_tasks: [], completed_tasks: [], message_history: [], started_at: new Date().toISOString(), last_activity: new Date().toISOString() },
      { agent: EVALUATOR_AGENT, active_goals: [], active_plans: [], pending_tasks: [], completed_tasks: [], message_history: [], started_at: new Date().toISOString(), last_activity: new Date().toISOString() }
    ],
    goals_achieved: [],
    goals_failed: [],
    total_spend: 0,
    total_revenue: 0,
    started_at: new Date().toISOString(),
    last_checkpoint: new Date().toISOString()
  };

  activeSessions.set(session.id, session);

  // Register mock skills for testing (replace with real skills in production)
  registerMockSkills();

  try {
    // Phase 1: Generate goals
    session.state = 'running';
    let goals: Goal[];

    if (config.initial_goals?.length) {
      goals = config.initial_goals;
    } else if (config.auto_generate_goals) {
      const goalInput: GoalGenerationInput = {
        store_id: config.store_id,
        store_name: `Store ${config.store_id}`,
        performance,
        constraints: {
          max_budget: config.budget_limit,
          max_daily_spend: config.budget_limit / 30,
          time_limit_days: config.time_limit_hours ? config.time_limit_hours / 24 : undefined
        }
      };

      goals = await generateGoals(goalInput);
      callbacks?.onGoalsGenerated?.(goals);
    } else {
      throw new Error('No goals provided and auto_generate_goals is false');
    }

    // Update agent state
    session.agents[0].active_goals = goals;

    // Phase 2: Process each goal
    for (const goal of goals) {
      if (session.state !== 'running') break;

      // Create plan for goal
      const plan = await generatePlan({
        goal,
        available_budget: config.budget_limit - session.total_spend
      });

      callbacks?.onPlanCreated?.(goal, plan);
      session.agents[1].active_plans.push(plan);

      // Execute plan
      const executionState = await executePlan(
        plan,
        (result) => {
          callbacks?.onTaskCompleted?.(result);
          if (result.result?.spend) {
            session.total_spend += result.result.spend;
          }
          if (result.result?.revenue) {
            session.total_revenue += result.result.revenue;
          }
        },
        undefined,
        () => session.state !== 'running' || session.total_spend >= config.budget_limit
      );

      // Evaluate progress
      const evaluation = await evaluateProgress(goal, plan, executionState, performance);
      callbacks?.onEvaluation?.(evaluation);

      // Update goal status based on evaluation
      if (evaluation.assessment === 'achieved') {
        goal.status = 'achieved';
        session.goals_achieved.push(goal);
        callbacks?.onGoalAchieved?.(goal);
      } else if (evaluation.assessment === 'failed' || !evaluation.should_continue) {
        goal.status = 'failed';
        session.goals_failed.push(goal);
        callbacks?.onGoalFailed?.(goal, 'Plan execution failed or goal unreachable');
      } else if (evaluation.should_adjust) {
        // Adjust plan and continue (simplified - full implementation would loop)
        const feedback = evaluation.recommendations
          .map(r => `${r.type}: ${r.reason}`)
          .join('; ');

        const adjustedPlan = await adjustPlan(
          plan,
          feedback,
          executionState.completed_tasks.map(r => r.task),
          executionState.failed_tasks.map(r => r.task)
        );

        // Continue with adjusted plan...
        // (In full implementation, this would be a recursive loop)
      }

      // Check budget limit
      if (session.total_spend >= config.budget_limit) {
        session.state = 'completed';
        break;
      }

      // Check time limit
      if (config.time_limit_hours) {
        const elapsedHours = (Date.now() - new Date(session.started_at).getTime()) / (1000 * 60 * 60);
        if (elapsedHours >= config.time_limit_hours) {
          session.state = 'completed';
          break;
        }
      }

      session.last_checkpoint = new Date().toISOString();
    }

    // Session complete
    if (session.state === 'running') {
      session.state = 'completed';
    }
    session.ended_at = new Date().toISOString();
    callbacks?.onSessionComplete?.(session);

  } catch (error) {
    session.state = 'failed';
    session.ended_at = new Date().toISOString();
    callbacks?.onError?.(error as Error);
  }

  return session;
}

export function pauseSession(sessionId: string): boolean {
  const session = activeSessions.get(sessionId);
  if (session && session.state === 'running') {
    session.state = 'paused';
    return true;
  }
  return false;
}

export function resumeSession(sessionId: string): boolean {
  const session = activeSessions.get(sessionId);
  if (session && session.state === 'paused') {
    session.state = 'running';
    // Would need to restart the loop from last checkpoint
    return true;
  }
  return false;
}

export function stopSession(sessionId: string): boolean {
  const session = activeSessions.get(sessionId);
  if (session) {
    session.state = 'completed';
    session.ended_at = new Date().toISOString();
    return true;
  }
  return false;
}

// ============ Continuous Monitoring Mode ============

export async function startContinuousMonitoring(
  config: AutonomousConfig,
  getPerformance: () => Promise<PerformanceSnapshot>,
  callbacks?: AutonomousLoopCallbacks
): Promise<string> {
  const sessionId = `continuous-${Date.now()}`;

  const session: AutonomousSession = {
    id: sessionId,
    config,
    state: 'running',
    agents: [],
    goals_achieved: [],
    goals_failed: [],
    total_spend: 0,
    total_revenue: 0,
    started_at: new Date().toISOString(),
    last_checkpoint: new Date().toISOString()
  };

  activeSessions.set(sessionId, session);

  // Run monitoring loop in background
  (async () => {
    while (session.state === 'running') {
      try {
        // Get current performance
        const performance = await getPerformance();

        // Generate/update goals
        if (config.auto_generate_goals) {
          const goals = await generateGoals({
            store_id: config.store_id,
            store_name: `Store ${config.store_id}`,
            performance,
            constraints: {
              max_budget: config.budget_limit - session.total_spend
            }
          });

          callbacks?.onGoalsGenerated?.(goals);

          // Process high-priority goals
          for (const goal of goals.filter(g => g.priority === 'critical' || g.priority === 'high')) {
            if (session.state !== 'running') break;

            const plan = await generatePlan({ goal, available_budget: config.budget_limit - session.total_spend });
            callbacks?.onPlanCreated?.(goal, plan);

            await executePlan(plan, callbacks?.onTaskCompleted);
          }
        }

        session.last_checkpoint = new Date().toISOString();

        // Wait for next evaluation interval
        await new Promise(resolve =>
          setTimeout(resolve, config.evaluation_interval_minutes * 60 * 1000)
        );

      } catch (error) {
        callbacks?.onError?.(error as Error);
        if (config.pause_on_error) {
          session.state = 'paused';
        }
      }
    }
  })();

  return sessionId;
}

// ============ Export Types ============

export type { AutonomousConfig, AutonomousSession, AutonomousLoopCallbacks };
