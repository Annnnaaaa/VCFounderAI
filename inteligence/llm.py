"""Thin OpenAI wrapper enforcing STRICT structured outputs.

Every reasoning call in this lane goes through `structured()`, which uses the
SDK's `.parse` helper with a Pydantic response_format. That helper sets
`strict: true` and `additionalProperties: false` under the hood, so the model
physically cannot return a shape that fails our contract — no defensive JSON
parsing anywhere downstream.

Two model tiers:
  * VISION_MODEL — best vision-capable model on the key (deck extraction, memo).
  * CHEAP_MODEL  — fast/cheap model for the viability screen.
Both are env-overridable so we can swap as the key's access changes.
"""
from __future__ import annotations

import base64
import os
from typing import List, Type, TypeVar

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

# Load .env from the repo root (one level up) so all lanes share one file.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv()  # also honor a local .env if present

VISION_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
CHEAP_MODEL = os.getenv("OPENAI_CHEAP_MODEL", "gpt-4o-mini")

_client: OpenAI | None = None
T = TypeVar("T", bound=BaseModel)


def client() -> OpenAI:
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set (check repo-root .env)")
        _client = OpenAI(api_key=key)
    return _client


def _content_with_images(text: str, image_bytes: List[bytes]) -> list:
    parts: list = [{"type": "text", "text": text}]
    for b in image_bytes:
        b64 = base64.b64encode(b).decode()
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )
    return parts


def structured(
    schema: Type[T],
    system: str,
    user: str,
    *,
    images: List[bytes] | None = None,
    model: str | None = None,
    temperature: float = 0.1,
) -> T:
    """One strict structured-output call. Returns a validated instance of
    `schema`. Raises if the model refuses (we surface, never silently fake)."""
    mdl = model or (VISION_MODEL if images else VISION_MODEL)
    user_content = (
        _content_with_images(user, images) if images else user
    )
    completion = client().beta.chat.completions.parse(
        model=mdl,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        response_format=schema,
    )
    msg = completion.choices[0].message
    if getattr(msg, "refusal", None):
        raise RuntimeError(f"Model refused: {msg.refusal}")
    parsed = msg.parsed
    if parsed is None:
        raise RuntimeError("Model returned no parsable content")
    return parsed
