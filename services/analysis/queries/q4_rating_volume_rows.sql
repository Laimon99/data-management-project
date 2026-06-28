SELECT * FROM (
    SELECT 'google' AS platform,
           google_rating_5 AS rating,
           google_review_count AS reviews
    FROM {INTEGRATED}
    WHERE google_rating_5 IS NOT NULL AND google_review_count IS NOT NULL
    UNION ALL
    SELECT 'tripadvisor' AS platform,
           tripadvisor_rating_5 AS rating,
           tripadvisor_review_count AS reviews
    FROM {INTEGRATED}
    WHERE tripadvisor_rating_5 IS NOT NULL AND tripadvisor_review_count IS NOT NULL
    UNION ALL
    SELECT 'thefork' AS platform,
           thefork_rating_5 AS rating,
           thefork_review_count AS reviews
    FROM {INTEGRATED}
    WHERE thefork_rating_5 IS NOT NULL AND thefork_review_count IS NOT NULL
)
