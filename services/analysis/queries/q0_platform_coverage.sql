SELECT has_google, has_tripadvisor, has_thefork, count() AS restaurants
FROM {INTEGRATED}
GROUP BY has_google, has_tripadvisor, has_thefork
ORDER BY restaurants DESC
