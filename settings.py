"""
Deal Scout settings — every number you might want to change lives here.
Edit this file with any text editor. No coding knowledge needed.
"""

# ── Demo mode ────────────────────────────────────────────────────────────
# True  = the tool uses realistic FAKE data so you can try everything
#         without any API keys.
# False = real mode. Requires eBay + Anthropic keys in your .env file.
DEMO_MODE = True

# ── Your profit bar ──────────────────────────────────────────────────────
# A deal is only a BUY if BOTH of these are met (after fees + shipping):
MIN_PROFIT_DOLLARS = 25      # at least this many dollars of profit
MIN_PROFIT_PERCENT = 30      # and at least this % return on what you pay

# A deal is a NEGOTIATE if it would become a BUY at a lower purchase
# price that's within this % below the asking price:
NEGOTIATE_DISCOUNT_LIMIT = 25   # e.g. 25 = worth negotiating if a 25%-off
                                # price would make the math work

# ── eBay selling fees (final value fee, % of sale price) ─────────────────
# eBay charges different fees by category. The tool guesses the category
# and applies the matching fee. If a category isn't listed, it uses DEFAULT.
# These are approximate — check ebay.com/help/selling/fees for current rates.
EBAY_CATEGORY_FEES = {
    "default": 13.6,
    "electronics": 13.25,
    "computers": 13.25,
    "video games": 13.6,
    "sneakers": 8.0,          # sneakers over $150 have a lower fee
    "clothing": 15.0,
    "watches": 15.0,
    "jewelry": 15.0,
    "tools": 13.6,
    "toys": 13.6,
    "collectibles": 13.6,
    "sporting goods": 13.6,
    "musical instruments": 13.25,
    "home & garden": 13.6,
}
EBAY_PER_ORDER_FEE = 0.40     # flat fee eBay adds per order (approx)

# ── Shipping cost estimates by size class ────────────────────────────────
SHIPPING_ESTIMATES = {
    "small":  6.00,    # fits in a padded envelope / small box (phone, game)
    "medium": 12.00,   # shoebox-to-microwave size (shoes, small appliance)
    "large":  25.00,   # big box (monitor, guitar, power tool set)
    "freight": 120.00, # furniture, exercise equipment — usually local-only
}

# ── Comparable listings search ───────────────────────────────────────────
COMPS_TO_FETCH = 20           # how many active eBay listings to compare
COMPS_TRIM_PERCENT = 10       # ignore the cheapest/priciest 10% (outliers)

# ── AI model for photo analysis and negotiation drafts ───────────────────
# Using Google Gemini's free tier — no credit card, no expiration.
# Get a free key at aistudio.google.com
GEMINI_MODEL = "gemini-2.5-flash"
MAX_PHOTOS = 6                # analyze at most this many photos per listing

# ── Web page ─────────────────────────────────────────────────────────────
PORT = 5001                   # the tool runs at http://localhost:5001
                              # (5000 is taken by macOS AirPlay Receiver)
