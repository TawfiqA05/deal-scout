"""
Deal Scout — run this file to start the tool:

    python3 dealscout.py

Then open http://localhost:5001 in your browser.
(It opens automatically. Port 5001 is used because macOS AirPlay
Receiver occupies port 5000 and blocks "localhost" requests there.)
"""

import hmac
import math
import os
import secrets
import time
import uuid
import webbrowser
from pathlib import Path
from threading import Timer

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request
from werkzeug.exceptions import HTTPException

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
try:
    UPLOAD_DIR.mkdir(exist_ok=True)
except OSError:
    pass  # analyze() tries again and warns if photos can't be saved

ALLOWED_PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_PHOTO_BYTES = int(4.5 * 1024 * 1024)   # photo analysis API limit
MAX_ASKING_PRICE = 1_000_000

# Only pages served by the tool itself may use it. Another site open in the
# same browser could otherwise post to /analyze, spend the API quota and
# write history. The token changes on every start; the Host check keeps
# another site from loading the page to read it.
LOCAL_HOSTNAMES = ("localhost", "127.0.0.1", "[::1]")
FORM_TOKEN = secrets.token_urlsafe(32)
REFUSED_ORIGIN = ("Deal Scout turned that down because it came from another "
                  "website. Use the form on this page instead.")
REFUSED_TOKEN = ("This page was out of date, so nothing was analyzed. Fill in "
                 "the form below and try again.")


def _usable_price(price: float) -> bool:
    """float() accepts "nan" and "inf", and nan slips past a <= 0 check,
    so check for a finite number in range."""
    return math.isfinite(price) and 0 < price <= MAX_ASKING_PRICE


def _download_image(url: str) -> Path | None:
    """Download one eBay listing image for the photo check.
    Returns the saved path, or None if the download fails."""
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
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        return path
    except (requests.RequestException, OSError):
        return None


def _server_port() -> str:
    """The port the server is listening on, which may not be settings.PORT
    if it was started some other way."""
    return str(request.environ.get("SERVER_PORT") or settings.PORT)


def _local_addresses() -> set[str]:
    port = _server_port()
    return {f"{name}:{port}" for name in LOCAL_HOSTNAMES}


def _host_ok() -> bool:
    return request.environ.get("HTTP_HOST", "").lower() in _local_addresses()


def _origin_ok() -> bool:
    """No Origin header is fine; the form token still has to match."""
    origin = request.headers.get("Origin")
    if origin is None:
        return True
    return origin.lower() in {f"http://{a}" for a in _local_addresses()}


def _token_ok() -> bool:
    sent = request.form.get("form_token", "")
    return hmac.compare_digest(sent.encode(), FORM_TOKEN.encode())


def _form_with_error(message: str, code: int):
    return render_template("index.html", demo_mode=settings.DEMO_MODE,
                           settings=settings, result=None,
                           error=message), code


@app.before_request
def only_this_tool():
    """Refuse requests from other sites before anything else runs. A wrong
    Host gets the error page, without the form, so the token never goes
    to a page that isn't this tool's."""
    if not _host_ok():
        return render_template(
            "error.html", wrong_host=True,
            local_address=f"http://localhost:{_server_port()}"), 400
    if not _origin_ok():
        return _form_with_error(REFUSED_ORIGIN, 403)
    if request.method == "POST" and not _token_ok():
        return _form_with_error(REFUSED_TOKEN, 403)
    return None


@app.context_processor
def form_token():
    return {"form_token": FORM_TOKEN}


@app.route("/")
def home():
    return render_template("index.html",
                           demo_mode=settings.DEMO_MODE,
                           settings=settings,
                           result=None)


@app.route("/analyze", methods=["POST"])
def analyze():
    warnings = []

    # Listing details come from the eBay URL if there is one, else the form.
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
        if not _usable_price(asking_price):
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
        if not title or not _usable_price(asking_price):
            return render_template("index.html", demo_mode=settings.DEMO_MODE,
                                   settings=settings, result=None,
                                   error="Please enter at least a title and "
                                         "an asking price (or an eBay URL).")

    size_class = request.form.get("size_class") or "medium"

    # Same title and price scored in the last 14 days gets a warning.
    dup = database.recent_duplicate(title, asking_price)
    if dup:
        warnings.append(f"You already analyzed this exact item on "
                        f"{dup['analyzed_at'][:10]} — verdict was "
                        f"{dup['verdict']}. Showing a fresh analysis anyway.")

    # Uploaded photos first, then the eBay listing's own images.
    photo_paths = []
    uploads_failed = False
    for f in request.files.getlist("photos"):
        if not f or not f.filename or uploads_failed:
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
        try:
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            f.save(path)
            size = path.stat().st_size
        except OSError:
            # Folder gone and can't be made, or read-only.
            uploads_failed = True
            warnings.append("Couldn't save the uploaded photos, so the "
                            "check ran without them.")
            continue
        if size > MAX_PHOTO_BYTES:
            path.unlink(missing_ok=True)
            warnings.append(f"Skipped '{f.filename}' — larger than the "
                            f"~4.5MB limit the photo analysis accepts. "
                            f"Use a smaller copy or a screenshot of it.")
            continue
        photo_paths.append(path)

    for img_url in ebay_image_urls[:settings.MAX_PHOTOS - len(photo_paths)]:
        saved = _download_image(img_url)
        if saved:
            photo_paths.append(saved)
    if ebay_image_urls and not any(
            p for p in photo_paths) and not settings.DEMO_MODE:
        warnings.append("Couldn't download the listing's photos from eBay — "
                        "the analysis ran on the text only.")

    # Gemini reads the photos and description. Demo mode makes up notes.
    vision = vision_analysis.analyze(title, asking_price, description,
                                     photo_paths)
    if vision.get("error"):
        warnings.append(vision["error"])

    # Comps are searched by the listing's own title. The model's suggested
    # title is left out, since words in the description could steer it
    # toward a pricier item.
    search_text = title
    try:
        comps = ebay_api.search_comps(search_text, asking_price)
    except ebay_api.EbayError as e:
        comps = []
        warnings.append(str(e))
    if not comps:
        warnings.append(f'The eBay search for "{search_text}" brought back '
                        f'no comparable listings.')

    result = scoring.score_deal(asking_price,
                                [c["price"] for c in comps],
                                vision.get("category_guess"),
                                size_class)

    # Only a NEGOTIATE verdict gets a draft message.
    negotiation_draft = None
    if result["verdict"] == "NEGOTIATE" and result["suggested_offer"]:
        negotiation_draft = negotiator.draft_message(
            title, asking_price, result["suggested_offer"],
            vision.get("condition"), vision.get("missing_info", []))

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
                               "search_text": search_text,
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


@app.errorhandler(Exception)
def error_page(e):
    """One plain page for anything unexpected. The traceback goes to the
    terminal, never to the browser."""
    if isinstance(e, HTTPException):
        code = e.code or 500
    else:
        app.logger.exception("Unhandled error on %s %s",
                             request.method, request.path)
        code = 500
    try:
        return render_template("error.html", not_found=code == 404), code
    except Exception:
        app.logger.exception("The error page failed too")
        return "Something went wrong", code, {"Content-Type": "text/plain"}


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
