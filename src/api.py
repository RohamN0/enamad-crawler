"""HTTP API for the enamad crawler.

Run:
    export ENAMAD_API_KEY="change-me-123"
    .venv/bin/python src/api.py

Endpoints:
    POST /lookup   JSON body {"domain": "...", "referer_url": "...", "include_trustseal": true}
                   Auth:  Authorization: Bearer <ENAMAD_API_KEY>  OR  X-API-Key: <ENAMAD_API_KEY>
    GET  /health   (public)

Example:
    curl -X POST http://localhost:8000/lookup \\
      -H "Content-Type: application/json" \\
      -H "Authorization: Bearer change-me-123" \\
      -d '{"domain": "example.ir"}'
"""
import os
import time
from functools import wraps

from flask import Flask, request, jsonify

from src.crawler import EnamadCrawler

app = Flask(__name__)

# Single crawler instance for the whole process so ddddocr loads once.
_crawler = EnamadCrawler(
    urls=[
        "https://enamad.ir/DomainListForMIMT",
        "https://enamad.ir/DomainListForMIMTSuspend",
    ],
    page_numbers=1,
    time_sleep=2,
    max_captcha_attempts=3,
)

# In-memory result cache so repeat lookups for the same domain don't re-crawl.
_CACHE = {}
_CACHE_TTL = 60 * 30  # 30 minutes

# Authentication: set ENAMAD_API_KEY in the environment before starting.
API_KEY = os.environ.get("ENAMAD_API_KEY")


def require_auth(fn):
    @wraps(fn)
    def decorated(*args, **kwargs):
        if API_KEY is None:
            # Misconfiguration: refuse to serve protected routes without a key.
            return jsonify({"error": "server misconfigured: no API key"}), 500
        # Accept Bearer token or X-API-Key header.
        provided = None
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            provided = auth[len("Bearer "):].strip()
        elif request.headers.get("X-API-Key"):
            provided = request.headers.get("X-API-Key").strip()
        if not provided or not _safe_compare(provided, API_KEY):
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return decorated


def _safe_compare(a, b):
    """Constant-time-ish comparison to avoid leaking the key via timing."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


@app.post("/lookup")
@require_auth
def lookup():
    body = request.get_json(silent=True) or {}
    domain = (body.get("domain") or "").strip()
    if not domain:
        return jsonify(
            {"error": "domain is required", "example": {"domain": "example.ir"}}
        ), 400

    referer_url = body.get("referer_url") or _crawler.urls[0]
    include_trustseal = body.get("include_trustseal", True)

    now = time.time()
    cached = _CACHE.get(domain)
    if cached and now - cached[0] < _CACHE_TTL:
        return jsonify(cached[1])

    try:
        result = _crawler.get_full_info(
            domain_address=domain,
            referer_url=referer_url,
            include_trustseal=include_trustseal,
            timeout=15,
        )
    except Exception as exc:  # never let the server crash on one bad request
        return jsonify({"error": str(exc), "found": False, "domain": domain}), 502

    _CACHE[domain] = (now, result)
    return jsonify(result)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    if API_KEY is None:
        print("WARNING: ENAMAD_API_KEY is not set — /lookup is unprotected!")
    # threaded so concurrent POSTs don't block each other.
    app.run(host="0.0.0.0", port=8000, threaded=True)
