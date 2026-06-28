SELECT
    canonical_name,
    canonical_street,
    {rating_a} AS {a}_rating,
    {rating_b} AS {b}_rating,
    round(abs({rating_a} - {rating_b}), 2) AS abs_diff,
    {review_a} AS {a}_reviews,
    {review_b} AS {b}_reviews
FROM {INTEGRATED}
WHERE {rating_a} IS NOT NULL AND {rating_b} IS NOT NULL
  AND abs({rating_a} - {rating_b}) > {min_diff}
  AND coalesce({review_a}, 0) >= {min_reviews_a} AND coalesce({review_b}, 0) >= {min_reviews_b}
ORDER BY abs_diff DESC
LIMIT {top_n}
