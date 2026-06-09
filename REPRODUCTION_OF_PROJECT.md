# Reproduction Guide

From cloning the repo to a populated, cleaned MongoDB with entity-resolution candidate
pairs. Pick the section for your OS.
Run every command **from the repository root** unless told otherwise.

What you'll have at the end: MongoDB running locally on `localhost:27017` with three
raw collections (`restaurants_raw_google`, `restaurants_raw_tripadvisor`,
`restaurants_raw_thefork`) and three clean collections (`restaurants_clean_google`,
`restaurants_clean_tripadvisor`, `restaurants_clean_thefork`), plus the
`entity_resolution_candidates` collection used for downstream matching review.

**Prerequisites:** [Git](https://git-scm.com/) and
[Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

---

## Unix-like (macOS / Linux)

### 1. Clone the repo

```bash
git clone git@github.com:Laimon99/data-management-project.git
cd data-management-project
```

### 2. Install `uv` and dependencies

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

### 3. Create your `.env`

The defaults work for local dev — just copy the example:

```bash
cp .env.example .env
```

### 4. Get the raw data

1. Go to our **Google Drive**.
2. Copy the whole **`raw`** folder.
3. Put it into the repo at **`data/raw`**.

You should end up with these files:

```
data/raw/google_places/restaurants_seed.jsonl
data/raw/tripadvisor/tripadvisor_scraper_results.json
data/raw/thefork/thefork_milan_restaurants_enriched.json
```

### 5. Start MongoDB

Make sure Docker Desktop is running, then:

```bash
docker compose up -d mongo
```

Mongo is now on `localhost:27017`. Its data lives in a Docker volume and survives restarts.

### 6. Load the data into Mongo

```bash
uv run dataman-load all
```

Or one source at a time:

```bash
uv run dataman-load google
uv run dataman-load tripadvisor
uv run dataman-load thefork
```

Each run is **idempotent** (re-running never creates duplicates) and prints a JSON report
(`read`, `inserted`, `modified`, `skipped`). Add `--reset` to wipe a collection first.

### 7. Run the transforms

Each source has a dedicated transform that reads from its raw collection and writes a
cleaned, structured, and flagged version to a clean collection (Mongo → Mongo, raw is
never mutated):

```bash
uv run google-clean
uv run tripadvisor-clean
uv run thefork-clean
```

See [Transform details](#transform-details) below for what each transform does.

### 8. Generate entity-resolution candidates

Generate Google-anchored candidate pairs for entity resolution:

```bash
uv run dataman-entity-resolve --replace-destination \
  --dmin-tripadvisor 0.58 \
  --dmax-tripadvisor 0.63 \
  --dmin-thefork 0.86 \
  --dmax-thefork 0.94 \
  --dmin-chain-tripadvisor 0.49 \
  --dmax-chain-tripadvisor 0.52 \
  --dmin-chain-thefork 0.76 \
  --dmax-chain-thefork 0.79
```

See [Entity resolution candidate details](#entity-resolution-candidate-details) below
for what this writes and how to inspect/calibrate it.

### 9. Generate the quality report PDF

The profiling command regenerates `data/quality/`, `docs/data-quality-assessment.md`,
and `report/tables/`; the LaTeX commands then rebuild `report/main.pdf`.

On macOS, PDF compilation requires `pdflatex`. Install it once with:

```bash
brew install --cask mactex-no-gui
```

After installing, open a new terminal. If `pdflatex` is still not found, add:

```bash
export PATH="/Library/TeX/texbin:$PATH"
```

From the repository root, generate the full report with one command:

```bash
uv run quality-assessment && (cd report && pdflatex -interaction=nonstopmode -halt-on-error main.tex && pdflatex -interaction=nonstopmode -halt-on-error main.tex)
```

### 10. Verify

```bash
docker exec -it dataman-mongo mongosh dataman --eval "db.getCollectionNames()"
```

Expect: `restaurants_raw_google`, `restaurants_raw_tripadvisor`, `restaurants_raw_thefork`,
`restaurants_clean_google`, `restaurants_clean_tripadvisor`, `restaurants_clean_thefork`,
`entity_resolution_candidates`.

---

## Windows

Use **PowerShell**.

### 1. Clone the repo

```powershell
git clone git@github.com:Laimon99/data-management-project.git
cd data-management-project
```

### 2. Install `uv` and dependencies

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
$env:Path = "$HOME\.local\bin;$env:Path"
uv sync
```

> The `PATH` line makes `uv` available in the current PowerShell session. Restarting
> the terminal after installing `uv` has the same effect.

### 3. Create your `.env`

The defaults work for local dev — just copy the example:

```powershell
copy .env.example .env
```

### 4. Get the raw data

1. Go to our **Google Drive**.
2. Copy the whole **`raw`** folder.
3. Put it into the repo at **`data\raw`**.

You should end up with these files:

```
data\raw\google_places\restaurants_seed.jsonl
data\raw\tripadvisor\tripadvisor_scraper_results.json
data\raw\thefork\thefork_milan_restaurants_enriched.json
```

### 5. Start MongoDB

Make sure Docker Desktop is running, then:

> **Reproduction feedback (Windows):** if `docker` is not recognized even though Docker
> Desktop is installed, add Docker Desktop's CLI directory to the current PowerShell
> session and verify it before continuing:
>
> ```powershell
> Test-Path "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
> $env:Path = "C:\Program Files\Docker\Docker\resources\bin;$env:Path"
> docker --version
> docker compose version
> ```

```powershell
docker compose up -d mongo
```

> **Reproduction feedback (Windows):** if the first run fails while downloading
> `mongo:7`, for example with `failed to fetch oauth token` or `504 Gateway Timeout`,
> pull the image manually and then retry:
>
> ```powershell
> docker pull mongo:7
> docker compose up -d mongo
> ```

Mongo is now on `localhost:27017`. Its data lives in a Docker volume and survives restarts.

### 6. Load the data into Mongo

```powershell
uv run dataman-load all
```

Or one source at a time:

```powershell
uv run dataman-load google
uv run dataman-load tripadvisor
uv run dataman-load thefork
```

Each run is **idempotent** (re-running never creates duplicates) and prints a JSON report
(`read`, `inserted`, `modified`, `skipped`). Add `--reset` to wipe a collection first.

### 7. Run the transforms

```powershell
uv run google-clean
uv run tripadvisor-clean
uv run thefork-clean
```

See [Transform details](#transform-details) below for what each transform does.

### 8. Generate entity-resolution candidates

Generate Google-anchored candidate pairs for entity resolution:

```powershell
uv run dataman-entity-resolve --replace-destination `
  --dmin-tripadvisor 0.58 `
  --dmax-tripadvisor 0.63 `
  --dmin-thefork 0.86 `
  --dmax-thefork 0.94 `
  --dmin-chain-tripadvisor 0.49 `
  --dmax-chain-tripadvisor 0.52 `
  --dmin-chain-thefork 0.76 `
  --dmax-chain-thefork 0.79
```

See [Entity resolution candidate details](#entity-resolution-candidate-details) below
for what this writes and how to inspect/calibrate it.

### 9. Generate the quality report PDF

The report build script regenerates `data/quality/`, `docs/data-quality-assessment.md`,
`report/tables/`, and `report/main.pdf`:

```powershell
powershell -ExecutionPolicy Bypass -File .\report\build_report.ps1
```

This requires a LaTeX distribution with `pdflatex` available on `PATH`.

### 10. Verify

```powershell
docker exec -it dataman-mongo mongosh dataman --eval "db.getCollectionNames()"
```

Expect: `restaurants_raw_google`, `restaurants_raw_tripadvisor`, `restaurants_raw_thefork`,
`restaurants_clean_google`, `restaurants_clean_tripadvisor`, `restaurants_clean_thefork`,
`entity_resolution_candidates`.

---

## Notes

- The OS-specific differences are the `uv` installer/PATH refresh (step 2) and the
  copy command (step 3).
- If `docker compose` isn't recognized, your Docker is older — use `docker-compose` (hyphen).
- To stop Mongo: `docker compose down` (keeps data). **Never** use `down -v` unless you want
  to delete all loaded data.
- **Editable-install gotcha:** because service source paths differ from import paths, the
  project is installed as a copied snapshot in `.venv`, not a live link. After editing service
  code, run `uv sync --reinstall-package data-management-project` before verifying through an
  entrypoint. Tests are unaffected — `uv run pytest` reads source directly.

---

## Transform details

All three transforms share the same idioms: per-record quality `flags`/`has_*` booleans, a
printed `CleanReport` of before/after counts, full-run stale-delete convergence (removes
docs whose source record vanished), and a source/destination collision guard. Raw
collections are never mutated.

### `google-clean` → `restaurants_clean_google`

**Source:** `restaurants_raw_google` (10,808 raw records; 22 inert junk dropped → **10,786** written)

Google data arrives already typed, valid, and geocoded — so this transform is **projection +
normalization + relevance flagging**, not type-repair or geocoding.

What it does:

1. **Projects** ~15 lean fields out of the ~24 KB raw `details` blob (the full blob stays in
   the raw collection for the optional LLM extension).
2. **Normalizes** `name` (whitespace-collapse, ALL-CAPS → title case best-effort) and `city`
   (derived from `details.addressComponents.locality`, `Milan` → `Milano`).
3. **Lifts structured address** from `addressComponents`: `street`, `street_number`,
   `postal_code`, `locality`, `province`, `country`.
4. **Classifies dining relevance:** `category_tier` (`restaurant` / `cafe_bar_bakery` /
   `non_dining` / `unknown`); `is_dining = restaurant OR cafe_bar_bakery`.
5. **Flags** quality issues without deleting: `is_operational`, `has_rating`, `low_review`
   (< 10 reviews), `name_is_geographic`, `city_out_of_area`, `flags[]` reason list.
6. **Derives features** from `details`: `photo_count`, `price_level`, `price_range`
   (`{start, end, currency}`), `has_website`/`has_phone`, and the present-only amenity
   booleans (`dine_in`, `takeout`, `delivery`, `reservable`, `outdoor_seating`,
   `serves_beer`, `serves_wine`, `good_for_children`, `good_for_groups`, …).
7. **Slims reviews** to ≤ 5 × `{rating, text, language, publish_time, author}`.

Coordinates are copied verbatim — **never re-geocoded**.

Drop rules (configurable):

- **Junk** (on by default): records that are `name_is_geographic` **and** have no rating are
  dropped (≈22 inert placeholders). Pass `--keep-junk` to retain them.
- **Non-dining** (off by default): flagged but kept. Pass `--drop-non-dining` to exclude.

CLI options:

```bash
uv run google-clean                          # full run
uv run google-clean --limit 50               # quick slice (never sync-deletes)
uv run google-clean --reset                  # wipe destination first
uv run google-clean --drop-non-dining --low-review 20
```

Output schema key fields:

| Field | Type | Description |
|---|---|---|
| `_id` / `place_id` | str | Google Places id (natural key) |
| `name` | str | Normalized display name |
| `latitude` / `longitude` | float | Authoritative coordinates (verbatim) |
| `address` | str | Full formatted address |
| `street`, `street_number`, `postal_code`, `locality`, `province`, `country` | str | Structured address parts |
| `city` | str | Canonical city (`Milano`) |
| `rating` / `review_count` | float / int | From `details.*` (fresher), coalesced to seed |
| `category_tier` / `is_dining` | str / bool | Dining relevance classification |
| `flags` | list[str] | Quality reason list |
| `photo_count`, `price_range` | int / obj | Richness/popularity features |
| `reviews` | list[obj] | ≤ 5 slimmed reviews |
| `_transformed_at` | datetime | UTC timestamp of the transform run |

---

### `tripadvisor-clean` → `restaurants_clean_tripadvisor`

**Source:** `restaurants_raw_tripadvisor` (**7,539** raw records)

Tripadvisor data arrives as Italian display strings with no coordinates — so this transform
is **type-repair + structure + geocode + flag**.

What it does:

1. **Type-repair** Italian display strings: `"5,0"` → `5.0`, `"(1.234 recensioni)"` → `1234`,
   `"NaN"`/empty → `null` across all fields.
2. **Normalizes** `restaurant_name`, `address`, and contacts (`website`/`phone_number`/`email`
   — `"NaN"`/blank → `null`).
3. **Structures the 1NF-violation fields** (raw strings dropped from the clean document):
   - `number_photo_uploaded` → `photo_count` (int, thousands separators handled)
   - `price_range` → `price_band` (source euro symbols) + ordinal `price_tier_level` (€→1, €€-€€€→2, €€€€→4)
   - `cuisine_type` CSV → `cuisines: list[str]` (trimmed, case-insensitive de-duped)
   - `working_days_hours` flattened Italian string → `opening_hours: [{day, opens, closes}]`
     (English day names, split shifts preserved, `Chiuso` days omitted, `closes_next_day`
     for past-midnight shifts)
   - `review` → slim, capped `reviews: [{nickname, contributions, title, text, date}]`
     (`"Scopri di più"` suffix stripped, Italian dates → ISO) + `sample_size`
4. **Lifts `ta_location_id`** (the `-d<n>-` URL token) as a stable join/blocking key.
   Best-effort structured address: `street`, `postal_code`, `city`.
5. **Geocodes the cleaned address** via Nominatim/OpenStreetMap into `latitude`/`longitude`.
   Geocoding is a sub-step, not a separate stage. Resumable: records with both coordinates
   already set are skipped; partial coordinates are re-geocoded.
6. **Flags** per record: `has_rating`, `has_review_count`, `low_review`, `has_address`,
   `has_coordinates`, `has_reviews`, `has_hours`, `has_phone`, `has_website`, `has_email`,
   `flags[]` reason list.

CLI options:

```bash
uv run tripadvisor-clean                    # full run (clean + geocode)
uv run tripadvisor-clean --limit 20         # quick slice
uv run tripadvisor-clean --skip-geocode     # fast clean-only pass (preserves existing coords)
uv run tripadvisor-clean --reset            # wipe destination first
```

Geocoding is rate-limited to ≥ 1 s/request (Nominatim ToS). A full geocode pass over
7,539 records takes roughly 2.5 hours. `--skip-geocode` is the fast path when you only
need the typed/structured fields.

Output schema key fields:

| Field | Type | Description |
|---|---|---|
| `_id` / `source_url` | str | Tripadvisor review URL (natural key) |
| `ta_location_id` | str | Stable venue id (join/blocking key) |
| `restaurant_name` | str | Normalized display name |
| `latitude` / `longitude` | float | WGS-84 from Nominatim on cleaned address |
| `has_coordinates` | bool | Both coordinates present |
| `address`, `street`, `postal_code`, `city` | str | Structured address |
| `rating` | float | 1.0–5.0, Italian display string repaired |
| `total_review` | int | Review count, Italian display string repaired |
| `price_band` / `price_tier_level` | str / int | Pricing tier |
| `cuisines` | list[str] | Structured cuisine list |
| `opening_hours` | list[obj] | `{day, opens, closes}` structured hours |
| `reviews` | list[obj] | ≤ 20 slimmed reviews |
| `flags` | list[str] | Quality reason list |
| `_transformed_at` | datetime | UTC timestamp of the transform run |

---

### `thefork-clean` → `restaurants_clean_thefork`

**Source:** `restaurants_raw_thefork`

TheFork data arrives already typed, geocoded, duplicate-free, and 100% dining — so this
transform is **parse + structure + flag**, not type-repair, geocoding, dedup, or relevance
filtering.

What it does:

1. **Parses** the 1NF-violation fields:
   - `price_range "30 €"` → `avg_price_eur` (int)
   - `discount` free-text → `discount_pct` (int, review-bleed strings nulled) + `has_discount`
   - `cuisine_type` → `cuisines[]` + `dietary_options[]` (an address accidentally stored in
     `cuisine_type` is rejected and flagged `invalid_cuisine_type`)
   - Opening hours → tidy `opening_hours[]` of `{day, opens, closes}` (prefers the
     pre-parsed `working_hours_structured`, falls back to raw JSON string; past-midnight
     `"24:00"`–`"29:00"` folded to valid `HH:MM` + `closes_next_day`)
2. **Normalizes** `restaurant_name` (whitespace + ALL-CAPS recase), `address` (strip the
   `I-` CAP prefix, fold EN `Milan`/`Italy`), `city` (`Milan` → `Milano`); lifts
   `street` / `house_number` / `postal_code`; lifts `tf_id` (the `-r<n>` venue id) as a
   join/blocking key.
3. **Drops** dead fields (`phone_number`, `email`, `website`, `social_links` — all empty in
   the dataset) and the always-null nested review `title`; slims `reviews` to
   `{author_name, rating, text, date}` (≤ 15).
4. **Flags** per record: `has_rating`, `has_review_count`, `low_review`, `has_discount`,
   `has_hours`, `has_reviews`, `rating_sample_divergent`, `flags[]` reason list.
5. **Honest sample features**: `sample_size`, `sample_avg_rating` — clearly sample-based,
   never used to backfill a missing platform `rating`.

`rating` stays on TheFork's native **0–10 scale** (scale harmonisation is an integration
concern handled at the unified-dataset stage). Coordinates are copied verbatim — never
recomputed.

CLI options:

```bash
uv run thefork-clean                    # full run
uv run thefork-clean --limit 50         # quick slice
uv run thefork-clean --reset            # wipe destination first
uv run thefork-clean --low-review 20    # change the low-review flag threshold
```

Output schema key fields:

| Field | Type | Description |
|---|---|---|
| `_id` / `source_id` | str | TheFork venue id (natural key) |
| `tf_id` | str | Stable `-r<n>` venue id (join/blocking key) |
| `restaurant_name` | str | Normalized display name |
| `latitude` / `longitude` | float | Verbatim from source (already geocoded) |
| `address`, `street`, `house_number`, `postal_code`, `city` | str | Structured address |
| `rating` | float | TheFork native 0–10 scale |
| `review_count` | int | Platform review count |
| `avg_price_eur` | int | Parsed from `price_range` string |
| `discount_pct` / `has_discount` | int / bool | Parsed discount |
| `cuisines` / `dietary_options` | list[str] | Structured cuisine/diet tags |
| `opening_hours` | list[obj] | `{day, opens, closes}` structured hours |
| `reviews` | list[obj] | ≤ 15 slimmed reviews |
| `sample_size` / `sample_avg_rating` | int / float | Sample-based features |
| `flags` | list[str] | Quality reason list |
| `_transformed_at` | datetime | UTC timestamp of the transform run |

---

## CleanReport output

Each transform prints a JSON `CleanReport` when it finishes, feeding the stage-5 quality
assessment. Key counters across all three:

- **Volume/convergence:** `read`, `written`, `stale_deleted`, `duplicates_collapsed`, `missing_key`
- **Quality flags raised:** `with_rating`/`without_rating`, `low_review`, `missing_review_count`
- **Rich-field coverage:** `cuisines_present`, `opening_hours_parsed`, `with_reviews`, `photo_count_parsed`, `price_parsed`

Tripadvisor additionally reports geocoding counters:
`geocode_found`, `geocode_not_found`, `geocode_skipped_done`, `geocode_skipped_null_addr`.

Google additionally reports relevance counters:
`tier_restaurant`, `tier_cafe_bar_bakery`, `tier_non_dining`, `is_dining`, `dropped_junk`, `dropped_non_dining`.

---

## Entity resolution candidate details

Candidate-pair generation starts after all three clean collections exist. Google is the
anchor source: the service creates Google × Tripadvisor and Google × TheFork candidates,
but it does not directly match Tripadvisor × TheFork.

The reproducible command above writes to `dataman.entity_resolution_candidates`. Each
candidate document stores the Google id, source id, blocking strategy, score, score
components, effective thresholds, provisional `label`, chain flags, and `llm_label=null`
for later manual/LLM adjudication.

The current calibrated run produces **137,880** candidate pair documents:

| Label | Count |
|---|---:|
| `MATCH` | 5,218 |
| `NON_MATCH` | 131,655 |
| `UNCERTAIN` | 906 |
| `UNBLOCKABLE` | 101 |

By source, this contains **4,303** Tripadvisor matches and **915** TheFork matches against
the Google anchor pool. The remaining `UNCERTAIN` rows are the review queue for the
future adjudication step; this collection is candidate/evidence data, not the final
integrated restaurant table.

Preview candidate volume without writing:

```bash
uv run dataman-entity-resolve --dry-run
```

Inspect the generated collection:

```bash
uv run python scripts/inspect_er_candidates.py
```

Threshold calibration is documented in
[`services/transform/entity_resolution/README.md`](services/transform/entity_resolution/README.md).
The root [`README.md`](README.md) records the current calibrated threshold values used in
this guide.
