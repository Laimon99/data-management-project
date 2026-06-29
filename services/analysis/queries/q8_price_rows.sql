-- Row-level price tier + integrated mean rating, for the per-tier rating distribution
-- (Q8 price angle, V2). Price tier is an ordinal category (1=€ … 4=€€€€); kept un-averaged.
SELECT
    price_tier,
    rating_avg_5 AS rating
FROM {INTEGRATED}
WHERE price_tier IS NOT NULL AND rating_avg_5 IS NOT NULL
