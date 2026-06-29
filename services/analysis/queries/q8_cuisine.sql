SELECT
    cuisine_primary AS cuisine,
    count() AS restaurants,
    round(avgIf(rating_avg_5, rating_avg_5 IS NOT NULL), 3) AS mean_rating,
    countIf(rating_platform_count >= {min_platforms}) AS multi_platform,
    round(avgIf(rating_range_5, rating_platform_count >= {min_platforms} AND rating_range_5 IS NOT NULL), 3) AS mean_range,
    round(medianIf(rating_range_5, rating_platform_count >= {min_platforms} AND rating_range_5 IS NOT NULL), 3) AS median_range,
    -- popularity: typical total review footprint across the three platforms
    round(median(coalesce(google_review_count, 0) + coalesce(tripadvisor_review_count, 0) + coalesce(thefork_review_count, 0)), 0) AS median_reviews,
    round(avg(coalesce(google_review_count, 0) + coalesce(tripadvisor_review_count, 0) + coalesce(thefork_review_count, 0)), 0) AS mean_reviews,
    -- price tier (1..4), where the integration could resolve one
    round(avgIf(price_tier, price_tier IS NOT NULL), 2) AS mean_price,
    countIf(price_tier IS NOT NULL) AS priced
FROM {INTEGRATED}
WHERE cuisine_primary NOT IN ('', 'Other')
GROUP BY cuisine
HAVING restaurants >= {min_restaurants}
ORDER BY restaurants DESC
LIMIT {top_n}
