# TheFork Milan Dataset — Change Report

**Comparison of the new scraper output vs. the previous dataset.**

- **Old dataset:** `data/raw/thefork/thefork_milan_restaurants_normalized_partial.json` (4.6 MB)
- **New dataset:** `thefork_scraper/output/` (new scraper version by teammate)
- **New scrape date:** 2026-06-06
- **Report generated:** 2026-06-07

---

## 1. TL;DR

The new run keeps the **same 1,344 restaurants and the same 25-field schema**, but:

- **Reviews ~tripled** (6,277 → 17,976) — this is the main reason the file grew from 4.6 MB to 11.1 MB.
- Added a **parsed `working_hours_structured`** field and a (currently empty) **`social_links`** field.
- **Geocoordinates are now complete** (1,344/1,344).
- ⚠️ **`website` data was lost** (25 → 0) and its intended replacement `social_links` is empty everywhere.
- ⚠️ **`discount` coverage shrank** (949 → 650).
- `phone_number` and `email` remain empty in both versions.

---

## 2. Files in the new output directory

| File | Size | What it is |
|---|---|---|
| `thefork_milan_restaurants_enriched.json` | 11.1 MB | **Primary deliverable.** Full scrape after the detail-enrichment pass (reviews, hours, photos). All 1,344 records have `detail_scraped: true`. Scraped 18:00–20:35Z. |
| `thefork_milan_restaurants_normalized_partial.json` | 11.1 MB | **Byte-for-byte identical to `enriched.json`** — a normalized copy/rename. This is the file that maps to the old dataset. |
| `thefork_milan_restaurants_enriched_mac_slots_7_13.json` | 6.0 MB | **Earlier, incomplete intermediate run** (09:47–18:23Z): only **670/1,344** records detail-scraped, ~8,792 reviews. A work-in-progress batch (Mac, page "slots 7–13"), **superseded** by `enriched.json`. Not the final dataset. |
| `thefork_milan_restaurants_normalized_partial.merge_report.json` | 1.3 KB | **Provenance/audit log.** Records that the final dataset = main run (1,342) + a targeted re-scrape of 2 previously-missing restaurants (`targeted_missing_20260606`), plus aggregate quality stats. |

> Note: `enriched.json` == `normalized_partial.json`. For analysis purposes there is effectively **one** new dataset, with `mac_slots_7_13` being a discardable intermediate and the merge report being metadata.

---

## 3. Schema changes

Record count unchanged (**1,344 → 1,344**). Two fields added; none removed.

| Field | Change | Notes |
|---|---|---|
| `working_hours_structured` | **➕ Added** (855/1,344 filled) | Parsed-object version of the raw JSON string in `working_days_hours` (schema.org `OpeningHoursSpecification`). |
| `social_links` | **➕ Added** (0/1,344 filled) | Present in schema but **empty `{}` on every record** — population step appears not to have run. |

All 23 previously-existing fields are retained.

---

## 4. Field-level coverage (non-empty values)

| Field | Old filled | New filled | Δ | Comment |
|---|---:|---:|---:|---|
| reviews | 1,280 | 1,299 | +19 | see depth change below |
| review_count | 1,304 | 1,318 | +14 | |
| review_snippets | 1,291 | 1,299 | +8 | |
| latitude | 1,341 | 1,344 | +3 | now complete |
| longitude | 1,341 | 1,344 | +3 | now complete |
| photo_count | 1,340 | 1,343 | +3 | |
| working_days_hours | 853 | 855 | +2 | |
| working_hours_structured | 0 | 855 | +855 | new field |
| cuisine_type | 1,330 | 1,323 | −7 | minor drift |
| rating | 1,300 | 1,265 | −35 | drift (see §6) |
| **discount** | **949** | **650** | **−299** | ⚠️ see §5 |
| **website** | **25** | **0** | **−25** | ⚠️ data lost |
| social_links | 0 | 0 | 0 | added but empty |
| phone_number | 0 | 0 | 0 | never populated |
| email | 0 | 0 | 0 | never populated |
| address, city, price_range, restaurant_name, restaurant_url, scraped_at, source, source_id, source_page_number, detail_scraped | 1,344 | 1,344 | 0 | full in both |

---

## 5. Key improvement: review depth

The biggest substantive change and the cause of the file-size increase.

| Metric | Old | New |
|---|---:|---:|
| Total reviews | 6,277 | **17,976** |
| Avg reviews / restaurant | 4.67 | **13.38** |
| Max reviews / restaurant | 5 | **15** |

The per-restaurant review cap was effectively raised from 5 to 15.

---

## 6. Regressions & things to check ⚠️

1. **`website` lost (25 → 0) and `social_links` empty everywhere.**
   It looks like website was intended to migrate into `social_links`, but the population step didn't run — net loss of contact data. The merge report confirms `with_website: 0` and `with_social_links: 0`.

2. **`discount` coverage dropped (949 → 650).**
   Among the 1,338 restaurants present in both versions:
   - kept same: 559
   - **lost discount: 298**
   - changed value: 87 (e.g. `"sconto -50%"`)
   - gained: 1
   - both empty: 393

   Likely partly real (time-limited promos expire between scrapes), but the magnitude is worth verifying against the scraper logic.

3. **`phone_number` and `email` still empty in both versions** — never populated by either scraper.

4. **Rating drift among shared restaurants:** 1,170 unchanged, 94 changed value, 31 lost their rating (0 gained).

---

## 7. Restaurant set changes

1,338 restaurants overlap. **6 dropped, 6 added** (likely delisted/relisted on TheFork):

**Dropped (only in old):**
- Osteria di Brera (`osteria-di-brera-r817732`)
- Blue M - Bottega Marchigiana Navigli (`blue-m-bottega-marchigiana-navigli-r843963`)
- Blue M - Bottega Marchigiana Lanzone (`blue-m-bottega-marchigiana-lanzone-r843965`)
- Experience Wine Milano (`experience-wine-milano-r860756`)
- That's Panaro Milano (`that-s-panaro-milano-r836347`)
- Soprattutto (`soprattutto-r464093`)

**Added (only in new):**
- Spuzzuliamm (`spuzzuliamm-r863570`)
- Vurria - Moscova (`vurria-moscova-r742644`)
- Ristorante Pizzeria Del Vento (`ristorante-pizzeria-del-vento-r863545`)
- Pellico 3 Milano (`pellico-3-milano-r56920`)
- Oro Pizza (`oro-pizza-r862764`)
- Ristorante Pizzeria La Carrozza (`ristorante-pizzeria-la-carrozza-r863759`)

---

## 8. Merge provenance (from `merge_report.json`)

- Final output = **1,342** records from the main enriched run + **2** records from a targeted re-scrape (`targeted_missing_20260606`) of restaurants that were missing detail data.
- Replacement reason for the 2: `candidate_has_detail`.
- Final aggregate richness score: **49.48** (up slightly from 49.43).
- Confirms: `with_website: 0`, `with_social_links: 0`, `with_phone: 0`, `with_email: 0`, `with_reviews: 1,299`, `with_working_hours_structured: 855`.

---

## 9. Recommendation

The new dataset is a clear upgrade for **review depth, structured opening hours, and complete geocoordinates**, and should replace the old one. Before treating it as final, follow up on:

- Why `social_links` is empty and whether `website` should have been migrated there (fix or restore).
- Whether the `discount` drop is genuine promo expiry or an extraction regression.
- Whether `phone`/`email` are intended to stay empty.
