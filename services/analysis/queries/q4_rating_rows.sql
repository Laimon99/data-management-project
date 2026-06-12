SELECT * FROM (
    SELECT 'google' AS platform,
           google_rating_5 AS rating,
           if(google_review_count < {sparse}, 'sparse (<20)', 'well-reviewed (>=20)') AS bucket
    FROM {INTEGRATED}
    WHERE google_rating_5 IS NOT NULL AND google_review_count IS NOT NULL
    UNION ALL
    SELECT 'tripadvisor' AS platform,
           tripadvisor_rating_5 AS rating,
           if(tripadvisor_review_count < {sparse}, 'sparse (<20)', 'well-reviewed (>=20)') AS bucket
    FROM {INTEGRATED}
    WHERE tripadvisor_rating_5 IS NOT NULL AND tripadvisor_review_count IS NOT NULL
    UNION ALL
    SELECT 'thefork' AS platform,
           thefork_rating_5 AS rating,
           if(thefork_review_count < {sparse}, 'sparse (<20)', 'well-reviewed (>=20)') AS bucket
    FROM {INTEGRATED}
    WHERE thefork_rating_5 IS NOT NULL AND thefork_review_count IS NOT NULL
)
