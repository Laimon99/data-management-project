from __future__ import annotations

START_URL = (
    "https://www.thefork.it/ristoranti/milano-c348156"
    "?cc=17176-c38&gad_source=1&gad_campaignid=8361461667"
    "&gclid=CjwKCAjw8uTQBhAdEiwAVvtJyuytSBG4Ly5PzeXRIz0hmBsi4Y0osJXr09YduTdbXMVxXZl2PldaIRoC-AoQAvD_BwE"
)
SCRAPE_DETAIL_PAGES = True
HEADLESS = True
MAX_RESTAURANTS = None
MAX_LISTING_PAGES = None
MAX_REVIEWS_PER_RESTAURANT = 5
DELAY_BETWEEN_LISTING_PAGES_SECONDS = 1.5
DELAY_BETWEEN_DETAIL_PAGES_SECONDS = 2.0
SAVE_PARTIAL_EVERY_N_RESTAURANTS = 25
MAX_CONSECUTIVE_EMPTY_PAGES = 3
DETAIL_BATCH_SIZE = 25
COOLDOWN_SECONDS = 900
MAX_COOLDOWN_SECONDS = 3600
COOLDOWN_MULTIPLIER = 1.5
MAX_AUTO_DETAIL_CYCLES = 50
OUTPUT_FILE = "data/raw/thefork/thefork_milan_restaurants_normalized.json"
PARTIAL_OUTPUT_FILE = "data/raw/thefork/thefork_milan_restaurants_normalized_partial.json"
VALIDATION_REPORT_FILE = "data/raw/thefork/thefork_milan_validation_report.json"
