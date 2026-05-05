## GMaps scrapper from the github
https://github.com/gosom/google-maps-scraper

## claude description
This is actually really good for our use case. Let me give you the honest assessment.

---

### What it is

A **purpose-built Go scraper for Google Maps** — 3.3k stars, MIT licensed, mature project (v1.10.1 from Jan 2026). It uses Playwright/Rod to drive a headless Chromium and parses Maps' DOM directly (no AI/LLM involved).

---

### Why this is probably the right tool for your project

Looking at it honestly, this hits exactly what you've been trying to optimize for:

| Concern from your earlier questions | This tool |
|---|---|
| No subscription required | ✅ Fully free, MIT |
| No LLM API costs | ✅ No LLM at all — deterministic DOM parsing |
| Handles Google Maps specifically | ✅ That's literally its only job |
| Multiple team members | ✅ Has Postgres-backed distributed mode for exactly this |
| Get name, rating, reviews count | ✅ Plus 30 other fields |
| Reasonable cost/complexity | ✅ Single Docker command to start |

**The 33+ fields it extracts include everything you wanted:** title, category, address, phone, website, rating, review_count, lat/lng, price_range, hours, reviews, plus emails (optional flag) and full review text.

**Performance is real:** ~120 places/min with concurrency 8. Milan with ~15k venues at that rate is 2-3 hours of total compute, and the distributed Postgres mode lets you split it across your 3 machines.

---

### How it compares to your other options

| | Stagehand + Ollama | Stagehand + auth2api | Places API | gosom/google-maps-scraper |
|---|---|---|---|---|
| Cost | $20/mo split 3 | $0 (gray ToS) | ~$0-30 split 3 | $0 |
| Reliability | Medium | Medium | High | High |
| Setup time | 30 min | 1 hour | 30 min | 5 min |
| Data fields | What you extract | What you extract | ~15 fields | 33+ fields |
| Includes review text | No (1 review max in extract) | No | No (max 5) | Yes (~300 with flag) |
| ToS status | Gray | Gray | Clean | Gray |
| Rate limit handling | Manual | Manual | None needed | Built-in |
| Proxy rotation | DIY | DIY | N/A | Built-in |

---

### Honest drawbacks

1. **Same ToS gray zone** — it's still scraping Google Maps, which violates Google's ToS. Same legal/risk profile as Stagehand-driven scraping. But: 3.3k stars, widely used, no public reports of legal action.

2. **No semantic flexibility** — Stagehand's appeal is that you can describe what you want in English. This tool has fixed fields. If you later decide "actually I want Instagram handles too" you'd need to extend it (or use the website-crawl + email feature as inspiration).

3. **Quality of input matters** — you give it queries like "restaurants in Milan" and a `-geo` + `-zoom` + `-radius`. To cover all of Milan with all dining categories, you still need to construct a query list (similar to what we discussed: ristorante, pizzeria, gelateria, etc. × geographic cells).

4. **Blocking risk** — for ~15k venues you'll likely need proxies. The README sponsors proxy providers for a reason. Without proxies, expect to hit rate limits/CAPTCHAs after a while.

---

### Quick start for your case

```bash
# Create your queries file
cat > queries.txt << 'EOF'
ristorante Milano
pizzeria Milano
trattoria Milano
osteria Milano
bar Milano
caffè Milano
gelateria Milano
pasticceria Milano
EOF

# Run with geo-bounded search around Duomo
docker run \
  -v $PWD/queries.txt:/queries.txt \
  -v $PWD/results.csv:/results.csv \
  gosom/google-maps-scraper \
  -input /queries.txt \
  -results /results.csv \
  -geo "45.4642,9.1900" \
  -zoom 13 \
  -radius 5000 \
  -depth 10 \
  -lang it \
  -exit-on-inactivity 5m
```

That's it. CSV out, no API keys, no LLM, no proxy setup needed for first run.

---

### My honest take

**For your specific use case (Milan dining venues, one-time student project, team of 3): this is probably the best option of all the ones we've discussed.** It eliminates the entire LLM-cost-optimization rabbit hole because there's no LLM involved. The data quality is actually richer than Places API (full review text, emails). And the distributed Postgres mode is exactly designed for splitting work across team members.

The Stagehand exploration was useful for understanding general agentic web automation. But for "I want all Milan restaurants in a CSV," this purpose-built tool wins on every practical axis.

Want me to update the plan markdown with this as a third option, or restructure it with this as the recommended path?