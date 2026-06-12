SELECT * FROM (
    SELECT
        'google' AS platform,
        countIf(google_photo_count IS NOT NULL) AS venues,
        round(corrIf(google_photo_count, google_review_count, google_photo_count IS NOT NULL AND google_review_count IS NOT NULL), 3) AS corr_photos_reviews,
        round(corrIf(google_photo_count, google_rating_5, google_photo_count IS NOT NULL AND google_rating_5 IS NOT NULL), 3) AS corr_photos_rating
    FROM {INTEGRATED}
    UNION ALL
    SELECT
        'tripadvisor' AS platform,
        countIf(tripadvisor_photo_count IS NOT NULL) AS venues,
        round(corrIf(tripadvisor_photo_count, tripadvisor_review_count, tripadvisor_photo_count IS NOT NULL AND tripadvisor_review_count IS NOT NULL), 3) AS corr_photos_reviews,
        round(corrIf(tripadvisor_photo_count, tripadvisor_rating_5, tripadvisor_photo_count IS NOT NULL AND tripadvisor_rating_5 IS NOT NULL), 3) AS corr_photos_rating
    FROM {INTEGRATED}
    UNION ALL
    SELECT
        'thefork' AS platform,
        countIf(thefork_photo_count IS NOT NULL) AS venues,
        round(corrIf(thefork_photo_count, thefork_review_count, thefork_photo_count IS NOT NULL AND thefork_review_count IS NOT NULL), 3) AS corr_photos_reviews,
        round(corrIf(thefork_photo_count, thefork_rating_5, thefork_photo_count IS NOT NULL AND thefork_rating_5 IS NOT NULL), 3) AS corr_photos_rating
    FROM {INTEGRATED}
) ORDER BY platform
