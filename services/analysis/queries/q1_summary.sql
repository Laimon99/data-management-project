SELECT
    CAST(rating_platform_count AS String) AS coverage,
    count() AS restaurants,
    round(avg(rating_range_5), 3) AS mean_range,
    round(stddevSamp(rating_range_5), 3) AS sd_range,
    round(quantile(0.9)(rating_range_5), 3) AS p90_range,
    round(max(rating_range_5), 3) AS max_range,
    round(100 * avg(rating_range_5 <= 0.5), 1) AS pct_within_0_5,
    round(100 * avg(rating_range_5 <= 1.0), 1) AS pct_within_1_0
FROM {INTEGRATED}
WHERE rating_platform_count >= {min_platforms} AND rating_range_5 IS NOT NULL
GROUP BY ROLLUP(coverage)
ORDER BY coverage
