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
from flask import Flask, g, render_template, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

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

# The formats Google lists for Gemini. GIF isn't one of them.
ALLOWED_PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
MAX_PHOTO_BYTES = int(4.5 * 1024 * 1024)   # photo analysis API limit
# The most one request may carry: six full-size photos plus room for the
# form. Extra photos inside that get skipped one by one with a warning;
# past it, Flask refuses the request before reading it all.
MAX_REQUEST_BYTES = settings.MAX_PHOTOS * MAX_PHOTO_BYTES + 1024 * 1024
REQUEST_MB = MAX_REQUEST_BYTES // (1024 * 1024)
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
TOTAL_MB = settings.MAX_TOTAL_PHOTO_BYTES // (1024 * 1024)
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
REFUSED_TOO_BIG = (f"That upload was over {REQUEST_MB} MB, so nothing was "
                   f"analyzed. Pick fewer or smaller photos and try again.")


def _usable_price(price: float) -> bool:
    """float() accepts "nan" and "inf", and nan slips past a <= 0 check,
    so check for a finite number in range."""
    return math.isfinite(price) and 0 < price <= MAX_ASKING_PRICE


def _download_image(url: str) -> tuple[bytes, str] | None:
    """Download one eBay listing image for the photo check.
    Returns its bytes and file suffix, or None if the download fails or
    the image isn't a format and size the photo check takes."""
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except requests.RequestException:
        return None
    content_type = r.headers.get("content-type", "")
    suffix = {"image/jpeg": ".jpg", "image/png": ".png",
              "image/webp": ".webp", "image/heic": ".heic",
              "image/heif": ".heif"}.get(content_type.split(";")[0].strip())
    if not suffix or len(r.content) > MAX_PHOTO_BYTES:
        return None
    return r.content, suffix


def _new_photo_path(suffix: str) -> Path:
    """A fresh path in the uploads folder, noted so the request removes it
    when it ends. Raises OSError if the folder can't be made."""
    path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    g.setdefault("saved_photos", []).append(path)
    return path


def _save_photo(data: bytes, suffix: str) -> Path:
    """Write one photo to the uploads folder. Raises OSError if it can't."""
    path = _new_photo_path(suffix)
    path.write_bytes(data)
    return path


def _upload_size(f) -> int:
    """The uploaded file's size, read from Flask's copy before it's saved."""
    stream = f.stream
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


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


def _wrong_host_page():
    return render_template(
        "error.html", wrong_host=True,
        local_address=f"http://localhost:{_server_port()}"), 400


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
        return _wrong_host_page()
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
    photo_bytes = 0
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
            warnings.append(f"Skipped '{f.filename}'. The photo check takes "
                            f"JPG, PNG, WebP and HEIC photos only.")
            continue
        # Sizes are checked before anything is written to the folder.
        size = _upload_size(f)
        if size > MAX_PHOTO_BYTES:
            warnings.append(f"Skipped '{f.filename}' because it's over "
                            f"4.5 MB. Use a smaller copy or a screenshot "
                            f"of it.")
            continue
        if photo_bytes + size > settings.MAX_TOTAL_PHOTO_BYTES:
            warnings.append(f"Skipped '{f.filename}' because the photos "
                            f"together would go over {TOTAL_MB} MB, the most "
                            f"the photo check can send.")
            continue
        try:
            path = _new_photo_path(suffix)
            f.save(path)
        except OSError:
            # Folder gone and can't be made, or read-only.
            uploads_failed = True
            warnings.append("Couldn't save the uploaded photos, so the "
                            "check ran without them.")
            continue
        photo_bytes += size
        photo_paths.append(path)

    listing_photos_left_out = False
    for img_url in ebay_image_urls[:settings.MAX_PHOTOS - len(photo_paths)]:
        photo = _download_image(img_url)
        if not photo:
            continue
        data, suffix = photo
        if photo_bytes + len(data) > settings.MAX_TOTAL_PHOTO_BYTES:
            listing_photos_left_out = True
            continue
        try:
            photo_paths.append(_save_photo(data, suffix))
        except OSError:
            continue
        photo_bytes += len(data)
    if listing_photos_left_out:
        warnings.append(f"Left out some of the listing's own photos to keep "
                        f"the photo check under {TOTAL_MB} MB.")
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


@app.teardown_request
def remove_saved_photos(exc=None):
    """The photos a request saved are only needed while it runs, so they
    go when it ends, whether or not the analysis finished. Anything else
    in the uploads folder is left alone."""
    for path in g.pop("saved_photos", []):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            app.logger.warning("Couldn't remove %s", path.name)


@app.errorhandler(RequestEntityTooLarge)
def request_too_big(e):
    if not _host_ok():
        return _wrong_host_page()
    return _form_with_error(REFUSED_TOO_BIG, 413)


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
