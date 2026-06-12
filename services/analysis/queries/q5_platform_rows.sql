SELECT
    google_rating_5,
    tripadvisor_rating_5,
    thefork_rating_5,
    rating_avg_5,
    rating_platform_count
FROM {INTEGRATED}
WHERE rating_platform_count >= {min_platforms}
