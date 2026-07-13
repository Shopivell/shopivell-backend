# scheduler.py - Background Scheduler for Automated Rules Engine
"""
Runs automated rules 24/7 on a configurable schedule.

Usage:
    from modules.agents.scheduler import start_rules_scheduler, stop_rules_scheduler

    # Start scheduler when app starts
    start_rules_scheduler(interval_minutes=15)

    # Stop scheduler when app shuts down
    stop_rules_scheduler()
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, List
from threading import Thread

from .monitor_optimizer_agent import automated_rules_engine

logger = logging.getLogger(__name__)


def _meta_learner_enabled() -> bool:
    """The autonomous meta-learner and LLM rule-proposal tiers are opt-in.

    Off by default (MVP): without ENABLE_META_LEARNER the scheduler never
    auto-tunes/auto-retires rules or spends LLM/API credits on its own. The
    endpoints and tables stay in place for manual use; only the unattended
    daily cycle is gated.
    """
    return os.getenv("ENABLE_META_LEARNER", "false").strip().lower() in ("1", "true", "yes")


class AutomatedRulesScheduler:
    """
    Background scheduler for running automated rules at regular intervals.

    Features:
    - Configurable interval (default: 15 minutes)
    - Runs for all configured ad accounts
    - Graceful shutdown
    - Execution logging
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[Thread] = None
        self._ad_account_ids: List[str] = []
        self._interval_minutes: int = 15
        self._last_run: Optional[datetime] = None
        self._run_count: int = 0

    def add_ad_account(self, ad_account_id: str) -> None:
        """Add an ad account to be processed by the scheduler"""
        if ad_account_id not in self._ad_account_ids:
            self._ad_account_ids.append(ad_account_id)
            logger.info(f"[Scheduler] Added ad account: {ad_account_id}")

    def remove_ad_account(self, ad_account_id: str) -> bool:
        """Remove an ad account from the scheduler"""
        if ad_account_id in self._ad_account_ids:
            self._ad_account_ids.remove(ad_account_id)
            logger.info(f"[Scheduler] Removed ad account: {ad_account_id}")
            return True
        return False

    def get_status(self) -> dict:
        """Get current scheduler status"""
        return {
            "running": self._running,
            "interval_minutes": self._interval_minutes,
            "ad_accounts": self._ad_account_ids,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "total_runs": self._run_count,
            "active_rules": len(automated_rules_engine.rules)
        }

    # ---- Tier gating (DB-persisted, survives restarts/deploys) ----

    def _tier_due(self, tier_name: str, interval_hours: float) -> bool:
        """True if the tier hasn't run within interval_hours.

        Last-run times are persisted in the DB so frequent deploys don't
        reset the schedule (the old run-count gating meant daily/weekly
        tiers never fired if the process restarted more often than daily).
        """
        try:
            from database import SessionLocal
            from .models import SchedulerTierState
            db = SessionLocal()
            try:
                state = db.query(SchedulerTierState).filter(
                    SchedulerTierState.tier_name == tier_name
                ).first()
                if state is None or state.last_run_at is None:
                    return True
                return datetime.utcnow() - state.last_run_at >= timedelta(hours=interval_hours)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[Scheduler] Tier-due check failed for {tier_name}: {e}")
            # Fallback: old count-based gating (resets on restart)
            cycles = max(1, int(interval_hours * 60 / self._interval_minutes))
            return self._run_count > 0 and self._run_count % cycles == 0

    def _mark_tier_run(self, tier_name: str) -> None:
        """Persist the tier's last-run time."""
        try:
            from database import SessionLocal
            from .models import SchedulerTierState
            db = SessionLocal()
            try:
                state = db.query(SchedulerTierState).filter(
                    SchedulerTierState.tier_name == tier_name
                ).first()
                if state:
                    state.last_run_at = datetime.utcnow()
                else:
                    db.add(SchedulerTierState(tier_name=tier_name, last_run_at=datetime.utcnow()))
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[Scheduler] Failed to persist tier state for {tier_name}: {e}")

    async def _run_cycle(self) -> dict:
        """Run one cycle of rule execution for all accounts.

        Tiered scheduling based on _run_count:
        - Every cycle (15 min): run_all_rules()
        - Every 24th cycle (~6 hr): sync_insights(days=3)
        - Every 96th cycle (~24 hr): performance summary + notifications
        - Every 672nd cycle (~7 days): audience refinement
        """
        cycle_results = {
            "started_at": datetime.utcnow().isoformat(),
            "accounts_processed": 0,
            "total_rules_triggered": 0,
            "insights_synced": False,
            "errors": []
        }

        # Tier 2: Sync insights every 6 hours (DB-gated, survives restarts)
        if self._tier_due("insights_sync", 6):
            self._mark_tier_run("insights_sync")
            try:
                from modules.marketing.insights_service import sync_insights_for_all_accounts
                logger.info("[Scheduler] Tier 2: Syncing insights (6-hour cycle)")
                sync_result = await sync_insights_for_all_accounts(days=3)
                cycle_results["insights_synced"] = True
                cycle_results["insights_result"] = sync_result
                logger.info(f"[Scheduler] Insights sync: {sync_result.get('synced', 0)} ads synced")
            except Exception as e:
                logger.error(f"[Scheduler] Insights sync error: {e}")
                cycle_results["errors"].append(f"Insights sync: {str(e)}")

        # Tier 2.5: Optimize URL campaigns after insights sync (every 6 hours)
        if self._tier_due("url_campaign_optimization", 6):
            self._mark_tier_run("url_campaign_optimization")
            try:
                from database import SessionLocal
                from modules.campaigns.models import UrlCampaign, CampaignStatus
                from modules.campaigns.optimizer import CampaignOptimizer
                opt_db = SessionLocal()
                try:
                    active_campaigns = opt_db.query(UrlCampaign).filter(
                        UrlCampaign.status == CampaignStatus.ACTIVE
                    ).all()
                    opt_results = []
                    for camp in active_campaigns:
                        optimizer = CampaignOptimizer(opt_db)
                        result = optimizer.optimize_campaign(camp.id, dry_run=False)
                        opt_results.append({
                            "campaign_id": str(camp.id),
                            "paused": result.get("paused_count", 0),
                        })
                    cycle_results["url_campaign_optimization"] = opt_results
                    logger.info(f"[Scheduler] Optimized {len(active_campaigns)} URL campaigns")
                finally:
                    opt_db.close()
            except Exception as e:
                logger.error(f"[Scheduler] URL campaign optimization error: {e}")
                cycle_results["errors"].append(f"URL optimization: {str(e)}")

        # Tier 1: Run rules every cycle (15 min)
        for ad_account_id in self._ad_account_ids:
            try:
                # Autopilot master switch: only execute live when the account has
                # explicitly opted in. Otherwise run advise-only (dry_run) so the
                # engine logs what it WOULD do without touching spend.
                autopilot = False
                try:
                    from database import SessionLocal
                    from modules.marketing.models import MetaAdAccount
                    _db = SessionLocal()
                    try:
                        _acct = _db.query(MetaAdAccount).filter(
                            MetaAdAccount.ad_account_id == ad_account_id
                        ).first()
                        autopilot = bool(_acct and _acct.autopilot_enabled)
                    finally:
                        _db.close()
                except Exception as ap_err:
                    logger.warning(f"[Scheduler] Autopilot lookup failed for {ad_account_id}, defaulting to advise-only: {ap_err}")

                mode = "LIVE" if autopilot else "advise-only (dry-run)"
                logger.info(f"[Scheduler] Running rules for account {ad_account_id} [{mode}]")
                result = await automated_rules_engine.run_all_rules(ad_account_id, dry_run=not autopilot)

                cycle_results["accounts_processed"] += 1
                cycle_results["total_rules_triggered"] += result.get("rules_triggered", 0)

                if result.get("errors"):
                    cycle_results["errors"].extend(result["errors"])

            except Exception as e:
                error_msg = f"Error processing account {ad_account_id}: {str(e)}"
                logger.error(f"[Scheduler] {error_msg}")
                cycle_results["errors"].append(error_msg)

        # Rollback checks (every cycle - lightweight, only processes eligible entries)
        try:
            rollbacks = await automated_rules_engine.check_rollbacks()
            if rollbacks:
                cycle_results["rollbacks"] = rollbacks
                logger.info(f"[Scheduler] Rollbacks executed: {len(rollbacks)}")
        except Exception as e:
            logger.error(f"[Scheduler] Rollback check error: {e}")
            cycle_results["errors"].append(f"Rollback: {str(e)}")

        # Run micro-strategy phase checks and pixel tracker monitoring
        try:
            from modules.micro_strategy.service import run_micro_strategy_cycle
            ms_result = await run_micro_strategy_cycle()
            cycle_results["micro_strategy"] = ms_result
            logger.info(
                f"[Scheduler] Micro-strategy: {ms_result.get('strategies_checked', 0)} strategies, "
                f"{ms_result.get('trackers_checked', 0)} trackers checked"
            )
        except Exception as e:
            logger.error(f"[Scheduler] Micro-strategy cycle error: {e}")
            cycle_results["errors"].append(f"Micro-strategy: {str(e)}")

        # Tier 3: Performance summary + lead quality + fatigue check every 24 hours
        if self._tier_due("daily_summary", 24):
            self._mark_tier_run("daily_summary")
            # Check ad fatigue for URL campaigns daily
            try:
                from database import SessionLocal
                from modules.campaigns.models import UrlCampaign, CampaignStatus as UrlCampaignStatus
                from modules.campaigns.fatigue_detector import FatigueDetector
                fatigue_db = SessionLocal()
                try:
                    active_url_campaigns = fatigue_db.query(UrlCampaign).filter(
                        UrlCampaign.status == UrlCampaignStatus.ACTIVE
                    ).all()
                    fatigue_results = []
                    for camp in active_url_campaigns:
                        detector = FatigueDetector(fatigue_db)
                        check = detector.check_fatigue(camp.id)
                        # Auto-refresh if fatigue score > 70
                        if check.get("fatigued_content_ids"):
                            import uuid as uuid_mod
                            fatigued_ids = [uuid_mod.UUID(fid) for fid in check["fatigued_content_ids"]]
                            refresh = await detector.refresh_creatives(camp.id, fatigued_ids)
                            check["refresh_result"] = refresh
                        fatigue_results.append({
                            "campaign_id": str(camp.id),
                            "fatigued": check.get("fatigued_count", 0),
                            "refreshed": check.get("refresh_result", {}).get("refreshed_count", 0) if check.get("refresh_result") else 0,
                        })
                    cycle_results["fatigue_detection"] = fatigue_results
                    logger.info(f"[Scheduler] Fatigue check: {len(active_url_campaigns)} campaigns checked")
                finally:
                    fatigue_db.close()
            except Exception as e:
                logger.error(f"[Scheduler] Fatigue detection error: {e}")
                cycle_results["errors"].append(f"Fatigue detection: {str(e)}")

            try:
                logger.info("[Scheduler] Tier 3: Daily performance summary (24-hour cycle)")

                # Get lead quality signal
                lead_signal = automated_rules_engine.get_lead_quality_signal("")
                cycle_results["lead_quality"] = lead_signal

                # Create daily summary notification
                try:
                    from database import SessionLocal
                    from modules.marketing.models import MetaAdAccount
                    db = SessionLocal()
                    try:
                        for acc_id in self._ad_account_ids:
                            account = db.query(MetaAdAccount).filter(
                                MetaAdAccount.ad_account_id == acc_id
                            ).first()
                            if account and account.business_account_id:
                                try:
                                    from modules.notifications.models import Notification
                                    notification = Notification(
                                        title="Daily Ad Performance Summary",
                                        message=(
                                            f"24h summary for {account.account_name}: "
                                            f"{self._run_count} cycles completed. "
                                            f"Lead quality: {lead_signal.get('average_score', 0)}/100 "
                                            f"({lead_signal.get('hot_leads', 0)} hot leads)"
                                        ),
                                        type="system",
                                        priority="normal"
                                    )
                                    db.add(notification)
                                except Exception:
                                    pass
                        db.commit()
                    finally:
                        db.close()
                except Exception as e:
                    logger.error(f"[Scheduler] Daily notification error: {e}")

                logger.info(f"[Scheduler] Lead quality: avg={lead_signal.get('average_score', 0)}, "
                           f"hot={lead_signal.get('hot_leads', 0)}")
            except Exception as e:
                logger.error(f"[Scheduler] Tier 3 error: {e}")
                cycle_results["errors"].append(f"Daily summary: {str(e)}")

        # Tier 3.4: Evaluate running creative tests (daily)
        if self._tier_due("creative_tests", 24):
            self._mark_tier_run("creative_tests")
            try:
                tests_completed = await automated_rules_engine.evaluate_creative_tests()
                cycle_results["creative_tests_completed"] = len(tests_completed)
                if tests_completed:
                    logger.info(f"[Scheduler] Creative tests completed: {len(tests_completed)}")
            except Exception as e:
                logger.error(f"[Scheduler] Creative test evaluation error: {e}")
                cycle_results["errors"].append(f"Creative tests: {str(e)}")

        # Tier 3.5: LLM rule proposals (daily, after performance summary)
        # Gated: opt-in only, so the MVP doesn't auto-generate rules or burn LLM credits.
        if _meta_learner_enabled() and self._tier_due("rule_proposals", 24):
            self._mark_tier_run("rule_proposals")
            try:
                from modules.agents.monitor_optimizer_agent import MonitorOptimizerAgent
                from modules.agents.models import Campaign as AgentCampaign
                from database import SessionLocal as PropSessionLocal

                proposer = MonitorOptimizerAgent()
                prop_db = PropSessionLocal()
                try:
                    # Propose rules for campaigns with recent performance data
                    campaigns = prop_db.query(AgentCampaign).filter(
                        AgentCampaign.status == "active"
                    ).limit(5).all()

                    total_proposals = 0
                    for campaign in campaigns:
                        from modules.agents.models import PerformanceMetrics as PM
                        metrics = prop_db.query(PM).filter(
                            PM.campaign_id == campaign.id
                        ).limit(20).all()

                        if not metrics:
                            continue

                        perf_data = [{
                            "ad_id": str(m.ad_id) if m.ad_id else "N/A",
                            "ctr": m.ctr or 0, "cpc": m.cpc or 0,
                            "roas": m.roas or 0, "spend": m.spend or 0,
                            "conversions": m.conversions or 0
                        } for m in metrics]

                        history = automated_rules_engine.get_execution_history(limit=15)
                        proposals = await proposer.propose_rules(
                            campaign=campaign,
                            performance_data=perf_data,
                            current_rules=automated_rules_engine.rules,
                            execution_history=history
                        )
                        total_proposals += len(proposals)

                    cycle_results["rule_proposals"] = {"total": total_proposals}
                    logger.info(f"[Scheduler] Rule proposals: {total_proposals} generated")
                finally:
                    prop_db.close()
            except Exception as e:
                logger.error(f"[Scheduler] Rule proposal error: {e}")
                cycle_results["errors"].append(f"Rule proposals: {str(e)}")

        # Tier 3.6: Meta-learner cycle (daily, after rule proposals)
        # Gated: opt-in only. The meta-learner auto-tunes/auto-retires rules; keep it
        # off for the MVP so nothing self-modifies without an operator enabling it.
        if _meta_learner_enabled() and self._tier_due("meta_learner", 24):
            self._mark_tier_run("meta_learner")
            try:
                from modules.agents.meta_learner import MetaLearner
                meta_learner = MetaLearner()
                for acc_id in self._ad_account_ids:
                    ml_result = await meta_learner.run_meta_learner_cycle(acc_id)
                    cycle_results["meta_learner"] = ml_result
                    logger.info(
                        f"[Scheduler] Meta-learner: {ml_result.get('data_maturity', 'unknown')} "
                        f"({ml_result.get('days_of_data', 0)}d), "
                        f"actions: {ml_result.get('actions_taken', [])}"
                    )
            except Exception as e:
                logger.error(f"[Scheduler] Meta-learner error: {e}")
                cycle_results["errors"].append(f"Meta-learner: {str(e)}")

        # Tier 4: Audience refinement + weekly report every 7 days
        if self._tier_due("weekly_tasks", 168):
            self._mark_tier_run("weekly_tasks")
            try:
                logger.info("[Scheduler] Tier 4: Weekly tasks (7-day cycle)")
                from modules.agents.creative_strategist_agent import CreativeStrategistAgent
                from modules.agents.report_generator import WeeklyReportGenerator
                from database import SessionLocal
                from modules.marketing.models import MetaAdAccount

                strategist = CreativeStrategistAgent()
                report_gen = WeeklyReportGenerator()
                db = SessionLocal()
                try:
                    for acc_id in self._ad_account_ids:
                        account = db.query(MetaAdAccount).filter(
                            MetaAdAccount.ad_account_id == acc_id
                        ).first()
                        if not account:
                            continue

                        # 4a: Audience refinement
                        refinement = await strategist.refine_audience_from_performance(
                            ad_account_id=acc_id,
                            access_token=account.access_token,
                            company_name=account.account_name
                        )
                        cycle_results["audience_refinement"] = refinement
                        if refinement.get("success"):
                            logger.info(f"[Scheduler] Audience refinement complete for {acc_id}")

                        # 4b: Weekly report generation
                        report = await report_gen.generate_weekly_report(
                            ad_account_id=acc_id,
                            access_token=account.access_token
                        )
                        cycle_results["weekly_report"] = {"success": report.get("success", False)}
                        if report.get("success"):
                            logger.info(f"[Scheduler] Weekly report generated for {acc_id}")
                            # Create notification with report summary
                            try:
                                from modules.notifications.models import Notification
                                metrics = report.get("summary_metrics", {})
                                notification = Notification(
                                    title="Weekly Ad Performance Report",
                                    message=(
                                        f"Weekly report for {account.account_name}: "
                                        f"${metrics.get('spend', 0):.2f} spent, "
                                        f"{metrics.get('clicks', 0)} clicks, "
                                        f"{metrics.get('conversions', 0)} conversions, "
                                        f"{metrics.get('ctr', 0):.1f}% CTR"
                                    ),
                                    type="system",
                                    priority="normal"
                                )
                                db.add(notification)
                                db.commit()
                            except Exception:
                                pass
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"[Scheduler] Tier 4 error: {e}")
                cycle_results["errors"].append(f"Weekly tasks: {str(e)}")

        self._last_run = datetime.utcnow()
        self._run_count += 1
        cycle_results["completed_at"] = self._last_run.isoformat()

        logger.info(f"[Scheduler] Cycle complete: {cycle_results['accounts_processed']} accounts, "
                    f"{cycle_results['total_rules_triggered']} rules triggered")

        return cycle_results

    async def _scheduler_loop(self):
        """Main scheduler loop"""
        logger.info(f"[Scheduler] Starting with {self._interval_minutes} minute interval")

        while self._running:
            try:
                # Run rules
                if self._ad_account_ids:
                    await self._run_cycle()
                else:
                    logger.debug("[Scheduler] No ad accounts configured, skipping cycle")

                # Wait for next interval
                await asyncio.sleep(self._interval_minutes * 60)

            except asyncio.CancelledError:
                logger.info("[Scheduler] Received cancellation, stopping...")
                break
            except Exception as e:
                logger.error(f"[Scheduler] Error in scheduler loop: {e}")
                # Continue running despite errors
                await asyncio.sleep(60)  # Short delay before retry

        logger.info("[Scheduler] Stopped")

    def start(self, interval_minutes: int = 15) -> bool:
        """
        Start the scheduler in a background thread.

        Args:
            interval_minutes: How often to run rules (default: 15 minutes)

        Returns:
            True if started successfully
        """
        if self._running:
            logger.warning("[Scheduler] Already running")
            return False

        self._interval_minutes = interval_minutes
        self._running = True

        def run_in_thread():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._scheduler_loop())
            finally:
                self._loop.close()

        self._thread = Thread(target=run_in_thread, daemon=True)
        self._thread.start()

        logger.info(f"[Scheduler] Started with {interval_minutes} minute interval")
        return True

    def stop(self) -> bool:
        """
        Stop the scheduler gracefully.

        Returns:
            True if stopped successfully
        """
        if not self._running:
            logger.warning("[Scheduler] Not running")
            return False

        self._running = False

        if self._task and not self._task.done():
            self._task.cancel()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        logger.info("[Scheduler] Stopped")
        return True

    async def run_now(self) -> dict:
        """Manually trigger an immediate rule execution cycle"""
        logger.info("[Scheduler] Manual trigger requested")
        return await self._run_cycle()


# Singleton instance
rules_scheduler = AutomatedRulesScheduler()


# Convenience functions
def start_rules_scheduler(interval_minutes: int = 15) -> bool:
    """Start the automated rules scheduler"""
    return rules_scheduler.start(interval_minutes)


def stop_rules_scheduler() -> bool:
    """Stop the automated rules scheduler"""
    return rules_scheduler.stop()


def add_ad_account_to_scheduler(ad_account_id: str) -> None:
    """Add an ad account to the scheduler"""
    rules_scheduler.add_ad_account(ad_account_id)


def get_scheduler_status() -> dict:
    """Get scheduler status"""
    return rules_scheduler.get_status()
