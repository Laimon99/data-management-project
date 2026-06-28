-- Cross-source cuisine agreement per canonical bucket: for venues that carry a
-- cuisine label on >= 2 platforms, how often do the platforms agree on the
-- primary bucket? ('disagree' means e.g. Tripadvisor says Asian, Google says Chinese.)
SELECT
    cuisine_primary AS cuisine,
    countIf(cuisine_n_sources >= 2) AS multi_source,
    round(100 * countIf(cuisine_agreement = 'agree') / countIf(cuisine_n_sources >= 2), 1) AS pct_agree
FROM {INTEGRATED}
WHERE cuisine_primary NOT IN ('', 'Other')
GROUP BY cuisine
HAVING multi_source >= {min_restaurants}
ORDER BY pct_agree DESC
LIMIT {top_n}
