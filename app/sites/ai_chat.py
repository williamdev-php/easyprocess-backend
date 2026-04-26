"""
AI Chat Theme Editor — WebSocket endpoint.

Provides a real-time chat interface where users can instruct Claude Haiku
to modify their site's sections, text, and layout.  Changes are validated
against SiteSchema and auto-saved as drafts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.auth.service import decode_access_token, get_user_by_id_cached, get_user_by_id
from app.config import settings
from app.database import get_db_session
from app.sites.models import (
    AIChatMessage,
    AIChatMessageRole,
    AIChatSession,
    GeneratedSite,
    SiteDraft,
    SiteStatus,
)
from app.sites.site_schema import SiteSchema

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AI_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 4096
_MAX_MESSAGES_PER_MINUTE = 20
_HEARTBEAT_INTERVAL = 30  # seconds
_MAX_HISTORY_MESSAGES = 50  # keep last N messages in context

# Cost per 1M tokens (USD) — Haiku 4.5
_INPUT_COST_PER_1M = 1.00
_OUTPUT_COST_PER_1M = 5.00

# Shared httpx client for Anthropic API
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=120.0,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=60,
            ),
        )
    return _http_client


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
Du är en AI-assistent som hjälper användare att redigera sin hemsida på Qvicko-plattformen.
Du pratar på samma språk som hemsidans innehåll. Svara alltid kort och koncist.

REGLER:
1. Svara max 2-3 meningar för vanliga svar.
2. Ställ förtydligande frågor om instruktionen är otydlig eller om du behöver bekräfta något.
3. När du gör ändringar, beskriv kort vad du ändrade och inkludera SEDAN ett JSON-block med de ändrade nycklarna.
4. JSON-blocket MÅSTE vara inneslutet i ```json ... ``` markdown-block.
5. Returnera BARA de top-level nycklar som ändrades — INTE hela site_data. Systemet mergar dina ändringar.
6. Tillgängliga sektionstyper: hero, about, features, stats, services, process, gallery, team, testimonials, faq, cta, contact, pricing, video, logo_cloud, custom_content, banner, ranking, quiz, page_content
7. För att TA BORT en sektion: sätt den till null OCH ta bort den från section_order.
8. För att LÄGGA TILL en sektion: inkludera dess data OCH lägg till den i section_order på önskad position.
9. För att ÄNDRA ORDNING: returnera en uppdaterad section_order-array.
10. Alla texter ska matcha språket i befintligt innehåll om användaren inte ber om annat.
11. Du kan INTE ändra bilder — meddela användaren att de behöver ladda upp bilder manuellt.
12. Ändra aldrig branding.colors eller branding.fonts om användaren inte uttryckligen ber om det.

AKTUELL SECTION_ORDER:
{section_order}

AKTUELLA SEKTIONER:
{sections_summary}
"""


def _build_system_prompt(site_data: dict) -> str:
    """Build the system prompt with current site state."""
    section_order = site_data.get("section_order", [])
    extra_sections = site_data.get("extra_sections", {}) or {}

    # Build summary of each active section
    sections = []
    for key in section_order:
        if key in extra_sections:
            sec = extra_sections[key]
            sections.append(f"- {key} (typ: {sec.get('type', '?')}): {json.dumps(sec.get('data', {}), ensure_ascii=False)[:500]}")
        elif key in site_data and site_data[key] is not None:
            sections.append(f"- {key}: {json.dumps(site_data[key], ensure_ascii=False)[:500]}")
        else:
            sections.append(f"- {key}: (tom/inaktiv)")

    return _SYSTEM_PROMPT_TEMPLATE.format(
        section_order=json.dumps(section_order, ensure_ascii=False),
        sections_summary="\n".join(sections) if sections else "(inga aktiva sektioner)",
    )


# ---------------------------------------------------------------------------
# JSON patch extraction & merge
# ---------------------------------------------------------------------------

def _extract_site_data_patch(ai_response: str) -> dict | None:
    """Extract a JSON patch from the AI response (```json ... ``` block)."""
    if "```json" not in ai_response:
        return None
    try:
        json_str = ai_response.split("```json")[1].split("```")[0].strip()
        return json.loads(json_str)
    except (IndexError, json.JSONDecodeError) as e:
        logger.warning("Failed to parse AI JSON patch: %s", e)
        return None


def _deep_merge(base: dict, patch: dict) -> dict:
    """Deep-merge patch into base. Patch values override base values.
    None values in patch delete the key from base."""
    merged = dict(base)
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _validate_and_merge(current_data: dict, patch: dict) -> dict | None:
    """Merge patch into current data and validate against SiteSchema.
    Returns merged data or None if invalid."""
    merged = _deep_merge(current_data, patch)
    try:
        SiteSchema.model_validate(merged)
        return merged
    except ValidationError as e:
        logger.warning("AI patch failed validation: %s", e)
        return None


# ---------------------------------------------------------------------------
# Claude API streaming
# ---------------------------------------------------------------------------

async def _stream_claude_response(
    system_prompt: str,
    messages: list[dict],
    websocket: WebSocket,
) -> tuple[str, int, int]:
    """Stream a Claude API response over the WebSocket.

    Returns (full_text, input_tokens, output_tokens).
    """
    payload = {
        "model": _AI_MODEL,
        "max_tokens": _MAX_TOKENS,
        "system": system_prompt,
        "messages": messages,
        "stream": True,
    }

    client = _get_http_client()
    full_text = ""
    input_tokens = 0
    output_tokens = 0

    async with client.stream(
        "POST",
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": settings.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
    ) as response:
        if response.status_code != 200:
            body = await response.aread()
            logger.error("Claude API error %d: %s", response.status_code, body[:500])
            raise RuntimeError(f"Claude API returned {response.status_code}")

        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break

            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")

            if event_type == "content_block_delta":
                delta = event.get("delta", {})
                text = delta.get("text", "")
                if text:
                    full_text += text
                    await websocket.send_json({"type": "chunk", "content": text})

            elif event_type == "message_delta":
                usage = event.get("usage", {})
                output_tokens = usage.get("output_tokens", output_tokens)

            elif event_type == "message_start":
                usage = event.get("message", {}).get("usage", {})
                input_tokens = usage.get("input_tokens", 0)

    return full_text, input_tokens, output_tokens


# ---------------------------------------------------------------------------
# Draft saving (reuses same pattern as resolvers.py save_draft)
# ---------------------------------------------------------------------------

async def _save_draft(db, site_id: str, draft_data: dict) -> None:
    """Upsert site draft with new data."""
    result = await db.execute(
        select(SiteDraft).where(SiteDraft.site_id == site_id)
    )
    draft = result.scalar_one_or_none()

    if draft:
        draft.draft_data = draft_data
        draft.updated_at = datetime.now(timezone.utc)
    else:
        draft = SiteDraft(site_id=site_id, draft_data=draft_data)
        db.add(draft)

    await db.flush()


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/ai-chat/{site_id}")
async def ai_chat_websocket(websocket: WebSocket, site_id: str):
    """WebSocket endpoint for AI chat theme editing."""

    # --- Auth: extract JWT from query param ---
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    user_id = decode_access_token(token)
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token")
        return

    user = await get_user_by_id_cached(user_id)
    if not user:
        # Fallback to DB lookup
        async with get_db_session() as db:
            user = await get_user_by_id(db, user_id)
    if not user:
        await websocket.close(code=4001, reason="User not found")
        return

    # --- Load site & verify ownership ---
    async with get_db_session() as db:
        result = await db.execute(
            select(GeneratedSite)
            .where(GeneratedSite.id == site_id)
            .options(selectinload(GeneratedSite.lead))
        )
        site = result.scalar_one_or_none()

    if not site:
        await websocket.close(code=4004, reason="Site not found")
        return

    is_owner = site.lead and site.lead.created_by == str(user.id)
    if not user.is_superuser and not is_owner:
        await websocket.close(code=4003, reason="Permission denied")
        return

    if site.status not in (SiteStatus.DRAFT, SiteStatus.PURCHASED):
        await websocket.close(code=4003, reason="Published sites cannot be edited via AI chat")
        return

    # --- Accept connection ---
    await websocket.accept()
    logger.info("AI chat connected: user=%s site=%s", user.id, site_id)

    # --- Get or create chat session & load history ---
    async with get_db_session() as db:
        session_result = await db.execute(
            select(AIChatSession)
            .where(
                AIChatSession.site_id == site_id,
                AIChatSession.user_id == str(user.id),
                AIChatSession.is_active == True,  # noqa: E712
            )
            .options(selectinload(AIChatSession.messages))
        )
        chat_session = session_result.scalar_one_or_none()

        if not chat_session:
            chat_session = AIChatSession(
                site_id=site_id,
                user_id=str(user.id),
                is_active=True,
            )
            db.add(chat_session)
            await db.flush()
            await db.refresh(chat_session, attribute_names=["messages"])

        # Send history to client
        history = []
        for msg in (chat_session.messages or [])[-_MAX_HISTORY_MESSAGES:]:
            history.append({
                "id": msg.id,
                "role": msg.role.value,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat(),
            })

        await db.commit()

    await websocket.send_json({"type": "history", "messages": history})

    # --- Rate limiting state ---
    message_timestamps: list[float] = []

    # --- Current site data (start from draft if available, else published) ---
    async with get_db_session() as db:
        draft_result = await db.execute(
            select(SiteDraft).where(SiteDraft.site_id == site_id)
        )
        draft = draft_result.scalar_one_or_none()
    current_site_data: dict = (draft.draft_data if draft else site.site_data) or {}

    # --- Message loop ---
    try:
        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=_HEARTBEAT_INTERVAL + 10,
                )
            except asyncio.TimeoutError:
                # Send a ping to keep connection alive
                try:
                    await websocket.send_json({"type": "pong"})
                except Exception:
                    break
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = msg.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type != "message":
                continue

            content = (msg.get("content") or "").strip()
            if not content:
                continue

            # --- Rate limiting ---
            now = time.monotonic()
            message_timestamps = [t for t in message_timestamps if now - t < 60]
            if len(message_timestamps) >= _MAX_MESSAGES_PER_MINUTE:
                await websocket.send_json({
                    "type": "error",
                    "message": "Du skickar meddelanden för snabbt. Vänta en stund.",
                })
                continue
            message_timestamps.append(now)

            # --- Save user message ---
            async with get_db_session() as db:
                user_msg = AIChatMessage(
                    session_id=chat_session.id,
                    role=AIChatMessageRole.USER,
                    content=content,
                )
                db.add(user_msg)
                await db.commit()
                user_msg_id = user_msg.id

            # --- Build Claude messages from history ---
            async with get_db_session() as db:
                hist_result = await db.execute(
                    select(AIChatMessage)
                    .where(AIChatMessage.session_id == chat_session.id)
                    .order_by(AIChatMessage.created_at)
                )
                all_msgs = hist_result.scalars().all()

            claude_messages = []
            for m in all_msgs[-_MAX_HISTORY_MESSAGES:]:
                claude_messages.append({
                    "role": m.role.value,
                    "content": m.content,
                })

            system_prompt = _build_system_prompt(current_site_data)

            # --- Stream Claude response ---
            try:
                full_text, input_tokens, output_tokens = await _stream_claude_response(
                    system_prompt=system_prompt,
                    messages=claude_messages,
                    websocket=websocket,
                )
            except Exception as e:
                logger.exception("Claude API streaming error")
                await websocket.send_json({
                    "type": "error",
                    "message": f"AI-tjänsten svarade inte. Försök igen. ({type(e).__name__})",
                })
                continue

            # --- Save assistant message ---
            total_tokens = input_tokens + output_tokens
            cost_usd = (
                (input_tokens / 1_000_000) * _INPUT_COST_PER_1M
                + (output_tokens / 1_000_000) * _OUTPUT_COST_PER_1M
            )

            # --- Check for site data changes ---
            patch = _extract_site_data_patch(full_text)
            site_data_snapshot = None

            if patch:
                merged = _validate_and_merge(current_site_data, patch)
                if merged:
                    current_site_data = merged
                    site_data_snapshot = merged

                    # Save as draft
                    async with get_db_session() as db:
                        await _save_draft(db, site_id, merged)
                        await db.commit()

                    # Send updated site data to client
                    await websocket.send_json({
                        "type": "site_update",
                        "site_data": merged,
                    })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Ändringarna kunde inte valideras. Försök beskriva vad du vill ändra på ett annat sätt.",
                    })

            # Save assistant message to DB
            async with get_db_session() as db:
                assistant_msg = AIChatMessage(
                    session_id=chat_session.id,
                    role=AIChatMessageRole.ASSISTANT,
                    content=full_text,
                    site_data_snapshot=site_data_snapshot,
                    tokens_used=total_tokens,
                )
                db.add(assistant_msg)
                await db.commit()
                assistant_msg_id = assistant_msg.id

            # Send message_complete
            await websocket.send_json({
                "type": "message_complete",
                "content": full_text,
                "message_id": assistant_msg_id,
            })

    except WebSocketDisconnect:
        logger.info("AI chat disconnected: user=%s site=%s", user.id, site_id)
    except Exception:
        logger.exception("AI chat unexpected error: user=%s site=%s", user.id if user else "?", site_id)
        try:
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass
