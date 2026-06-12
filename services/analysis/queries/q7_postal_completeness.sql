SELECT
    canonical_postal_code AS postal_code,
    count() AS restaurants,
    round(avg(platform_count), 2) AS mean_platform_count,
    round(100 * avg(has_tripadvisor), 1) AS pct_on_tripadvisor,
    round(100 * avg(has_thefork), 1) AS pct_on_thefork,
    round(100 * avgIf(google_has_website, has_google = 1), 1) AS pct_google_website,
    round(avg(ifNull(google_photo_count, 0)), 1) AS mean_google_photos
FROM {INTEGRATED}
WHERE canonical_postal_code != ''
GROUP BY postal_code
HAVING restaurants >= {min_restaurants}
ORDER BY restaurants DESC
