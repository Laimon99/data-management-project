"""Transform: clean raw Tripadvisor records and geocode them, Mongo -> Mongo.

The single Tripadvisor transform. Reads ``restaurants_raw_tripadvisor``, cleans
each record (type coercion + normalization), geocodes the *cleaned* address, and
upserts one document (clean fields + latitude/longitude) into
``restaurants_clean_tripadvisor``. Geocoding is a sub-step of cleaning, not a
separate stage. See ``specs/tripadvisor-elt-transform.md`` for the design.
"""
