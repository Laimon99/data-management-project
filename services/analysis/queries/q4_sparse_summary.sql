SELECT * FROM (
    SELECT
        'google' AS platform,
        if(google_review_count < {sparse}, 'sparse (<20)', 'well-reviewed (>=20)') AS bucket,
        count() AS restaurants,
        round(avg(google_rating_5), 3) AS mean_rating,
        round(stddevSamp(google_rating_5), 3) AS sd_rating
    FROM {INTEGRATED}
    WHERE google_rating_5 IS NOT NULL AND google_review_count IS NOT NULL
    GROUP BY platform, bucket
    UNION ALL
    SELECT
        'tripadvisor' AS platform,
        if(tripadvisor_review_count < {sparse}, 'sparse (<20)', 'well-reviewed (>=20)') AS bucket,
        count() AS restaurants,
        round(avg(tripadvisor_rating_5), 3) AS mean_rating,
        round(stddevSamp(tripadvisor_rating_5), 3) AS sd_rating
    FROM {INTEGRATED}
    WHERE tripadvisor_rating_5 IS NOT NULL AND tripadvisor_review_count IS NOT NULL
    GROUP BY platform, bucket
    UNION ALL
    SELECT
        'thefork' AS platform,
        if(thefork_review_count < {sparse}, 'sparse (<20)', 'well-reviewed (>=20)') AS bucket,
        count() AS restaurants,
        round(avg(thefork_rating_5), 3) AS mean_rating,
        round(stddevSamp(thefork_rating_5), 3) AS sd_rating
    FROM {INTEGRATED}
    WHERE thefork_rating_5 IS NOT NULL AND thefork_review_count IS NOT NULL
    GROUP BY platform, bucket
) ORDER BY platform, bucket
