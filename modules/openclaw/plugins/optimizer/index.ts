import { Plugin, PluginContext } from "@openclaw/sdk";

interface CampaignMetrics {
  id: string;
  name: string;
  type: "standard" | "ctwa";
  spend: number;
  impressions: number;
  clicks: number;
  conversions: number;
  roas: number;
  cpa: number;
  ctr: number;
  frequency: number;
  // CTWA specific
  conversations?: number;
  cost_per_conversation?: number;
  qualified_leads?: number;
  cost_per_qualified_lead?: number;
}

interface StoreTargets {
  roas: number;
  cpa: number;
  cpql?: number; // Cost per qualified lead
}

interface Rule {
  name: string;
  check: (metrics: CampaignMetrics, targets: StoreTargets, history: any) => boolean;
  action: (ctx: PluginContext, campaign: any, metrics: CampaignMetrics) => Promise<RuleResult>;
  cooldown: number; // hours
}

interface RuleResult {
  type: string;
  details: any;
  notification: string;
  priority: "low" | "medium" | "high";
}

const RULES: Rule[] = [
  {
    name: "scale_winner",
    cooldown: 6,
    check: (metrics, targets, history) => {
      const goodDays = history.consecutive_good_days || 0;
      return metrics.roas >= targets.roas * 1.25 && goodDays >= 3;
    },
    action: async (ctx, campaign, metrics) => {
      const newBudget = Math.min(campaign.budget * 1.2, 10000);
      await ctx.skills.zernioAds.scale_budget({
        ad_id: campaign.id,
        percentage: 20,
        max_budget: 10000,
      });
      return {
        type: "budget_increase",
        details: { old_budget: campaign.budget, new_budget: newBudget },
        notification: `✅📈 Winner! "${campaign.name}" ROAS ${(metrics.roas * 100).toFixed(0)}%. Budget: $${campaign.budget} → $${newBudget.toFixed(0)}`,
        priority: "low",
      };
    },
  },
  {
    name: "kill_loser",
    cooldown: 12,
    check: (metrics, targets) => {
      return (
        metrics.cpa > targets.cpa * 2 &&
        metrics.conversions === 0 &&
        metrics.impressions >= 2000
      );
    },
    action: async (ctx, campaign, metrics) => {
      const newBudget = campaign.budget * 0.5;
      await ctx.skills.zernioAds.scale_budget({
        ad_id: campaign.id,
        percentage: -50,
      });
      return {
        type: "budget_decrease",
        details: { old_budget: campaign.budget, new_budget: newBudget },
        notification: `⚠️📉 Underperforming: "${campaign.name}" CPA $${metrics.cpa.toFixed(2)} (target $${(targets.cpa).toFixed(2)}). Budget cut to $${newBudget.toFixed(0)}`,
        priority: "medium",
      };
    },
  },
  {
    name: "pause_no_spend",
    cooldown: 24,
    check: (metrics, targets, history) => {
      const hoursNoSpend = history.hours_no_spend || 0;
      return metrics.spend === 0 && hoursNoSpend >= 24;
    },
    action: async (ctx, campaign) => {
      await ctx.skills.zernioAds.pause_ad({
        ad_id: campaign.id,
        reason: "No spend for 24+ hours",
      });
      return {
        type: "paused",
        details: { reason: "no_spend" },
        notification: `⛔ Paused: "${campaign.name}" - No spend for 24+ hours. Please review.`,
        priority: "high",
      };
    },
  },
  {
    name: "creative_fatigue",
    cooldown: 48,
    check: (metrics, targets, history) => {
      const ctrDecline = history.ctr_decline_percent || 0;
      return metrics.frequency > 3 && ctrDecline >= 30 && history.declining_days >= 3;
    },
    action: async (ctx, campaign) => {
      await ctx.skills.zernioAds.pause_ad({
        ad_id: campaign.id,
        reason: "Creative fatigue detected",
      });
      return {
        type: "creative_fatigue",
        details: { frequency: campaign.frequency },
        notification: `🎨 Creative Fatigue: "${campaign.name}" - Frequency ${campaign.frequency}x, CTR declining. Time for fresh creative!`,
        priority: "medium",
      };
    },
  },
  {
    name: "ctwa_quality_winner",
    cooldown: 6,
    check: (metrics, targets, history) => {
      if (metrics.type !== "ctwa" || !metrics.cost_per_qualified_lead) return false;
      const cpqlTarget = targets.cpql || targets.cpa;
      return metrics.cost_per_qualified_lead < cpqlTarget * 0.7 && history.good_quality_days >= 3;
    },
    action: async (ctx, campaign, metrics) => {
      const newBudget = Math.min(campaign.budget * 1.25, 10000);
      await ctx.skills.zernioAds.scale_budget({
        ad_id: campaign.id,
        percentage: 25,
        max_budget: 10000,
      });
      return {
        type: "ctwa_scale",
        details: { cpql: metrics.cost_per_qualified_lead, new_budget: newBudget },
        notification: `✅💬 Quality Leads! "${campaign.name}" CPQL $${metrics.cost_per_qualified_lead?.toFixed(2)}. Budget: $${campaign.budget} → $${newBudget.toFixed(0)}`,
        priority: "low",
      };
    },
  },
  {
    name: "ctwa_quality_loser",
    cooldown: 12,
    check: (metrics, targets, history) => {
      if (metrics.type !== "ctwa" || !metrics.cost_per_qualified_lead) return false;
      const cpqlTarget = targets.cpql || targets.cpa;
      return metrics.cost_per_qualified_lead > cpqlTarget * 2 && history.bad_quality_days >= 3;
    },
    action: async (ctx, campaign, metrics) => {
      const newBudget = campaign.budget * 0.7;
      await ctx.skills.zernioAds.scale_budget({
        ad_id: campaign.id,
        percentage: -30,
      });
      return {
        type: "ctwa_cut",
        details: { cpql: metrics.cost_per_qualified_lead, new_budget: newBudget },
        notification: `⚠️💬 Low Quality Leads: "${campaign.name}" CPQL $${metrics.cost_per_qualified_lead?.toFixed(2)} (target $${(targets.cpql || targets.cpa).toFixed(2)}). Budget cut to $${newBudget.toFixed(0)}`,
        priority: "medium",
      };
    },
  },
];

async function sendNotification(
  ctx: PluginContext,
  store: any,
  message: string,
  priority: string
) {
  // Send via WhatsApp
  if (store.whatsapp_number) {
    try {
      await ctx.http.post(`${ctx.env.SHOPIVELL_API_URL}/whatsapp/send`, {
        to: store.whatsapp_number,
        message: `🎯 Ad Update: ${store.name}\n\n${message}`,
      });
    } catch (e) {
      ctx.log.error("WhatsApp notification failed", e);
    }
  }

  // Send via Telegram
  if (store.telegram_chat_id) {
    try {
      await ctx.http.post(
        `https://api.telegram.org/bot${ctx.env.TELEGRAM_BOT_TOKEN}/sendMessage`,
        {
          chat_id: store.telegram_chat_id,
          text: `🎯 Ad Update: ${store.name}\n\n${message}`,
          parse_mode: "Markdown",
        }
      );
    } catch (e) {
      ctx.log.error("Telegram notification failed", e);
    }
  }
}

async function getCampaignHistory(ctx: PluginContext, campaignId: string) {
  // Get historical metrics for trend analysis
  const history = await ctx.db.query(
    `SELECT * FROM campaign_history WHERE campaign_id = ? ORDER BY date DESC LIMIT 7`,
    [campaignId]
  );

  if (history.length < 2) {
    return { consecutive_good_days: 0, hours_no_spend: 0, ctr_decline_percent: 0, declining_days: 0 };
  }

  // Calculate consecutive good days (ROAS above target)
  let consecutiveGoodDays = 0;
  for (const day of history) {
    if (day.roas >= day.target_roas * 1.25) {
      consecutiveGoodDays++;
    } else {
      break;
    }
  }

  // Calculate CTR decline
  const latestCTR = history[0]?.ctr || 0;
  const oldestCTR = history[history.length - 1]?.ctr || latestCTR;
  const ctrDecline = oldestCTR > 0 ? ((oldestCTR - latestCTR) / oldestCTR) * 100 : 0;

  // Calculate declining days
  let decliningDays = 0;
  for (let i = 0; i < history.length - 1; i++) {
    if (history[i].ctr < history[i + 1].ctr) {
      decliningDays++;
    } else {
      break;
    }
  }

  return {
    consecutive_good_days: consecutiveGoodDays,
    hours_no_spend: history[0]?.spend === 0 ? 24 : 0, // Simplified
    ctr_decline_percent: ctrDecline,
    declining_days: decliningDays,
    good_quality_days: consecutiveGoodDays, // For CTWA
    bad_quality_days: history.filter((h: any) => h.cpql > h.target_cpql * 2).length,
  };
}

async function canTriggerRule(
  ctx: PluginContext,
  campaignId: string,
  ruleName: string,
  cooldownHours: number
): Promise<boolean> {
  const lastTrigger = await ctx.db.queryOne(
    `SELECT triggered_at FROM rule_triggers
     WHERE campaign_id = ? AND rule_name = ?
     ORDER BY triggered_at DESC LIMIT 1`,
    [campaignId, ruleName]
  );

  if (!lastTrigger) return true;

  const hoursSinceLastTrigger =
    (Date.now() - new Date(lastTrigger.triggered_at).getTime()) / (1000 * 60 * 60);
  return hoursSinceLastTrigger >= cooldownHours;
}

async function recordRuleTrigger(
  ctx: PluginContext,
  campaignId: string,
  ruleName: string,
  result: RuleResult
) {
  await ctx.db.insert("rule_triggers", {
    campaign_id: campaignId,
    rule_name: ruleName,
    result_type: result.type,
    details: JSON.stringify(result.details),
    triggered_at: new Date().toISOString(),
  });
}

export const optimizer: Plugin = {
  name: "optimizer",
  description: "24/7 autonomous ad optimization with automated rules",
  interval: "15m", // Run every 15 minutes

  async run(ctx: PluginContext) {
    ctx.log.info("Optimizer run started");

    // Get all stores with ads enabled
    const stores = await ctx.http.get(`${ctx.env.SHOPIVELL_API_URL}/stores?ads_enabled=true`);

    for (const store of stores.data) {
      try {
        // Get store's Zernio profile
        const profile = await ctx.skills.zernioAds.get_store_profile({
          store_id: store.id,
        });

        if (!profile?.id) continue;

        // Get all active campaigns
        const campaigns = await ctx.skills.zernioAds.list_campaigns({
          profile_id: profile.id,
          status: "active",
        });

        const targets: StoreTargets = {
          roas: store.target_roas || 2.5,
          cpa: store.target_cpa || 10,
          cpql: store.target_cpql || store.target_cpa || 10,
        };

        for (const campaign of campaigns.campaigns || []) {
          // Get campaign insights
          const insights = await ctx.skills.zernioAds.get_insights({
            ad_id: campaign.id,
            date_preset: "last_7d",
          });

          // For CTWA campaigns, get additional metrics
          let ctwaMetrics = {};
          if (campaign.type === "ctwa") {
            const ctwaInsights = await ctx.skills.zernioAds.get_ctwa_insights({
              campaign_id: campaign.id,
              date_preset: "last_7d",
            });
            ctwaMetrics = {
              conversations: ctwaInsights.messaging_conversations_started,
              cost_per_conversation: ctwaInsights.cost_per_conversation,
              qualified_leads: ctwaInsights.leads_qualified,
              cost_per_qualified_lead: ctwaInsights.cost_per_qualified_lead,
            };
          }

          const metrics: CampaignMetrics = {
            id: campaign.id,
            name: campaign.name,
            type: campaign.type || "standard",
            spend: insights.spend || 0,
            impressions: insights.impressions || 0,
            clicks: insights.clicks || 0,
            conversions: insights.conversions || 0,
            roas: insights.roas || 0,
            cpa: insights.cpa || 0,
            ctr: insights.ctr || 0,
            frequency: insights.frequency || 0,
            ...ctwaMetrics,
          };

          // Get campaign history for trend analysis
          const history = await getCampaignHistory(ctx, campaign.id);

          // Save current metrics to history
          await ctx.db.insert("campaign_history", {
            campaign_id: campaign.id,
            date: new Date().toISOString().split("T")[0],
            ...metrics,
            target_roas: targets.roas,
            target_cpa: targets.cpa,
            target_cpql: targets.cpql,
          });

          // Evaluate rules
          for (const rule of RULES) {
            try {
              // Check cooldown
              if (!(await canTriggerRule(ctx, campaign.id, rule.name, rule.cooldown))) {
                continue;
              }

              // Check if rule conditions are met
              if (rule.check(metrics, targets, history)) {
                ctx.log.info(`Rule ${rule.name} triggered for campaign ${campaign.name}`);

                // Execute action
                const result = await rule.action(ctx, campaign, metrics);

                // Record trigger
                await recordRuleTrigger(ctx, campaign.id, rule.name, result);

                // Send notification
                await sendNotification(ctx, store, result.notification, result.priority);

                // Only one rule per campaign per run
                break;
              }
            } catch (ruleError) {
              ctx.log.error(`Rule ${rule.name} failed for campaign ${campaign.id}`, ruleError);
            }
          }
        }
      } catch (storeError) {
        ctx.log.error(`Failed to process store ${store.id}`, storeError);
      }
    }

    ctx.log.info("Optimizer run completed");
  },

  // API endpoints for the optimizer
  api: {
    "GET /status": async (ctx, req) => {
      const { store_id } = req.query;
      const campaigns = await ctx.db.query(
        `SELECT COUNT(*) as count FROM campaign_history WHERE store_id = ?`,
        [store_id]
      );
      const lastRun = await ctx.db.queryOne(
        `SELECT MAX(triggered_at) as last_run FROM rule_triggers`
      );
      return {
        store_id,
        active_campaigns: campaigns[0]?.count || 0,
        last_check: lastRun?.last_run,
        next_check: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
      };
    },

    "GET /history": async (ctx, req) => {
      const { store_id, limit = 20 } = req.query;
      const decisions = await ctx.db.query(
        `SELECT * FROM rule_triggers
         WHERE campaign_id IN (SELECT id FROM campaigns WHERE store_id = ?)
         ORDER BY triggered_at DESC LIMIT ?`,
        [store_id, limit]
      );
      return { decisions };
    },

    "POST /config": async (ctx, req) => {
      const { store_id, rules } = req.body;
      await ctx.db.update("stores", { id: store_id }, { optimizer_config: JSON.stringify(rules) });
      return { success: true };
    },
  },
};

export default optimizer;
