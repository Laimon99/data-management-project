SELECT
    multiIf(
        google_review_count < {sparse}, '0_sparse(<20)',
        google_review_count < 100, '1_low(20-99)',
        google_review_count < 500, '2_mid(100-499)',
        google_review_count < 2000, '3_high(500-1999)',
        '4_very_high(2000+)'
    ) AS popularity_bin,
    count() AS restaurants,
    round(avg(rating_range_5), 3) AS mean_range,
    round(stddevSamp(rating_range_5), 3) AS sd_range
FROM {INTEGRATED}
WHERE rating_platform_count >= {min_platforms} AND rating_range_5 IS NOT NULL AND google_review_count IS NOT NULL
GROUP BY popularity_bin
ORDER BY popularity_bin
