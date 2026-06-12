SELECT {photo} AS photos, {review} AS reviews, {rating} AS rating
FROM {INTEGRATED}
WHERE {photo} IS NOT NULL AND {review} IS NOT NULL AND {photo} > 0 AND {review} > 0
