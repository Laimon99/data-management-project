SELECT
    round(floor(rating_range_5 / 0.25) * 0.25, 2) AS range_bin,
    count() AS restaurants
FROM {INTEGRATED}
WHERE rating_platform_count >= {min_platforms} AND rating_range_5 IS NOT NULL
GROUP BY range_bin
ORDER BY range_bin
