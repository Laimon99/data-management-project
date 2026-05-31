from __future__ import annotations

START_URL = "https://www.tripadvisor.it/Restaurants-g187849-Milan_Lombardy.html"
SCRAPE_DETAIL_PAGES = True
HEADLESS = True
MAX_RESTAURANTS = None
MAX_LISTING_PAGES = None
MAX_REVIEWS_PER_RESTAURANT = 5
DELAY_BETWEEN_LISTING_PAGES_SECONDS = 1.5
DELAY_BETWEEN_DETAIL_PAGES_SECONDS = 5.0
SAVE_PARTIAL_EVERY_N_RESTAURANTS = 25
MAX_CONSECUTIVE_EMPTY_PAGES = 3
DETAIL_BATCH_SIZE = 50
COOLDOWN_SECONDS = 900
MAX_COOLDOWN_SECONDS = 3600
COOLDOWN_MULTIPLIER = 1.5
MAX_AUTO_DETAIL_CYCLES = 300
OUTPUT_FILE = "output/tripadvisor_milan_restaurants_normalized.json"
PARTIAL_OUTPUT_FILE = "output/tripadvisor_milan_restaurants_normalized_partial.json"
VALIDATION_REPORT_FILE = "output/tripadvisor_milan_validation_report.json"
