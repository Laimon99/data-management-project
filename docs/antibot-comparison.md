# TheFork vs. Tripadvisor scraper: anti-bot comparison

This note explains **why we kept Simone's Chromium-based approach for TheFork**
as-is, and what the Tripadvisor scraper's real-browser + persistent-profile
design buys over it. It frames the difference as an **escalation ladder** so we
can climb it deliberately only if a full TheFork *detail* dataset turns out to
need it.

## The 403 reality on TheFork

The blocking is **phase-specific**:

- **Listing phase is fine.** Listing pages load and parse reliably, so the
  listing-level data (name, address, rating, review count, cuisine, price,
  discount, snippets) always survives even when detail enrichment is blocked.
- **Only the detail phase 403s.** Per-restaurant detail pages are where
  TheFork pushes back.

Simone's scraper already handles this gracefully:

- **Per-page soft-fail** — a detail page returning HTTP ≥ 400 (or timing out)
  is logged, marked `detail_scraped = False`, and skipped rather than aborting
  the run (`detail_scraper.py`, `enrich_record`).
- **Channel fallback** — `_candidate_channels()` tries
  `("chrome", "msedge", None)` in order, i.e. installed Chrome, then Edge, then
  bundled Chromium (`scraper.py:26`, `scraper.py:118`).
- **Light anti-detection** — every launch passes
  `--disable-blink-features=AutomationControlled` and builds an it-IT /
  Europe/Rome context with a realistic desktop user agent
  (`scraper.py:139` listing launch, `scraper.py:522` detail-batch launch,
  `DEFAULT_USER_AGENT` at `scraper.py:27`).
- **Exponential cooldown + resume** — `--auto-detail-until-complete` keeps
  retrying the still-missing detail pages in batches, reopening the browser and
  backing off between batches (initial 900s → ×1.5 → cap 3600s), and resumes
  from the partial JSON so progress is never lost (`_auto_detail_until_complete`,
  config `COOLDOWN_SECONDS` / `MAX_COOLDOWN_SECONDS` / `COOLDOWN_MULTIPLIER`).

### Limitation

Cooldowns fix **rate-based** blocks, not **fingerprint-based** ones. A headless
bundled Chromium leaks automation tells regardless of how long you wait:
`navigator.webdriver === true`, a `HeadlessChrome` user-agent token, and no
browsing profile/history/cookies to establish trust. If TheFork's detail-page
gate is keying on the fingerprint rather than request rate, waiting longer will
not clear it — which is the likely reason 403s persist despite the backoff.

## The escalation ladder

| Level | Setup | When |
|-------|-------|------|
| **L0** | Headless **bundled** Chromium | Simone's zero-config default; fine for the listing phase. |
| **L1** | **Headed + real channel** (`--headed --browser-channel chrome` or `msedge`) | **The recommended testing/runtime default.** A real, headed browser binary sheds the most obvious headless fingerprint tells at near-zero cost. |
| **L2** | **Persistent real-browser profile** (Tripadvisor's design) | Documented escalation if a *complete* detail dataset is required. |
| **L3** | Residential proxies / rotating egress | Out of scope for this project. |

### What L2 (the Tripadvisor design) adds

The Tripadvisor scraper uses
`chromium.launch_persistent_context(user_data_dir=…, headless=False)`
(`services/extract/tripadvisor_scraper/scraper.py:780`) against a **persistent
on-disk profile** under `data/raw/tripadvisor/browser_automation_profile/`.
Versus L0/L1 this buys:

- **Accumulated trust** — cookies, local storage, and history persist across
  runs, so the session looks like a returning human rather than a cold,
  stateless bot on every request.
- **A real, headed window** — same headless-tell reduction as L1, but always on.
- **Manual challenge solve** — because the window is visible and the profile is
  durable, a human can clear a one-off CAPTCHA/consent wall once and the
  unblocked state carries forward into subsequent automated runs.

We deliberately did **not** port this machinery into the TheFork service now.
It is recorded here as the next rung if listing-only detail coverage proves
insufficient.

## Consistency note (verified)

There was a concern that the detail-batch browser launch might not set the same
anti-detection `args` as the listing launch. **Verified — both already set it:**
the listing launch (`scraper.py:139`) and the detail-batch launch
(`scraper.py:522`) both pass
`args=["--disable-blink-features=AutomationControlled"]`. No change needed.

## Practical recommendation

- For routine collection and CI smoke tests, run **L0** (listing data is
  reliable regardless).
- When you actually need detail-page enrichment, run **L1**:
  `uv run thefork-scraper-extract --headed --browser-channel chrome --auto-detail-until-complete`.
- Only climb to **L2** if L1 still leaves a materially incomplete detail set.
