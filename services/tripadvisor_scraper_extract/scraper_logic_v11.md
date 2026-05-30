## Table of Contents

1. [Introduction and Target Complexity (TripAdvisor)](#1-introduction-and-target-complexity-tripadvisor)
2. [Tech Stack: Playwright Asyncio](#2-tech-stack-playwright-asyncio)
3. [Evasion Strategies and Anti-Detection (Human Behaviour Simulation)](#3-evasion-strategies-and-anti-detection-human-behaviour-simulation)
4. [Data Flow Architecture (The Two Loops)](#4-data-flow-architecture-the-two-loops)
5. [Advanced Debug Focus: Reviews and Author Extraction](#5-advanced-debug-focus-reviews-and-author-extraction)
6. [Checkpoint System (Resume Logic)](#6-checkpoint-system-resume-logic)

---

## 1. Introduction and Target Complexity (TripAdvisor)

### 1.1 Why TripAdvisor Represents a High-Complexity Scraping Target

Unlike simpler static websites, TripAdvisor deploys a layered, multi-vendor anti-bot infrastructure that combines passive fingerprinting, active behavioural analysis, and real-time traffic scoring. The platform integrates solutions consistent with industry leaders such as **Cloudflare Bot Management** and **DataDome**, creating a defense-in-depth model that is deliberately opaque to reverse engineering.

The key threat vectors that make TripAdvisor a hostile environment for automated agents include:

| Defense Layer | Mechanism | Impact on Naive Scrapers |
|---|---|---|
| **TLS Fingerprinting** | Identifies non-browser TLS handshakes from Python `requests` or `httpx` | Immediate IP block |
| **Browser Fingerprinting** | Collects canvas hash, WebGL renderer, font metrics, screen resolution | Headless Chromium profiling and blacklisting |
| **Behavioural Analytics** | Tracks mouse velocity, scroll patterns, inter-click timing, and DOM interaction entropy | Flags robotic regularity |
| **IP Velocity Scoring** | Tracks requests-per-second per IP and subnet | Rate limiting and temporary or permanent bans |
| **Honeypot Links** | Invisible `<a>` tags that no human would click | Instant ban trigger if followed |
| **JavaScript Challenges** | Dynamic scripts validate browser environment before rendering content | Python HTTP clients receive empty or partial HTML |

Any automation tool that does not replicate a genuine, human-operated browser session at the TLS, HTTP, and behavioural layers simultaneously will be identified and blocked, typically within the first few dozen requests.

### 1.2 The Problem of Dynamic CSS Classes

A structural challenge that compounds all of the above is TripAdvisor's aggressive use of **dynamically generated CSS class names**. These are short, apparently random alphanumeric strings (e.g., `biGQs`, `_P`, `ezezH`, `BMQDV`) generated at build time and rotated with every front-end deployment. Their sole purpose from a scraping-defense perspective is to invalidate any CSS-class-based selector strategy.

A scraper that targets a class such as `.restaurant-title` would survive indefinitely on a stable site. On TripAdvisor, the equivalent class string may look like `biGQs _P pZUbB` today and `xQTnl _R kPTgm` after the next production deploy — a time horizon that could be as short as hours.

**The solution implemented in `services/tripadvisor_scraper_extract/scraper.py`** systematically avoids this fragility by anchoring all selectors exclusively to structural attributes that encode semantic meaning and are therefore stable across deployments:

- **`data-automation`** attributes (e.g., `data-automation="restaurantCard"`, `data-automation="reviewCard"`) are injected by TripAdvisor's engineering team as internal testing and QA hooks. They are semantically coupled to the element's function, not its styling, and therefore survive CSS refactors entirely.
- **`data-test-target`** attributes (e.g., `data-test-target="reviews-tab"`, `data-test-target="review-body"`) serve the same purpose at the test automation level.
- **`data-smoke-attr`** attributes (e.g., `data-smoke-attr="pagination-next-arrow"`) are used for smoke testing critical user flows and are among the most stable identifiers in the DOM.
- **Partial `href` attribute filters** (e.g., `href^="/Restaurant_Review-"`, `href^="/Profile/"`) rely on URL path conventions that are part of TripAdvisor's canonical URL schema — stable by the nature of SEO and permalink integrity requirements.

---

## 2. Tech Stack: Playwright Asyncio

### 2.1 Why Playwright Over Alternative Libraries

The choice of **Microsoft Playwright** as the automation engine over alternatives such as BeautifulSoup, Scrapy, or Selenium is neither arbitrary nor merely conventional. It is a direct engineering response to TripAdvisor's defense model.

| Library | Protocol | JavaScript Execution | Browser Fingerprint | Anti-Bot Evasion |
|---|---|---|---|---|
| `requests` / `httpx` | HTTP only | None | Python HTTP client | Trivially detected |
| **BeautifulSoup** | HTTP + `requests` | None | Python HTTP client | Trivially detected |
| **Scrapy** | HTTP/HTTPS | None | Python HTTP client | Trivially detected |
| **Selenium (WebDriver)** | WebDriver Protocol | Full browser | Exposes `navigator.webdriver = true` | Detected by standard checks |
| **Playwright (CDP)** | Chrome DevTools Protocol (CDP) | Full browser | Controllable; patches available | Resistant with configuration |

The critical differentiator is that Playwright communicates with the browser over the **Chrome DevTools Protocol (CDP)** rather than the legacy WebDriver protocol. This architectural choice has two key consequences:

1. **`navigator.webdriver` suppression:** The `--disable-blink-features=AutomationControlled` flag passed in the `args` array of the `launch_persistent_context` call prevents Chromium from setting the `navigator.webdriver = true` JavaScript property, which is a standard first-pass check in virtually all anti-bot JavaScript payloads.

2. **Native event simulation:** Playwright's click, scroll, and navigation events are synthesised at the CDP level, producing browser-native DOM events indistinguishable from user-generated ones — unlike Selenium's JavaScript `element.click()` injection, which leaves a detectable execution trace.

### 2.2 The Asyncio Concurrency Model

The script's runtime is built on Python's native `asyncio` framework, with Playwright's async API (`async_playwright`, `async with`, `await`). This design has significant architectural implications beyond mere syntactic convention.

**The Core Concept:** `asyncio` implements a *cooperative multitasking* model on a single OS thread. Tasks voluntarily yield control to the event loop at `await` points, allowing other coroutines to execute during I/O waits. This stands in contrast to multi-threading (preemptive context switching) or synchronous code (sequential blocking).

In the context of web scraping, the practical benefit is:

```python
# WITHOUT asyncio (synchronous, blocking):
# Thread blocks for the entire 5-10 second delay.
# CPU is idle. No other work possible.
time.sleep(7.3)

# WITH asyncio (non-blocking):
# Event loop suspends this coroutine, remaining free to process
# internal Playwright I/O events (e.g., network responses,
# DOM mutations, cookie updates) during the wait.
await page.wait_for_timeout(7300)
```

During the `await page.wait_for_timeout()` calls, Playwright's internal C++ networking layer continues to process HTTP responses, execute page JavaScript, and handle browser-internal events — all without blocking the Python thread. The result is a scraper that is both resource-efficient and behaviourally more natural, since the browser's background activity during idle periods closely mirrors a real user's session.

The `async_input()` utility function, which wraps the blocking `input()` call in `loop.run_in_executor(None, input, prompt_text)`, is a textbook pattern for bridging synchronous I/O operations (terminal input) with an async event loop without deadlocking it.

---

## 3. Evasion Strategies and Anti-Detection (Human Behaviour Simulation)

### 3.1 Brave Automation Profile: Persistent Context and the Fingerprint Advantage

The single most impactful anti-detection measure in the entire system is not a timing delay or a selector strategy — it is the use of a **Brave Browser persistent profile** via `launch_persistent_context()`.

```python
context = await p.chromium.launch_persistent_context(
    user_data_dir=USER_DATA_DIR,   # Path: data/raw/tripadvisor/brave_automation_profile
    executable_path=BRAVE_PATH,    # Path to Brave's binary
    headless=False,
    args=[
        '--disable-blink-features=AutomationControlled',
        '--disable-infobars'
    ]
)
```

**What makes this architecturally superior to a standard browser launch:**

A standard `await playwright.chromium.launch()` creates a **sterile, ephemeral browser context** — a clean-room Chromium instance with no history, no cookies, no installed fonts beyond defaults, a generic screen resolution, and a hardware fingerprint that matches millions of other headless Chromium instances. Anti-bot systems maintain databases of these fingerprints and flag them on sight.

A `launch_persistent_context()` pointing to a real Brave profile directory carries with it:

| Fingerprint Component | Standard Launch | Brave Persistent Profile |
|---|---|---|
| Cookie store | Empty | Real TripAdvisor session cookies |
| Browser history | None | Populated (raises trust score) |
| localStorage / IndexedDB | Empty | Populated with prior TripAdvisor state |
| Installed fonts | OS defaults only | Full user font stack |
| Canvas fingerprint | Chromium generic | Brave's randomized anti-fingerprinting output |
| WebGL renderer | Generic string | Real GPU string from the operator's machine |
| Accepted-Language header | Default | Operator's real locale preference |

Brave's built-in **fingerprint randomization** (Brave Shields) is particularly valuable: it randomizes canvas and WebGL readouts on a per-session basis, meaning the scraper presents a different fingerprint on each run — precisely the variance pattern that anti-bot systems use to distinguish real humans from reproducible bots.

### 3.2 Randomised Delay Policy: Destroying Statistical Patterns

The requirement to never use `time.sleep()` and exclusively use `await page.wait_for_timeout()` combined with `random.uniform()` is enforced throughout the codebase at three distinct temporal scales:

```
┌─────────────────────────────────────────────────────────┐
│  TEMPORAL SCALE 1: Between Pages (5,000–10,000ms)       │
│  pause_between_pages() — Loop 1                         │
├─────────────────────────────────────────────────────────┤
│  TEMPORAL SCALE 2: Between Restaurants (5,000–10,000ms) │
│  pause_between_pages() — Loop 2                         │
├─────────────────────────────────────────────────────────┤
│  TEMPORAL SCALE 3: Between Features (400–1,200ms)       │
│  micro_reading_pause() — Feature extraction             │
└─────────────────────────────────────────────────────────┘
```

The engineering rationale is rooted in statistical signal processing. Anti-bot systems model user behaviour as a stochastic process and flag sessions whose inter-event timing is insufficiently random — specifically, sessions whose timing coefficient of variation (CV = σ/μ) is too low, indicating mechanical regularity.

`random.uniform(a, b)` generates values from a **continuous uniform distribution** over `[a, b]`. This produces the following beneficial properties:

- **No fixed cadence:** There is no repeating period or fundamental frequency in the timing signal that a frequency-domain analysis could detect.
- **Asymmetric bounds:** The 5,000–10,000ms inter-page range is deliberately non-symmetric around any human-expected mean, preventing the system from being identified by its average latency alone.
- **Multi-scale jitter:** By applying randomisation at three different temporal granularities simultaneously, the aggregate timing signal has a complex, multi-fractal character that closely resembles genuine human browsing sessions.

### 3.3 Progressive Stepped Scrolling: Simulating Ocular Reading

The `human_scroll_slow()` function implements a scroll behaviour specifically designed to defeat both **lazy-loading triggers** (content that only loads when scrolled into the viewport) and **scroll velocity analysis** (anti-bot heuristics that flag instant full-page scrolls):

```python
async def human_scroll_slow(page):
    steps = random.randint(3, 5)          # Variable number of scroll steps
    for step in range(steps):
        await page.evaluate("window.scrollBy(0, 300)")   # 300px per step
        pause_ms = random.uniform(1000, 2000)
        await page.wait_for_timeout(pause_ms)
    
    if random.random() > 0.5:            # 50% chance of a human "re-read" micro-scroll
        await page.evaluate("window.scrollBy(0, -150)")
        await page.wait_for_timeout(random.uniform(800, 1200))
```

**The 300px scroll increment** is not arbitrary. Human reading on a standard monitor processes approximately 2–4 lines of content at a time before the eyes trigger a saccadic scroll movement. At typical web font sizes (16–18px) and line heights (1.5), 300 pixels corresponds to 10–12 lines — a natural reading chunk.

**The probabilistic backward scroll** (`if random.random() > 0.5`) introduces the single most distinctively human behavioural signal: re-reading. Automated agents never scroll backward; humans frequently do. This stochastic reversal is computationally cheap but analytically potent.

**The lazy-loading consequence** is equally important: TripAdvisor's review section (`div[data-test-target="reviews-tab"]`) and photo count button are not rendered in the initial DOM payload. They are injected by Intersection Observer callbacks once the relevant viewport regions are scrolled into view. Without the progressive scroll, `await review_cards.count()` would return 0 for every restaurant regardless of actual review presence.

---

## 4. Data Flow Architecture (The Two Loops)

The script implements a clean **two-phase sequential pipeline** that separates URL discovery from structured data extraction. This separation of concerns is a fundamental pattern in resilient, large-scale scraping systems.

```
┌──────────────────────────────────────────────────────────────────┐
│                         PHASE 1: URL DISCOVERY                   │
│                    extract_restaurant_urls(page)                 │
│                                                                  │
│  TripAdvisor Listing Page (Milan) ──► Restaurant Cards ──► URLs  │
│       (Paginated, N pages)              (href filter)            │
│                          │                                       │
│                          ▼                                       │
│              data/raw/tripadvisor/tripadvisor_list_restaurant.txt                     │
│                    (append mode)                                 │
└──────────────────────────────────────┬───────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                      PHASE 2: FEATURE EXTRACTION                 │
│               extract_restaurant_features(page, url)             │
│                                                                  │
│   URL List ──► Navigate ──► Extract 12 Features ──► JSON Object  │
│   (filtered by checkpoint)     (with fallbacks)                  │
│                          │                                       │
│                          ▼                                       │
│              data/raw/tripadvisor/tripadvisor_scraper_results.json                    │
│            + data/raw/tripadvisor/tripadvisor_checkpoint.json                         │
└──────────────────────────────────────────────────────────────────┘
```

### 4.1 Phase 1: The First Loop — URL Extraction and Pagination

The first loop executes within `extract_restaurant_urls(page)` and operates on TripAdvisor's Milan restaurant listing page (`BASE_URL`). Its primary design challenge is **reliable pagination** — a feature that failed in earlier versions of the script.

**URL extraction logic:**

The script locates restaurant cards using the stable `data-automation="restaurantCard"` attribute, then extracts the canonical restaurant URL from child `<a>` tags whose `href` begins with `/Restaurant_Review-`:

```python
cards = page.locator('div[data-automation="restaurantCard"]')
link_locator = card.locator('a[href^="/Restaurant_Review-"]')
href = await link_locator.first.get_attribute('href')
```

The `#REVIEWS` exclusion filter (`if href and "#REVIEWS" not in href`) prevents collecting anchor-fragment links that point to the review section of a restaurant page rather than the page root — a critical deduplication step.

**Pagination mechanism (v11 correction):**

The core bug in earlier versions was selector fragility on the "Next Page" button. The v11 fix pins the selector to two co-present stable attributes:

```python
next_button = page.locator(
    'a[data-smoke-attr="pagination-next-arrow"]'
    '[aria-label="Pagina successiva"]'
)
```

Rather than clicking this button (which risks triggering navigation events before Playwright is ready), the script extracts the button's `href` attribute and performs a direct `page.goto()` to the reconstructed absolute URL. This is architecturally safer because it decouples the "find next page" step from the "navigate" step, allowing explicit timeout control over each.

URLs are written to `data/raw/tripadvisor/tripadvisor_list_restaurant.txt` in **write mode after each page** (rebuilding from the in-memory list), with deduplication enforced by the `if full_url not in extracted_urls` guard. The file therefore converges to a clean, unique set of restaurant URLs.

### 4.2 Phase 2: The Second Loop — Structured Feature Extraction

The second loop iterates over the URL file and extracts 12 structured data fields per restaurant, building toward the final JSON dataset.

**The 12 extracted features and their selectors:**

| # | Feature Key | Selector Strategy | Notes |
|---|---|---|---|
| 1 | `restaurant_name` | `div[data-test-target="restaurant-detail-info"] h1` | Semantic target attribute |
| 2 | `rating` | `div[data-automation="bubbleRatingValue"] span` | Automation hook |
| 3 | `total_review` | `div[data-automation="bubbleReviewCount"] span` | Automation hook |
| 4 | `cuisine_type` | `a[href*="/Restaurants-g187849-c"]` | URL pattern filter |
| 5 | `price_range` | `a[href*="-zfp"] span` | URL pattern filter |
| 6 | `number_photo_uploaded` | `button[data-automation="seeAllPhotosCountButton"] span` | Automation hook; digit-extracted |
| 7 | `address` | `span[data-automation="restaurantsMapLinkOnName"]` | Automation hook |
| 8 | `website` | `a[data-automation="restaurantsWebsiteButton"]` | Automation hook; href extracted |
| 9 | `phone_number` | `a[href^="tel:"]` | Protocol prefix filter |
| 10 | `email` | `a[href^="mailto:"]` | Protocol prefix filter |
| 11 | `working_days_hours` | `div[data-automation="hours-section"] > div.f` | Automation hook + structural child |
| 12 | `review` | `div[data-test-target="reviews-tab"] div[data-automation="reviewCard"]` | Deep nested extraction |

**Global fallback resilience:**

Every feature extraction is wrapped in a `try/except` block, and two helper functions — `safe_text(locator)` and `safe_attr(locator, attr_name)` — encapsulate the standard pattern:

```python
async def safe_text(locator, default="NaN"):
    try:
        if await locator.count() > 0:
            text = await locator.first.text_content(timeout=2500)
            return text.strip() if text else default
    except Exception:
        pass
    return default
```

The `timeout=2500` parameter in `text_content()` prevents the script from hanging indefinitely on elements that exist in the DOM but whose content is still being loaded. The return value of `"NaN"` (a string, not the IEEE 754 float `NaN`) provides a consistent null-sentinel value compatible with downstream pandas or JSON processing pipelines.

---

## 5. Advanced Debug Focus: Reviews and Author Extraction

The `review` array represents the most structurally complex extraction task in the entire script. TripAdvisor's review cards are deeply nested, semantically opaque HTML structures where the relevant data is embedded in sibling and cousin nodes relative to the data's logical container.

### 5.1 Nickname Extraction via Href Attribute Manipulation

A fundamental decision in the v11 revision was to extract the reviewer's nickname **not from visible text** but **from the `href` attribute of the profile link**. This is a more robust strategy for two reasons:

1. **Text rendering instability:** The displayed nickname text inside the `<a>` tag can be truncated, ellipsized, or modified by JavaScript at render time. The `href` attribute, being a server-rendered URL, is never modified by client-side display logic.
2. **Encoding consistency:** The href encodes the canonical username as used in TripAdvisor's internal systems (e.g., `ermanna46`), which is guaranteed unique and machine-readable.

```python
profile_link = review_card.locator('a[target="_self"][href^="/Profile/"]')
if await profile_link.count() > 0:
    href = await profile_link.first.get_attribute('href')
    if href and "/Profile/" in href:
        author_dict["nickname"] = href.split("/Profile/")[-1].strip()
```

The `href.split("/Profile/")[-1]` call is a clean, robust string manipulation: it splits on the literal prefix `/Profile/` and takes the last segment, which is the raw username. This is equivalent to a right-anchored substring extraction starting after the last slash, and it handles edge cases (query parameters, anchor fragments) gracefully because `[-1]` always returns the rightmost segment.

### 5.2 Contribution Count: Structural Proximity Search

The `number_of_contribution` field cannot be extracted by a direct unique selector because the wrapping element uses dynamic class names. The solution is a **structural search heuristic**:

```python
bold_spans = review_card.locator('span.b')
for i in range(await bold_spans.count()):
    bold_text = await bold_spans.nth(i).text_content()
    if bold_text and bold_text.strip().isdigit():
        parent_text = await review_card.text_content()
        if "contributi" in parent_text.lower():
            author_dict["number_of_contribution"] = bold_text.strip()
            break
```

The logic is: "Find any `<span>` with class `b` (bold formatting) whose content is purely numeric, and confirm it is contextually adjacent to the word 'contributi'." The `isdigit()` guard eliminates false positives from other bold numeric elements (star ratings, photo counts), while the `"contributi" in parent_text` check validates the semantic context without requiring a fixed DOM path.

### 5.3 Publication Date: The Preceding-Node Algorithm

The date extraction is the most elegant piece of algorithmic DOM navigation in the script. The challenge: TripAdvisor renders review dates in a `<div>` that has no unique ID, `data-*` attribute, or stable class name. The only reliable anchor point is a **fixed disclaimer text** that always appears immediately after the date.

```
DOM Structure:
<div>
    <div class="...">Scritta in data 27 maggio 2026</div>     ← TARGET
    <div class="...">Questa recensione rappresenta l'opinione...</div> ← ANCHOR
</div>
```

The implemented strategy uses a **text-content search** rather than a structural traversal, exploiting the fact that the phrase `"Scritta in data"` is a stable Italian UI string:

```python
# Primary strategy: direct text locator
date_elements = review_card.locator('text=/Scritta in data/')
if await date_elements.count() > 0:
    raw_date = await date_elements.first.text_content()
    return raw_date.replace("Scritta in data", "").strip()

# Fallback: full-DOM text scan within the card
all_divs = review_card.locator('div')
for i in range(div_count):
    div_text = await all_divs.nth(i).text_content()
    if div_text and "Scritta in data" in div_text:
        return div_text.replace("Scritta in data", "").strip()
```

The cleanup operation `raw_date.replace("Scritta in data", "").strip()` strips the Italian label prefix and surrounding whitespace, leaving only the date string (e.g., `"27 maggio 2026"`). This is a locale-safe transformation because it operates on a known-fixed prefix, not a date format pattern that could vary by locale.

---

## 6. Checkpoint System (Resume Logic)

### 6.1 Architecture and Data Model

The checkpoint system is one of the most important reliability features in any large-scale scraping project. It transforms the script from a fragile, all-or-nothing batch process into a **resumable, fault-tolerant pipeline**.

The system operates on three files:

```
data/raw/tripadvisor/tripadvisor_list_restaurant.txt      ← Source of truth for all URLs
data/raw/tripadvisor/tripadvisor_scraper_results.json     ← Accumulated structured data output
data/raw/tripadvisor/tripadvisor_checkpoint.json          ← Progress tracking state
```

The checkpoint JSON structure is:

```json
{
  "processed_urls": [
    "https://www.tripadvisor.it/Restaurant_Review-g187849-...",
    "..."
  ],
  "failed_urls": [
    "https://www.tripadvisor.it/Restaurant_Review-g187849-..."
  ],
  "last_update": "2026-05-27T14:33:22.101234"
}
```

The `failed_urls` list is a critical operational feature: it distinguishes between "this URL was processed successfully" and "this URL was attempted but failed." This allows an operator to review the failed set after a session and manually inspect, retry, or discard those specific restaurants.

### 6.2 The Resume Filtering Operation

At the start of every second-loop session, the checkpoint is loaded and the pending work set is computed by a single set-difference operation:

```python
checkpoint = load_checkpoint()
processed = checkpoint["processed_urls"]
urls_to_scrape = [url for url in all_urls if url not in processed]
```

This list comprehension filter is O(n × m) in the naive case (where n is total URLs and m is processed URLs), but given typical dataset sizes in the hundreds to low thousands, this is operationally negligible. The result is a reduced work list containing only the genuinely pending URLs.

### 6.3 Atomic Write-on-Success Pattern

The checkpoint is updated **immediately after each successful restaurant extraction**, before moving to the next URL:

```python
# Save results to JSON
with open(JSON_FILE, "w", encoding="utf-8") as jf:
    json.dump(results, jf, ensure_ascii=False, indent=2)

# Mark as processed in checkpoint
mark_url_processed(checkpoint, url)
```

This write-on-success pattern means the maximum possible data loss from any failure (crash, IP ban, power outage) is **exactly one restaurant record** — the one currently being scraped at the moment of interruption. All prior records are safely committed to disk.

The `ensure_ascii=False` parameter in `json.dump()` is essential for Italian restaurant data: it preserves UTF-8 characters (accented vowels, special characters in Italian addresses and names) rather than escaping them to `\uXXXX` sequences, which would inflate file size and reduce human readability.

### 6.4 Operational Failure Recovery Workflow

The system's recovery flow in a practical IP-ban or crash scenario is:

```
FAILURE EVENT
     │
     ▼
data/raw/tripadvisor/tripadvisor_checkpoint.json contains last known good state
     │
     ▼
Script re-launched → load_checkpoint() reads file
     │
     ▼
urls_to_scrape = [all_urls] - [processed_urls]
     │
     ▼
Script resumes from the first unprocessed URL
     │
     ▼
data/raw/tripadvisor/tripadvisor_scraper_results.json loaded with prior records
     │
     ▼
new results appended to existing dataset
```

This architecture guarantees that the final `data/raw/tripadvisor/tripadvisor_scraper_results.json` is always a complete, deduplicated, and chronologically coherent dataset regardless of how many sessions were required to produce it.

---

*End of Technical Architecture Report — `services/tripadvisor_scraper_extract/scraper.py`*
