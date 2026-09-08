
from __future__ import annotations

import webbrowser
import difflib
import json
import logging
import signal
import sys
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import os

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
PORT = 8000
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

# ── Food term registry ────────────────────────────────────────────────────────
# Google Text Search does the actual place lookup (names, existence, address),
# so this is just for typo correction and building a richer search phrase —
# it no longer maps to any external category system.
FOOD_REGISTRY: dict[str, list[str]] = {
    "pizza":        ["pizza", "italian"],
    "burger":       ["burger", "grill", "smash"],
    "coffee":       ["coffee", "cafe", "espresso"],
    "latte":        ["coffee", "cafe", "latte"],
    "espresso":     ["espresso", "coffee", "cafe"],
    "cappuccino":   ["cappuccino", "coffee", "cafe"],
    "sushi":        ["sushi", "japanese", "rolls"],
    "ramen":        ["ramen", "japanese", "noodle"],
    "pho":          ["pho", "vietnamese", "noodle"],
    "wings":        ["chicken", "wings", "wing"],
    "fried chicken":["chicken", "fried", "poultry"],
    "beer":         ["pub", "bar", "beer", "ale", "draft"],
    "pub":          ["pub", "bar", "tavern"],
    "nachos":       ["mexican", "nachos", "tex-mex"],
    "tacos":        ["tacos", "mexican", "taqueria"],
    "fries":        ["fast food", "fries", "burger"],
    "chinese":      ["chinese", "dim sum", "wonton"],
    "thai":         ["thai", "pad thai", "curry"],
    "indian":       ["indian", "curry", "tandoor", "biryani"],
    "curry":        ["curry", "indian", "thai", "spice"],
    "pasta":        ["italian", "pasta", "trattoria"],
    "italian":      ["italian", "pasta", "pizza", "trattoria"],
    "steak":        ["steak", "steakhouse", "grill", "chop"],
    "bbq":          ["bbq", "barbecue", "smokehouse", "grill"],
    "sandwich":     ["sandwich", "deli", "sub", "wrap"],
    "breakfast":    ["breakfast", "brunch", "eggs", "pancake"],
    "brunch":       ["brunch", "breakfast", "eggs", "mimosa"],
    "vegan":        ["vegan", "plant-based", "vegetarian"],
    "vegetarian":   ["vegetarian", "vegan", "veggie"],
    "noodles":      ["noodle", "ramen", "pho", "asian"],
    "kebab":        ["kebab", "shawarma", "doner", "döner", "gyro"],
    "shawarma":     ["shawarma", "kebab", "doner", "döner", "gyro"],
    "ice cream":    ["ice cream", "gelato", "sorbet", "frozen"],
    "dessert":      ["dessert", "bakery", "cake", "pastry"],
    "bakery":       ["bakery", "bread", "pastry", "boulangerie"],
    "dumplings":    ["dumpling", "dim sum", "gyoza", "bao"],
    "greek":        ["greek", "mediterranean", "gyro", "souvlaki"],
    "mediterranean":["mediterranean", "greek", "falafel", "hummus"],
    "korean":       ["korean", "bibimbap", "bulgogi", "kbbq"],
}

# ── Category resolver ──────────────────────────────────────────────────────────
def resolve_category(text: str) -> tuple[str, list[str]]:
    lower = text.lower().strip()

    if lower in FOOD_REGISTRY:
        return text.title(), FOOD_REGISTRY[lower]

    for key, hints in FOOD_REGISTRY.items():
        if key in lower:
            return key.title(), hints

    for key, hints in FOOD_REGISTRY.items():
        if lower in key:
            return key.title(), hints

    # Catch typos (e.g. "shawama" for "shawarma") so a small misspelling
    # doesn't fall through as a raw, uncorrected search term.
    close = difflib.get_close_matches(lower, FOOD_REGISTRY.keys(), n=1, cutoff=0.75)
    if close:
        key = close[0]
        return key.title(), FOOD_REGISTRY[key]

    return text.title(), [lower]

# ── HTML frontend ──────────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nearby Eats</title>

<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0D0D14">
<link rel="icon" href="/icon-192.png">
<link rel="apple-touch-icon" href="/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Nearby Eats">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:         #0D0D14;
    --surface:    rgba(22, 22, 31, 0.85);
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

  /* ── Hamburger Button ── */
  .hamburger {
    position: fixed;
    top: 20px;
    left: 20px;
    z-index: 1001;
    background: var(--surface);
    backdrop-filter: blur(12px);
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    padding: 10px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 5px;
    transition: border-color var(--ease), background var(--ease);
  }

  .hamburger:hover { border-color: var(--accent); }

  .hamburger span {
    display: block;
    width: 20px;
    height: 2px;
    background-color: var(--text);
    border-radius: 2px;
    transition: all 300ms ease;
  }

  .hamburger.open span:nth-child(1) { transform: translateY(7px) rotate(45deg); }
  .hamburger.open span:nth-child(2) { opacity: 0; }
  .hamburger.open span:nth-child(3) { transform: translateY(-7px) rotate(-45deg); }

  /* ── Sliding Sidebar ── */
  .sidebar {
    position: fixed;
    top: 0;
    left: -280px;
    width: 280px;
    height: 100vh;
    background: var(--surface);
    backdrop-filter: blur(20px);
    border-right: 1px solid var(--border);
    padding: 80px 24px 30px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    z-index: 1000;
    transition: left 300ms ease-in-out;
    box-shadow: 10px 0 30px rgba(0, 0, 0, 0.5);
  }

  .sidebar.active { left: 0; }

  .sidebar-header {
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 12px;
  }

  .sidebar a {
    color: var(--text);
    text-decoration: none;
    font-size: 1rem;
    font-weight: 600;
    padding: 12px 16px;
    border-radius: var(--r-sm);
    transition: background var(--ease), color var(--ease);
  }

  .sidebar a:hover {
    background: var(--accent-lo);
    color: var(--accent);
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
    opacity: 0.22;
    filter: blur(2px);
  }

  .video-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(13, 13, 20, 0.5);
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

  .hero h1 em { font-style: normal; color: var(--accent); }

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

  /* ── Results Header ── */
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

  .results-header h2 em { font-style: normal; color: var(--accent); }

  .results-header .count {
    font-size: 0.8rem;
    color: var(--muted);
  }

  /* ── Cards & Dynamic Place Details ── */
  .results {
    width: 100%;
    max-width: 660px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .card {
    background: var(--surface);
    backdrop-filter: blur(12px);
    border: 1.5px solid var(--border);
    border-radius: var(--r-lg);
    padding: 22px;
    display: flex;
    flex-direction: column;
    gap: 12px;
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

  .card-top {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 10px;
  }

  .card-name {
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--text);
  }

  .card-address {
    font-size: 0.85rem;
    color: var(--muted);
    line-height: 1.4;
  }

  .card-badge {
    background: var(--accent-lo);
    color: var(--accent);
    border-radius: 50px;
    padding: 4px 12px;
    font-size: 0.75rem;
    font-weight: 700;
    white-space: nowrap;
  }

  /* Rating and Phone Bar */
  .rating-phone-bar {
    display: flex;
    align-items: center;
    gap: 14px;
    font-size: 0.88rem;
    flex-wrap: wrap;
  }
  .rating-box { display: flex; align-items: center; gap: 6px; }
  .stars { color: #f39c12; font-weight: bold; letter-spacing: 1px; }
  .rating-score { font-weight: bold; color: #fff; }
  .rating-count { color: var(--muted); font-size: 0.8rem; }
  .phone-box a { color: #4da6ff; text-decoration: none; font-weight: 500; }
  .phone-box a:hover { text-decoration: underline; }

  /* Dynamic Color Themes for Hours Tile */
  .hours-container {
    border-radius: 8px;
    padding: 14px;
    transition: all 0.3s ease;
  }
  .theme-open {
    background: linear-gradient(135deg, rgba(40, 167, 69, 0.15) 0%, rgba(30, 30, 30, 0.95) 70%);
    border: 1px solid rgba(40, 167, 69, 0.4);
  }
  .theme-closing-soon {
    background: linear-gradient(135deg, rgba(255, 193, 7, 0.18) 0%, rgba(30, 30, 30, 0.95) 70%);
    border: 1px solid rgba(255, 193, 7, 0.5);
  }
  .theme-closed {
    background: linear-gradient(135deg, rgba(220, 53, 69, 0.15) 0%, rgba(30, 30, 30, 0.95) 70%);
    border: 1px solid rgba(220, 53, 69, 0.4);
  }

  .status-badge {
    display: inline-block;
    font-size: 0.75rem;
    font-weight: bold;
    padding: 3px 8px;
    border-radius: 4px;
    margin-bottom: 8px;
  }
  .badge-open { background: rgba(40, 167, 69, 0.25); color: #2ecc71; border: 1px solid #2ecc71; }
  .badge-closing-soon { background: rgba(255, 193, 7, 0.25); color: #ffca28; border: 1px solid #ffca28; }
  .badge-closed { background: rgba(220, 53, 69, 0.25); color: #e74c3c; border: 1px solid #e74c3c; }

  .hours-list {
    list-style: none;
    padding: 0;
    margin: 0;
    font-size: 0.82rem;
    color: #ccc;
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 4px;
  }

  /* Photo Gallery Grid */
  .gallery {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-top: 4px;
  }
  .photo-card {
    display: flex;
    flex-direction: column;
    background: #1e1e1e;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid #2a2a2a;
  }
  .photo-card img { width: 100%; height: 110px; object-fit: cover; background: #333; }
  .author { font-size: 0.7rem; color: #aaa; padding: 6px; text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* Recent Reviews */
  .reviews-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .review-item {
    background: #1e1e1e;
    border: 1px solid #2a2a2a;
    border-radius: 8px;
    padding: 10px 12px;
  }
  .review-top {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 4px;
  }
  .review-author { font-size: 0.8rem; font-weight: 600; color: var(--text); }
  .review-stars { color: #f39c12; font-size: 0.8rem; letter-spacing: 1px; }
  .review-time { font-size: 0.75rem; color: var(--muted); margin-left: auto; }
  .review-text {
    font-size: 0.82rem;
    color: #ccc;
    line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  /* Skeletons */
  .skeleton-card { display: flex; flex-direction: column; background: #1e1e1e; border-radius: 8px; overflow: hidden; border: 1px solid #2a2a2a; }
  .skeleton-img { width: 100%; height: 110px; background: #2a2a2a; position: relative; overflow: hidden; }
  .skeleton-text { height: 10px; margin: 8px; background: #2a2a2a; border-radius: 4px; position: relative; overflow: hidden; }
  .skeleton-hours { height: 70px; background: #1e1e1e; border: 1px solid #2a2a2a; border-radius: 8px; position: relative; overflow: hidden; }

  .skeleton-img::after, .skeleton-text::after, .skeleton-hours::after {
    content: "";
    position: absolute;
    top: 0; right: 0; bottom: 0; left: 0;
    transform: translateX(-100%);
    background: linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.05) 50%, rgba(255,255,255,0) 100%);
    animation: shimmer 1.5s infinite;
  }

  @keyframes shimmer { 100% { transform: translateX(100%); } }

  .card-links {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 6px;
    padding-top: 12px;
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
    body { padding-top: 44px; }
    .hero h1 { font-size: 1.9rem; }
    .gallery { grid-template-columns: 1fr; }
    .hours-list { grid-template-columns: 1fr; }
  }
</style>

<script src="https://maps.googleapis.com/maps/api/js?key=__GOOGLE_MAPS_API_KEY__&libraries=places"></script>
</head>
<body>

<button class="hamburger" id="hamburgerBtn" aria-label="Toggle menu">
  <span></span>
  <span></span>
  <span></span>
</button>

<nav class="sidebar" id="sidebar">
  <div class="sidebar-header">Menu</div>
  <a href="#home">Home</a>
  <a href="#saved">Saved Places</a>
  <a href="#history">Search History</a>
  <a href="#settings">Settings</a>
</nav>

<div class="video-background">
  <video autoplay loop muted playsinline>
    <source src="cooking.mp4" type="video/mp4">
  </video>
  <div class="video-overlay"></div>
</div>

<header class="hero">
  <span class="hero-eyebrow">🍝 Nearby Eats</span>
  <h1>What do you want<br>to <em>eat tonight?</em></h1>
  <p>Type any craving — pizza, ramen, a cold beer — and we'll find spots nearby.</p>
</header>

<div class="search-wrap">
  <input id="search" type="text"
    placeholder="pizza, sushi, tacos, coffee…"
    autocomplete="off" spellcheck="false" aria-label="Food search">
  <button class="search-btn" id="searchBtn" aria-label="Search">🔍</button>
</div>

<p class="status" id="status" aria-live="polite"></p>
<div class="results-header" id="resultsHeader" hidden aria-live="polite"></div>
<div class="results" id="results" role="list"></div>

<div id="map-dummy" style="display:none;"></div>

<script>
  const hamburgerBtn = document.getElementById("hamburgerBtn");
  const sidebar      = document.getElementById("sidebar");
  const searchInput  = document.getElementById("search");
  const searchBtn    = document.getElementById("searchBtn");
  const statusEl     = document.getElementById("status");
  const resultsEl    = document.getElementById("results");
  const headerEl     = document.getElementById("resultsHeader");

  hamburgerBtn.addEventListener("click", () => {
    hamburgerBtn.classList.toggle("open");
    sidebar.classList.toggle("active");
  });

  document.addEventListener("click", (e) => {
    if (!sidebar.contains(e.target) && !hamburgerBtn.contains(e.target)) {
      sidebar.classList.remove("active");
      hamburgerBtn.classList.remove("open");
    }
  });

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

  function checkIfOpen(openingHours) {
    if (!openingHours) return false;

    // Detect Google's 24/7 period structure (starts Sunday 00:00 with no closing time)
    if (openingHours.periods && openingHours.periods.length === 1) {
      const period = openingHours.periods[0];
      if (period.open && period.open.day === 0 && period.open.time === "0000" && !period.close) {
        return true;
      }
    }

    // Standard check for regular operating hours
    return openingHours.isOpen ? openingHours.isOpen() : false;
  }

  function checkClosingSoon(periods) {
    if (!periods || periods.length === 0) return false;
    const now = new Date();
    const currentDay = now.getDay(); 
    const currentMinutes = now.getHours() * 60 + now.getMinutes();

    const todayPeriod = periods.find(p => p.open && p.open.day === currentDay);
    if (!todayPeriod || !todayPeriod.close) return false;

    const closeMinutes = parseInt(todayPeriod.close.time.substring(0, 2)) * 60 + parseInt(todayPeriod.close.time.substring(2));
    const diffMinutes = closeMinutes - currentMinutes;

    return diffMinutes > 0 && diffMinutes <= 60;
  }

  function haversineKm(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const toRad = d => d * Math.PI / 180;
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a = Math.sin(dLat / 2) ** 2 +
      Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }

  // Google Text Search is the single source of truth for the place list
  // itself (names, existence, address) — one call per user search. Per-card
  // getDetails still supplies hours/rating/phone, same as before.
  function googleTextSearch(service, query, lat, lon) {
    return new Promise((resolve) => {
      service.textSearch({
        query,
        location: new google.maps.LatLng(lat, lon),
        radius: 10000,
      }, (results, status) => {
        if (status !== google.maps.places.PlacesServiceStatus.OK || !results) {
          resolve([]);
          return;
        }
        resolve(results);
      });
    });
  }

  function buildPlacesFromGoogle(googleResults, userLat, userLon) {
    return googleResults
      .filter(g => g.geometry && g.geometry.location && g.name)
      .map(g => {
        const glat = g.geometry.location.lat();
        const glon = g.geometry.location.lng();
        return {
          name:     g.name,
          distance: Math.round(haversineKm(userLat, userLon, glat, glon) * 100) / 100,
          lat:      glat,
          lon:      glon,
          address:  g.formatted_address || g.vicinity || "",
          maps:     `https://www.google.com/maps/search/?api=1&query=${glat},${glon}`,
          website:  null,
          phone:    null,
          placeId:  g.place_id,
        };
      })
      .sort((a, b) => a.distance - b.distance);
  }

  function renderStars(rating) {
    const fullStars = Math.floor(rating);
    const halfStar = rating % 1 >= 0.5 ? '★' : '';
    const emptyStars = 5 - Math.ceil(rating);
    return '★'.repeat(fullStars) + (halfStar ? '½' : '') + '☆'.repeat(Math.max(0, emptyStars));
  }

  function renderResults({ label, query, places }, service) {
    headerEl.hidden = false;
    headerEl.innerHTML =
      `<h2>Near you for <em>${esc(query)}</em></h2>` +
      `<span class="count">${places.length} place${places.length !== 1 ? "s" : ""}</span>`;

    if (!places.length) {
      resultsEl.innerHTML =
        `<div class="empty">` +
          `<span class="icon">😭</span>` +
          `Nothing nearby matched <strong>${esc(query)}</strong>.<br>` +
          `Try a broader term like "restaurant".` +
        `</div>`;
      return;
    }

    resultsEl.innerHTML = places.map((p, i) => {
      const websiteHtml = p.website
        ? `<a class="btn btn-secondary" href="${esc(p.website)}" target="_blank" rel="noopener">🌐 Website</a>`
        : "";

      return (
        `<div class="card" id="card-${i}" role="listitem" style="animation-delay:${i * 50}ms">` +
          `<div class="card-top">` +
            `<span class="card-name">${esc(p.name)}</span>` +
            `<span class="card-badge">📍 ${p.distance} km</span>` +
          `</div>` +
          (p.address ? `<div class="card-address">${esc(p.address)}</div>` : "") +
          `<div id="place-info-${i}" class="rating-phone-bar"><span style="color:#888;">Loading details...</span></div>` +
          `<div id="hours-${i}"><div class="skeleton-hours"></div></div>` +
          `<div id="gallery-${i}" class="gallery">` +
            `<div class="skeleton-card"><div class="skeleton-img"></div><div class="skeleton-text"></div></div>` +
            `<div class="skeleton-card"><div class="skeleton-img"></div><div class="skeleton-text"></div></div>` +
            `<div class="skeleton-card"><div class="skeleton-img"></div><div class="skeleton-text"></div></div>` +
          `</div>` +
          `<div id="reviews-${i}" class="reviews-list"></div>` +
          `<div class="card-links">` +
            `<a class="btn btn-primary" href="${esc(p.maps)}" target="_blank" rel="noopener">🗺 Open in Maps</a>` +
            websiteHtml +
          `</div>` +
        `</div>`
      );
    }).join("");

    // Throttle Google Places API requests by 80ms per place to avoid OVER_QUERY_LIMIT
    service = service || new google.maps.places.PlacesService(document.getElementById("map-dummy"));
    places.forEach((p, i) => {
      setTimeout(() => fetchGoogleDetails(service, p, i), i * 80);
    });
  }

  function fetchGoogleDetails(service, place, index) {
    const infoEl    = document.getElementById(`place-info-${index}`);
    const hoursEl   = document.getElementById(`hours-${index}`);
    const galleryEl = document.getElementById(`gallery-${index}`);
    const reviewsEl = document.getElementById(`reviews-${index}`);

    // Every place comes from the Google Text Search that built the list, so
    // its place_id is already known — go straight to getDetails.
    service.getDetails({
        placeId: place.placeId,
        // 'utc_offset_minutes' is required alongside 'opening_hours' for isOpen() to
        // correctly compute the place's status relative to its own local time —
        // without it isOpen() silently reads as closed even when actually open.
        fields: ['name', 'formatted_address', 'opening_hours', 'utc_offset_minutes', 'rating', 'user_ratings_total', 'formatted_phone_number', 'business_status', 'photos', 'reviews']
      }, (details, detailStatus) => {
        if (detailStatus !== google.maps.places.PlacesServiceStatus.OK || !details) {
          infoEl.innerHTML = `<span style="color:#888; font-size:0.8rem;">Details unavailable</span>`;
          hoursEl.innerHTML = "";
          galleryEl.innerHTML = "";
          reviewsEl.innerHTML = "";
          return;
        }

        if (details.business_status === "CLOSED_PERMANENTLY") {
          const card = document.getElementById(`card-${index}`);
          if (card) card.remove();
          return;
        }

        // Rating & Phone
        const ratingHtml = details.rating ? `
          <div class="rating-box">
            <span class="rating-score">${details.rating.toFixed(1)}</span>
            <span class="stars">${renderStars(details.rating)}</span>
            <span class="rating-count">(${details.user_ratings_total ? details.user_ratings_total.toLocaleString() : 0})</span>
          </div>
        ` : '<span style="color:#888;">No rating</span>';

        const phoneNum = details.formatted_phone_number || place.phone;
        const phoneHtml = phoneNum ? `
          <div class="phone-box">
            📞 <a href="tel:${phoneNum.replace(/\\s+/g, '')}">${phoneNum}</a>
          </div>
        ` : '<span style="color:#888;">No phone available</span>';

        infoEl.innerHTML = `${ratingHtml} <span style="color:#444;">•</span> ${phoneHtml}`;

        // Hours & Status
        if (details.opening_hours) {
          const isOpen = checkIfOpen(details.opening_hours);
          const isClosingSoon = isOpen && checkClosingSoon(details.opening_hours.periods);

          let themeClass = 'theme-closed';
          let badgeClass = 'badge-closed';
          let statusText = '● CLOSED';

          if (isOpen) {
            if (isClosingSoon) {
              themeClass = 'theme-closing-soon';
              badgeClass = 'badge-closing-soon';
              statusText = '● CLOSING SOON';
            } else {
              themeClass = 'theme-open';
              badgeClass = 'badge-open';
              statusText = '● OPEN NOW';
            }
          }

          const weekdayList = details.opening_hours.weekday_text 
            ? details.opening_hours.weekday_text.map(day => `<li>${day}</li>`).join('') 
            : '<li>Hours unavailable</li>';

          hoursEl.innerHTML = `
            <div class="hours-container ${themeClass}">
              <span class="status-badge ${badgeClass}">${statusText}</span>
              <ul class="hours-list">${weekdayList}</ul>
            </div>
          `;
        } else {
          hoursEl.innerHTML = "";
        }

        // Photos
        if (!details.photos || details.photos.length === 0) {
          galleryEl.innerHTML = "";
        } else {
          const userPhotos = details.photos.filter(p => p.html_attributions && p.html_attributions.length > 0);
          const recentPhotos = (userPhotos.length > 0 ? userPhotos : details.photos).reverse().slice(0, 3);

          galleryEl.innerHTML = recentPhotos.map(p => {
            const imgUrl = p.getUrl({ maxWidth: 400, maxHeight: 400 });
            let author = "Google Reviewer";

            if (p.html_attributions && p.html_attributions.length > 0) {
              const tempDiv = document.createElement("div");
              tempDiv.innerHTML = p.html_attributions[0];
              author = tempDiv.textContent || tempDiv.innerText || "Google Reviewer";
            }

            return `
              <div class="photo-card">
                <img src="${imgUrl}" alt="Google Review Photo">
                <div class="author">By ${author}</div>
              </div>
            `;
          }).join("");
        }

        // Reviews — sorted most-recent-first using each review's real
        // `time` (a Unix timestamp), unlike photos which carry no date at all.
        if (!details.reviews || details.reviews.length === 0) {
          reviewsEl.innerHTML = "";
        } else {
          const oneYearAgo = Date.now() / 1000 - 365 * 24 * 60 * 60;
          const recentReviews = details.reviews
            .filter(r => r.time >= oneYearAgo)
            .sort((a, b) => b.time - a.time)
            .slice(0, 3);

          reviewsEl.innerHTML = recentReviews.map(r => `
            <div class="review-item">
              <div class="review-top">
                <span class="review-author">${esc(r.author_name)}</span>
                <span class="review-stars">${renderStars(r.rating)}</span>
                <span class="review-time">${esc(r.relative_time_description)}</span>
              </div>
              <p class="review-text">${esc(r.text)}</p>
            </div>
          `).join("");
        }
      });
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
      // Local typo-correction / search-phrase lookup only — no external API
      // call here. Google Text Search (below) is what actually finds places.
      const resp = await fetch("/api/places", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ food }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
        throw new Error(err.error || `HTTP ${resp.status}`);
      }

      const { label, query } = await resp.json();

      const service = new google.maps.places.PlacesService(document.getElementById("map-dummy"));
      const googleResults = await googleTextSearch(
        service, label, position.coords.latitude, position.coords.longitude
      );
      const places = buildPlacesFromGoogle(
        googleResults, position.coords.latitude, position.coords.longitude
      );

      setStatus("");
      renderResults({ label, query, places }, service);
    } catch (err) {
      setStatus(`Could not load results: ${err.message}`, true);
    }
  }

  searchBtn.addEventListener("click", doSearch);
  searchInput.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js").catch(err => {
        console.error("Service worker registration failed:", err);
      });
    });
  }
</script>
</body>
</html>"""

# ── PWA assets ─────────────────────────────────────────────────────────────────
MANIFEST_JSON = """{
  "name": "Nearby Eats",
  "short_name": "Nearby Eats",
  "description": "Find nearby restaurants for any craving.",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0D0D14",
  "theme_color": "#0D0D14",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}"""

# Minimal offline shell caching — just enough to satisfy PWA installability
# and let the app open (with stale content) when briefly offline.
SERVICE_WORKER_JS = """
const CACHE_NAME = "nearby-eats-v2";
const SHELL_URLS = ["/", "/manifest.json", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  // Network-first: always try to get the latest version. Cache is only a
  // fallback for when the network is actually unavailable — a cache-first
  // strategy here would keep serving stale HTML/JS forever after every code
  // change, even across server restarts.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
"""

# ── HTTP Handler ───────────────────────────────────────────────────────────────
class RequestHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        """Serve frontend HTML or static media/PWA files."""
        if self.path.endswith(".mp4"):
            file_path = self.path.lstrip("/")
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(file_size))
                self.end_headers()

                with open(file_path, "rb") as f:
                    while chunk := f.read(64 * 1024):
                        try:
                            self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            break
                return
            else:
                self.send_error(404, "Video file not found")
                return

        if self.path == "/manifest.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json")
            self.end_headers()
            self.wfile.write(MANIFEST_JSON.encode("utf-8"))
            return

        if self.path == "/service-worker.js":
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.end_headers()
            self.wfile.write(SERVICE_WORKER_JS.encode("utf-8"))
            return

        if self.path in ("/icon-192.png", "/icon-512.png"):
            file_path = self.path.lstrip("/")
            if os.path.exists(file_path):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "Icon not found")
            return

        page = HTML.replace("__GOOGLE_MAPS_API_KEY__", GOOGLE_MAPS_API_KEY)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def do_POST(self):
        """Handle JSON requests sent to /api/places."""
        if self.path == "/api/places":
            content_length = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_length)

            try:
                data = json.loads(post_body.decode("utf-8"))
                food = str(data["food"])

                label, hints = resolve_category(food)

                response_payload = {
                    "label": label,
                    "query": food,
                    "hints": hints,
                }

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(response_payload).encode("utf-8"))

            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Invalid payload: {exc}"}).encode("utf-8"))
        else:
            self.send_error(404, "Endpoint Not Found")

    def log_message(self, format, *args):
        """Route HTTP server logs through Python's standard logging module."""
        log.info("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), format % args))


# ── Server Runner ──────────────────────────────────────────────────────────────
def run_server():
    if not GOOGLE_MAPS_API_KEY:
        log.warning(
            "GOOGLE_MAPS_API_KEY is not set — search will not work. "
            "Run: export GOOGLE_MAPS_API_KEY=your_key_here"
        )

    # Hosting platforms (Render, Railway, etc.) assign their own port via
    # $PORT and require binding to 0.0.0.0, not 127.0.0.1 — a server bound
    # to localhost only accepts connections from inside the same machine,
    # which is unreachable from their router/load balancer.
    port = int(os.environ.get("PORT", PORT))
    is_deployed = bool(os.environ.get("RENDER") or os.environ.get("PORT"))
    host = "0.0.0.0" if is_deployed else "127.0.0.1"

    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, RequestHandler)
    log.info("Server listening on http://%s:%d", host, port)

    # Only auto-open a browser tab for local runs — there's no browser to
    # open on a remote server, and no display to open it on even if there were.
    if not is_deployed:
        threading.Thread(target=lambda: webbrowser.open(f"http://127.0.0.1:{port}"), daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down server...")
        httpd.server_close()
        sys.exit(0)

if __name__ == "__main__":
    run_server()

