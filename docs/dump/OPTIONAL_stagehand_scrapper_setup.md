# Milan Dining Venues Scraping — Plan

Two options for scraping cafés, bars, restaurants, pizzerias, gelaterias, pasticcerie, trattorias, osterias around Duomo (and the rest of Milan).

Both options use **Stagehand running fully locally** — no Browserbase subscription, no Stagehand-specific subscription. Stagehand is MIT-licensed and `env: "LOCAL"` runs everything against a local Chromium instance via Playwright.

The two options differ only in **where the LLM brain comes from**:

- **Option A** — Ollama Cloud subscription ($20/mo flat) — clean, ToS-compliant
- **Option B** — Codex/ChatGPT subscription via `auth2api` proxy — gray-zone, but uses subs you may already have

---

## Verification: Stagehand needs no subscription

Confirmed against official docs:

- Stagehand is MIT-licensed open source (github.com/browserbase/stagehand)
- The `env: "LOCAL"` mode launches a local Chromium via Playwright
- No `BROWSERBASE_API_KEY` or `BROWSERBASE_PROJECT_ID` is required when `env: "LOCAL"`
- The only required external dependency is an LLM endpoint (which is what Options A and B differ on)

Quote from Stagehand docs: *"Stagehand works locally out of the box with any Chromium browser. Browserbase is optional."*

---

## Common setup (both options)

### 1. Project scaffold

```bash
mkdir milan-scraper && cd milan-scraper
npm init -y
npm install @browserbasehq/stagehand zod dotenv
npm install -D typescript tsx @types/node
npx tsc --init
npx playwright install chromium
```

### 2. `tsconfig.json` minimal tweaks

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "esModuleInterop": true,
    "strict": true,
    "skipLibCheck": true,
    "outDir": "dist"
  },
  "include": ["src/**/*"]
}
```

Add to `package.json`:

```json
"type": "module",
"scripts": {
  "scrape": "tsx src/scrape.ts"
}
```

### 3. Project layout

```
milan-scraper/
├── .env
├── package.json
├── tsconfig.json
└── src/
    ├── scrape.ts        # main entry point
    ├── grid.ts          # generates lat/lng grid covering Milan
    └── extractor.ts     # Stagehand extraction logic
```

---

## Option A — Stagehand + Ollama Cloud ($20/mo, ToS-clean)

### Why this option

- $20/mo flat — split 3 ways = ~$7/person for a one-time project
- GPU-time-based pricing (not per-token), favorable for many small extraction calls
- 3 concurrent model slots — your team of 3 can run in parallel
- Fully ToS-compliant — official OpenAI-compatible endpoint
- Models include Qwen3-Coder 480B (strong at structured output), DeepSeek-V3.1, GPT-OSS 120B, Kimi K2.6

### Setup

1. Sign up at [ollama.com](https://ollama.com), upgrade to Pro ($20/mo)
2. Generate an API key in Settings → Keys
3. Add to `.env`:

```bash
OLLAMA_API_KEY=your_ollama_cloud_key_here
OLLAMA_BASE_URL=https://ollama.com/v1
MODEL_NAME=qwen3-coder:480b-cloud
```

### Stagehand config (`src/extractor.ts`)

```typescript
import { Stagehand } from "@browserbasehq/stagehand";
import "dotenv/config";

export function createStagehand() {
  return new Stagehand({
    env: "LOCAL",                    // no Browserbase
    headless: false,                 // set true for batch runs
    modelName: process.env.MODEL_NAME!,
    modelClientOptions: {
      baseURL: process.env.OLLAMA_BASE_URL!,
      apiKey: process.env.OLLAMA_API_KEY!,
    },
  });
}
```

That's it. No proxy, no extra processes.

---

## Option B — Stagehand + auth2api proxy on Codex/ChatGPT subscription

### Why this option

- Reuses ChatGPT Plus/Pro you may already have
- Zero additional spend on LLM inference
- Uses the same OAuth flow as the official Codex CLI

### ⚠️ Important caveats (be aware before going this route)

- **OpenAI ToS does not officially allow relaying ChatGPT sessions through third-party tools** for non-coding-agent use. The proxy README explicitly notes this. Use for personal/local use only, not commercial.
- ChatGPT Plus has a **weekly Codex quota** (~5h/week) — for one-time Milan scrape it's likely enough but plan around it
- Proxies break when OpenAI updates auth flows — may need updates mid-project
- For a uni project this is realistic; for production this is not the path

### Setup

#### 1. Authenticate the official Codex CLI first

This is what populates `~/.codex/auth.json` with valid OAuth tokens that `auth2api` reuses.

```bash
npm install -g @openai/codex
codex login   # opens browser, sign in with ChatGPT Plus/Pro account
```

Verify:

```bash
codex login status   # should report logged in
ls -la ~/.codex/auth.json
```

#### 2. Run auth2api proxy

```bash
# clone or use directly
git clone https://github.com/AmazingAng/auth2api.git
cd auth2api
npm install
npm run build

# start the proxy — it will read tokens from ~/.codex/auth.json automatically
npm start -- --provider codex --port 8787
```

You should see:

```
auth2api listening on http://127.0.0.1:8787/v1
Loaded codex profile: codex-<your-email>.json
Available models: gpt-5.4, gpt-5.3-codex, ...
```

Keep this terminal running while scraping.

#### 3. Configure Stagehand

Add to `.env`:

```bash
PROXY_BASE_URL=http://127.0.0.1:8787/v1
PROXY_API_KEY=any-non-empty-string
MODEL_NAME=gpt-5.4
```

Stagehand config in `src/extractor.ts`:

```typescript
import { Stagehand } from "@browserbasehq/stagehand";
import "dotenv/config";

export function createStagehand() {
  return new Stagehand({
    env: "LOCAL",
    headless: false,
    modelName: process.env.MODEL_NAME!,
    modelClientOptions: {
      baseURL: process.env.PROXY_BASE_URL!,
      apiKey: process.env.PROXY_API_KEY!,   // proxy ignores value but Stagehand requires it
    },
  });
}
```

#### 4. Verify the proxy works before scraping

```bash
curl -X POST http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dummy" \
  -d '{"model":"gpt-5.4","messages":[{"role":"user","content":"say hi"}]}'
```

If you get a normal completion → ready to use with Stagehand.
If 401/403 → re-run `codex login`.

---

## Scraping example: dining venues around Duomo

This works identically for both options — the only difference was in `extractor.ts`.

### `src/grid.ts` — generate search points

For a quick first pass let's just do the Duomo area (1km radius). Scale later for full Milan.

```typescript
// Duomo di Milano coordinates: 45.4642, 9.1900
// We'll generate a small grid: 5 points around Duomo
export const DUOMO_LAT = 45.4642;
export const DUOMO_LNG = 9.1900;

export const searchPoints = [
  { name: "Duomo center",     lat: 45.4642, lng: 9.1900 },
  { name: "Brera",            lat: 45.4720, lng: 9.1880 },
  { name: "Navigli",          lat: 45.4515, lng: 9.1770 },
  { name: "Porta Romana",     lat: 45.4540, lng: 9.2010 },
  { name: "Quadrilatero",     lat: 45.4680, lng: 9.1960 },
];

export const venueQueries = [
  "ristorante",
  "pizzeria",
  "trattoria",
  "osteria",
  "bar",
  "caffè",
  "gelateria",
  "pasticceria",
];
```

### `src/scrape.ts` — main scraping loop

```typescript
import { z } from "zod";
import { createStagehand } from "./extractor.js";
import { searchPoints, venueQueries } from "./grid.js";
import { writeFileSync } from "fs";

// Schema for what we want to extract per venue
const VenueSchema = z.object({
  name: z.string().describe("venue name"),
  rating: z.number().nullable().describe("star rating 1-5, null if absent"),
  reviewCount: z.number().nullable().describe("total number of reviews"),
  category: z.string().nullable().describe("Google's primary category label"),
  priceLevel: z.string().nullable().describe("price level like €, €€, €€€"),
  address: z.string().nullable(),
});

const ResultSchema = z.object({
  venues: z.array(VenueSchema),
});

interface CollectedVenue {
  name: string;
  rating: number | null;
  reviewCount: number | null;
  category: string | null;
  priceLevel: string | null;
  address: string | null;
  searchPoint: string;
  searchQuery: string;
}

async function main() {
  const stagehand = await createStagehand();
  await stagehand.init();
  const page = stagehand.page;

  const allVenues: CollectedVenue[] = [];

  for (const point of searchPoints) {
    for (const query of venueQueries) {
      console.log(`\n--- Searching: ${query} near ${point.name} ---`);

      // Navigate to Google Maps centered at this point
      const url = `https://www.google.com/maps/search/${encodeURIComponent(query)}/@${point.lat},${point.lng},16z`;
      await page.goto(url, { waitUntil: "domcontentloaded" });

      // Let the results panel render
      await page.waitForTimeout(3000);

      // Scroll the results sidebar a few times to load more entries
      await stagehand.act(
        "scroll down inside the search results panel on the left to load more venues"
      );
      await page.waitForTimeout(2000);
      await stagehand.act(
        "scroll down inside the search results panel on the left to load more venues"
      );
      await page.waitForTimeout(2000);

      // Extract all visible venues with structured schema
      const result = await stagehand.extract({
        instruction:
          "Extract all dining venues visible in the left search results panel. Skip ads and 'sponsored' entries. Get name, star rating, review count (number in parentheses), category label, price level if shown, and address.",
        schema: ResultSchema,
      });

      console.log(`Found ${result.venues.length} venues`);

      for (const v of result.venues) {
        allVenues.push({
          ...v,
          searchPoint: point.name,
          searchQuery: query,
        });
      }

      // Save incrementally so a crash doesn't lose everything
      writeFileSync(
        "venues.json",
        JSON.stringify(allVenues, null, 2)
      );
    }
  }

  await stagehand.close();

  // Deduplicate by name+address
  const seen = new Set<string>();
  const unique = allVenues.filter((v) => {
    const key = `${v.name}|${v.address ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  writeFileSync("venues_dedup.json", JSON.stringify(unique, null, 2));
  console.log(`\nTotal: ${allVenues.length} raw, ${unique.length} after dedup`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

### Run it

```bash
npm run scrape
```

A Chromium window opens (because `headless: false` — useful for first runs to watch what happens), Google Maps loads, and you'll see Stagehand scroll, extract, and move on. Output goes to `venues.json` (raw) and `venues_dedup.json` (deduplicated).

---

## Practical notes & gotchas

### Google Maps specifics

- **Cookie banner** — first navigation hits the consent screen. Add an `act("reject all cookies")` or `act("click reject all on the cookie banner")` once at the start of the run, before the loop.
- **Rate limiting** — Google starts returning empty results or CAPTCHAs after ~20-30 rapid searches. Add `await page.waitForTimeout(5000)` between iterations and consider running in batches with breaks.
- **Result count per search** — sidebar shows ~20 venues by default, scrolling loads more (up to ~120). For a single small radius like 1km around Duomo this is plenty.

### Stagehand-specific

- **Cost optimization** — Stagehand's `act()` is more expensive than `extract()` because it analyzes the whole page. Use Playwright's native APIs (`page.click()`, `page.goto()`) for known-deterministic steps; reserve `act()`/`extract()` for the AI-needed parts.
- **Caching** — set `enableCaching: true` in Stagehand options to cache action plans. After the first iteration, repeat scrolls/clicks won't hit the LLM.
- **Headless for batch** — switch `headless: true` once you've confirmed it works. ~30% faster, no window pops up.

### Scaling beyond Duomo to all Milan

Replace the `searchPoints` array with a generated grid. Quick generator:

```typescript
function generateMilanGrid(stepKm: number = 1) {
  const points: { name: string; lat: number; lng: number }[] = [];
  // Milan bounding box (rough)
  const latMin = 45.40, latMax = 45.53;
  const lngMin = 9.10, lngMax = 9.28;
  // 1km ≈ 0.009 deg lat, ≈ 0.013 deg lng at this latitude
  const dLat = stepKm * 0.009;
  const dLng = stepKm * 0.013;
  let i = 0;
  for (let lat = latMin; lat <= latMax; lat += dLat) {
    for (let lng = lngMin; lng <= lngMax; lng += dLng) {
      points.push({ name: `cell_${i++}`, lat, lng });
    }
  }
  return points;
}
```

That's ~250 points × 8 queries = 2000 searches. At Stagehand's pace this is several hours of runtime, which is why the team's 3-account / parallel-process angle matters — split the grid into 3 segments, each team member runs one.

### Comparison vs Places API (the third path)

For full Milan coverage, **realistically the Places API is still cheaper and more reliable** than either option here:

- 3 accounts × $200 free credit = $600 free, enough for full Milan
- No CAPTCHAs, no scrolling, no flaky DOM
- Returns clean structured JSON

The Stagehand+sub approach makes more sense as **enrichment** for things Places API doesn't expose (full review text, photos, etc.) or as a learning exercise in agentic browser automation.

---

## Quick decision summary

| | Option A (Ollama Cloud) | Option B (auth2api + Codex) |
|---|---|---|
| Monthly cost | $20 (split 3 = ~$7) | $0 if you have ChatGPT Plus |
| ToS status | Clean | Gray zone (personal use) |
| Setup time | 5 min | 20 min |
| Reliability | High | Medium (proxy may break) |
| Quota | GPU time, fairly generous on Pro | ~5h/week on Plus |
| Recommended for | Default choice | If you want zero spend & accept fragility |