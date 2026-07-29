import webbrowser
import json
import logging
import signal
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode
import os
import requests

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
API_KEY = "c856b8481d47439e953d1fbe0efedd60"
PORT    = 8000
RADIUS  = 10_000   # metres
LIMIT   = 20
TIMEOUT = 8        # seconds for Geoapify request

# ── Food category registry ─────────────────────────────────────────────────────
FOOD_REGISTRY: dict[str, dict] = {
    "pizza":        {"cats": "catering.restaurant",                               "hints": ["pizza", "italian"]},
    "burger":       {"cats": "catering.fast_food,catering.restaurant",            "hints": ["burger", "grill", "smash"]},
    "coffee":       {"cats": "catering.cafe",                                     "hints": ["coffee", "cafe", "espresso"]},
    "latte":        {"cats": "catering.cafe",                                     "hints": ["coffee", "cafe", "latte"]},
    "espresso":     {"cats": "catering.cafe",                                     "hints": ["espresso", "coffee", "cafe"]},
    "cappuccino":   {"cats": "catering.cafe",                                     "hints": ["cappuccino", "coffee", "cafe"]},
    "sushi":        {"cats": "catering.restaurant",                               "hints": ["sushi", "japanese", "rolls"]},
    "ramen":        {"cats": "catering.restaurant",                               "hints": ["ramen", "japanese", "noodle"]},
    "pho":          {"cats": "catering.restaurant",                               "hints": ["pho", "vietnamese", "noodle"]},
    "wings":        {"cats": "catering.fast_food,catering.restaurant",            "hints": ["chicken", "wings", "wing"]},
    "fried chicken":{"cats": "catering.fast_food,catering.restaurant",            "hints": ["chicken", "fried", "poultry"]},
    "beer":         {"cats": "catering.pub,catering.bar",                         "hints": ["pub", "bar", "beer", "ale", "draft"]},
    "pub":          {"cats": "catering.pub,catering.bar",                         "hints": ["pub", "bar", "tavern"]},
    "nachos":       {"cats": "catering.restaurant",                               "hints": ["mexican", "nachos", "tex-mex"]},
    "tacos":        {"cats": "catering.restaurant",                               "hints": ["tacos", "mexican", "taqueria"]},
    "fries":        {"cats": "catering.fast_food",                                "hints": ["fast food", "fries", "burger"]},
    "chinese":      {"cats": "catering.restaurant",                               "hints": ["chinese", "dim sum", "wonton"]},
    "thai":         {"cats": "catering.restaurant",                               "hints": ["thai", "pad thai", "curry"]},
    "indian":       {"cats": "catering.restaurant",                               "hints": ["indian", "curry", "tandoor", "biryani"]},
    "curry":        {"cats": "catering.restaurant",                               "hints": ["curry", "indian", "thai", "spice"]},
    "pasta":        {"cats": "catering.restaurant",                               "hints": ["italian", "pasta", "trattoria"]},
    "italian":      {"cats": "catering.restaurant",                               "hints": ["italian", "pasta", "pizza", "trattoria"]},
    "steak":        {"cats": "catering.restaurant",                               "hints": ["steak", "steakhouse", "grill", "chop"]},
    "bbq":          {"cats": "catering.restaurant",                               "hints": ["bbq", "barbecue", "smokehouse", "grill"]},
    "sandwich":     {"cats": "catering.fast_food,catering.cafe",                  "hints": ["sandwich", "deli", "sub", "wrap"]},
    "breakfast":    {"cats": "catering.cafe,catering.restaurant",                 "hints": ["breakfast", "brunch", "eggs", "pancake"]},
    "brunch":       {"cats": "catering.cafe,catering.restaurant",                 "hints": ["brunch", "breakfast", "eggs", "mimosa"]},
    "vegan":        {"cats": "catering.restaurant,catering.cafe",                 "hints": ["vegan", "plant-based", "vegetarian"]},
    "vegetarian":   {"cats": "catering.restaurant,catering.cafe",                 "hints": ["vegetarian", "vegan", "veggie"]},
    "noodles":      {"cats": "catering.restaurant",                               "hints": ["noodle", "ramen", "pho", "asian"]},
    "kebab":        {"cats": "catering.fast_food,catering.restaurant",            "hints": ["kebab", "shawarma", "doner"]},
    "shawarma":     {"cats": "catering.fast_food,catering.restaurant",            "hints": ["shawarma", "kebab", "wrap"]},
    "ice cream":    {"cats": "catering.ice_cream,catering.cafe",                  "hints": ["ice cream", "gelato", "sorbet", "frozen"]},
    "dessert":      {"cats": "catering.cafe,catering.restaurant",                 "hints": ["dessert", "bakery", "cake", "pastry"]},
    "bakery":       {"cats": "catering.cafe",                                     "hints": ["bakery", "bread", "pastry", "boulangerie"]},
    "dumplings":    {"cats": "catering.restaurant",                               "hints": ["dumpling", "dim sum", "gyoza", "bao"]},
    "greek":        {"cats": "catering.restaurant",                               "hints": ["greek", "mediterranean", "gyro", "souvlaki"]},
    "mediterranean":{"cats": "catering.restaurant",                               "hints": ["mediterranean", "greek", "falafel", "hummus"]},
    "korean":       {"cats": "catering.restaurant",                               "hints": ["korean", "bibimbap", "bulgogi", "kbbq"]},
}

DEFAULT_META = {
    "cats":  "catering.restaurant,catering.fast_food,catering.cafe,catering.pub",
    "hints": [],
}

# ── Category resolver ──────────────────────────────────────────────────────────
def resolve_category(text: str) -> tuple[str, dict]:
    lower = text.lower().strip()

    if lower in FOOD_REGISTRY:
        return text.title(), FOOD_REGISTRY[lower]

    for key, meta in FOOD_REGISTRY.items():
        if key in lower:
            return key.title(), meta

    for key, meta in FOOD_REGISTRY.items():
        if lower in key:
            return key.title(), meta

    return text.title(), {**DEFAULT_META, "hints": [lower]}

# ── Geoapify fetch ─────────────────────────────────────────────────────────────
def fetch_places(lat: float, lon: float, meta: dict) -> list[dict]:
    params = {
        "categories": meta["cats"],
        "filter":     f"circle:{lon},{lat},{RADIUS}",
        "bias":       f"proximity:{lon},{lat}",
        "limit":      LIMIT,
        "details":    "opening_hours,website,contact",
        "apiKey":     API_KEY,
    }
    url = "https://api.geoapify.com/v2/places?" + urlencode(params)
    log.info("Geoapify → %s", url)

    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("Geoapify request failed: %s", exc)
        return []

    features = resp.json().get("features", [])
    hints    = [h.lower() for h in meta["hints"]]
    results  = []

    for feature in features:
        props = feature.get("properties", {})
        name  = (props.get("name") or "").strip()
        if not name:
            continue

        blob = " ".join([
            " ".join(props.get("categories", [])),
            props.get("formatted", ""),
            name,
        ]).lower()

        score    = sum(10 for word in hints if word in blob)
        distance = props.get("distance", 0)
        lat_p    = props.get("lat")
        lon_p    = props.get("lon")
        contact  = props.get("contact") or {}

        maps_url = (
            "https://www.google.com/maps/search/?api=1"
            f"&query={lat_p},{lon_p}"
        )

        results.append({
            "name":     name,
            "distance": round(distance / 1_000, 2),
            "score":    score,
            "maps":     maps_url,
            "hours":    props.get("opening_hours") or None,
            "website":  props.get("website")        or None,
            "phone":    contact.get("phone")        or None,
        })

    results.sort(key=lambda x: (-x["score"], x["distance"]))
    return results[:15]

# ── HTML frontend ──────────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nearby Eats</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:         #0D0D14;
    --surface:    rgba(22, 22, 31, 0.85); /* Slightly translucent for blur feel */
    --border:     rgba(255, 255, 255, 0.12);
    --accent:     #FF6B35;
    --accent-lo:  rgba(255, 107, 53, 0.15);
    --accent-mid: rgba(255, 107, 53, 0.35);
    --text:       #EDEAE3;
    --muted:      #A09DB8;
    --r-sm:       10px;
    --r-lg:       18px;
    --ease:       220ms ease;
  }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 64px 20px 100px;
  }

  /* ── Video Background ── */
  .video-background {
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    z-index: -1;
    overflow: hidden;
  }

  .video-background video {
    width: 100%;
    height: 100%;
    object-fit: cover;
    opacity: 0.22; /* Controls video intensity */
    filter: blur(2px);
  }

  .video-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(13, 13, 20, 0.5); /* Tint to match dark theme */
  }

  /* ── Hero ── */
  .hero { text-align: center; margin-bottom: 44px; }

  .hero-eyebrow {
    display: inline-block;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 18px;
  }

  .hero h1 {
    font-size: clamp(2rem, 6vw, 3.4rem);
    font-weight: 800;
    letter-spacing: -0.03em;
    line-height: 1.1;
  }

  .hero h1 em {
    font-style: normal;
    color: var(--accent);
  }

  .hero p {
    margin-top: 14px;
    font-size: 0.95rem;
    color: var(--muted);
    max-width: 380px;
    margin-inline: auto;
    line-height: 1.6;
  }

  /* ── Search ── */
  .search-wrap {
    width: 100%;
    max-width: 540px;
    position: relative;
    margin-bottom: 36px;
  }

  .search-wrap input {
    width: 100%;
    padding: 17px 56px 17px 24px;
    background: var(--surface);
    backdrop-filter: blur(12px);
    border: 1.5px solid var(--border);
    border-radius: 50px;
    color: var(--text);
    font-size: 1rem;
    outline: none;
    transition: border-color var(--ease), box-shadow var(--ease);
  }

  .search-wrap input::placeholder { color: var(--muted); }

  .search-wrap input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 4px var(--accent-lo), 0 0 28px var(--accent-lo);
  }

  .search-btn {
    position: absolute;
    right: 7px;
    top: 50%;
    transform: translateY(-50%);
    background: var(--accent);
    border: none;
    border-radius: 50%;
    width: 40px;
    height: 40px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1rem;
    transition: opacity var(--ease), transform var(--ease);
    flex-shrink: 0;
  }

  .search-btn:hover  { opacity: 0.85; transform: translateY(-50%) scale(1.06); }
  .search-btn:active { opacity: 0.7;  transform: translateY(-50%) scale(0.97); }

  /* ── Status ── */
  .status {
    font-size: 0.85rem;
    color: var(--muted);
    min-height: 20px;
    margin-bottom: 28px;
    text-align: center;
  }

  .status.error { color: #FF6B6B; }

  /* ── Results header ── */
  .results-header {
    width: 100%;
    max-width: 660px;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 16px;
    padding: 0 2px;
  }

  .results-header h2 {
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--text);
  }

  .results-header h2 em {
    font-style: normal;
    color: var(--accent);
  }

  .results-header .count {
    font-size: 0.8rem;
    color: var(--muted);
  }

  /* ── Cards ── */
  .results {
    width: 100%;
    max-width: 660px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .card {
    background: var(--surface);
    backdrop-filter: blur(12px);
    border: 1.5px solid var(--border);
    border-radius: var(--r-lg);
    padding: 20px 22px;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 6px 14px;
    opacity: 0;
    transform: translateY(14px);
    animation: rise 320ms ease forwards;
    transition: border-color var(--ease), box-shadow var(--ease);
  }

  .card:hover {
    border-color: var(--accent-mid);
    box-shadow: 0 6px 28px rgba(0, 0, 0, 0.45);
  }

  @keyframes rise {
    to { opacity: 1; transform: translateY(0); }
  }

  @media (prefers-reduced-motion: reduce) {
    .card { animation: none; opacity: 1; transform: none; }
    .video-background video { display: none; }
  }

  .card-name {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--text);
    grid-column: 1;
    align-self: center;
  }

  .card-badge {
    grid-column: 2;
    grid-row: 1;
    align-self: start;
    background: var(--accent-lo);
    color: var(--accent);
    border-radius: 50px;
    padding: 3px 10px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    white-space: nowrap;
  }

  .card-meta {
    grid-column: 1 / -1;
    display: flex;
    flex-wrap: wrap;
    gap: 10px 18px;
    font-size: 0.82rem;
    color: var(--muted);
    margin-top: 6px;
  }

  .card-links {
    grid-column: 1 / -1;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 14px;
    padding-top: 14px;
    border-top: 1px solid var(--border);
  }

  .btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 7px 14px;
    border-radius: var(--r-sm);
    font-size: 0.8rem;
    font-weight: 600;
    text-decoration: none;
    transition: opacity var(--ease), background var(--ease);
  }

  .btn-primary   { background: var(--accent);  color: #fff; }
  .btn-primary:hover { opacity: 0.85; }

  .btn-secondary { background: rgba(255, 255, 255, 0.08); color: var(--text); }
  .btn-secondary:hover { background: rgba(255, 255, 255, 0.15); }

  .empty {
    text-align: center;
    padding: 60px 20px;
    color: var(--muted);
    line-height: 1.7;
  }

  .empty .icon { font-size: 2.2rem; display: block; margin-bottom: 14px; }

  @media (max-width: 600px) {
    body  { padding-top: 44px; }
    .hero h1 { font-size: 1.9rem; }
    .card { padding: 16px 18px; }
  }
</style>
</head>
<body>

<!-- Video Background Loop -->
<div class="video-background">
  <video autoplay loop muted playsinline>
    <source src="cooking.mp4" type="video/mp4">
  </video>
  <div class="video-overlay"></div>
</div>

<header class="hero">
  <span class="hero-eyebrow">&#x1F35D; Nearby Eats</span>
  <h1>What do you want<br>to <em>eat tonight?</em></h1>
  <p>Type any craving — pizza, ramen, a cold beer — and we'll find spots nearby.</p>
</header>

<div class="search-wrap">
  <input id="search" type="text"
    placeholder="pizza, sushi, tacos, coffee&#x2026;"
    autocomplete="off" spellcheck="false" aria-label="Food search">
  <button class="search-btn" id="searchBtn" aria-label="Search">&#x1F50D;</button>
</div>

<p class="status" id="status" aria-live="polite"></p>
<div class="results-header" id="resultsHeader" hidden aria-live="polite"></div>
<div class="results" id="results" role="list"></div>

<script>
  const searchInput = document.getElementById("search");
  const searchBtn   = document.getElementById("searchBtn");
  const statusEl    = document.getElementById("status");
  const resultsEl   = document.getElementById("results");
  const headerEl    = document.getElementById("resultsHeader");

  function setStatus(msg, isError = false) {
    statusEl.textContent = msg;
    statusEl.className   = isError ? "status error" : "status";
  }

  function esc(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function getLocation() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) {
        reject(new Error("Geolocation is not supported by this browser."));
        return;
      }
      navigator.geolocation.getCurrentPosition(resolve, (err) => {
        const messages = {
          1: "Location access denied — please allow it in your browser settings.",
          2: "Location unavailable — check your connection and try again.",
          3: "Location request timed out — try again.",
        };
        reject(new Error(messages[err.code] || "Unknown location error."));
      }, { timeout: 8000 });
    });
  }

  function renderResults({ label, query, places }) {
    headerEl.hidden = false;
    headerEl.innerHTML =
      `<h2>Near you for <em>${esc(query)}</em></h2>` +
      `<span class="count">${places.length} place${places.length !== 1 ? "s" : ""}</span>`;

    if (!places.length) {
      resultsEl.innerHTML =
        `<div class="empty">` +
          `<span class="icon">&#x1F62D;</span>` +
          `Nothing nearby matched <strong>${esc(query)}</strong>.<br>` +
          `Try a broader term like "restaurant".` +
        `</div>`;
      return;
    }

    resultsEl.innerHTML = places.map((p, i) => {
      const hoursHtml   = p.hours   ? `<span>&#x1F552; ${esc(p.hours)}</span>`   : "";
      const phoneHtml   = p.phone   ? `<span>&#x1F4DE; ${esc(p.phone)}</span>`   : "";
      const websiteHtml = p.website
        ? `<a class="btn btn-secondary" href="${esc(p.website)}" target="_blank" rel="noopener">&#x1F310; Website</a>`
        : "";

      return (
        `<div class="card" role="listitem" style="animation-delay:${i * 50}ms">` +
          `<span class="card-name">${esc(p.name)}</span>` +
          `<span class="card-badge">&#x1F4CD; ${p.distance} km</span>` +
          `<div class="card-meta">${hoursHtml}${phoneHtml}</div>` +
          `<div class="card-links">` +
            `<a class="btn btn-primary" href="${esc(p.maps)}" target="_blank" rel="noopener">&#x1F5FA; Open in Maps</a>` +
            websiteHtml +
          `</div>` +
        `</div>`
      );
    }).join("");
  }

  async function doSearch() {
    const food = searchInput.value.trim();
    if (!food) { setStatus("Type something first.", true); return; }

    setStatus("Getting your location\u2026");
    resultsEl.innerHTML = "";
    headerEl.hidden     = true;

    let position;
    try {
      position = await getLocation();
    } catch (err) {
      setStatus(err.message, true);
      return;
    }

    setStatus("Finding nearby spots\u2026");

    try {
      const resp = await fetch("/api/places", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          latitude:  position.coords.latitude,
          longitude: position.coords.longitude,
          food,
        }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
        throw new Error(err.error || `HTTP ${resp.status}`);
      }

      const data = await resp.json();
      setStatus("");
      renderResults(data);
    } catch (err) {
      setStatus(`Could not load results: ${err.message}`, true);
    }
  }

  searchBtn.addEventListener("click", doSearch);
  searchInput.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });
</script>
</body>
</html>"""

# ── HTTP handler ───────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        log.info("%s  %s", self.address_string(), fmt % args)

    def do_GET(self):
        # Dynamically serve ANY requested .mp4 file
        if self.path.endswith(".mp4"):
            file_path = self.path.lstrip("/")
            if os.path.exists(file_path):
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(os.path.getsize(file_path)))
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_error(404, "Video file not found")
                return

        # Serve the HTML frontend
        body = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type",   "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/places":
            self._send_json({"error": "Not found"}, 404)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length))
            lat    = float(body["latitude"])
            lon    = float(body["longitude"])
            food   = str(body["food"]).strip()
            if not food:
                raise ValueError("food must not be empty")
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, 400)
            return

        log.info("Search  food=%r  lat=%.4f  lon=%.4f", food, lat, lon)
        label, meta = resolve_category(food)
        log.info("Matched label=%r  cats=%s", label, meta["cats"])

        places  = fetch_places(lat, lon, meta)
        payload = {"label": label, "query": food, "places": places}
        self._send_json(payload, 200)

    def _send_json(self, data: dict, status: int):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    # Render assigns a dynamic port via environment variables
    port = int(os.environ.get("PORT", 8000))

    # Bind to "0.0.0.0" so Render's routing proxy can direct web traffic to your app
    server = HTTPServer(("0.0.0.0", port), Handler)
    log.info("Server running on port %d", port)

    # Blocks and keeps the server listening continuously in the cloud
    server.serve_forever()


if __name__ == "__main__":
    main()
