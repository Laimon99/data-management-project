# Stage 1 — Seed Acquisition Method

Report-oriented notes on *what* was done in the seed-acquisition stage and *why*.
Concrete figures (venue counts, tile counts, coverage %) are intentionally left
out here — they belong in the report and are produced from the data directly.

## Goal

Build the geographic backbone of the project: a base list of Milan food venues
(name, address, coordinates, type, rating, review count) from Google Maps via
the Places API (New). These coordinates are the reference for later stages and
are not re-geocoded downstream.

## Collection strategy: tiled Nearby Search

The Places **Nearby Search** endpoint returns at most one page set per query and
is bounded by a search radius, so a single call cannot cover a whole city. We
therefore tile the target area: a grid of overlapping circular search "tiles",
each issuing its own Nearby Search, with results merged and de-duplicated by
`place_id`.

Two parameters govern the grid:

- **Search radius** — the radius of each individual tile. This is the
  *granularity* knob: a smaller radius means more, tighter tiles and denser
  coverage (important where venues are densely packed and a single query would
  hit the API result cap and silently miss venues).
- **Overlap** — neighbouring tile centres are pulled closer than touching so
  there are no gaps at tile edges.

## Why multi-centre neighbourhood tiling

A naive approach tiles one large circle centred on the Duomo out to a fixed
radius. This is wasteful and uneven: it spends most of its queries on
low-density outskirts while *under-sampling* the dense central districts, where
the API result cap per tile causes venues to be missed.

We replaced this with **multi-centre tiling**. Coverage is defined as a set of
named *neighbourhood anchors* — curated high-density areas (e.g. Navigli, Brera,
Isola, Porta Venezia, Porta Romana, Corso Sempione, Loreto, Duomo). Each anchor
has its own centre and coverage radius. Linear districts (canals, long
corso/strips) are represented as several anchors spaced along the corridor
rather than one oversized circle.

Tiles generated for every anchor are **merged and de-duplicated** so the same
ground is never queried twice: tile centres are snapped to a single shared grid
and only one tile is kept per cell. This keeps the query budget proportional to
the area actually worth scanning and makes the result independent of the order
in which anchors are processed.

## Coverage modes

The collection command supports selectable scope so coverage can be reasoned
about and reproduced:

- **Default** — whole-city circle *plus* all neighbourhood anchors (maximum
  coverage).
- **Whole-city only** — the single large circle (the original baseline
  behaviour), useful as a comparison/fallback.
- **All neighbourhoods only** — the dense anchors without the broad circle, used
  to concentrate the query budget on high-density districts.
- **Single neighbourhood** — one named anchor, for targeted top-ups.

The per-tile search radius is global, so a given run can be re-issued at finer
granularity (smaller radius) over the neighbourhood anchors to recover venues
missed at coarser settings. The anchor list itself is configuration, so the
coverage definition is explicit and auditable rather than hard-coded.

## Idempotency and reproducibility

Each completed tile is recorded in a checkpoint keyed by its centre and radius.
Re-running skips already-completed tiles, so collection can be interrupted and
resumed, and a finer-radius pass adds only the genuinely new tiles instead of
re-querying. Venues are upserted by `place_id`, so repeated coverage of the same
area never duplicates records in the seed store.

## What each venue carries forward

For every venue the seed store keeps its Places identifier, name, formatted
address, city, coordinates, the Places type information (`primary_type` and the
full `types` list), and the Google rating and review count. The type fields are
what later allow filtering the raw venue set down to genuine dining
establishments (separating restaurants from bars, cafés, bakeries, shops, and
other non-dining places the broad search inevitably picks up).

## Next stage

Seed records are collected with lightweight fields only. A separate enrichment
pass (Place Details) augments selected venues with the full detail payload,
tracked by its own checkpoint so only un-enriched venues are fetched.
