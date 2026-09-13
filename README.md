# Ad Generator — Mobile Game Ad Intelligence Tool

A single-file Python CLI tool that generates data-driven, short-form video
ad concepts and ad copy for mobile game user-acquisition (UA) campaigns,
using the Gemini API — with a built-in mock-data fallback so it **always
runs successfully**, API key or not.

---

## Features

- **Interactive CLI intake** — prompts for Game Name, Genre, and Target
  Audience.
- **Gemini-powered creative generation**
  - 3 distinct short-form ad script concepts for **Meta (Reels) & TikTok**,
    each with a **Hook**, **Core Gameplay Concept**, and **Call To Action**.
  - 5 short-form ad copy variants (headline + body + CTA) for campaign copy
    testing.
- **Automatic mock-data fallback** — if the Gemini SDK isn't installed, no
  API key is set, or the live call fails for any reason (network, rate
  limit, malformed response), the script transparently generates
  template-based mock content instead of crashing.
- **Retry logic** — live API calls are retried with a short backoff before
  falling back to mock data.
- **Transparent engagement scoring engine** — every concept gets a 0–100
  score based on:
  - Hook length (ideal: 5–12 words)
  - Action-verb density (from a curated verb list)
  - Clarity (average sentence length across the concept text)
- **Clean structured exports**
  - `campaign_report.json` — machine-readable, for pipelines/dashboards.
  - `campaign_summary.md` — human-readable, ranked and formatted.
- **Zero required setup** — runs out of the box with no API key.

---

## Prerequisites

- Python 3.10+
- (Optional) A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)
  if you want live, model-generated concepts instead of mock data.

---

## Installation

```bash
# 1. Clone or copy the project files into a folder
cd ad-generator/

# 2. (Recommended) Create a virtual environment
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Setup

### Option A — Environment variable (quickest)

```bash
export GEMINI_API_KEY="your-api-key-here"          # macOS / Linux
setx GEMINI_API_KEY "your-api-key-here"             # Windows (new shell)
```

### Option B — `.env` file (recommended for local dev)

Create a `.env` file in the project root:

```
GEMINI_API_KEY=your-api-key-here
```

`python-dotenv` (included in `requirements.txt`) loads this automatically —
no extra code needed.

### No API key?

That's fine. Just run the script — it will log that it's continuing in
mock-data mode and generate fully-structured, on-topic placeholder content
so the rest of your pipeline (scoring, exports) can still be tested and
used end-to-end.

### Optional: choosing a model

By default the script uses `gemini-3.8-flash`. Gemini model names change
over time as Google ships new versions and retires old ones. If you get a
"model not found" style error, check the current list at
<https://ai.google.dev/gemini-api/docs/models> and override the default
with:

```bash
export GEMINI_MODEL="gemini-3.8-flash"   # or whichever current model ID you prefer
```

---

## Usage

```bash
python ad_generator.py
```

Sample interactive session:

```
================================================================
 MOBILE GAME AD INTELLIGENCE GENERATOR
================================================================
Game Name: Block Puzzle Pro
Genre (e.g. Hyper-casual, Puzzle, Strategy): Puzzle
Target Audience (e.g. Gen Z mobile gamers, casual commuters): Casual commuters aged 25-40

10:14:02 | INFO    | Calling Gemini (gemini-3.8-flash) for ad concepts...

================================================================
 Done! Generated 3 concepts and 5 ad copy variants.
 Data source:     gemini-api
 JSON report:     /path/to/campaign_report.json
 Markdown report: /path/to/campaign_summary.md
================================================================

Top concept (score 96.5/100):
  Hook: Can you beat this level in under ten seconds
```

---

## Output Files

### `campaign_report.json`

Structured output for downstream tooling (dashboards, spreadsheets,
pipelines):

```json
{
  "metadata": {
    "generated_at_utc": "2026-09-14T10:14:05+00:00",
    "game_name": "Block Puzzle Pro",
    "genre": "Puzzle",
    "target_audience": "Casual commuters aged 25-40",
    "data_source": "gemini-api",
    "model_name": "gemini-3.8-flash"
  },
  "ad_concepts": [
    {
      "id": 1,
      "hook": "...",
      "gameplay_concept": "...",
      "call_to_action": "...",
      "platform_notes": "...",
      "engagement_score": 96.5,
      "score_breakdown": {
        "hook_length_score": 100.0,
        "action_verb_count": 2,
        "action_verb_score": 60.0,
        "clarity_score": 100.0,
        "weighted_total": 96.5
      },
      "rank": 1
    }
  ],
  "ad_copy_variants": [
    { "id": 1, "headline": "...", "body": "...", "cta": "..." }
  ],
  "insights": {
    "average_engagement_score": 91.3,
    "top_concept_id": 1,
    "top_concept_hook": "..."
  }
}
```

### `campaign_summary.md`

The same data rendered as a clean, ranked, human-readable Markdown report —
ready to paste into a Notion doc, Slack message, or creative brief.

---

## Scoring Methodology

Every concept is scored 0–100 using three weighted signals:

| Signal          | Weight | What it measures                                                                 |
|------------------|:------:|-----------------------------------------------------------------------------------|
| Hook length      | 30%    | Word count vs. an ideal range of 5–12 words (the sweet spot for a scroll-stopper). |
| Action verbs     | 35%    | How many words from a curated action-verb list (e.g. *crush, unlock, dodge, swipe*) appear in the concept. |
| Clarity          | 35%    | Average sentence length across the concept text — too short under-explains it, too long is a run-on. |

This is intentionally a simple, transparent heuristic (not a machine-learned
model) — it's meant to give you a fast, explainable first-pass ranking
across generated concepts, not a guarantee of real-world ad performance.

---

## A Note on the Gemini Python SDK

This project uses **`google-genai`**, the Gemini API SDK Google currently
recommends. If you've previously seen tutorials using
`import google.generativeai as genai`, note that Google deprecated that
package in favor of the unified `google-genai` SDK. This script is built
on the current SDK to stay production-ready; if your existing codebase
still depends on the old package, see Google's official migration guide
for the (fairly mechanical) code changes needed.

---

## Project Structure

```
ad-generator/
├── ad_generator.py     # Main script (this is the only file you run)
├── requirements.txt    # Python dependencies
├── README.md           # This file
├── campaign_report.json    # Generated on run
└── campaign_summary.md     # Generated on run
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Script logs "not installed" and uses mock data | `google-genai` isn't installed | `pip install -r requirements.txt` |
| Script logs "No GEMINI_API_KEY... continuing with mock data" | Env var not set | Export it or add it to `.env` |
| Live calls fail, falls back to mock data | Invalid key, expired model name, rate limit, or network issue | Check the logged error; verify your key at [Google AI Studio](https://aistudio.google.com/apikey); check current model IDs at the [models page](https://ai.google.dev/gemini-api/docs/models) |
| `ModuleNotFoundError: No module named 'google'` | Dependencies not installed in the active environment | Confirm your virtual environment is activated, then reinstall |

---

## License

Provided as-is for internal tooling / prototyping use. Adapt freely for
your own ad-intelligence pipeline.
