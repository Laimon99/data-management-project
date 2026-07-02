SELECT
    integrated_restaurant_id AS id,
    canonical_name AS name,
    canonical_city AS city,
    canonical_postal_code AS postal_code,
    latitude,
    longitude,
    platform_count,
    has_google, has_tripadvisor, has_thefork,
    google_has_website, google_has_phone,
    tripadvisor_has_website, tripadvisor_has_phone, tripadvisor_has_email,
    -- `primary_cuisine` is the raw TA/TF label on purpose: Q7 measures human-platform
    -- metadata completeness, not Q8's canonical (Google-saturated) `cuisine_primary`.
    website, primary_cuisine,
    google_photo_count, tripadvisor_photo_count, thefork_photo_count,
    google_review_count, tripadvisor_review_count, thefork_review_count,
    -- per-platform + consensus ratings (0–5) so Q7 can also ask whether geography
    -- shifts the rating itself, not just metadata completeness.
    google_rating_5, tripadvisor_rating_5, thefork_rating_5, rating_avg_5,
    rating_range_5
FROM {INTEGRATED}
WHERE canonical_city = 'Milano'
