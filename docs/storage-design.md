# Storage Design — Candidate Databases & Architecture

Technical evaluation of storage options for the multi-platform restaurant-ratings
project. Covers the data characteristics, the query workload implied by our research
questions, candidate engines (document and columnar), and the architecture options on
the table.

This is a **design exploration**, not a locked decision. Open choices are listed at the
end.

---

## 1. What the storage layer has to serve

### 1.1 Data characteristics

| Layer | Shape | Volume | Notes |
|---|---|---|---|
| **Seed (Google Places)** | Deeply nested JSON document (`details` blob: address components, opening hours, service/amenity flags, up to 5 reviews, up to 10 photo metas) | ~10,808 records | Naturally document-shaped; flattening to columns is lossy. See `dataset-schema.md`. |
| **Per-platform records** (Tripadvisor, TheFork, Google) | Scraped name/address + rating + review count + review text | ~1–3k matched venues per platform | Text reviews are document-shaped and variable. |
| **Integrated ratings table** | Flat: one row per resolved restaurant, ratings from each platform + coordinates | ~1–3k rows | The analytical surface; must answer the mandatory queries. |

Coordinates (`latitude`/`longitude`) are authoritative on the seed and present
end-to-end — **geo is a first-class access pattern**, not an afterthought.

### 1.2 Research questions driving the workload

From `pitch/PROF_PITCH.md` and `pitch/DATA_VISUALIZATION_PROJECT_IDEA.md`:

1. How consistent are ratings across platforms? *(distribution of pairwise gaps)*
2. Which restaurants show the highest disagreement? *(rank by rating spread)*
3. Is inconsistency related to data-quality issues (review count, missing fields, staleness)?
4. Can low-quality / sparse data inflate perceived quality? *(rating × review-count)*
5. Are some platforms systematically more optimistic/pessimistic? *(per-platform bias)*
6. Does inconsistency grow for smaller / less popular restaurants?
7. Does geographic location (centre vs periphery) matter? *(spatial aggregation)*

Grouped by the viz doc into three analytical themes:
- **A — Agreement:** pairwise rating differences, gap distributions, consensus vs disagreement.
- **B — Geographic divergence:** avg rating per area per platform, spatial clusters of disagreement, heatmaps.
- **C — Review-volume reliability:** rating vs review count, high-rating/low-review outliers.

### 1.3 Resulting access patterns

| Pattern | Used by | Storage implication |
|---|---|---|
| Store & retrieve raw nested venue docs | Seed, per-platform raw | Document model (no flattening loss) |
| Full-text over review text | Optional LLM features, QA | Text indexing helps |
| **Proximity blocking** (candidates within radius + name/addr similarity) | Entity resolution | Geo index (`2dsphere` / spatial) |
| Pairwise rating-gap aggregation, ranking, distributions | RQ 1, 2, 5, 6; theme A | Columnar aggregation shines |
| **Avg rating / disagreement per area**, hex/grid binning | RQ 7; theme B | Geo + group-by aggregation |
| Rating × review-count correlation, outlier detection | RQ 3, 4; theme C | Columnar aggregation |

The **two mandatory queries** (exam FAQ 6) fall straight out of this: e.g.
"restaurants with cross-platform rating difference > 1 star" and "average rating by
city area." Both are aggregation/geo queries — well-suited to either a document
aggregation pipeline or a columnar engine.

---

## 2. Document database candidates

| Engine | Fit | Strengths | Weaknesses |
|---|---|---|---|
| **MongoDB** | Best all-rounder | Native `2dsphere` geo (`$geoNear`, `$geoWithin`), aggregation pipeline (non-SQL), nested-doc fit, huge tooling, trivial Docker | SSPL license (free to self-host) |
| **OpenSearch** (Apache-2.0 fork of Elasticsearch) | Strong dark-horse | Document + **full-text search on review text** + rich geo (`geo_point`/`geo_shape`) + **free Dashboards for EDA viz** | Heavier; index-mapping management; better as search/analytics layer than sole system-of-record |
| **CouchDB** (Apache) | OK | Truly open, simple HTTP/JSON API, strong replication | Weak ad-hoc querying, no real geo aggregation |
| **ArangoDB** | Interesting | **Multi-model: document + graph** — could host the entity-resolution graph in one engine; built-in geo | BSL license since 3.12; smaller community |
| **Couchbase** | Capable | SQL++/N1QL, built-in full-text + analytics + geo | Operationally heavy for project scale |

**Lead:** MongoDB for the document layer. **Watch:** OpenSearch maps unusually well to
this project (review-text search + geo + free dashboards) and could serve as either the
search layer or a second document store.

---

## 3. Columnar engine candidates

For the analytical / integrated layer. All are column-stores (not row-store RDBMS); most
speak SQL, which is acceptable — the steer is away from the relational/row-store *model*,
not the SQL language.

| Engine | Deployment | Strengths | Weaknesses |
|---|---|---|---|
| **DuckDB** | Embedded (file + lib) | Zero server, **`spatial` extension = PostGIS-grade geo** (`ST_Distance`, `ST_Within`, polygon ops), reads Parquet/JSON/Mongo exports directly, ideal for notebook EDA | Single-process; "library" rather than deployed server |
| **ClickHouse** | Server (Docker) | Fastest aggregations, native geo (`greatCircleDistance`, `pointInPolygon`, geohash/H3), mature, easy Docker image | Perf is overkill at our scale (still a clean fit) |
| **MonetDB** | Server (Docker) | The original column-store server, SQL, mature, lightweight-ish | Smaller community, less modern tooling |
| **StarRocks** | Server (MPP) | Modern MPP column store, MySQL protocol, fast | Multi-component, heavier Docker footprint |
| **Apache Doris** | Server (MPP) | MPP columnar, MySQL protocol | Same multi-component overhead |
| **Apache Druid / Pinot** | Server (multi-process) | Real-time OLAP powerhouses | Overkill / heavy for ~1–3k rows |

**Leads:** **DuckDB** (lowest friction, embedded, and the spatial extension covers the
geo workload without a separate spatial DB) or **ClickHouse** (if a deployed column-store
*server* is preferred for the architecture narrative). **MonetDB** is the lightweight
server middle ground.

---

## 4. Architecture options

### Option 1 — MongoDB only (single document store)
One engine across the whole pipeline:
- `restaurants_seed` — raw nested Places docs
- `tripadvisor_raw`, `thefork_raw`, `google_raw` — per-platform scraped docs (incl. reviews)
- `restaurants_ratings` — integrated collection (one doc per resolved restaurant)

Queries run as **aggregation pipelines** (`$match`, `$group`, `$bucket`, `$geoNear`);
geo via `2dsphere`, which also powers entity-resolution proximity blocking.

*+* Simplest ops (one container), single paradigm, matches `CLAUDE.md` preference.
*−* Aggregation-pipeline analytics are less ergonomic than a columnar engine for heavy
group-bys / pairwise comparisons.

### Option 2 — Document + columnar *(recommended)*
- **MongoDB** = system of record for raw nested seed + per-platform review documents;
  `2dsphere` for proximity blocking.
- **Columnar engine** (DuckDB / ClickHouse / MonetDB) = flat integrated ratings table,
  the ≥2 mandatory queries, and all theme A/B/C analytics.

*+* Strongest multi-paradigm narrative (document + columnar); each engine used where it's
strongest; clean ETL boundary between raw and integrated.
*−* Two systems + an ETL step.

### Option 3 — Document + document-with-search
- **MongoDB** = system of record.
- **OpenSearch** = review-text search + geo aggregations + free Dashboards for EDA/viz.

*+* Leans into full-text review analysis and out-of-the-box geo dashboards (theme B).
*−* Two document-style stores; less of a "column store" story; OpenSearch ops overhead.

---

## 5. Recommendation & stage mapping

**Recommended:** Option 2 — **MongoDB + a columnar engine**, with **DuckDB** as the
default columnar pick (embedded, spatial extension covers geo, zero infra) and
**ClickHouse** retained as a server-based alternative if we want a deployed second DBMS.

| Pipeline stage | Store | Why |
|---|---|---|
| 1. Seed acquisition | MongoDB `restaurants_seed` | Nested Places doc stored as-is |
| 2. Per-platform collection | MongoDB `*_raw` collections | Variable, text-heavy docs |
| 3. Entity resolution | MongoDB (`2dsphere` blocking) → match table | Geo + name/addr similarity blocking |
| 4. Unified dataset | Columnar `restaurants_ratings` | Flat analytical surface; mandatory queries |
| 5. Quality assessment & EDA | Columnar (+ optional OpenSearch Dashboards) | Aggregations, before/after metrics |

All three architecture options satisfy the exam requirement of "one or more DBMS + ≥2
queries."

---

## 6. Open decisions

- **Columnar engine:** DuckDB vs ClickHouse vs MonetDB — defer until we prototype the two
  mandatory queries against sample data.
- **PostGIS:** flagged as interesting. Likely unnecessary — Mongo `2dsphere` and DuckDB
  `spatial` cover proximity blocking and area aggregation. Revisit only if heavier polygon
  operations are needed.
- **OpenSearch:** include as a search/dashboard layer, or keep document analytics inside
  Mongo? Decide alongside the LLM review-feature extension scope.
- **Optional extensions (not yet scoped):** graph store (Neo4j/ArangoDB) for entity
  resolution as a graph; vector store (pgvector/Qdrant) for semantic matching / review
  sentiment.