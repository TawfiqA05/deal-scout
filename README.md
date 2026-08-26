# Deal Scout

Paste an eBay listing and get a BUY / NEGOTIATE / PASS call with an honest
profit range, plus a photo analysis and a ready-to-send negotiation message.

*I built it because I kept eyeballing resale deals and doing the same math by
hand: what it's worth, what eBay takes, whether there's room to haggle. This
does the math and adds a second read on the listing photos before I commit.*

## Demo mode (no keys needed)
It runs on fake data out of the box:

    pip install -r requirements.txt
    python dealscout.py

Your browser opens to the tool. To run it for real, add your keys (below).

## What it does
- Scores a deal against comparable eBay listings → BUY / NEGOTIATE / PASS with a profit range
- Reads the listing photos with Gemini vision: condition, scam/authenticity red flags, what to ask the seller, and a category guess to pick the right eBay fee
- When the call is NEGOTIATE, drafts a specific offer message for you to review and send. It never messages anyone automatically
- Saves every analysis to a local SQLite history

## Built with
Python + Flask, the eBay Browse API for comps, Google Gemini (vision + text),
and SQLite. Keys load from a `.env`; nothing is hardcoded.

## Honest about the numbers
Estimates use *active* listings (asking prices), not confirmed sales. Real sale
prices run lower, so the numbers are optimistic and labeled that way everywhere
they appear. It's a decision aid, not a guarantee.

## Running it for real
1. Copy `.env.example` to `.env`, add your eBay Client ID/Secret (developer.ebay.com) and a free Gemini key (aistudio.google.com)
2. Set `DEMO_MODE = False` in `settings.py`
3. `python dealscout.py`

## What I'd do next
- Use sold-price data (eBay Marketplace Insights) for realistic estimates
- Support marketplaces beyond eBay
