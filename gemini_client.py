"""Gemini calls: plain text generation and the visual plan (vision + JSON)."""
import time
from pathlib import Path
from typing import List

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

RETRY_STATUS = {429, 500, 502, 503, 504}  # rate limit / overloaded: worth waiting for
RETRY_DELAYS = (5, 15, 45, 120)  # seconds before each retry (5 attempts in total)

PLAN_PROMPT = """You design the on-screen visuals for a viral vertical news video (TikTok/Shorts).
The narration below will be read aloud over the lead image. Produce:
- hook: the opening headline, 2-4 words, ALL CAPS, saying what happened (shown on screen at 0.3s).
- beats: 10-14 short on-screen callouts IN THE ORDER they are spoken. text = 1-3 words ALL CAPS.
  anchor_word = one word copied exactly from the narration at the moment the callout should appear.
  kind: number (money, counts, dates), key (the single most important phrase), fact (supporting phrase), place (location/names).
- focus_points: 4-6 normalized (x,y in 0-1, origin top-left) points on the IMAGE worth zooming into.

NEWS TITLE: {title}
NARRATION:
{narration}
"""


class Beat(BaseModel):
    text: str
    anchor_word: str
    kind: str = Field(description="number | key | fact | place")


class Point(BaseModel):
    x: float
    y: float


class Plan(BaseModel):
    hook: str
    beats: List[Beat]
    focus_points: List[Point]


class SocialCopy(BaseModel):
    youtube_title: str
    youtube_description: str
    facebook_description: str


def make_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def generate_with_retry(client, **kwargs):
    """`generate_content` that waits and retries on temporary Gemini errors (e.g. 503 high demand)."""
    for attempt, delay in enumerate(RETRY_DELAYS + (None,), start=1):
        try:
            return client.models.generate_content(**kwargs)
        except (errors.ServerError, errors.APIError) as exc:
            if delay is None or getattr(exc, "code", None) not in RETRY_STATUS:
                raise
            print(f"    - Gemini {exc.code} (attempt {attempt}/{len(RETRY_DELAYS) + 1}); retrying in {delay}s", flush=True)
            time.sleep(delay)


def generate_text(client, model: str, prompt: str) -> str:
    """Single-prompt text generation; returns stripped text ('' when the model returns none)."""
    response = generate_with_retry(client, model=model, contents=prompt)
    return (response.text or "").strip()


def generate_json(client, model: str, prompt: str, schema):
    """Single-prompt generation parsed into a pydantic `schema` instance."""
    response = generate_with_retry(
        client,
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema),
    )
    return response.parsed


def generate_plan(client, model: str, title: str, narration: str, image_path: Path) -> Plan:
    image_part = types.Part.from_bytes(data=image_path.read_bytes(), mime_type="image/jpeg")
    response = generate_with_retry(
        client,
        model=model,
        contents=[image_part, PLAN_PROMPT.format(title=title, narration=narration)],
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=Plan, temperature=0.7
        ),
    )
    return response.parsed
