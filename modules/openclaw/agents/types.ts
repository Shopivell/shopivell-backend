/**
 * Multi-Agent System Types
 * Defines the communication protocol between autonomous agents
 */

// ============ Agent Identity ============

export type AgentRole = 'goal_setter' | 'planner' | 'executor' | 'evaluator' | 'optimizer';

export interface AgentIdentity {
  id: string;
  role: AgentRole;
  name: string;
}

// ============ Message Protocol ============

export type MessageType =
  | 'goal_request'      // Ask goal agent to set goals
  | 'goal_response'     // Goal agent returns goals
  | 'plan_request'      // Ask planner to create plan
  | 'plan_response'     // Planner returns execution plan
  | 'task_assignment'   // Assign task to executor
  | 'task_result'       // Executor reports result
  | 'evaluation_request'// Ask evaluator to assess progress
  | 'evaluation_response'// Evaluator returns assessment
  | 'adjustment'        // Request strategy adjustment
  | 'completion'        // Goal achieved or abandoned
  | 'error';            // Error occurred

export interface AgentMessage {
  id: string;
  type: MessageType;
  from: AgentIdentity;
  to: AgentRole | 'broadcast';
  timestamp: string;
  payload: any;
  correlation_id?: string;  // Links related messages
  parent_id?: string;       // For threading
}

// ============ Goals ============

export type GoalType =
  | 'maximize_roas'
  | 'minimize_cpa'
  | 'increase_conversions'
  | 'grow_audience'
  | 'reduce_cac'
  | 'improve_lead_quality'
  | 'scale_revenue'
  | 'brand_awareness';

export type GoalPriority = 'critical' | 'high' | 'medium' | 'low';

export type GoalStatus = 'pending' | 'active' | 'achieved' | 'failed' | 'abandoned';

export interface Goal {
  id: string;
  type: GoalType;
  description: string;
  target_metric: string;
  target_value: number;
  current_value?: number;
  deadline?: string;
  priority: GoalPriority;
  status: GoalStatus;
  constraints: GoalConstraints;
  context: GoalContext;
  created_at: string;
  updated_at: string;
}

export interface GoalConstraints {
  max_budget?: number;
  max_daily_spend?: number;
  min_roas?: number;
  max_cpa?: number;
  brand_voice?: 'professional' | 'casual' | 'playful' | 'luxury';
  excluded_audiences?: string[];
  geographic_focus?: string[];
  time_limit_days?: number;
}

export interface GoalContext {
  store_id: string;
  store_name?: string;
  product_ids?: string[];
  campaign_ids?: string[];
  current_performance?: PerformanceSnapshot;
  market_conditions?: MarketConditions;
}

export interface PerformanceSnapshot {
  roas: number;
  cpa: number;
  ctr: number;
  conversion_rate: number;
  total_spend: number;
  total_revenue: number;
  active_campaigns: number;
  date_range: string;
}

export interface MarketConditions {
  seasonality: 'peak' | 'normal' | 'low';
  competition_level: 'high' | 'medium' | 'low';
  trending_topics?: string[];
  estimated_cpm: number;
}

// ============ Plans & Tasks ============

export type TaskType =
  | 'research_market'
  | 'analyze_competitors'
  | 'generate_campaign'
  | 'create_ad_variations'
  | 'launch_campaign'
  | 'pause_campaign'
  | 'scale_budget'
  | 'kill_underperformer'
  | 'refresh_creative'
  | 'adjust_targeting'
  | 'create_lookalike'
  | 'send_conversion_event'
  | 'generate_report'
  | 'wait_and_monitor';

export type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped';

export interface Task {
  id: string;
  type: TaskType;
  description: string;
  skill: string;           // Which skill to use
  action: string;          // Which action on the skill
  parameters: Record<string, any>;
  dependencies: string[];  // Task IDs that must complete first
  status: TaskStatus;
  result?: any;
  error?: string;
  started_at?: string;
  completed_at?: string;
  retry_count: number;
  max_retries: number;
}

export interface ExecutionPlan {
  id: string;
  goal_id: string;
  description: string;
  tasks: Task[];
  parallel_groups: string[][];  // Groups of task IDs that can run in parallel
  estimated_duration_hours: number;
  estimated_cost: number;
  success_criteria: SuccessCriteria[];
  fallback_strategy?: string;
  created_at: string;
}

export interface SuccessCriteria {
  metric: string;
  operator: 'gt' | 'gte' | 'lt' | 'lte' | 'eq';
  value: number;
  weight: number;  // For composite scoring
}

// ============ Evaluation ============

export interface Evaluation {
  id: string;
  goal_id: string;
  plan_id: string;
  timestamp: string;
  progress_percentage: number;
  metrics: EvaluationMetrics;
  assessment: 'on_track' | 'at_risk' | 'off_track' | 'achieved' | 'failed';
  recommendations: Recommendation[];
  should_continue: boolean;
  should_adjust: boolean;
}

export interface EvaluationMetrics {
  target_metric: string;
  target_value: number;
  current_value: number;
  trend: 'improving' | 'stable' | 'declining';
  confidence: number;
  projected_achievement_date?: string;
}

export interface Recommendation {
  type: 'scale' | 'reduce' | 'pivot' | 'pause' | 'continue' | 'abandon';
  reason: string;
  suggested_action?: Task;
  priority: GoalPriority;
}

// ============ Agent State ============

export interface AgentState {
  agent: AgentIdentity;
  active_goals: Goal[];
  active_plans: ExecutionPlan[];
  pending_tasks: Task[];
  completed_tasks: Task[];
  message_history: AgentMessage[];
  last_evaluation?: Evaluation;
  started_at: string;
  last_activity: string;
}

// ============ Autonomous Loop ============

export interface AutonomousConfig {
  store_id: string;
  initial_goals?: Goal[];
  auto_generate_goals: boolean;
  evaluation_interval_minutes: number;
  max_concurrent_tasks: number;
  budget_limit: number;
  time_limit_hours?: number;
  notification_webhook?: string;
  pause_on_error: boolean;
}

export interface AutonomousSession {
  id: string;
  config: AutonomousConfig;
  state: 'initializing' | 'running' | 'paused' | 'completed' | 'failed';
  agents: AgentState[];
  goals_achieved: Goal[];
  goals_failed: Goal[];
  total_spend: number;
  total_revenue: number;
  started_at: string;
  last_checkpoint: string;
  ended_at?: string;
}
