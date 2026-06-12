SELECT
    count() AS multi_platform_restaurants,
    round(100 * avg(rating_range_5 <= 0.25), 1) AS within_0_25,
    round(100 * avg(rating_range_5 <= 0.5), 1) AS within_0_5,
    round(100 * avg(rating_range_5 <= 0.75), 1) AS within_0_75,
    round(100 * avg(rating_range_5 <= 1.0), 1) AS within_1_0,
    round(100 * avg(rating_range_5 <= 1.5), 1) AS within_1_5,
    round(100 * avg(rating_range_5 <= 2.0), 1) AS within_2_0
FROM {INTEGRATED}
WHERE rating_platform_count >= {min_platforms} AND rating_range_5 IS NOT NULL
