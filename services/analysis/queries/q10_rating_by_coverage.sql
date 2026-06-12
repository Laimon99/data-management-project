SELECT
    CAST(platform_count AS String) AS platform_count,
    count() AS restaurants,
    round(avgIf(google_rating_5, google_rating_5 IS NOT NULL), 3) AS mean_google_rating,
    round(medianIf(google_review_count, google_review_count IS NOT NULL), 0) AS median_google_reviews
FROM {INTEGRATED}
WHERE has_google = 1
GROUP BY platform_count
ORDER BY platform_count
