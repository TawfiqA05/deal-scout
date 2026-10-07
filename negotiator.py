"""
Deal Scout negotiation drafter — powered by Google Gemini (free).
When the verdict is NEGOTIATE, this writes a friendly, direct message
with a specific offer number — FOR YOU TO REVIEW AND SEND YOURSELF.
Nothing in this tool ever sends a message automatically.
"""

import os

import demo_data
import gemini
import settings

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
        return demo_data.negotiation_message(title, offer)

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return _template(title, offer)

    questions = "; ".join(missing_info[:3]) if missing_info else "(none)"
    try:
        text = gemini.generate(api_key, [{"text": PROMPT.format(
            title=title, asking=asking_price, offer=f"{offer:.0f}",
            condition=condition or "(unknown)", questions=questions)}],
            max_tokens=300, timeout=60)
    except gemini.GeminiError:
        return _template(title, offer)
    return text.strip() or _template(title, offer)


def _template(title: str, offer: float) -> str:
    return (f"Hi! Is this still available? I'm interested and can pick up "
            f"whenever works for you — would you take ${offer:.0f}?")
