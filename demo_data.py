"""
Made-up data for demo mode: photo notes, comp titles and the sample
listing that any eBay link returns. Nothing here makes a network call.

Notes are picked by words in the title. Each set has a category from
settings.EBAY_CATEGORY_FEES so the fee matches the kind of item.
"""

import re

# Kept on the sample listing and on every note, because they are saved
# with the history row and nothing else marks a made-up row yet.
DEMO_PREFIX = "DEMO: "

SAMPLE_LISTING = {
    "title": "DEMO: DeWalt 20V Max Cordless Drill Kit (sample listing)",
    "asking_price": 55.00,
    "description": "Sample listing for demo mode. Comes with one battery "
                   "and the charger. Light wear on the housing.",
    "image_urls": [],
}

NOTE_SETS = [
    {
        "category": "tools",
        "keywords": ["drill", "driver", "saw", "sander", "grinder", "wrench",
                     "dewalt", "makita", "milwaukee", "ryobi", "ridgid",
                     "craftsman", "tool"],
        "condition": "Light scuffs on the housing. Looks like it works in "
                     "the photos.",
        "red_flags": ["No photo of it running",
                      "The battery and charger aren't shown"],
        "missing_info": ["Ask if the battery holds a charge",
                         "Ask whether the charger is included"],
        "question": "Does the battery still hold a charge?",
    },
    {
        "category": "video games",
        "keywords": ["nintendo", "switch", "playstation", "ps4", "ps5",
                     "xbox", "game boy", "gameboy", "wii", "console",
                     "controller", "video game"],
        "condition": "Light wear from normal use. Nothing looks broken in "
                     "the photos.",
        "red_flags": ["Can't tell if it's signed out of the owner's account",
                      "One photo looks like a stock image"],
        "missing_info": ["Ask if it's been reset and signed out",
                         "Ask which cables and controllers come with it"],
        "question": "Has it been reset and signed out of your account?",
    },
    {
        "category": "sneakers",
        "keywords": ["sneaker", "shoe", "jordan", "nike", "adidas", "yeezy",
                     "dunk", "new balance", "asics", "converse", "vans"],
        "condition": "Some creasing on the toe box and light wear on the "
                     "soles.",
        "red_flags": ["No photo of the size tag inside the shoe",
                      "The box label isn't shown, so the style code can't "
                      "be checked"],
        "missing_info": ["Ask for a photo of the size tag",
                         "Ask if the original box comes with them"],
        "question": "Do they come with the original box?",
    },
    {
        "category": "electronics",
        "keywords": ["phone", "iphone", "ipad", "tablet", "laptop", "macbook",
                     "headphones", "earbuds", "airpods", "camera", "speaker",
                     "monitor", "tv", "kindle", "sony", "bose", "samsung"],
        "condition": "Light wear on the outside. No cracks or dents in the "
                     "photos.",
        "red_flags": ["No photo of it powered on",
                      "The serial number isn't shown"],
        "missing_info": ["Ask for a photo of it turned on",
                         "Ask if it's ever been repaired or opened up"],
        "question": "Could you send a quick photo of it turned on?",
    },
]

GENERAL_NOTES = {
    "category": "default",
    "keywords": [],
    "condition": "Looks used but in decent shape. No damage shows in the "
                 "photos.",
    "red_flags": ["Only a few photos, and none up close",
                  "The listing doesn't say how old it is"],
    "missing_info": ["Ask for close-up photos of any wear",
                     "Ask how long they've had it"],
    "question": "Is there any wear or damage I should know about?",
}

# Endings for comp titles. The item title comes first.
COMP_ENDINGS = ["", " - Used", " - Pre-Owned", " - Good Condition",
                " - Excellent Condition", " - Very Good Condition",
                " - Light Wear", " - Free Shipping", " - Fast Shipping",
                " - Clean"]

EBAY_TITLE_LIMIT = 80


def clean_title(title: str) -> str:
    """The item title without the demo prefix or the sample-listing tag."""
    title = title.strip()
    if title.startswith(DEMO_PREFIX):
        title = title[len(DEMO_PREFIX):]
    return title.removesuffix(" (sample listing)").strip()


def notes_for(title: str) -> dict:
    """The note set whose keywords appear in the title, else the general one."""
    lowered = title.lower()
    for notes in NOTE_SETS:
        for word in notes["keywords"]:
            if re.search(rf"\b{re.escape(word)}s?\b", lowered):
                return notes
    return GENERAL_NOTES


def vision_report(title: str) -> dict:
    """A photo report shaped like the real one, with every note marked DEMO."""
    notes = notes_for(title)
    return {
        "condition": DEMO_PREFIX + notes["condition"],
        "condition_grade": "Good",
        "red_flags": [DEMO_PREFIX + f for f in notes["red_flags"]],
        "missing_info": [DEMO_PREFIX + q for q in notes["missing_info"]],
        "category_guess": notes["category"],
        "resale_title_suggestion": clean_title(title),
    }


# Words a cut title shouldn't end on.
_DANGLING = {"a", "an", "and", "the", "of", "for", "with", "in", "on", "or", "to"}


def _shorten(text: str, limit: int) -> str:
    """Cut at the last whole word that fits, without a dangling 'with the'."""
    if len(text) <= limit:
        return text
    words = text[:limit + 1].split(" ")[:-1]
    while words and words[-1].lower().strip(",") in _DANGLING:
        words.pop()
    return " ".join(words).rstrip(" ,-") or text[:limit]


def comp_titles(title: str, count: int, rng) -> list[str]:
    """Believable comp titles: the item title plus a common ending, with the
    endings shuffled so neighbors rarely repeat."""
    endings = COMP_ENDINGS[:]
    rng.shuffle(endings)
    base = clean_title(title)
    return [_shorten(base, EBAY_TITLE_LIMIT - len(e)) + e
            for e in (endings[i % len(endings)] for i in range(count))]


def negotiation_message(title: str, offer: float) -> str:
    """The demo draft. It doesn't repeat the title, so it reads right for any item."""
    return (f"Hey! Is this still available? I can pick it up today and pay "
            f"cash. Would you take ${offer:.0f}? {notes_for(title)['question']}")
