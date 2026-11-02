# AGENTS.md

Deal Scout takes an eBay listing and returns BUY / NEGOTIATE / PASS with a profit range, a photo check from Gemini vision, and a drafted offer message. It runs locally on localhost:5001 and keeps a SQLite history.

## Stack
- Python 3.10+ and Flask, with requests and python-dotenv (requirements.txt)
- eBay Browse API for comparable listings and listing lookup (ebay_api.py)
- Google Gemini REST API for the photo check and the offer draft (gemini.py, vision_analysis.py, negotiator.py)
- SQLite from the standard library (database.py)
- Scoring and fee math in scoring.py, all tunable numbers in settings.py
- Fake data for demo mode in demo_data.py
- Tests: standard library unittest in tests/ (no pytest)

## Run it
```
pip install -r requirements.txt
python3 dealscout.py          # opens http://localhost:5001, demo mode by default
python3 -m unittest           # run from the repo root
```
Real mode: copy `.env.example` to `.env`, fill in EBAY_CLIENT_ID, EBAY_CLIENT_SECRET and GEMINI_API_KEY, and set `DEALSCOUT_DEMO_MODE=off`. The README has the full eBay keyset steps. There is no build step, no CI, and no deploy. Pushing to main only updates GitHub.

## Project rules
- Never send a message to a seller or anyone else. The negotiator drafts text for the user to review and send.
- Estimates come from active listings (asking prices), not sales. Keep the "optimistic" label on every number that shows one. Don't present the result as a guarantee.
- Demo mode is the default and must make zero network calls. tests/test_no_network.py checks this; keep it passing.
- Demo mode is switched by DEALSCOUT_DEMO_MODE in .env. Don't tell users to edit settings.py for it (tests/test_wording.py checks this).
- Keys load only from .env. Never hardcode a key. The Gemini key goes in the x-goog-api-key header, never in a URL, log line, page banner or history row.
- Raw API errors and tracebacks never reach the page. Show a plain message; log only a status code or exception name.
- Type-check every field that comes back from Gemini or eBay before using it.
- The comp search uses the listing's own title, not a title the model suggests. The model may only pick categories from settings.EBAY_CATEGORY_FEES.
- Keep the localhost guard: Host must be localhost, 127.0.0.1 or [::1] on the server port, cross-site Origins are refused, and form POSTs carry the per-start token.
- Photos: PNG, JPEG, WebP, HEIC, HEIF only. Respect MAX_PHOTOS and MAX_TOTAL_PHOTO_BYTES. Check sizes before saving, and delete each request's photos when it ends.
- Port stays 5001 (macOS AirPlay uses 5000).
- Code should name the tools it really uses (Gemini, not Claude or Anthropic) and talk to developers plainly. No box-drawing comment banners.
- No em dashes in README text or commit messages.

## Tests
- Tests must never touch the real deal_scout.db, uploads/, or .env. tests/__init__.py points DEALSCOUT_DB_PATH, DEALSCOUT_UPLOADS_DIR and DEALSCOUT_ENV_FILE at a temp folder and strips real keys before the app is imported. Keep that order.
- All sockets are blocked in tests except the local fake Google and eBay server in tests/fake_server.py on 127.0.0.1. Add real-mode tests against that fake, never the real APIs.
- Talk to the app through tests/helpers.py LocalClient so the Host and form token are right.
- Fresh-interpreter tests must pass temp paths (helpers.run_fresh_python fills them in).
- scoring_pinned.json pins score_deal outputs. If you change scoring on purpose, update the pins in the same commit and say why.
- Run the full suite and see it pass before calling a change done.

## Git rules
- Never force-push. Never rewrite pushed history.
- No AI co-author trailers and no "Generated with" lines in commits, PRs or the README.
- Commit author is "Tawfiq Abulail".
- Keep .env, *.db and uploads/ contents out of commits. They are in .gitignore; check the diff for keys before pushing.
- Don't delete branches or files unless the owner asks in that session.
- Commit messages: plain, first person where it fits, say what changed and why.

Status and decisions are in the private brain repo under projects/deal-scout/.
