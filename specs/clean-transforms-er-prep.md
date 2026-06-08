# Spec for clean-transforms-er-prep
branch: feature/clean-transforms-er-prep

## Summary

Update the three clean transforms (`google_clean`, `tripadvisor_clean`, `thefork_clean`)
to produce consistent, ER-ready fields before entity resolution runs:

1. **Address decomposition**: all three collections must have `street` (route name only)
   and `house_number` (civic number) as separate fields with the same names.
2. **Normalized canonical contact fields**: Google and Tripadvisor clean collections must
   expose normalized `phone` and `website` fields with the same names, so the ER service
   can compare directly without in-memory preprocessing. Original source contact strings
   remain available in the raw collections.

Currently the three collections are inconsistent:

| Collection | Street field | Civic number field | Phone field | Normalized phone? |
|---|---|---|---|---|
| `restaurants_clean_google` | `street` ✓ | `street_number` ✗ (wrong name) | `phone` (E.164 with spaces) | no |
| `restaurants_clean_tripadvisor` | `street` embeds civic number ✗ | — (missing) | `phone_number` (varies) | no |
| `restaurants_clean_thefork` | `street` ✓ | `house_number` ✓ | n/a (0% coverage) | n/a |

Target contact shape:

| Collection | Clean phone field | Clean website field | Notes |
|---|---|---|---|
| `restaurants_clean_google` | `phone` | `website` | Same field names as today, but values are normalized in place. |
| `restaurants_clean_tripadvisor` | `phone` | `website` | `phone_number` is replaced by canonical `phone`; values are normalized. |
| `restaurants_clean_thefork` | n/a | n/a | No clean contact fields because current scrape coverage is 0%. |

TheFork already uses the target shape for address fields; it requires no changes.

**Documentation that must be updated alongside the code** (see Acceptance Criteria):
- `services/transform/google_clean/clean-dataset-schema.md`
- `services/transform/tripadvisor_clean/clean-dataset-schema.md`
- `docs/schema-matching.md` — §3 table (`house_number` row, `street` row)
- `docs/schema-correspondences.md` — any reference to `street_number`

No `specs/entity-resolution.md` file exists in this checkout; ER-preprocessing assumptions
must be reflected in the existing schema matching/correspondence docs instead.

---

## Functional Requirements

### 1. `tripadvisor_clean` — fix `street`, add `house_number`

**Current behaviour**: `street` is parsed from the full `address` line by taking
everything before the postal code. This includes the civic number and sometimes a
venue-description suffix. Examples from live data:

```
address : "Via Carlo Pascal 6, 20133 Milano Italia"
street  : "Via Carlo Pascal 6"                     ← should be "Via Carlo Pascal"
                                                    ← house_number "6" is missing
```
```
address : "Via Pastrengo 16 Il bistrot del Teatro Verdi, 20159 Milano Italia"
street  : "Via Pastrengo 16 Il bistrot del Teatro Verdi"  ← should be "Via Pastrengo"
                                                           ← house_number "16"
```

**Required change**: after parsing the address prefix, split further:

- `street`: take tokens up to (but not including) the first token that is a standalone
  integer or starts with a digit. Strip trailing whitespace and commas.
- `house_number`: the first digit-starting token immediately following the street route.
  Null when no such token exists (e.g., named piazzas without a number).
- Any tokens after `house_number` (venue descriptions, zone labels) are discarded from
  both fields; they remain implicitly preserved in `address`.

Coverage expectation from current data: `street` already has 99.1% non-null coverage;
the split should preserve that. `house_number` will be lower (not all addresses carry a
civic number) — document the actual coverage after the run.

### 2. `tripadvisor_clean` — normalize contacts into canonical `phone` and `website`

- `phone`: normalize raw `phone_number` to compact E.164 and store it as canonical
  `phone` in the clean collection.
  Rules: strip spaces, dashes, dots, parentheses; if the result starts with `0` (Italian
  landline) or `3` (Italian mobile) prepend `+39`; if it already starts with `+` leave
  the country code unchanged. Null input → null output.
- `website`: normalize raw `website` by stripping scheme (`http://`/`https://`),
  stripping leading `www.`, stripping trailing `/`. Null or blank input → null output.
- `phone_number` disappears from `restaurants_clean_tripadvisor`; the original value
  remains available in `restaurants_raw_tripadvisor`.

### 3. `google_clean` — rename `street_number` → `house_number`

`street_number` is a breaking rename to `house_number` for consistency with TheFork and
the target integrated schema. The old field name disappears from `restaurants_clean_google`.

Coverage is unchanged: `house_number` will have the same 92.4% non-null coverage that
`street_number` had.

### 4. `google_clean` — normalize `phone` and `website` in place

Same normalization rules as §2:

- `phone`: Google's phone is already mostly E.164 format but contains spaces
  (e.g., `+39 02 645 6224`). Normalize to `+39026456224`.
- `website`: strip scheme, `www.`, trailing slash from `website`.

The field names stay `phone` and `website`; only the clean values change.

### 5. `thefork_clean` — no changes required

`street` and `house_number` already match the target shape. Phone and website are absent
(0% coverage in the scrape) and have no fields to normalize.

### Re-run requirement

After code changes, all three transforms must be re-run to refresh the clean collections:

```bash
uv run google-clean
uv run tripadvisor-clean
uv run thefork-clean
```

Use `uv sync --reinstall-package data-management-project` before running (editable-install
gotcha documented in CLAUDE.md).

---

## Possible Edge Cases

- **TA addresses with no civic number**: piazzas, named squares, hotel-style addresses
  (`"Piazza del Duomo, 20121 Milano Italia"`). `street` = `"Piazza del Duomo"`,
  `house_number` = null. Do not force a number where there is none.
- **TA addresses with letter-suffixed numbers**: Italian civic numbers can be `12/A`,
  `4bis`, `3r`. The split must treat these as valid `house_number` values, not strip them.
- **TA addresses with multiple digit tokens**: `"Via XX Settembre 8"` — `XX` is a Roman
  numeral in the street name, `8` is the civic number. The split rule (first digit-*starting*
  token) correctly picks `8`, not `XX`.
- **Google `phone` with national format**: some Google records have a national-format
  phone without `+39` (e.g., `02 1234567`). The normalization rule (prepend `+39` if
  starts with `0`) handles this; verify it does not double-prepend on records already in
  E.164.
- **Downstream breakage from `street_number` rename and TA `phone_number` rename**: any
  code or query that reads `street_number` from `restaurants_clean_google` or
  `phone_number` from `restaurants_clean_tripadvisor` will break silently. Schema matching
  docs and any analytics queries must be updated at the same time as the transform.

---

## Acceptance Criteria

- [ ] `restaurants_clean_tripadvisor` has a `house_number` field; `street` no longer
  contains civic numbers or venue-description suffixes in any document.
- [ ] `restaurants_clean_google` has `house_number`; `street_number` field no longer
  exists in any document.
- [ ] `restaurants_clean_google.phone` and `.website` contain normalized values; no
  `phone_normalized` or `website_normalized` sidecar fields are added.
- [ ] `restaurants_clean_tripadvisor.phone` and `.website` contain normalized values;
  `phone_number` no longer exists in any clean document.
- [ ] `restaurants_clean_thefork.house_number` and `.street` are unchanged.
- [ ] `phone` for `+39 02 645 6224` → `+39026456224`; for `02 1234567` →
  `+39021234567`; for `null` → `null`.
- [ ] `website` for `https://www.example.it/` → `example.it`; for `null` → `null`.
- [ ] TA `street` for `"Via Pastrengo 16 Il bistrot del Teatro Verdi"` → `"Via Pastrengo"`,
  `house_number` → `"16"`.
- [ ] TA `house_number` is null for an address with no civic number token.
- [ ] The following documentation files are updated to reflect the new field names and
  normalized contact semantics:
  - `services/transform/google_clean/clean-dataset-schema.md` (`street_number` → `house_number`; `phone` / `website` documented as normalized)
  - `services/transform/tripadvisor_clean/clean-dataset-schema.md` (updated `street` description; new `house_number`; `phone_number` → canonical `phone`; `phone` / `website` documented as normalized)
  - `docs/schema-matching.md` §3 — `house_number` row updated to show all three sources now consistent; `street` row updated for TA
  - `docs/schema-matching.md` §6 — contacts updated to show Google/Tripadvisor use the same canonical normalized `phone` / `website` fields
  - `docs/schema-correspondences.md` — `street_number` references replaced with `house_number`; `phone_number` references replaced with `phone`

---

## Resolved Decisions

- Normalized contacts replace the old clean contact representation and use canonical
  names: `phone` and `website`.
- Raw collections remain the audit source for original source-specific contact strings.
- `thefork_clean` should be re-run for collection consistency even though its schema is
  unchanged.
- If a live MongoDB index exists on `street_number`, drop it and recreate the relevant
  index on `house_number`.

---

## Out of Scope

- Geocoding the remaining 15.9% of TA records without coordinates.
- Phone/website normalization for TheFork (no data to normalize).
- Cuisine vocabulary normalization.
- Entity resolution itself.

---

## Feature Testing Guidelines

Create `tests/transform/test_er_prep.py`. Cover without going heavy:

- **TA street split**: route + house_number correctly extracted for: standard address
  (`Via Carlo Pascal 6`), address with suffix (`Via Pastrengo 16 Il bistrot del Teatro Verdi`),
  address with no civic number (`Piazza del Duomo`), letter-suffix number (`Via Roma 12/A`),
  Roman numeral in name (`Via XX Settembre 8`).
- **Phone normalization**: E.164 with spaces → compact; national format with `0` prefix →
  `+39` prepended; already-`+39` format → not double-prepended; null → null. Assert the
  normalized value is stored in clean field `phone`.
- **Website normalization**: `https://www.example.it/` → `example.it`; `http://example.it`
  → `example.it`; no scheme → unchanged; null → null. Assert the normalized value is
  stored in clean field `website`.
- **Google `house_number`**: same value as old `street_number`; old field absent from
  output document.
- **Tripadvisor canonical contacts**: raw `phone_number` becomes clean `phone`;
  `phone_number` is absent from the output document.
- **Re-run idempotency**: running the transform twice produces the same clean document.
