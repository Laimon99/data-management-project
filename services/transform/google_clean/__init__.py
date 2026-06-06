"""Transform: clean + normalize raw Google Places records, Mongo -> Mongo.

The single Google Places transform — the ``T`` of the ELT pipeline for Google. Reads
``restaurants_raw_google``, projects the ~15 relevant fields out of the heavy ``details``
blob, normalizes name/city, lifts structured address parts from ``addressComponents``,
classifies dining relevance, derives quality flags + feature fields, and upserts one lean
document into ``restaurants_clean_google``.

Unlike ``transform.tripadvisor_clean`` there is **no geocoding** (Google coordinates are
authoritative and copied verbatim) and **no type-repair** (ratings/counts arrive already
typed). See ``specs/google-places-elt-transform.md`` for the design.
"""
