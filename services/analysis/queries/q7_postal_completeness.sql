SELECT
    canonical_postal_code AS postal_code,
    count() AS restaurants,
    round(avg(platform_count), 2) AS mean_platform_count,
    round(100 * avg(has_tripadvisor), 1) AS pct_on_tripadvisor,
    round(100 * avg(has_thefork), 1) AS pct_on_thefork,
    round(100 * avg(website != ''), 1) AS pct_has_website,
    round(100 * avg(primary_cuisine != ''), 1) AS pct_has_cuisine,
    round(median(google_review_count), 0) AS median_google_reviews
FROM {INTEGRATED}
WHERE canonical_city = 'Milano' AND canonical_postal_code != ''
GROUP BY postal_code
HAVING restaurants >= {min_restaurants}
ORDER BY restaurants DESC
