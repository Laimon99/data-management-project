SELECT
    primary_cuisine AS cuisine,
    count() AS restaurants,
    round(avgIf(rating_avg_5, rating_avg_5 IS NOT NULL), 3) AS mean_rating,
    countIf(rating_platform_count >= {min_platforms}) AS multi_platform,
    round(avgIf(rating_range_5, rating_platform_count >= {min_platforms} AND rating_range_5 IS NOT NULL), 3) AS mean_range
FROM {INTEGRATED}
WHERE primary_cuisine != ''
GROUP BY cuisine
HAVING restaurants >= {min_restaurants}
ORDER BY restaurants DESC
LIMIT {top_n}
