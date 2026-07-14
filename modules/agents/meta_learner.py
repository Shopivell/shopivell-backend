# meta_learner.py - Autonomous Meta-Learner for Ad Optimization
"""
The meta-learner runs autonomously to:
1. Check data maturity (how much history is available)
2. Backtest proposed rules against historical data
3. Auto-accept/reject proposals based on backtest results
4. Auto-tune rule thresholds based on outcome tracking
5. Auto-retire ineffective or dormant rules
6. Measure outcomes of past AI decisions
7. Log every decision for fine-tuning

No human-in-the-loop — circuit breakers are the only safety net.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from database import SessionLocal

logger = logging.getLogger(__name__)


def log_ai_decision(
    decision_type: str,
    agent_name: str,
    input_context: Optional[Dict] = None,
    decision: Optional[Dict] = None,
    reasoning: Optional[str] = None,
    confidence: Optional[float] = None,
    ad_account_id: Optional[str] = None,
    store_id: Optional[str] = None,
    data_maturity_level: Optional[str] = None,
    model_used: Optional[str] = None
) -> None:
    """Log an AI decision to the audit trail for fine-tuning."""
    db = SessionLocal()
    try:
        from .models import AIDecisionLog
        log = AIDecisionLog(
            ad_account_id=ad_account_id,
            store_id=store_id,
            decision_type=decision_type,
            agent_name=agent_name,
            input_context=input_context,
            decision=decision,
            reasoning=reasoning,
            confidence=confidence,
            data_maturity_level=data_maturity_level,
            model_used=model_used
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.error(f"[MetaLearner] Failed to log AI decision: {e}")
        db.rollback()
    finally:
        db.close()


class MetaLearner:
    """
    Autonomous meta-learner that validates, tunes, and retires optimization rules.

    Data maturity levels:
    - observation (0-6 days): Collect data only, no automated actions
    - basic (7-13 days): Default rule templates can fire
    - intermediate (14-29 days): Backtesting + auto-process proposals
    - full (30+ days): Full autonomy — auto-tune, auto-retire, all features
    """

    def __init__(self):
        logger.info("[MetaLearner] Initialized")

    # ============ Data Maturity ============

    def check_data_maturity(self, ad_account_id: str) -> Tuple[str, int]:
        """
        Check how many days of performance data are available.

        Returns: (maturity_level, days_of_data)
        """
        db = SessionLocal()
        try:
            from modules.marketing.models import MetaAdInsight, MetaAdAccount, MetaAd
            from sqlalchemy import func

            account = db.query(MetaAdAccount).filter(
                MetaAdAccount.ad_account_id == ad_account_id
            ).first()

            if not account:
                return "observation", 0

            # Count distinct dates with data
            ads = db.query(MetaAd).filter(MetaAd.ad_account_id == account.id).all()
            if not ads:
                return "observation", 0

            ad_ids = [ad.id for ad in ads]
            date_count = db.query(
                func.count(func.distinct(func.date(MetaAdInsight.date)))
            ).filter(
                MetaAdInsight.ad_id.in_(ad_ids)
            ).scalar() or 0

            if date_count >= 30:
                return "full", date_count
            elif date_count >= 14:
                return "intermediate", date_count
            elif date_count >= 7:
                return "basic", date_count
            else:
                return "observation", date_count

        except Exception as e:
            logger.error(f"[MetaLearner] Data maturity check error: {e}")
            return "observation", 0
        finally:
            db.close()

    # ============ Backtesting ============

    def backtest_rule(
        self,
        conditions: List[Dict],
        action_type: str,
        ad_account_id: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Backtest a rule against historical data.

        Replays conditions day by day and checks if the action would have
        improved performance (ROAS up or CPA down within 3 days of trigger).

        Returns: {success_rate, verdict, triggers, good, bad, neutral}
        """
        db = SessionLocal()
        try:
            from modules.marketing.models import MetaAdInsight, MetaAdAccount, MetaAd, MetaAdSet
            from sqlalchemy import func

            account = db.query(MetaAdAccount).filter(
                MetaAdAccount.ad_account_id == ad_account_id
            ).first()
            if not account:
                return {"success_rate": 0, "verdict": "rejected", "error": "Account not found"}

            # Get all ad sets for this account
            adsets = db.query(MetaAdSet).filter(
                MetaAdSet.ad_account_id == account.id
            ).all()

            if not adsets:
                return {"success_rate": 0, "verdict": "rejected", "error": "No ad sets found"}

            total_good = 0
            total_bad = 0
            total_neutral = 0
            roas_changes = []
            cpa_changes = []

            for adset in adsets:
                ads = db.query(MetaAd).filter(MetaAd.adset_id == adset.id).all()
                ad_ids = [ad.id for ad in ads]
                if not ad_ids:
                    continue

                # Get daily aggregated performance
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=days)

                daily_data = db.query(
                    func.date(MetaAdInsight.date).label('day'),
                    func.sum(MetaAdInsight.impressions).label('impressions'),
                    func.sum(MetaAdInsight.clicks).label('clicks'),
                    func.sum(MetaAdInsight.spend).label('spend'),
                    func.sum(MetaAdInsight.conversions).label('conversions'),
                    func.sum(MetaAdInsight.revenue).label('revenue')
                ).filter(
                    MetaAdInsight.ad_id.in_(ad_ids),
                    MetaAdInsight.date >= start_date,
                    MetaAdInsight.date <= end_date
                ).group_by(func.date(MetaAdInsight.date)).order_by(
                    func.date(MetaAdInsight.date)
                ).all()

                if len(daily_data) < 7:
                    continue

                # Only trust ROAS if revenue tracking has recorded real values
                # (rows synced before revenue tracking existed are all 0)
                has_revenue = any((d.revenue or 0) > 0 for d in daily_data)

                # Convert to list of dicts. Metrics that can't be computed on
                # a given day are None (NOT 0 or inf) — None never satisfies
                # a rule condition, so unknown values can't fake a trigger.
                history = []
                for d in daily_data:
                    imp = d.impressions or 0
                    clicks = d.clicks or 0
                    spend = d.spend or 0
                    conv = d.conversions or 0
                    revenue = d.revenue or 0
                    history.append({
                        "date": d.day,
                        "impressions": imp,
                        "clicks": clicks,
                        "spend": spend,
                        "conversions": conv,
                        "ctr": (clicks / imp * 100) if imp > 0 else 0,
                        "cpc": (spend / clicks) if clicks > 0 else None,
                        "cpm": (spend / imp * 1000) if imp > 0 else None,
                        "cpa": (spend / conv) if conv > 0 else None,
                        "roas": (revenue / spend) if (has_revenue and spend > 0) else None
                    })

                # Walk through and find trigger points
                for i in range(len(history)):
                    # Check if conditions would be met at this point
                    # Look back N consecutive days
                    triggered = True
                    for cond in conditions:
                        metric = cond.get("metric", "")
                        operator = cond.get("operator", "gt")
                        value = cond.get("value", 0)
                        consec = cond.get("consecutive_days", 1)

                        if i < consec - 1:
                            triggered = False
                            break

                        # Check consecutive days
                        for j in range(consec):
                            day_idx = i - j
                            if day_idx < 0:
                                triggered = False
                                break
                            day_val = history[day_idx].get(metric)
                            if day_val is None:
                                # Metric unavailable that day (no conversions,
                                # revenue not tracked, or unknown metric name)
                                # — cannot trigger on unknown values
                                triggered = False
                                break

                            if operator in ("gt", "GREATER_THAN") and not (day_val > value):
                                triggered = False
                                break
                            elif operator in ("gte", "GREATER_THAN_OR_EQUAL") and not (day_val >= value):
                                triggered = False
                                break
                            elif operator in ("lt", "LESS_THAN") and not (day_val < value):
                                triggered = False
                                break
                            elif operator in ("lte", "LESS_THAN_OR_EQUAL") and not (day_val <= value):
                                triggered = False
                                break
                            elif operator in ("eq", "EQUAL") and not (day_val == value):
                                triggered = False
                                break

                        if not triggered:
                            break

                    if not triggered:
                        continue

                    # Trigger found at day i — compare day i vs 3-day avg after
                    if i + 3 >= len(history):
                        continue  # Not enough data after trigger

                    # Before: day i metrics (cpa is None when no conversions)
                    before_cpa = history[i].get("cpa")
                    before_ctr = history[i].get("ctr", 0)

                    # After: avg of days i+1, i+2, i+3 (skip None CPA days)
                    after_days = [history[i + k] for k in range(1, 4) if i + k < len(history)]
                    after_cpa_vals = [d["cpa"] for d in after_days if d.get("cpa") is not None]
                    after_ctr_vals = [d.get("ctr", 0) for d in after_days]

                    after_cpa = sum(after_cpa_vals) / len(after_cpa_vals) if after_cpa_vals else None
                    after_ctr = sum(after_ctr_vals) / len(after_ctr_vals) if after_ctr_vals else 0

                    cpa_comparable = before_cpa is not None and after_cpa is not None

                    # Determine outcome
                    if action_type in ("scale_up", "scale_down"):
                        # For budget actions: good if CPA decreased or CTR improved
                        cpa_improved = cpa_comparable and after_cpa < before_cpa * 0.95
                        cpa_worsened = cpa_comparable and after_cpa > before_cpa * 1.15
                        ctr_improved = after_ctr > before_ctr * 1.05

                        if cpa_improved or ctr_improved:
                            total_good += 1
                        elif cpa_worsened:
                            total_bad += 1
                        else:
                            total_neutral += 1

                        if cpa_comparable:
                            cpa_changes.append((after_cpa - before_cpa) / before_cpa * 100)
                    elif action_type == "pause":
                        # Pause is justified if performance did NOT recover on
                        # its own in the days after the trigger
                        if before_cpa is None and after_cpa is None:
                            # No conversions before or after — continued wasted
                            # spend; pausing would have been right
                            total_good += 1
                        elif before_cpa is None:
                            # Recovered on its own — pause would have killed
                            # a recovering ad
                            total_bad += 1
                        elif after_cpa is None:
                            # Conversions stopped entirely — pause justified
                            total_good += 1
                        elif after_cpa >= before_cpa * 0.95:
                            # CPA did not meaningfully improve — pause justified
                            total_good += 1
                        elif after_cpa < before_cpa * 0.85:
                            # CPA recovered strongly — pause would have hurt
                            total_bad += 1
                        else:
                            total_neutral += 1

                        if cpa_comparable:
                            cpa_changes.append((after_cpa - before_cpa) / before_cpa * 100)
                    else:
                        # Informational actions (notify etc.): no budget impact
                        total_neutral += 1

            total_triggers = total_good + total_bad + total_neutral
            measured = total_good + total_bad

            if total_triggers == 0:
                result = {
                    "success_rate": 0,
                    "verdict": "rejected",
                    "total_triggers": 0,
                    "good_outcomes": 0,
                    "bad_outcomes": 0,
                    "neutral_outcomes": 0,
                    "reason": "Rule never triggered in historical data"
                }
            elif measured == 0:
                if action_type in ("scale_up", "scale_down", "pause"):
                    # Triggered, but no measurable CPA/CTR outcome — too risky
                    result = {
                        "success_rate": 0,
                        "verdict": "rejected",
                        "total_triggers": total_triggers,
                        "good_outcomes": 0,
                        "bad_outcomes": 0,
                        "neutral_outcomes": total_neutral,
                        "reason": "Triggered but outcomes were unmeasurable",
                        "days_tested": days
                    }
                else:
                    # Informational action (notify) that does fire — harmless
                    result = {
                        "success_rate": 1.0,
                        "verdict": "accepted",
                        "total_triggers": total_triggers,
                        "good_outcomes": 0,
                        "bad_outcomes": 0,
                        "neutral_outcomes": total_neutral,
                        "reason": "Informational action; accepted on trigger frequency",
                        "days_tested": days
                    }
            else:
                # Success rate over MEASURED outcomes only — neutral triggers
                # no longer dilute the score
                success_rate = total_good / measured
                avg_cpa_change = sum(cpa_changes) / len(cpa_changes) if cpa_changes else 0

                if success_rate >= 0.7:
                    verdict = "accepted"
                elif success_rate >= 0.4:
                    verdict = "tightened"
                else:
                    verdict = "rejected"

                result = {
                    "success_rate": round(success_rate, 3),
                    "verdict": verdict,
                    "total_triggers": total_triggers,
                    "good_outcomes": total_good,
                    "bad_outcomes": total_bad,
                    "neutral_outcomes": total_neutral,
                    "avg_cpa_change_pct": round(avg_cpa_change, 1),
                    "days_tested": days
                }

            # Save backtest result
            from .models import BacktestResult
            bt = BacktestResult(
                rule_id=str(uuid.uuid4()),
                ad_account_id=ad_account_id,
                days_tested=days,
                total_triggers=total_triggers,
                good_outcomes=total_good,
                bad_outcomes=total_bad,
                neutral_outcomes=total_neutral,
                success_rate=result.get("success_rate", 0),
                avg_cpa_change=result.get("avg_cpa_change_pct"),
                verdict=result.get("verdict", "rejected")
            )
            db.add(bt)
            db.commit()

            # Log AI decision
            log_ai_decision(
                decision_type="backtest",
                agent_name="meta_learner",
                input_context={"conditions": conditions, "action_type": action_type, "days": days},
                decision=result,
                reasoning=f"Backtest {result['verdict']}: {result['success_rate']*100:.0f}% success over {total_triggers} triggers",
                confidence=result.get("success_rate"),
                ad_account_id=ad_account_id
            )

            return result

        except Exception as e:
            logger.error(f"[MetaLearner] Backtest error: {e}")
            return {"success_rate": 0, "verdict": "rejected", "error": str(e)}
        finally:
            db.close()

    # ============ Auto-Process Proposals ============

    def auto_process_proposals(self, ad_account_id: str) -> List[Dict]:
        """
        Automatically process pending rule proposals via backtesting.
        No human approval needed — circuit breakers are the safety net.
        """
        db = SessionLocal()
        results = []
        try:
            from .models import ProposedRule
            from .monitor_optimizer_agent import automated_rules_engine, AutomatedRule, RuleCondition, RuleAction, RuleType

            pending = db.query(ProposedRule).filter(
                ProposedRule.status == "pending"
            ).all()

            for proposal in pending:
                # Backtest the proposed rule
                bt_result = self.backtest_rule(
                    conditions=proposal.conditions,
                    action_type=proposal.action_type,
                    ad_account_id=ad_account_id
                )

                verdict = bt_result.get("verdict", "rejected")

                if verdict == "accepted":
                    # Convert to active rule
                    try:
                        conditions = [
                            RuleCondition(
                                metric=c.get("metric", "ctr"),
                                operator=c.get("operator", "gt"),
                                value=c.get("value", 0),
                                consecutive_days=c.get("consecutive_days", 1)
                            )
                            for c in proposal.conditions
                        ]
                        action = RuleAction(
                            type=RuleType(proposal.action_type),
                            adjustment_percent=proposal.adjustment_percent
                        )
                        rule = AutomatedRule(
                            name=proposal.name,
                            description=f"Auto-accepted: {proposal.reasoning}",
                            conditions=conditions,
                            action=action
                        )
                        automated_rules_engine.add_rule(rule)
                        proposal.status = "accepted"
                        proposal.accepted_at = datetime.utcnow()

                        log_ai_decision(
                            decision_type="rule_auto_accept",
                            agent_name="meta_learner",
                            input_context={"proposal": proposal.name, "conditions": proposal.conditions},
                            decision={"verdict": "accepted", "rule_id": rule.id, "backtest": bt_result},
                            reasoning=f"Backtest passed: {bt_result['success_rate']*100:.0f}% success rate",
                            confidence=bt_result.get("success_rate"),
                            ad_account_id=ad_account_id
                        )

                        results.append({"proposal": proposal.name, "action": "accepted", "rule_id": rule.id})
                    except Exception as e:
                        logger.error(f"[MetaLearner] Failed to activate rule {proposal.name}: {e}")
                        results.append({"proposal": proposal.name, "action": "error", "error": str(e)})

                elif verdict == "tightened":
                    # Tighten conditions by 15% and backtest again
                    tightened_conditions = []
                    for c in proposal.conditions:
                        new_c = c.copy()
                        if c.get("operator") in ("gt", "gte"):
                            new_c["value"] = round(c["value"] * 1.15, 2)
                        elif c.get("operator") in ("lt", "lte"):
                            new_c["value"] = round(c["value"] * 0.85, 2)
                        tightened_conditions.append(new_c)

                    # Backtest with tightened conditions
                    bt2 = self.backtest_rule(
                        conditions=tightened_conditions,
                        action_type=proposal.action_type,
                        ad_account_id=ad_account_id
                    )

                    if bt2.get("verdict") == "accepted":
                        # Accept with tightened conditions
                        try:
                            conditions = [
                                RuleCondition(
                                    metric=c.get("metric", "ctr"),
                                    operator=c.get("operator", "gt"),
                                    value=c.get("value", 0),
                                    consecutive_days=c.get("consecutive_days", 1)
                                )
                                for c in tightened_conditions
                            ]
                            action = RuleAction(
                                type=RuleType(proposal.action_type),
                                adjustment_percent=proposal.adjustment_percent
                            )
                            rule = AutomatedRule(
                                name=f"{proposal.name} (tightened)",
                                description=f"Auto-accepted with tightened thresholds: {proposal.reasoning}",
                                conditions=conditions,
                                action=action
                            )
                            automated_rules_engine.add_rule(rule)
                            proposal.status = "accepted"
                            proposal.accepted_at = datetime.utcnow()
                            results.append({"proposal": proposal.name, "action": "accepted_tightened", "rule_id": rule.id})
                        except Exception as e:
                            results.append({"proposal": proposal.name, "action": "error", "error": str(e)})
                    else:
                        proposal.status = "rejected"
                        proposal.rejected_at = datetime.utcnow()
                        results.append({"proposal": proposal.name, "action": "rejected_after_tighten"})

                    log_ai_decision(
                        decision_type="rule_auto_accept",
                        agent_name="meta_learner",
                        input_context={"proposal": proposal.name, "original": proposal.conditions, "tightened": tightened_conditions},
                        decision={"verdict": "tightened", "second_backtest": bt2},
                        reasoning=f"Original backtest marginal ({bt_result['success_rate']*100:.0f}%), tightened and re-tested",
                        ad_account_id=ad_account_id
                    )

                else:  # rejected
                    proposal.status = "rejected"
                    proposal.rejected_at = datetime.utcnow()
                    results.append({"proposal": proposal.name, "action": "rejected", "success_rate": bt_result.get("success_rate")})

                    log_ai_decision(
                        decision_type="rule_auto_accept",
                        agent_name="meta_learner",
                        input_context={"proposal": proposal.name, "conditions": proposal.conditions},
                        decision={"verdict": "rejected", "backtest": bt_result},
                        reasoning=f"Backtest failed: {bt_result['success_rate']*100:.0f}% success rate (need >40%)",
                        ad_account_id=ad_account_id
                    )

            db.commit()
        except Exception as e:
            logger.error(f"[MetaLearner] Auto-process proposals error: {e}")
            db.rollback()
        finally:
            db.close()

        return results

    # ============ Auto-Tune Thresholds ============

    def auto_tune_thresholds(self, ad_account_id: str) -> List[Dict]:
        """
        Auto-tune rule thresholds based on outcome tracking.
        - <40% success rate → tighten threshold by 15%
        - >80% success rate → loosen threshold by 10%
        """
        db = SessionLocal()
        tuning_results = []
        try:
            from .models import RuleExecutionLog, RulePerformanceTracker
            from .monitor_optimizer_agent import automated_rules_engine

            for rule in automated_rules_engine.rules:
                if not rule.is_enabled or not rule.id:
                    continue

                # Get executions in last 14 days
                cutoff = datetime.utcnow() - timedelta(days=14)
                executions = db.query(RuleExecutionLog).filter(
                    RuleExecutionLog.rule_id == rule.id,
                    RuleExecutionLog.executed_at >= cutoff,
                    RuleExecutionLog.success == True,
                    RuleExecutionLog.is_simulation == False
                ).all()

                if len(executions) < 3:
                    continue  # Not enough data to tune

                # Evaluate outcomes: compare performance_at_action vs what happened after
                good = 0
                bad = 0
                neutral = 0
                for ex in executions:
                    snapshot = ex.performance_at_action or {}
                    before_cpa = snapshot.get("cpa", 0)
                    before_ctr = snapshot.get("ctr", 0)

                    # Get performance 3 days after the action
                    from .monitor_optimizer_agent import AutomatedRulesEngine
                    engine = AutomatedRulesEngine.__new__(AutomatedRulesEngine)
                    engine.access_token = None
                    after_history = engine.get_performance_history(
                        ex.entity_id, ex.entity_type, days=3
                    )
                    if not after_history:
                        neutral += 1
                        continue

                    after_cpa = after_history[0].get("cpa", 0)
                    after_ctr = after_history[0].get("ctr", 0)

                    if before_cpa > 0 and after_cpa < before_cpa * 0.95:
                        good += 1
                    elif before_cpa > 0 and after_cpa > before_cpa * 1.15:
                        bad += 1
                    elif after_ctr > before_ctr * 1.05:
                        good += 1
                    else:
                        neutral += 1

                total = good + bad + neutral
                if total == 0:
                    continue

                success_rate = good / total
                action_taken = None

                # Get or create performance tracker
                tracker = db.query(RulePerformanceTracker).filter(
                    RulePerformanceTracker.rule_id == rule.id
                ).first()
                if not tracker:
                    tracker = RulePerformanceTracker(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        original_conditions=[c.model_dump() for c in rule.conditions]
                    )
                    db.add(tracker)

                tracker.total_triggers = total
                tracker.good_outcomes = good
                tracker.bad_outcomes = bad
                tracker.neutral_outcomes = neutral
                tracker.success_rate = round(success_rate, 3)
                tracker.last_evaluated_at = datetime.utcnow()

                if success_rate < 0.4 and total >= 5:
                    # Tighten: increase threshold for gt/gte, decrease for lt/lte
                    for condition in rule.conditions:
                        if condition.operator.value in ("gt", "gte"):
                            old_val = condition.value
                            condition.value = round(condition.value * 1.15, 2)
                            action_taken = f"Tightened {condition.metric} from {old_val} to {condition.value}"
                        elif condition.operator.value in ("lt", "lte"):
                            old_val = condition.value
                            condition.value = round(condition.value * 0.85, 2)
                            action_taken = f"Tightened {condition.metric} from {old_val} to {condition.value}"
                    tracker.times_tightened += 1

                elif success_rate > 0.8 and total >= 5:
                    # Loosen: decrease threshold for gt/gte, increase for lt/lte
                    for condition in rule.conditions:
                        if condition.operator.value in ("gt", "gte"):
                            old_val = condition.value
                            condition.value = round(condition.value * 0.9, 2)
                            action_taken = f"Loosened {condition.metric} from {old_val} to {condition.value}"
                        elif condition.operator.value in ("lt", "lte"):
                            old_val = condition.value
                            condition.value = round(condition.value * 1.1, 2)
                            action_taken = f"Loosened {condition.metric} from {old_val} to {condition.value}"
                    tracker.times_loosened += 1

                tracker.current_conditions = [c.model_dump() for c in rule.conditions]
                automated_rules_engine.persist_rule(rule)  # persist tuned thresholds

                if action_taken:
                    log_ai_decision(
                        decision_type="threshold_tune",
                        agent_name="meta_learner",
                        input_context={"rule": rule.name, "success_rate": success_rate, "triggers": total, "good": good, "bad": bad},
                        decision={"action": action_taken, "new_conditions": [c.model_dump() for c in rule.conditions]},
                        reasoning=f"Success rate {success_rate*100:.0f}% over {total} triggers — {action_taken}",
                        confidence=success_rate,
                        ad_account_id=ad_account_id
                    )

                    tuning_results.append({
                        "rule": rule.name,
                        "success_rate": round(success_rate, 3),
                        "action": action_taken
                    })

            db.commit()
        except Exception as e:
            logger.error(f"[MetaLearner] Auto-tune error: {e}")
            db.rollback()
        finally:
            db.close()

        return tuning_results

    # ============ Auto-Retire Rules ============

    def auto_retire_rules(self, ad_account_id: str) -> List[Dict]:
        """
        Auto-disable rules that are dormant (30+ days no trigger)
        or consistently harmful (<30% success over 10+ triggers).
        """
        db = SessionLocal()
        retired = []
        try:
            from .models import RuleExecutionLog, RulePerformanceTracker
            from .monitor_optimizer_agent import automated_rules_engine

            cutoff_30d = datetime.utcnow() - timedelta(days=30)

            for rule in automated_rules_engine.rules:
                if not rule.is_enabled or not rule.id:
                    continue

                reason = None

                # Check dormancy: no triggers in 30 days
                recent_triggers = db.query(RuleExecutionLog).filter(
                    RuleExecutionLog.rule_id == rule.id,
                    RuleExecutionLog.executed_at >= cutoff_30d,
                    RuleExecutionLog.is_simulation == False
                ).count()

                if recent_triggers == 0 and rule.trigger_count > 0:
                    reason = f"Dormant: no triggers in 30 days (last trigger count: {rule.trigger_count})"

                # Check performance: <30% success over 10+ triggers
                if not reason:
                    tracker = db.query(RulePerformanceTracker).filter(
                        RulePerformanceTracker.rule_id == rule.id
                    ).first()
                    if tracker and tracker.total_triggers >= 10 and tracker.success_rate < 0.3:
                        reason = f"Poor performance: {tracker.success_rate*100:.0f}% success rate over {tracker.total_triggers} triggers"

                if reason:
                    rule.is_enabled = False
                    automated_rules_engine.persist_rule(rule)  # persist auto-retire

                    # Update tracker
                    tracker = db.query(RulePerformanceTracker).filter(
                        RulePerformanceTracker.rule_id == rule.id
                    ).first()
                    if tracker:
                        tracker.auto_disabled = True
                        tracker.disabled_reason = reason

                    log_ai_decision(
                        decision_type="rule_retire",
                        agent_name="meta_learner",
                        input_context={"rule": rule.name, "rule_id": rule.id},
                        decision={"action": "disabled", "reason": reason},
                        reasoning=reason,
                        ad_account_id=ad_account_id
                    )

                    retired.append({"rule": rule.name, "reason": reason})
                    logger.info(f"[MetaLearner] Auto-retired rule '{rule.name}': {reason}")

            db.commit()
        except Exception as e:
            logger.error(f"[MetaLearner] Auto-retire error: {e}")
            db.rollback()
        finally:
            db.close()

        return retired

    # ============ Measure Outcomes ============

    def measure_outcomes(self) -> int:
        """
        Measure outcomes for past AI decisions (3+ days old).
        Compares performance before vs after each decision.
        Creates the fine-tuning dataset.
        """
        db = SessionLocal()
        measured = 0
        try:
            from .models import AIDecisionLog
            from .monitor_optimizer_agent import AutomatedRulesEngine

            cutoff = datetime.utcnow() - timedelta(days=3)

            unmeasured = db.query(AIDecisionLog).filter(
                AIDecisionLog.outcome_measured == False,
                AIDecisionLog.created_at <= cutoff,
                AIDecisionLog.decision_type.in_(["rule_execution", "rule_auto_accept", "threshold_tune"])
            ).limit(50).all()

            engine = AutomatedRulesEngine.__new__(AutomatedRulesEngine)
            engine.access_token = None

            for log in unmeasured:
                try:
                    context = log.input_context or {}
                    decision = log.decision or {}

                    entity_id = context.get("entity") or decision.get("entity_id")
                    if not entity_id:
                        log.outcome_measured = True
                        log.outcome_score = 0
                        measured += 1
                        continue

                    # Get current performance
                    current = engine.get_performance_history(entity_id, "adset", days=3)
                    if not current:
                        current = engine.get_performance_history(entity_id, "ad", days=3)

                    if not current:
                        log.outcome_measured = True
                        log.outcome_score = 0
                        measured += 1
                        continue

                    # Compare to snapshot at decision time
                    before_cpa = context.get("cpa", 0) or (context.get("performance", {}).get("cpa", 0))
                    before_ctr = context.get("ctr", 0) or (context.get("performance", {}).get("ctr", 0))
                    after_cpa = current[0].get("cpa", 0)
                    after_ctr = current[0].get("ctr", 0)

                    # Score: -1 (terrible) to +1 (excellent)
                    score = 0
                    if before_cpa > 0:
                        cpa_change = (before_cpa - after_cpa) / before_cpa  # Positive = CPA decreased = good
                        score += cpa_change * 0.6  # CPA has 60% weight
                    if before_ctr > 0:
                        ctr_change = (after_ctr - before_ctr) / before_ctr  # Positive = CTR increased = good
                        score += ctr_change * 0.4  # CTR has 40% weight

                    score = max(-1.0, min(1.0, score))

                    log.outcome_measured = True
                    log.outcome_data = {
                        "before": {"cpa": before_cpa, "ctr": before_ctr},
                        "after": {"cpa": after_cpa, "ctr": after_ctr}
                    }
                    log.outcome_score = round(score, 3)
                    log.outcome_measured_at = datetime.utcnow()
                    measured += 1

                except Exception as e:
                    logger.warning(f"[MetaLearner] Failed to measure outcome for decision {log.id}: {e}")
                    log.outcome_measured = True
                    log.outcome_score = 0
                    measured += 1

            db.commit()
            logger.info(f"[MetaLearner] Measured outcomes for {measured} decisions")
        except Exception as e:
            logger.error(f"[MetaLearner] Outcome measurement error: {e}")
            db.rollback()
        finally:
            db.close()

        return measured

    # ============ Orchestrator ============

    async def run_meta_learner_cycle(self, ad_account_id: str) -> Dict[str, Any]:
        """
        Run the full meta-learner cycle based on data maturity.

        - observation (0-6 days): Do nothing
        - basic (7-13 days): Only measure outcomes
        - intermediate (14-29 days): Measure outcomes + auto-process proposals
        - full (30+ days): All of the above + auto-tune + auto-retire
        """
        maturity, days = self.check_data_maturity(ad_account_id)

        result = {
            "ad_account_id": ad_account_id,
            "data_maturity": maturity,
            "days_of_data": days,
            "actions_taken": []
        }

        if maturity == "observation":
            result["message"] = f"Observation mode ({days} days of data). Collecting data, no automated actions."
            logger.info(f"[MetaLearner] {result['message']}")
            return result

        # Basic+: Measure outcomes of past decisions
        outcomes_measured = self.measure_outcomes()
        result["outcomes_measured"] = outcomes_measured
        result["actions_taken"].append(f"Measured {outcomes_measured} decision outcomes")

        if maturity in ("intermediate", "full"):
            # Process pending proposals via backtesting
            proposals = self.auto_process_proposals(ad_account_id)
            result["proposals_processed"] = proposals
            result["actions_taken"].append(f"Processed {len(proposals)} proposals")

        if maturity == "full":
            # Auto-tune thresholds
            tuning = self.auto_tune_thresholds(ad_account_id)
            result["thresholds_tuned"] = tuning
            result["actions_taken"].append(f"Tuned {len(tuning)} rule thresholds")

            # Auto-retire bad/dormant rules
            retired = self.auto_retire_rules(ad_account_id)
            result["rules_retired"] = retired
            result["actions_taken"].append(f"Retired {len(retired)} rules")

        logger.info(f"[MetaLearner] Cycle complete for {ad_account_id}: {maturity} ({days}d), actions: {result['actions_taken']}")
        return result
