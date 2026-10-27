/**
 * OpenClaw Multi-Agent System
 *
 * A goal-driven autonomous advertising system where:
 * - Goal Agent analyzes performance and sets strategic goals
 * - Planner Agent decomposes goals into executable tasks
 * - Executor Agent runs tasks using available skills
 * - Evaluator assesses progress and triggers adjustments
 *
 * Usage:
 *   import { startAutonomousSession } from './agents';
 *
 *   const session = await startAutonomousSession({
 *     store_id: 'store_123',
 *     auto_generate_goals: true,
 *     budget_limit: 500,
 *     evaluation_interval_minutes: 60
 *   }, currentPerformance);
 */

// Types
export * from './types';

// Agents
export { GOAL_AGENT, generateGoals, evaluateGoalProgress, suggestGoalAdjustments } from './goal_agent';
export { PLANNER_AGENT, generatePlan, adjustPlan, getNextTasks } from './planner_agent';
export { EXECUTOR_AGENT, executeTask, executePlan, registerSkill, registerMockSkills } from './executor_agent';

// Autonomous Loop
export {
  startAutonomousSession,
  startContinuousMonitoring,
  pauseSession,
  resumeSession,
  stopSession,
  getSession,
  getAllSessions
} from './autonomous_loop';

// Re-export commonly used types
export type {
  Goal,
  GoalType,
  GoalConstraints,
  ExecutionPlan,
  Task,
  TaskType,
  AutonomousConfig,
  AutonomousSession,
  PerformanceSnapshot,
  Evaluation
} from './types';
