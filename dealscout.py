"""
Deal Scout — run this file to start the tool:

    python3 dealscout.py

Then open http://localhost:5001 in your browser.
(It opens automatically. Port 5001 is used because macOS AirPlay
Receiver occupies port 5000 and blocks "localhost" requests there.)
"""

import os
import time
import uuid
import webbrowser
from pathlib import Path
from threading import Timer

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request

import database
import ebay_api
import negotiator
import scoring
import settings
import vision_analysis

APP_DIR = Path(__file__).parent

# DEALSCOUT_ENV_FILE has to come from the shell, since it says which .env to load.
ENV_FILE = Path(os.environ.get("DEALSCOUT_ENV_FILE") or APP_DIR / ".env")
load_dotenv(ENV_FILE)
settings.apply_demo_mode_from_env()
database.init_db()

app = Flask(__name__)
UPLOAD_DIR = Path(os.environ.get("DEALSCOUT_UPLOADS_DIR") or APP_DIR / "uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_PHOTO_BYTES = int(4.5 * 1024 * 1024)   # photo analysis API limit


def _download_image(url: str) -> Path | None:
    """Download one eBay listing image so Claude Vision can look at it.
    Returns the saved path, or None if anything went wrong (never crashes)."""
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        content_type = r.headers.get("content-type", "")
        suffix = {"image/jpeg": ".jpg", "image/png": ".png",
                  "image/webp": ".webp", "image/gif": ".gif"}.get(
                      content_type.split(";")[0].strip())
        if not suffix or len(r.content) > MAX_PHOTO_BYTES:
            return None
        path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
        path.write_bytes(r.content)
        return path
    except requests.RequestException:
        return None


@app.route("/")
def home():
    return render_template("index.html",
                           demo_mode=settings.DEMO_MODE,
                           settings=settings,
                           result=None)


@app.route("/analyze", methods=["POST"])
def analyze():
    warnings = []

    # ── 1. Get the listing details ──────────────────────────────────────
    ebay_url = (request.form.get("ebay_url") or "").strip()
    source = "ebay_url" if ebay_url else "manual"

    ebay_image_urls = []
    if ebay_url:
        try:
            details = ebay_api.fetch_listing_from_url(ebay_url)
        except ebay_api.EbayError as e:
            return render_template("index.html", demo_mode=settings.DEMO_MODE,
                                   settings=settings, result=None,
                                   error=str(e))
        title = details["title"]
        asking_price = details["asking_price"]
        description = details["description"]
        ebay_image_urls = details.get("image_urls", [])
        if asking_price <= 0:
            return render_template(
                "index.html", demo_mode=settings.DEMO_MODE,
                settings=settings, result=None,
                error="That eBay listing didn't return a usable price — it "
                      "may be an auction without a Buy It Now price. Enter "
                      "the details manually instead, using the current bid "
                      "or the price you'd realistically pay.")
    else:
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        try:
            asking_price = float(request.form.get("asking_price") or 0)
        except ValueError:
            asking_price = 0
        if not title or asking_price <= 0:
            return render_template("index.html", demo_mode=settings.DEMO_MODE,
                                   settings=settings, result=None,
                                   error="Please enter at least a title and "
                                         "an asking price (or an eBay URL).")

    size_class = request.form.get("size_class") or "medium"

    # ── 2. Have you already scored this exact item recently? ────────────
    dup = database.recent_duplicate(title, asking_price)
    if dup:
        warnings.append(f"You already analyzed this exact item on "
                        f"{dup['analyzed_at'][:10]} — verdict was "
                        f"{dup['verdict']}. Showing a fresh analysis anyway.")

    # ── 3. Gather photos: uploads first, then eBay's own listing images ──
    photo_paths = []
    for f in request.files.getlist("photos"):
        if not f or not f.filename:
            continue
        if len(photo_paths) >= settings.MAX_PHOTOS:
            warnings.append(f"Only the first {settings.MAX_PHOTOS} photos "
                            f"are analyzed — extras were skipped.")
            break
        suffix = Path(f.filename).suffix.lower()
        if suffix not in ALLOWED_PHOTO_TYPES:
            warnings.append(f"Skipped '{f.filename}' — not a photo format "
                            f"this tool understands.")
            continue
        path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
        f.save(path)
        if path.stat().st_size > MAX_PHOTO_BYTES:
            path.unlink(missing_ok=True)
            warnings.append(f"Skipped '{f.filename}' — larger than the "
                            f"~4.5MB limit the photo analysis accepts. "
                            f"Use a smaller copy or a screenshot of it.")
            continue
        photo_paths.append(path)

    # Download the listing's own images if this came from an eBay URL
    for img_url in ebay_image_urls[:settings.MAX_PHOTOS - len(photo_paths)]:
        saved = _download_image(img_url)
        if saved:
            photo_paths.append(saved)
    if ebay_image_urls and not any(
            p for p in photo_paths) and not settings.DEMO_MODE:
        warnings.append("Couldn't download the listing's photos from eBay — "
                        "the analysis ran on the text only.")

    # ── 4. Photo/description analysis (Claude Vision) ───────────────────
    vision = vision_analysis.analyze(title, asking_price, description,
                                     photo_paths)
    if vision.get("error"):
        warnings.append(vision["error"])

    # ── 5. Find comparable eBay listings ────────────────────────────────
    search_query = vision.get("resale_title_suggestion") or title
    try:
        comps = ebay_api.search_comps(search_query, asking_price)
    except ebay_api.EbayError as e:
        comps = []
        warnings.append(str(e))

    # ── 6. Score it ──────────────────────────────────────────────────────
    result = scoring.score_deal(asking_price,
                                [c["price"] for c in comps],
                                vision.get("category_guess"),
                                size_class)

    # ── 7. Draft a negotiation message if it's a NEGOTIATE ──────────────
    negotiation_draft = None
    if result["verdict"] == "NEGOTIATE" and result["suggested_offer"]:
        negotiation_draft = negotiator.draft_message(
            title, asking_price, result["suggested_offer"],
            vision.get("condition"), vision.get("missing_info", []))

    # ── 8. Save to history ───────────────────────────────────────────────
    database.save_listing({
        "source": source, "title": title, "asking_price": asking_price,
        "url": ebay_url or None, "description": description,
        "category_guess": vision.get("category_guess"),
        "size_class": size_class, "verdict": result["verdict"],
        "est_resale_low": result["comps"]["low"],
        "est_resale_high": result["comps"]["high"],
        "est_profit_low": result["est_profit_low"],
        "est_profit_high": result["est_profit_high"],
        "suggested_offer": result["suggested_offer"],
        "comps_count": result["comps"]["count"],
        "fee_percent": result["fee_percent"],
        "shipping_est": result["shipping_est"],
        "vision_report": vision,
        "negotiation_draft": negotiation_draft,
    })

    # ── 9. Show the results ──────────────────────────────────────────────
    return render_template("index.html",
                           demo_mode=settings.DEMO_MODE,
                           settings=settings,
                           result={
                               "title": title,
                               "asking_price": asking_price,
                               "verdict": result["verdict"],
                               "reason": result["reason"],
                               "comps": result["comps"],
                               "sample_comps": comps[:6],
                               "est_profit_low": result["est_profit_low"],
                               "est_profit_high": result["est_profit_high"],
                               "suggested_offer": result["suggested_offer"],
                               "fee_percent": result["fee_percent"],
                               "shipping_est": result["shipping_est"],
                               "vision": vision,
                               "negotiation_draft": negotiation_draft,
                           },
                           warnings=warnings)


@app.route("/history")
def history():
    verdict = request.args.get("verdict")
    rows = database.get_history(verdict)
    return render_template("history.html", rows=rows,
                           active_filter=verdict or "ALL",
                           demo_mode=settings.DEMO_MODE)


def startup_message() -> str:
    lines = [f"\nDeal Scout is starting at http://localhost:{settings.PORT}"]
    if settings.DEMO_MODE:
        lines.append("Demo mode is on, so all data is made up. Set "
                     "DEALSCOUT_DEMO_MODE=off in .env when your API keys "
                     "are ready.\n")
    return "\n".join(lines)


def _open_browser():
    webbrowser.open(f"http://localhost:{settings.PORT}")


if __name__ == "__main__":
    print(startup_message())
    Timer(1.0, _open_browser).start()
    app.run(port=settings.PORT, debug=False)
