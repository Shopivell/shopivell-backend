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
from datetime import datetime
from typing import Optional, List
from threading import Thread

from .monitor_optimizer_agent import automated_rules_engine

logger = logging.getLogger(__name__)


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

    async def _run_cycle(self) -> dict:
        """Run one cycle of rule execution for all accounts"""
        cycle_results = {
            "started_at": datetime.utcnow().isoformat(),
            "accounts_processed": 0,
            "total_rules_triggered": 0,
            "errors": []
        }

        for ad_account_id in self._ad_account_ids:
            try:
                logger.info(f"[Scheduler] Running rules for account: {ad_account_id}")
                result = await automated_rules_engine.run_all_rules(ad_account_id)

                cycle_results["accounts_processed"] += 1
                cycle_results["total_rules_triggered"] += result.get("rules_triggered", 0)

                if result.get("errors"):
                    cycle_results["errors"].extend(result["errors"])

            except Exception as e:
                error_msg = f"Error processing account {ad_account_id}: {str(e)}"
                logger.error(f"[Scheduler] {error_msg}")
                cycle_results["errors"].append(error_msg)

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
