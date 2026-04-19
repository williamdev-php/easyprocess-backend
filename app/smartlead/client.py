"""
Smartlead.ai async API client.

Handles authentication, rate limiting, and all REST API interactions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://server.smartlead.ai/api/v1"

# Concurrency limiter — Smartlead rate limits vary by plan
_semaphore = asyncio.Semaphore(5)


class SmartleadError(Exception):
    """Raised when the Smartlead API returns an error."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Smartlead API {status_code}: {detail}")


class SmartleadClient:
    """Async client for the Smartlead REST API."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or settings.SMARTLEAD_API_KEY

    # ------------------------------------------------------------------
    # Low-level request helper
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | list | None = None,
        params: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> dict | list:
        """Make an authenticated request with rate limiting and retry on 429."""
        if not self._api_key:
            raise RuntimeError("SMARTLEAD_API_KEY not configured")

        url = f"{BASE_URL}/{path.lstrip('/')}"
        query = {"api_key": self._api_key}
        if params:
            query.update(params)

        for attempt in range(max_retries):
            async with _semaphore:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.request(
                        method,
                        url,
                        params=query,
                        json=json,
                    )

            if resp.status_code == 429:
                wait = min(2 ** attempt * 2, 30)
                logger.warning("Smartlead 429 rate limited, retrying in %ds", wait)
                await asyncio.sleep(wait)
                continue

            if resp.status_code >= 400:
                detail = resp.text[:500]
                logger.error("Smartlead %s %s → %d: %s", method, path, resp.status_code, detail)
                raise SmartleadError(resp.status_code, detail)

            return resp.json()

        raise SmartleadError(429, "Rate limited after max retries")

    # ------------------------------------------------------------------
    # Campaign endpoints
    # ------------------------------------------------------------------

    async def list_campaigns(self) -> list[dict]:
        return await self._request("GET", "/campaigns/")

    async def create_campaign(self, name: str) -> dict:
        return await self._request("POST", "/campaigns/create", json={"name": name})

    async def get_campaign(self, campaign_id: int) -> dict:
        return await self._request("GET", f"/campaigns/{campaign_id}")

    async def update_campaign_status(self, campaign_id: int, status: str) -> dict:
        """Status: ACTIVE, PAUSED, STOPPED, DRAFTED, ARCHIVED."""
        return await self._request(
            "PATCH",
            f"/campaigns/{campaign_id}/status",
            json={"status": status},
        )

    async def set_campaign_schedule(
        self,
        campaign_id: int,
        *,
        timezone: str = "Europe/Stockholm",
        days: list[int] | None = None,
        start_hour: str = "09:00",
        end_hour: str = "17:00",
    ) -> dict:
        if days is None:
            days = [1, 2, 3, 4, 5]  # Mon-Fri
        return await self._request(
            "POST",
            f"/campaigns/{campaign_id}/schedule",
            json={
                "tz": timezone,
                "days": days,
                "startHour": start_hour,
                "endHour": end_hour,
            },
        )

    async def update_campaign_settings(self, campaign_id: int, settings_data: dict) -> dict:
        return await self._request(
            "PATCH",
            f"/campaigns/{campaign_id}/settings",
            json=settings_data,
        )

    async def save_sequences(self, campaign_id: int, sequences: list[dict]) -> dict:
        return await self._request(
            "POST",
            f"/campaigns/{campaign_id}/sequences",
            json={"sequences": sequences},
        )

    async def get_sequences(self, campaign_id: int) -> list[dict]:
        return await self._request("GET", f"/campaigns/{campaign_id}/sequences")

    # ------------------------------------------------------------------
    # Lead endpoints
    # ------------------------------------------------------------------

    async def add_leads(
        self,
        campaign_id: int,
        leads: list[dict],
        *,
        ignore_global_block_list: bool = False,
        ignore_unsubscribe_list: bool = False,
        ignore_duplicate_leads_in_other_campaign: bool = False,
    ) -> dict:
        """Add leads to a campaign. Max 400 per request."""
        if len(leads) > 400:
            raise ValueError("Max 400 leads per request")
        return await self._request(
            "POST",
            f"/campaigns/{campaign_id}/leads",
            json={
                "lead_list": leads,
                "settings": {
                    "ignore_global_block_list": ignore_global_block_list,
                    "ignore_unsubscribe_list": ignore_unsubscribe_list,
                    "ignore_duplicate_leads_in_other_campaign": ignore_duplicate_leads_in_other_campaign,
                    "ignore_community_bounce_list": False,
                },
            },
        )

    async def get_campaign_leads(self, campaign_id: int) -> list[dict]:
        return await self._request("GET", f"/campaigns/{campaign_id}/leads")

    async def get_lead_by_email(self, email: str) -> dict | None:
        try:
            return await self._request("GET", "/leads/", params={"email": email})
        except SmartleadError as e:
            if e.status_code == 404:
                return None
            raise

    async def update_lead(self, campaign_id: int, lead_id: int, data: dict) -> dict:
        return await self._request(
            "POST",
            f"/campaigns/{campaign_id}/leads/{lead_id}",
            json=data,
        )

    async def pause_lead(self, campaign_id: int, lead_id: int) -> dict:
        return await self._request(
            "POST",
            f"/campaigns/{campaign_id}/leads/{lead_id}/pause",
        )

    async def unsubscribe_lead_global(self, lead_id: int) -> dict:
        return await self._request("POST", f"/leads/{lead_id}/unsubscribe")

    # ------------------------------------------------------------------
    # Email account endpoints
    # ------------------------------------------------------------------

    async def list_email_accounts(self) -> list[dict]:
        return await self._request("GET", "/email-accounts/")

    async def get_email_account(self, account_id: int) -> dict:
        return await self._request("GET", f"/email-accounts/{account_id}/")

    async def add_email_account_to_campaign(
        self, campaign_id: int, account_ids: list[int]
    ) -> dict:
        return await self._request(
            "POST",
            f"/campaigns/{campaign_id}/email-accounts",
            json={"email_account_ids": account_ids},
        )

    async def update_warmup(self, account_id: int, config: dict) -> dict:
        return await self._request(
            "POST",
            f"/email-accounts/{account_id}/warmup",
            json=config,
        )

    async def get_warmup_stats(self, account_id: int) -> dict:
        return await self._request("GET", f"/email-accounts/{account_id}/warmup-stats")

    # ------------------------------------------------------------------
    # Message history
    # ------------------------------------------------------------------

    async def get_message_history(
        self,
        campaign_id: int,
        lead_id: int,
    ) -> list[dict]:
        return await self._request(
            "GET",
            f"/campaigns/{campaign_id}/leads/{lead_id}/message-history",
        )

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    async def get_campaign_analytics(self, campaign_id: int) -> dict:
        return await self._request("GET", f"/campaigns/{campaign_id}/analytics")

    async def get_campaign_analytics_by_date(
        self, campaign_id: int, *, start_date: str, end_date: str
    ) -> dict:
        return await self._request(
            "GET",
            f"/campaigns/{campaign_id}/analytics-by-date",
            params={"start_date": start_date, "end_date": end_date},
        )
