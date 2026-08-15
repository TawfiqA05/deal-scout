"""
Deal Scout negotiation drafter — powered by Google Gemini (free).
When the verdict is NEGOTIATE, this writes a friendly, direct message
with a specific offer number — FOR YOU TO REVIEW AND SEND YOURSELF.
Nothing in this tool ever sends a message automatically.
"""

import os

import requests

import settings

API_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
          "{model}:generateContent")

PROMPT = """Write a short marketplace negotiation message for me to send to a seller.

Item: {title}
Their asking price: ${asking}
My offer: ${offer}
Known condition notes: {condition}
Open questions worth asking: {questions}

Rules:
- Friendly and casual, but confident — not apologetic, not stiff
- 2-4 sentences max, the way real people message on marketplace apps
- Include the specific offer number ${offer}
- If there are open questions, work ONE of them in naturally
- No lowball insults, no fake urgency, no claiming flaws we haven't seen
- Sound like a real person, not a template

Respond with ONLY the message text, nothing else."""


def draft_message(title: str, asking_price: float, offer: float,
                  condition: str | None, missing_info: list[str]) -> str:
    """Returns the draft message text. Falls back to a simple template
    if the API isn't available — never crashes."""
    if settings.DEMO_MODE:
        return (f"Hey! Is the {title.replace('DEMO: ', '')} still available? "
                f"I can pick it up today and pay cash — would you take "
                f"${offer:.0f}? Also, does the battery still hold a charge?")

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return _template(title, offer)

    questions = "; ".join(missing_info[:3]) if missing_info else "(none)"
    try:
        r = requests.post(
            API_URL.format(model=settings.GEMINI_MODEL),
            params={"key": api_key},
            headers={"content-type": "application/json"},
            json={"contents": [{"parts": [{"text": PROMPT.format(
                      title=title, asking=asking_price, offer=f"{offer:.0f}",
                      condition=condition or "(unknown)",
                      questions=questions)}]}],
                  "generationConfig": {"maxOutputTokens": 300}},
            timeout=60)
        r.raise_for_status()
        candidates = r.json().get("candidates", [])
        if not candidates:
            return _template(title, offer)
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        return text.strip() or _template(title, offer)
    except (requests.RequestException, KeyError, IndexError):
        return _template(title, offer)


def _template(title: str, offer: float) -> str:
    return (f"Hi! Is this still available? I'm interested and can pick up "
            f"whenever works for you — would you take ${offer:.0f}?")
