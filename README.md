# Deal Scout

Paste an eBay listing and get a BUY / NEGOTIATE / PASS call with an honest
profit range, plus a photo analysis and a ready-to-send negotiation message.

*I built it because I kept eyeballing resale deals and doing the same math by
hand: what it's worth, what eBay takes, whether there's room to haggle. This
does the math and adds a second read on the listing photos before I commit. It
does what I needed, so I stopped there.*

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
Here's how to run it with your own keys. Real mode calls eBay for the listing and comparable prices and Google Gemini for the photo check, and eBay has one extra step before production keys work.

1. Sign up for the eBay Developers Program at developer.ebay.com with your eBay account.
2. Under Application Keys, create a Production keyset (not Sandbox).
3. eBay won't turn on a new production keyset until you answer its marketplace account deletion notice. On the Application Keys page, open Notifications next to your App ID and pick Marketplace Account Deletion. Then either give it an endpoint that answers eBay's check, or turn on "Not persisting eBay data" and choose the reason that fits. Deal Scout keeps listing titles, prices and descriptions in its local history, but no eBay account data.
4. Copy the production App ID and Cert ID. Those are your Client ID and Client Secret.
5. Get a Gemini API key at aistudio.google.com.
6. Copy `.env.example` to `.env`, fill in EBAY_CLIENT_ID, EBAY_CLIENT_SECRET and GEMINI_API_KEY, and change `DEALSCOUT_DEMO_MODE=on` to `DEALSCOUT_DEMO_MODE=off`.
7. Run `python dealscout.py` and try a listing you know. If something is wrong, a banner on the result says which side failed and what to check.

eBay's default limit for the Browse API is 5,000 calls a day. Each analysis makes one comp search, plus one listing lookup when you paste a link. The tool asks Gemini for `gemini-flash-latest`. If your key can't use that name, it picks the newest Flash model your key can see and keeps it until you restart. The Gemini key goes in a request header, so it never shows up in an address, a banner or the history.

## If I came back to it
- Use sold-price data (eBay Marketplace Insights) for realistic estimates
- Support marketplaces beyond eBay

## License

MIT — see [LICENSE](LICENSE).
