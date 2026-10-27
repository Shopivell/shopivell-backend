# Optimizer Plugin

24/7 autonomous ad optimization plugin that monitors campaigns, scales winners, pauses losers, and sends notifications.

## Description
Runs continuously in the background, checking all active campaigns every 15 minutes. Applies automated rules to optimize performance and notifies store owners of important changes.

## Configuration

```yaml
optimizer:
  enabled: true
  check_interval: 15m  # How often to check campaigns
  notification_channels:
    - whatsapp
    - telegram
  rules:
    scale_winner:
      enabled: true
      roas_threshold: 1.25  # Scale when ROAS >= target * 1.25
      consecutive_days: 3
      budget_increase: 20  # Percent
      max_budget: 10000
      cooldown: 6h
    kill_loser:
      enabled: true
      cpa_threshold: 2.0  # Cut when CPA > target * 2
      min_impressions: 2000
      budget_decrease: 50  # Percent
      cooldown: 12h
    pause_no_spend:
      enabled: true
      hours_no_spend: 24
      cooldown: 24h
    creative_fatigue:
      enabled: true
      frequency_threshold: 3
      ctr_decline_percent: 30
      consecutive_days: 3
    ctwa_quality:
      enabled: true
      cpql_threshold: 2.0  # Cost per qualified lead
      scale_threshold: 0.7
```

## How It Works

### Monitoring Loop
```
Every 15 minutes:
  1. Fetch all active campaigns from Zernio
  2. For each campaign:
     a. Get insights (spend, ROAS, CPA, etc.)
     b. For CTWA: Get offline conversion data
     c. Evaluate against rules
     d. Execute actions if rules trigger
     e. Log decision and notify if needed
  3. Update campaign history for trend analysis
```

### Rules Engine

#### scale_winner
Scales budget for high-performing ads.
- **Trigger**: ROAS >= target_roas * 1.25 for 3 consecutive days
- **Action**: Increase budget by 20%
- **Guard**: Max budget cap, 6-hour cooldown
- **Notification**: "Your ad [name] is performing great! Budget increased to $X"

#### kill_loser
Reduces budget for underperforming ads.
- **Trigger**: CPA > target_cpa * 2 AND impressions >= 2000 AND conversions == 0
- **Action**: Decrease budget by 50%
- **Guard**: 12-hour cooldown
- **Notification**: "Ad [name] not converting. Budget reduced to $X"

#### pause_no_spend
Pauses stuck campaigns.
- **Trigger**: $0 spend for 24+ hours
- **Action**: Pause campaign
- **Notification**: "Ad [name] has no spend. Paused for review."

#### creative_fatigue
Detects when creatives are getting stale.
- **Trigger**: Frequency > 3 AND CTR declined 30%+ over 3 days
- **Action**: Pause and flag for creative refresh
- **Notification**: "Ad [name] showing fatigue. Consider new creative."

#### ctwa_quality (For Click-to-WhatsApp)
Optimizes based on lead quality, not just conversations.
- **Scale Trigger**: cost_per_qualified_lead < target * 0.7
- **Scale Action**: Increase budget 25%
- **Kill Trigger**: cost_per_qualified_lead > target * 2 for 3 days
- **Kill Action**: Reduce budget 30%
- **Note**: Uses offline conversion data from `send_lead_event()`

## Data Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Zernio    │────▶│  Optimizer   │────▶│ Zernio Ads  │
│  Insights   │     │   Plugin     │     │  (actions)  │
└─────────────┘     └──────────────┘     └─────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ Notifications │
                    │ WhatsApp/TG  │
                    └──────────────┘
```

## Notifications

### WhatsApp Notification Format
```
🎯 Ad Update: [Store Name]

[Winner] Summer Sale Campaign
✅ ROAS: 350% (above 312% target)
📈 Budget increased: $50 → $60

Performance (Last 7 days):
• Spend: $350
• Revenue: $1,225
• Conversions: 45
• CPA: $7.78

Keep it up! 🚀
```

### Alert Types
| Type | Emoji | Priority |
|------|-------|----------|
| Winner Scaled | ✅📈 | Low |
| Loser Cut | ⚠️📉 | Medium |
| Campaign Paused | ⛔ | High |
| Creative Fatigue | 🎨 | Medium |
| Budget Depleted | 💰 | High |
| Anomaly Detected | 🔍 | High |

## API Endpoints

### GET /optimizer/status
Current optimizer status for a store.
```json
{
  "store_id": "store_123",
  "active_campaigns": 5,
  "last_check": "2024-01-15T10:30:00Z",
  "next_check": "2024-01-15T10:45:00Z",
  "actions_today": [
    {"campaign": "Summer Sale", "action": "scale_up", "time": "08:15"}
  ]
}
```

### GET /optimizer/history
Recent optimization decisions.
```json
{
  "decisions": [
    {
      "timestamp": "2024-01-15T08:15:00Z",
      "campaign_id": "123456",
      "campaign_name": "Summer Sale",
      "rule": "scale_winner",
      "metrics": {"roas": 3.5, "target_roas": 2.5},
      "action": "budget_increase",
      "details": {"old_budget": 50, "new_budget": 60}
    }
  ]
}
```

### POST /optimizer/config
Update optimizer rules for a store.
```json
{
  "store_id": "store_123",
  "rules": {
    "scale_winner": {"roas_threshold": 1.3},
    "kill_loser": {"cpa_threshold": 1.8}
  }
}
```

## Integration Points

### With Zernio Ads Skill
- `get_all_store_insights()` - Fetch campaign metrics
- `scale_budget()` - Increase winner budgets
- `pause_ad()` - Pause underperformers
- `get_ctwa_insights()` - WhatsApp campaign metrics
- `get_conversion_stats()` - Offline conversion data

### With Shopivell Backend
- Fetch store notification preferences
- Get target ROAS/CPA per store
- Send WhatsApp notifications via store's WhatsApp

### With Ad Creator Skill
- When creative fatigue detected, trigger new creative generation
- Feed winning ad patterns to improve future creatives

## Example Plugin Code

```typescript
import { Plugin, PluginContext } from "@openclaw/sdk";
import { zernioAds } from "../skills/zernio-ads";

const RULES = {
  scale_winner: {
    check: (metrics, targets) =>
      metrics.roas >= targets.roas * 1.25 &&
      metrics.consecutive_good_days >= 3,
    action: async (ctx, campaign) => {
      await zernioAds.scale_budget(ctx, {
        ad_id: campaign.id,
        percentage: 20,
        max_budget: 10000
      });
      return { type: "budget_increase", percent: 20 };
    }
  },
  kill_loser: {
    check: (metrics, targets) =>
      metrics.cpa > targets.cpa * 2 &&
      metrics.conversions === 0 &&
      metrics.impressions >= 2000,
    action: async (ctx, campaign) => {
      await zernioAds.scale_budget(ctx, {
        ad_id: campaign.id,
        percentage: -50
      });
      return { type: "budget_decrease", percent: 50 };
    }
  }
};

export const optimizer: Plugin = {
  name: "optimizer",
  interval: "15m",

  async run(ctx: PluginContext) {
    const stores = await ctx.db.query("SELECT * FROM stores WHERE ads_enabled = true");

    for (const store of stores) {
      const profile = await zernioAds.get_store_profile(ctx, { store_id: store.id });
      const campaigns = await zernioAds.list_campaigns(ctx, {
        profile_id: profile.id,
        status: "active"
      });

      for (const campaign of campaigns) {
        const insights = await zernioAds.get_insights(ctx, {
          ad_id: campaign.id,
          date_preset: "last_7d"
        });

        const targets = store.ad_targets; // { roas: 2.5, cpa: 10 }

        for (const [ruleName, rule] of Object.entries(RULES)) {
          if (rule.check(insights, targets)) {
            const result = await rule.action(ctx, campaign);
            await notify(ctx, store, campaign, ruleName, result);
            await logDecision(ctx, campaign, ruleName, insights, result);
          }
        }
      }
    }
  }
};
```

## Environment Variables
- ZERNIO_API_KEY (required)
- WHATSAPP_API_TOKEN (for notifications)
- TELEGRAM_BOT_TOKEN (for notifications)
- SHOPIVELL_API_URL (for store data)
