"""
Image generation service using Google Imagen (Nano Banana) via Google AI API.

Supports three model tiers:
  - nano-banana     : imagen-3.0-fast-generate-002 — fastest
  - nano-banana-2   : imagen-3.0-generate-002 — improved quality (default)
  - nano-banana-pro : imagen-3.0-generate-001 — highest quality

All models use the same GOOGLE_AI_API_KEY as Gemini.
This module provides the architecture for image generation/editing.
Integration into the site generation pipeline is planned for a future release.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GOOGLE_AI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Map our model names to Google Imagen model IDs
MODELS = {
    "nano-banana": {
        "name": "Nano Banana",
        "google_model": "imagen-4.0-fast-generate-001",
        "description": "Standard quality, fastest generation",
    },
    "nano-banana-2": {
        "name": "Nano Banana 2",
        "google_model": "imagen-4.0-generate-001",
        "description": "Improved quality, balanced speed",
    },
    "nano-banana-pro": {
        "name": "Nano Banana Pro",
        "google_model": "imagen-4.0-ultra-generate-001",
        "description": "Highest quality, production-grade",
    },
}


@dataclass
class ImageResult:
    """Result from an image generation request."""
    image_bytes: bytes
    mime_type: str
    model: str
    prompt: str


async def generate_image(
    prompt: str,
    model: str = "nano-banana-2",
    aspect_ratio: str = "1:1",
    number_of_images: int = 1,
) -> list[ImageResult]:
    """Generate images from a text prompt via Google Imagen API.

    Args:
        prompt: Text description of the desired image.
        model: Model tier (nano-banana, nano-banana-2, nano-banana-pro).
        aspect_ratio: Aspect ratio (e.g. "1:1", "16:9", "9:16", "4:3", "3:4").
        number_of_images: Number of images to generate (1-4).

    Returns:
        List of ImageResult with generated image bytes.

    Raises:
        RuntimeError: If the API key is missing or the API call fails.
    """
    api_key = settings.GOOGLE_AI_API_KEY
    if not api_key:
        raise RuntimeError("GOOGLE_AI_API_KEY is not configured")

    if model not in MODELS:
        raise ValueError(f"Unknown model: {model}. Available: {', '.join(MODELS)}")

    google_model = MODELS[model]["google_model"]
    url = f"{GOOGLE_AI_BASE_URL}/models/{google_model}:predict?key={api_key}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "instances": [{"prompt": prompt}],
                "parameters": {
                    "sampleCount": min(number_of_images, 4),
                    "aspectRatio": aspect_ratio,
                },
            },
        )
        if resp.status_code != 200:
            logger.error(
                "Imagen API error %d: %s", resp.status_code, resp.text[:500]
            )
            resp.raise_for_status()

        data = resp.json()
        predictions = data.get("predictions", [])

        results = []
        for pred in predictions:
            image_b64 = pred.get("bytesBase64Encoded", "")
            mime = pred.get("mimeType", "image/png")
            results.append(
                ImageResult(
                    image_bytes=base64.b64decode(image_b64),
                    mime_type=mime,
                    model=model,
                    prompt=prompt,
                )
            )

        logger.info(
            "Image generated: model=%s (%s) count=%d prompt=%s",
            model, google_model, len(results), prompt[:80],
        )

        return results


async def edit_image(
    image_bytes: bytes,
    prompt: str,
    model: str = "nano-banana-2",
    mime_type: str = "image/png",
) -> list[ImageResult]:
    """Edit an existing image based on a text prompt via Google Imagen API.

    Args:
        image_bytes: Raw bytes of the source image.
        prompt: Text description of the desired changes.
        model: Model tier to use.
        mime_type: MIME type of the source image.

    Returns:
        List of ImageResult with edited image bytes.
    """
    api_key = settings.GOOGLE_AI_API_KEY
    if not api_key:
        raise RuntimeError("GOOGLE_AI_API_KEY is not configured")

    if model not in MODELS:
        raise ValueError(f"Unknown model: {model}. Available: {', '.join(MODELS)}")

    google_model = MODELS[model]["google_model"]
    url = f"{GOOGLE_AI_BASE_URL}/models/{google_model}:predict?key={api_key}"

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "instances": [
                    {
                        "prompt": prompt,
                        "image": {
                            "bytesBase64Encoded": image_b64,
                        },
                    }
                ],
                "parameters": {
                    "sampleCount": 1,
                },
            },
        )
        if resp.status_code != 200:
            logger.error(
                "Imagen edit error %d: %s", resp.status_code, resp.text[:500]
            )
            resp.raise_for_status()

        data = resp.json()
        predictions = data.get("predictions", [])

        results = []
        for pred in predictions:
            out_b64 = pred.get("bytesBase64Encoded", "")
            out_mime = pred.get("mimeType", mime_type)
            results.append(
                ImageResult(
                    image_bytes=base64.b64decode(out_b64),
                    mime_type=out_mime,
                    model=model,
                    prompt=prompt,
                )
            )

        logger.info(
            "Image edited: model=%s (%s) prompt=%s",
            model, google_model, prompt[:80],
        )

        return results
