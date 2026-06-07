"""Transform: clean + structure raw TheFork records, Mongo -> Mongo.

The single TheFork transform — the ``T`` of the ELT pipeline for TheFork. Reads
``restaurants_raw_thefork``, resolves the dataset's First-Normal-Form violations (parses
``price_range`` -> ``avg_price_eur``, ``discount`` -> ``discount_pct``, ``cuisine_type`` ->
``cuisines``/``dietary_options``, and tidies opening hours), normalizes name/address/city,
lifts ``tf_id``, drops the dead fields, derives count-only quality flags and clearly
sample-labeled review features, and upserts one lean document into
``restaurants_clean_thefork``.

Unlike ``transform.tripadvisor_clean`` there is **no geocoding** (TheFork coordinates are
authoritative) and **no type-repair** (fields arrive typed); unlike
``transform.google_clean`` there are **no drop rules** (the slice is duplicate-free and
100% dining). See ``specs/thefork-elt-transform.md`` for the design and
``services/extract/thefork_scraper/eda-report.md`` for the EDA.
"""
