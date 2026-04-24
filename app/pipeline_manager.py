"""
Pipeline concurrency manager.

Controls how many site-generation pipelines can run simultaneously,
prevents duplicate runs for the same lead, tracks active/queued state,
and recovers stuck leads.

Usage:
    from app.pipeline_manager import pipeline_manager

    await pipeline_manager.enqueue(lead_id)  # queues or runs immediately
    stats = pipeline_manager.stats()         # monitoring info
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# --- Configuration -----------------------------------------------------------
MAX_CONCURRENT_PIPELINES = 5          # max pipelines running at once
STUCK_LEAD_THRESHOLD_SECONDS = 600    # 10 minutes → consider stuck


@dataclass
class _PipelineEntry:
    lead_id: str
    enqueued_at: float
    started_at: float | None = None
    task: asyncio.Task | None = None


class PipelineManager:
    """Manages pipeline concurrency with semaphore, per-lead locking, and stats."""

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_PIPELINES) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        # Currently held lead locks (lead_id → True)
        self._active_leads: dict[str, _PipelineEntry] = {}
        # Waiting in queue (not yet started)
        self._queued: dict[str, _PipelineEntry] = {}
        self._lock = asyncio.Lock()
        # Completed/failed counters
        self._completed: int = 0
        self._failed: int = 0
        self._total_duration_ms: float = 0

    async def enqueue(
        self,
        lead_id: str,
        *,
        post_pipeline_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> bool:
        """Enqueue a pipeline run for *lead_id*.

        Returns True if accepted, False if already running/queued (dedup).
        *post_pipeline_callback* is called after a successful pipeline run
        (e.g. to auto-claim the site).
        """
        async with self._lock:
            if lead_id in self._active_leads or lead_id in self._queued:
                logger.warning(
                    "Pipeline already running/queued for lead %s — skipping",
                    lead_id,
                )
                return False

            entry = _PipelineEntry(lead_id=lead_id, enqueued_at=time.monotonic())
            self._queued[lead_id] = entry

        # Launch a wrapper task that waits for the semaphore
        task = asyncio.create_task(
            self._run_with_semaphore(entry, post_pipeline_callback)
        )
        entry.task = task
        return True

    async def _run_with_semaphore(
        self,
        entry: _PipelineEntry,
        post_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Wait for a semaphore slot, then run the pipeline."""
        lead_id = entry.lead_id
        try:
            async with self._semaphore:
                # Move from queued → active
                async with self._lock:
                    self._queued.pop(lead_id, None)
                    entry.started_at = time.monotonic()
                    self._active_leads[lead_id] = entry

                logger.info(
                    "Pipeline starting for lead %s (active=%d, queued=%d)",
                    lead_id,
                    len(self._active_leads),
                    len(self._queued),
                )

                start = time.monotonic()
                try:
                    await self._execute_pipeline(lead_id)
                    duration_ms = (time.monotonic() - start) * 1000
                    async with self._lock:
                        self._completed += 1
                        self._total_duration_ms += duration_ms
                    # Run optional post-pipeline callback (e.g. auto-claim)
                    if post_callback:
                        try:
                            await post_callback()
                        except Exception:
                            logger.exception(
                                "Post-pipeline callback failed for lead %s", lead_id
                            )
                except Exception:
                    async with self._lock:
                        self._failed += 1
                    raise
        except Exception:
            logger.exception("Pipeline failed for lead %s", lead_id)
        finally:
            async with self._lock:
                self._active_leads.pop(lead_id, None)
                self._queued.pop(lead_id, None)

    @staticmethod
    async def _execute_pipeline(lead_id: str) -> None:
        """Run the actual scrape+generate pipeline with its own DB session."""
        from app.database import get_db_session
        from app.scraper.pipeline import run_pipeline

        async with get_db_session() as db:
            await run_pipeline(db, lead_id)

    def stats(self) -> dict:
        """Return current pipeline stats for monitoring."""
        avg_ms = (
            self._total_duration_ms / self._completed
            if self._completed > 0
            else 0
        )
        return {
            "max_concurrent": self._max_concurrent,
            "active": len(self._active_leads),
            "queued": len(self._queued),
            "completed": self._completed,
            "failed": self._failed,
            "avg_duration_ms": round(avg_ms),
            "active_leads": list(self._active_leads.keys()),
            "queued_leads": list(self._queued.keys()),
        }

    def is_lead_busy(self, lead_id: str) -> bool:
        """Check if a lead is currently running or queued."""
        return lead_id in self._active_leads or lead_id in self._queued

    def get_stuck_leads(self) -> list[str]:
        """Return lead IDs that have been active longer than the threshold."""
        now = time.monotonic()
        stuck = []
        for lead_id, entry in self._active_leads.items():
            if entry.started_at and (now - entry.started_at) > STUCK_LEAD_THRESHOLD_SECONDS:
                stuck.append(lead_id)
        return stuck


# Global singleton
pipeline_manager = PipelineManager()
