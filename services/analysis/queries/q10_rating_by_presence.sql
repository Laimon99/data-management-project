SELECT * FROM (
    SELECT
        'tripadvisor' AS other_platform,
        if(has_tripadvisor = 1, 'also listed', 'not listed') AS bucket,
        count() AS restaurants,
        round(avgIf(google_rating_5, google_rating_5 IS NOT NULL), 3) AS mean_google_rating,
        round(medianIf(google_review_count, google_review_count IS NOT NULL), 0) AS median_google_reviews
    FROM {INTEGRATED}
    WHERE has_google = 1
    GROUP BY other_platform, bucket
    UNION ALL
    SELECT
        'thefork' AS other_platform,
        if(has_thefork = 1, 'also listed', 'not listed') AS bucket,
        count() AS restaurants,
        round(avgIf(google_rating_5, google_rating_5 IS NOT NULL), 3) AS mean_google_rating,
        round(medianIf(google_review_count, google_review_count IS NOT NULL), 0) AS median_google_reviews
    FROM {INTEGRATED}
    WHERE has_google = 1
    GROUP BY other_platform, bucket
) ORDER BY other_platform, bucket
