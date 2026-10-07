"""
Deal Scout settings: the profit bar, eBay fees, shipping estimates and the
other numbers the scoring uses.
"""

import os

# Demo mode
# True uses made-up data and needs no keys.
# False is real mode and needs eBay and Gemini keys in .env.
# DEALSCOUT_DEMO_MODE=off in .env overrides this; see apply_demo_mode_from_env.
DEMO_MODE = True


def apply_demo_mode_from_env() -> None:
    """Set DEMO_MODE from DEALSCOUT_DEMO_MODE (on or off). dealscout.py imports
    this module before it loads .env, so it calls this after load_dotenv().
    A missing or unknown value leaves DEMO_MODE as it is."""
    global DEMO_MODE
    value = os.environ.get("DEALSCOUT_DEMO_MODE", "").strip().lower()
    if value in ("off", "false", "0", "no"):
        DEMO_MODE = False
    elif value in ("on", "true", "1", "yes"):
        DEMO_MODE = True


# Profit bar
# A deal is only a BUY if BOTH of these are met (after fees + shipping):
MIN_PROFIT_DOLLARS = 25      # at least this many dollars of profit
MIN_PROFIT_PERCENT = 30      # and at least this % return on what you pay

# A deal is a NEGOTIATE if it would become a BUY at a lower purchase
# price that's within this % below the asking price:
NEGOTIATE_DISCOUNT_LIMIT = 25   # e.g. 25 = worth negotiating if a 25%-off
                                # price would make the math work

# eBay selling fees (final value fee, % of sale price)
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

# Shipping cost estimates by size class
SHIPPING_ESTIMATES = {
    "small":  6.00,    # fits in a padded envelope / small box (phone, game)
    "medium": 12.00,   # shoebox-to-microwave size (shoes, small appliance)
    "large":  25.00,   # big box (monitor, guitar, power tool set)
    "freight": 120.00, # furniture, exercise equipment — usually local-only
}

# Comparable listings search
COMPS_TO_FETCH = 20           # how many active eBay listings to compare
COMPS_TRIM_PERCENT = 10       # ignore the cheapest/priciest 10% (outliers)

# Gemini model for the photo check and the offer draft.
# gemini-flash-latest is Google's alias for its newest Flash model. If a
# key can't use it, gemini.py picks a Flash model from the model list.
GEMINI_MODEL = "gemini-flash-latest"
MAX_PHOTOS = 6                # analyze at most this many photos per listing

# Web page
PORT = 5001                   # the tool runs at http://localhost:5001
                              # (5000 is taken by macOS AirPlay Receiver)
