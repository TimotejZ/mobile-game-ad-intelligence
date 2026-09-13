#!/usr/bin/env python3
"""
ad_generator.py
================

Mobile Game Ad Intelligence Generator.

This tool interviews the user about a mobile game (name, genre, target
audience), then uses the Gemini API to generate:

    1. Three (3) distinct short-form video ad script concepts tailored for
       Meta (Reels) and TikTok, each with a Hook, a Core Gameplay Concept,
       and a Call To Action.
    2. Five (5) short-form ad copy variants (headline + body + CTA) suitable
       for mobile ad campaign copy testing.

Every concept is then run through a lightweight, transparent engagement
scoring engine based on hook length, action-verb density, and clarity, and
the results are exported to:

    - campaign_report.json  (machine-readable, structured)
    - campaign_summary.md   (human-readable, formatted)

Design goals
------------
- The script ALWAYS runs to completion. If the ``google-genai`` package is
  not installed, no ``GEMINI_API_KEY`` is configured, or the live API call
  fails for any reason, the script transparently falls back to a
  template-based mock data generator so the pipeline never breaks.
- No third-party dependency is strictly required to execute the script.

Usage
-----
    python ad_generator.py

Environment variables
----------------------
    GEMINI_API_KEY   Your Gemini API key (from Google AI Studio).
                      If unset, mock data is used automatically.
    GEMINI_MODEL     Optional. Overrides the default Gemini model name.
                      See https://ai.google.dev/gemini-api/docs/models for
                      current model IDs (this list changes over time).
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Optional: load a local .env file if python-dotenv is installed. This is
# purely a developer convenience and the script works fine without it.
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Optional dependency: Google Gen AI SDK (the current, supported SDK for the
# Gemini API -- see the README for a note on the older `google-generativeai`
# package). The script must remain fully functional even if this import
# fails, so it is wrapped and checked via GENAI_SDK_AVAILABLE everywhere.
# ---------------------------------------------------------------------------
try:
    from google import genai
    from google.genai import types as genai_types

    GENAI_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when dep is absent
    GENAI_SDK_AVAILABLE = False


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ad_generator")


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------
ENV_API_KEY = "GEMINI_API_KEY"
ENV_MODEL_NAME = "GEMINI_MODEL"

# Sensible default; override with the GEMINI_MODEL env var as the Gemini
# model lineup evolves. Check https://ai.google.dev/gemini-api/docs/models
# if you see a 404 / model-not-found error.
DEFAULT_MODEL_NAME = "gemini-3.8-flash"

NUM_CONCEPTS = 3
NUM_VARIANTS = 5

MAX_API_RETRIES = 2
RETRY_BACKOFF_SECONDS = 2.0

JSON_REPORT_PATH = "campaign_report.json"
MARKDOWN_REPORT_PATH = "campaign_summary.md"

# Vocabulary used by the engagement-scoring heuristic. Multi-word phrases
# (like "level up") are supported by the regex-based counter below.
ACTION_VERBS = (
    "crush", "smash", "build", "escape", "unlock", "dodge", "collect",
    "survive", "run", "jump", "solve", "match", "swipe", "tap", "win",
    "beat", "explore", "discover", "level up", "customize", "upgrade",
    "battle", "race", "conquer", "defend", "attack", "grab", "slice",
    "stack", "merge", "download", "play", "join", "master", "climb",
    "blast", "rescue", "outsmart", "outrun", "chase",
)

# Scoring weights must sum to 1.0.
SCORE_WEIGHTS = {
    "hook_length": 0.30,
    "action_verbs": 0.35,
    "clarity": 0.35,
}


# ===========================================================================
# Section 1: User input
# ===========================================================================
def prompt_nonempty(label: str, hint: str = "") -> str:
    """Prompt the user until a non-empty string is provided."""
    suffix = f" ({hint})" if hint else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        print("  -> This field can't be empty. Please try again.")


def get_user_input() -> Tuple[str, str, str]:
    """Collect Game Name, Genre, and Target Audience from the user."""
    print("=" * 64)
    print(" MOBILE GAME AD INTELLIGENCE GENERATOR")
    print("=" * 64)
    game_name = prompt_nonempty("Game Name")
    genre = prompt_nonempty("Genre", "e.g. Hyper-casual, Puzzle, Strategy")
    audience = prompt_nonempty(
        "Target Audience", "e.g. Gen Z mobile gamers, casual commuters"
    )
    return game_name, genre, audience


# ===========================================================================
# Section 2: Gemini client setup
# ===========================================================================
def get_gemini_client_and_model() -> Tuple[Optional["genai.Client"], str]:
    """
    Build a Gemini client from environment variables.

    Returns
    -------
    (client, model_name)
        `client` is None whenever the SDK isn't installed, no API key is
        configured, or client construction fails -- in every such case the
        caller is expected to fall back to mock data generation.
    """
    model_name = (
        os.environ.get(ENV_MODEL_NAME, "").strip() or DEFAULT_MODEL_NAME
    )

    if not GENAI_SDK_AVAILABLE:
        logger.info(
            "'google-genai' is not installed. Run "
            "'pip install -r requirements.txt' to enable live Gemini "
            "calls. Continuing with mock data."
        )
        return None, model_name

    api_key = os.environ.get(ENV_API_KEY, "").strip()
    if not api_key:
        logger.info(
            "No %s environment variable found. Continuing with mock "
            "data. Set it to enable live Gemini calls.",
            ENV_API_KEY,
        )
        return None, model_name

    try:
        client = genai.Client(api_key=api_key)
        return client, model_name
    except Exception as exc:  # noqa: BLE001 - any failure -> mock fallback
        logger.warning(
            "Failed to initialize the Gemini client (%s). Falling back "
            "to mock data.",
            exc,
        )
        return None, model_name


# ===========================================================================
# Section 3: Prompt construction & live API call
# ===========================================================================
def build_prompt(game_name: str, genre: str, audience: str) -> str:
    """Construct the instruction prompt sent to Gemini."""
    schema_hint = {
        "concepts": [
            {
                "hook": (
                    "string, 5-12 words, an attention-grabbing opening "
                    "line for the first 1-2 seconds of the ad"
                ),
                "gameplay_concept": (
                    "string, 1-2 sentences describing the core gameplay "
                    "loop shown on screen"
                ),
                "call_to_action": "string, a short punchy CTA",
                "platform_notes": (
                    "string, one short line on adapting this for Meta "
                    "vs. TikTok"
                ),
            }
        ],
        "ad_variants": [
            {
                "headline": "string, under 8 words",
                "body": "string, 1-2 short sentences",
                "cta": "string, a short punchy CTA",
            }
        ],
    }
    schema_json = json.dumps(schema_hint, indent=2)

    return f"""
You are a senior user-acquisition (UA) creative strategist for mobile games.

Game name: {game_name}
Genre: {genre}
Target audience: {audience}

TASK 1: Write exactly {NUM_CONCEPTS} distinct short-form video ad script
concepts (for Meta Reels & TikTok). Each concept needs:
  - A Hook: the first line/visual beat that stops the scroll.
  - A Core Gameplay Concept: what the viewer sees played out on screen.
  - A Call To Action.
Make the three concepts meaningfully different in angle (for example:
skill-challenge, relatable/POV, and satisfying/oddly-satisfying styles).

TASK 2: Write exactly {NUM_VARIANTS} short-form ad copy variants (headline +
body + CTA) suitable for mobile ad campaign copy testing.

Respond with ONLY valid JSON, no markdown code fences, no commentary,
matching exactly this shape:

{schema_json}
""".strip()


def _parse_json_payload(raw_text: str) -> Dict[str, Any]:
    """Parse a JSON payload, stripping stray markdown fences if present."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _validate_payload(payload: Dict[str, Any]) -> None:
    """Raise ValueError if the payload doesn't match the expected shape."""
    if not isinstance(payload, dict):
        raise ValueError("Top-level JSON payload must be an object.")
    if "concepts" not in payload or "ad_variants" not in payload:
        raise ValueError("Response JSON is missing required keys.")
    if not payload["concepts"] or not payload["ad_variants"]:
        raise ValueError("Response JSON contained empty lists.")


def call_gemini_api(
    client: "genai.Client",
    model_name: str,
    prompt: str,
    max_retries: int = MAX_API_RETRIES,
) -> Optional[Dict[str, Any]]:
    """
    Call the Gemini API and return the parsed JSON payload.

    Retries transient failures with a short linear backoff. Returns None
    (triggering the mock-data fallback) if every attempt fails.
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 2):  # +1 for the initial try
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.9,
                    response_mime_type="application/json",
                ),
            )
            raw_text = (getattr(response, "text", "") or "").strip()
            if not raw_text:
                raise ValueError("Empty response from Gemini API.")

            payload = _parse_json_payload(raw_text)
            _validate_payload(payload)
            return payload

        except Exception as exc:  # noqa: BLE001 - broad by design
            last_error = exc
            if attempt <= max_retries:
                wait_time = RETRY_BACKOFF_SECONDS * attempt
                logger.warning(
                    "Gemini API attempt %d failed (%s). Retrying in "
                    "%.0fs...",
                    attempt,
                    exc,
                    wait_time,
                )
                time.sleep(wait_time)

    logger.warning(
        "Gemini API call failed after %d attempt(s). Falling back to "
        "mock data. Last error: %s",
        max_retries + 1,
        last_error,
    )
    return None


# ===========================================================================
# Section 4: Mock data generation (no external dependencies required)
# ===========================================================================
def _pick_verbs(count: int) -> List[str]:
    """Return `count` distinct, randomly chosen action verbs."""
    pool = list(ACTION_VERBS)
    random.shuffle(pool)
    return pool[:count]


def generate_mock_concepts(
    game_name: str, genre: str, audience: str
) -> List[Dict[str, str]]:
    """Produce 3 template-based ad concepts when no live API is available."""
    v = _pick_verbs(6)
    genre_lower = genre.lower()

    return [
        {
            "hook": f"Can you {v[0]} and {v[1]} faster than 98% of players?",
            "gameplay_concept": (
                f"A split-screen challenge shows two players racing to "
                f"{v[0]} through a {genre_lower} level, ending on a "
                f"satisfying win screen aimed squarely at {audience}."
            ),
            "call_to_action": f"Download {game_name} now and prove it.",
            "platform_notes": (
                "TikTok: add an on-screen countdown timer. Meta: add "
                "captions for sound-off viewers."
            ),
        },
        {
            "hook": (
                f"POV: you just found the most addictive {genre_lower} "
                "game of the year."
            ),
            "gameplay_concept": (
                f"First-person, hands-on gameplay shows the player tap "
                f"to {v[2]} and swipe to {v[3]}, with difficulty "
                "escalating every few seconds."
            ),
            "call_to_action": f"Tap the link and {v[2]} your way to the top.",
            "platform_notes": (
                "TikTok: native handheld filming style. Meta: pair with "
                "a carousel of level previews."
            ),
        },
        {
            "hook": f"This is oddly satisfying. Watch until the {v[4]}.",
            "gameplay_concept": (
                f"Smooth macro gameplay footage shows the player {v[4]} "
                f"objects in {game_name} while a progress bar fills, "
                f"designed to hook {audience} through visual payoff."
            ),
            "call_to_action": f"Install {game_name} for free today.",
            "platform_notes": (
                "TikTok: loop the final 2 seconds. Meta: crop natively "
                "for vertical Reels placement."
            ),
        },
    ]


def generate_mock_variants(
    game_name: str, genre: str, audience: str
) -> List[Dict[str, str]]:
    """Produce 5 template-based ad copy variants."""
    v = _pick_verbs(5)
    genre_lower = genre.lower()

    templates = [
        (
            f"{v[0].capitalize()} your way to the top",
            f"{game_name} throws a brand-new {genre_lower} challenge at "
            "you every level.",
            "Play free now",
        ),
        (
            f"Built for {audience}",
            f"{game_name} is the {genre_lower} game everyone's talking "
            "about.",
            "Download today",
        ),
        (
            f"Can you {v[1]} it?",
            f"Thousands of {audience} are already hooked on {game_name}.",
            "Try it free",
        ),
        (
            f"{v[2].capitalize()} smarter, not harder",
            f"Master the {genre_lower} loop that's breaking the internet.",
            "Get the app",
        ),
        (
            "Warning: highly addictive",
            f"{game_name} was designed to make you {v[3]} just one more "
            "level.",
            "Install now",
        ),
    ]
    return [
        {"headline": h, "body": b, "cta": c} for h, b, c in templates
    ]


# ===========================================================================
# Section 5: Engagement scoring engine
# ===========================================================================
def score_hook_length(hook: str) -> float:
    """Score a hook 0-100 based on how close its word count is to 5-12."""
    word_count = len(hook.split())
    ideal_min, ideal_max = 5, 12

    if ideal_min <= word_count <= ideal_max:
        return 100.0
    if word_count < ideal_min:
        deficit = ideal_min - word_count
        return max(0.0, 100.0 - deficit * 15.0)
    surplus = word_count - ideal_max
    return max(0.0, 100.0 - surplus * 10.0)


def count_action_verbs(text: str) -> int:
    """Count (whole-word / whole-phrase) occurrences of ACTION_VERBS."""
    lowered = text.lower()
    total = 0
    for verb in ACTION_VERBS:
        pattern = r"\b" + re.escape(verb) + r"\b"
        total += len(re.findall(pattern, lowered))
    return total


def score_action_verbs(verb_count: int) -> float:
    """Score 0-100 based on action-verb density (diminishing returns)."""
    if verb_count <= 0:
        return 10.0
    return min(100.0, verb_count * 30.0)


def score_clarity(text: str) -> float:
    """
    Score 0-100 based on average sentence length.

    Very short sentences fail to communicate the concept; very long,
    run-on sentences hurt clarity in a 15-30 second ad. The ideal range
    (6-16 words/sentence) is treated as fully clear.
    """
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    if not sentences:
        return 0.0

    avg_len = sum(len(s.split()) for s in sentences) / len(sentences)
    ideal_min, ideal_max = 6.0, 16.0

    if ideal_min <= avg_len <= ideal_max:
        return 100.0
    if avg_len < ideal_min:
        return max(0.0, 100.0 - (ideal_min - avg_len) * 8.0)
    return max(0.0, 100.0 - (avg_len - ideal_max) * 6.0)


def score_concept(concept: Dict[str, str]) -> Tuple[float, Dict[str, Any]]:
    """Compute the weighted engagement score and its breakdown."""
    hook = concept.get("hook", "")
    gameplay = concept.get("gameplay_concept", "")
    cta = concept.get("call_to_action", "")
    combined_text = " ".join([hook, gameplay, cta])

    hook_score = score_hook_length(hook)
    verb_count = count_action_verbs(combined_text)
    verb_score = score_action_verbs(verb_count)
    clarity_score = score_clarity(combined_text)

    total = (
        hook_score * SCORE_WEIGHTS["hook_length"]
        + verb_score * SCORE_WEIGHTS["action_verbs"]
        + clarity_score * SCORE_WEIGHTS["clarity"]
    )

    breakdown = {
        "hook_length_score": round(hook_score, 1),
        "action_verb_count": verb_count,
        "action_verb_score": round(verb_score, 1),
        "clarity_score": round(clarity_score, 1),
        "weighted_total": round(total, 1),
    }
    return round(total, 1), breakdown


def score_and_rank_concepts(
    raw_concepts: List[Dict[str, str]]
) -> List[Dict[str, Any]]:
    """Attach scores to each concept and sort best-first."""
    scored: List[Dict[str, Any]] = []

    for idx, concept in enumerate(raw_concepts, start=1):
        total, breakdown = score_concept(concept)
        scored.append(
            {
                "id": idx,
                "hook": concept.get("hook", ""),
                "gameplay_concept": concept.get("gameplay_concept", ""),
                "call_to_action": concept.get("call_to_action", ""),
                "platform_notes": concept.get("platform_notes", ""),
                "engagement_score": total,
                "score_breakdown": breakdown,
            }
        )

    scored.sort(key=lambda c: c["engagement_score"], reverse=True)
    for rank, concept in enumerate(scored, start=1):
        concept["rank"] = rank
    return scored


# ===========================================================================
# Section 6: Report assembly & export
# ===========================================================================
def build_report(
    game_name: str,
    genre: str,
    audience: str,
    source: str,
    model_name: str,
    concepts: List[Dict[str, Any]],
    variants: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Assemble the final report dictionary."""
    avg_score = (
        round(sum(c["engagement_score"] for c in concepts) / len(concepts), 1)
        if concepts
        else 0.0
    )

    return {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
            "game_name": game_name,
            "genre": genre,
            "target_audience": audience,
            "data_source": source,  # "gemini-api" or "mock-fallback"
            "model_name": model_name if source == "gemini-api" else "n/a",
        },
        "ad_concepts": concepts,
        "ad_copy_variants": [
            {"id": i, **variant} for i, variant in enumerate(variants, 1)
        ],
        "insights": {
            "average_engagement_score": avg_score,
            "top_concept_id": concepts[0]["id"] if concepts else None,
            "top_concept_hook": concepts[0]["hook"] if concepts else None,
        },
    }


def export_json(report: Dict[str, Any], path: str = JSON_REPORT_PATH) -> None:
    """Write the report to a structured JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def export_markdown(
    report: Dict[str, Any], path: str = MARKDOWN_REPORT_PATH
) -> None:
    """Write the report to a formatted Markdown file."""
    meta = report["metadata"]
    lines: List[str] = [
        f"# Campaign Ad Intelligence Report: {meta['game_name']}",
        "",
        f"- **Genre:** {meta['genre']}",
        f"- **Target Audience:** {meta['target_audience']}",
        f"- **Generated (UTC):** {meta['generated_at_utc']}",
        f"- **Data Source:** {meta['data_source']}",
        f"- **Model:** {meta['model_name']}",
        "",
        "## Ranked Ad Script Concepts",
        "",
    ]

    for concept in report["ad_concepts"]:
        bd = concept["score_breakdown"]
        lines.extend(
            [
                f"### #{concept['rank']} - Engagement Score: "
                f"{concept['engagement_score']}/100",
                "",
                f"**Hook:** {concept['hook']}",
                "",
                f"**Core Gameplay Concept:** {concept['gameplay_concept']}",
                "",
                f"**Call To Action:** {concept['call_to_action']}",
                "",
            ]
        )
        if concept.get("platform_notes"):
            lines.extend([f"**Platform Notes:** {concept['platform_notes']}", ""])
        lines.extend(
            [
                f"*Score breakdown - hook length: {bd['hook_length_score']}, "
                f"action verbs: {bd['action_verb_count']} "
                f"(score {bd['action_verb_score']}), "
                f"clarity: {bd['clarity_score']}*",
                "",
                "---",
                "",
            ]
        )

    lines.extend(["## Short-Form Ad Copy Variants", ""])
    for variant in report["ad_copy_variants"]:
        lines.extend(
            [
                f"**Variant {variant['id']}: {variant['headline']}**",
                "",
                variant["body"],
                "",
                f"*CTA: {variant['cta']}*",
                "",
            ]
        )

    insights = report["insights"]
    lines.extend(
        [
            "## Insights",
            "",
            "- Average engagement score: "
            f"**{insights['average_engagement_score']}/100**",
            "- Top-performing concept: "
            f"**#{insights['top_concept_id']}** - "
            f"\"{insights['top_concept_hook']}\"",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ===========================================================================
# Section 7: Orchestration
# ===========================================================================
def main() -> None:
    """Run the full ad-intelligence generation pipeline."""
    game_name, genre, audience = get_user_input()

    client, model_name = get_gemini_client_and_model()

    result_payload: Optional[Dict[str, Any]] = None
    if client is not None:
        prompt = build_prompt(game_name, genre, audience)
        logger.info("Calling Gemini (%s) for ad concepts...", model_name)
        result_payload = call_gemini_api(client, model_name, prompt)

    if result_payload is not None:
        source = "gemini-api"
        raw_concepts = result_payload["concepts"][:NUM_CONCEPTS]
        raw_variants = result_payload["ad_variants"][:NUM_VARIANTS]
    else:
        source = "mock-fallback"
        raw_concepts = generate_mock_concepts(game_name, genre, audience)
        raw_variants = generate_mock_variants(game_name, genre, audience)

    concepts = score_and_rank_concepts(raw_concepts)
    variants = [
        {
            "headline": v.get("headline", ""),
            "body": v.get("body", ""),
            "cta": v.get("cta", ""),
        }
        for v in raw_variants
    ]

    report = build_report(
        game_name, genre, audience, source, model_name, concepts, variants
    )

    export_json(report)
    export_markdown(report)

    print("\n" + "=" * 64)
    print(
        f" Done! Generated {len(concepts)} concepts and "
        f"{len(variants)} ad copy variants."
    )
    print(f" Data source:     {source}")
    print(f" JSON report:     {os.path.abspath(JSON_REPORT_PATH)}")
    print(f" Markdown report: {os.path.abspath(MARKDOWN_REPORT_PATH)}")
    print("=" * 64)

    if concepts:
        top = concepts[0]
        print(f"\nTop concept (score {top['engagement_score']}/100):")
        print(f"  Hook: {top['hook']}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting.")
        sys.exit(1)
