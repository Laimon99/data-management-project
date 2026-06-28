---
name: plotly-chart-fixes
description: Battle-tested fixes for Plotly static-image (kaleido/PNG) charts in this project's notebooks — diagnosing "broken" charts, adding on-figure storytelling captions, choosing mean vs median, and placing platform/brand logos as axis labels. Use when a Plotly figure renders wrong (bars look horizontal, faint, squashed, axis stretched), when asked to add a narrative caption onto a chart, when a notebook cell raises an error on run, or when polishing the Q1–Q11 research-questions charts. Pairs with the `plotly` and `data-visualization` skills.
version: 1.3
license: MIT
---

# Plotly Chart Fixes (static PNG notebooks)

Concrete, verified fixes from real debugging sessions on the per-question analysis
notebooks `notebooks/qNN_*.ipynb` (each opens with `from analysis.notebook import *`).
These render Plotly as
**static PNG via kaleido** (`pio.renderers.default = "png"`) so charts show in VS
Code, GitHub's notebook viewer, and exported HTML. That changes what "good" means:
no hover/zoom to rescue a cluttered chart — everything must read from the static
image.

## Self-improvement protocol (READ FIRST, for future agents)

This skill is meant to grow. When you fix a chart problem that isn't already
covered here — or find a cleaner fix for one that is — **append it**:

1. Add a new `### Symptom → Cause → Fix` block under "Diagnosed problems",
   following the existing shape: a one-line symptom the user would describe, the
   real root cause (not the first guess), and a minimal verified code fix.
2. Record the **first wrong guess** if you had one (the "Misdiagnosis" line).
   These are the highest-value lessons — they stop the next agent burning turns.
3. Only add a fix you **rendered and eyeballed**. Write a PNG to the scratchpad
   and Read it back (see "Verification loop"). Never document an unrendered fix.
4. Bump `version` (minor for a new entry, major for a restructure) and keep
   entries minimal — delete a workaround when a better fix supersedes it.
5. Keep code snippets copy-pasteable and dependency-honest (note if PIL/network
   is needed).

## Verification loop (how to confirm any fix, no ClickHouse-free guessing)

Static charts must be *seen*, not assumed. The reliable loop:

```python
fig.write_image(SCRATCHPAD + "/check.png", width=1050, height=620)
```

Then Read that PNG back to inspect it. For a notebook, after editing a cell,
re-run end-to-end and extract the embedded output rather than trusting the code:

```bash
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/q07_location_completeness.ipynb
# (or notebooks/q*.ipynb for all of them)
# then extract a cell's image: json.load -> cells[i].outputs[*].data['image/png'] -> base64decode -> Read
```

Prereqs for these notebooks: ClickHouse must be up and loaded
(`docker compose --profile analytics up -d clickhouse`; the data persists in the
volume across restarts). `uv run` uses the project venv; a user's Jupyter kernel
may not — see "ValidationError" below.

## Diagnosed problems

### Bars render as faint horizontal lines; x-axis stretched far past the data
- **Symptom (user words):** "what are those bins, why are they horizontal, the
  x-axis goes to 10, it's not readable."
- **Misdiagnosis (don't repeat):** assuming it's faint colours / bar width. It is
  NOT primarily a styling issue.
- **Cause:** `px.bar` with **two numeric columns** auto-detects
  `orientation="h"`. The bars are drawn horizontally — bar *length* = the x value,
  bar *position* = the y (count) value — which reads as faint horizontal lines and
  stretches the x-axis to the data's max.
- **Fix:** force vertical orientation.
  ```python
  fig = px.bar(df, x="range_bin", y="restaurants", orientation="v")
  ```
- **Then polish** (secondary, after orientation is correct): solid colour, explicit
  bar width just under the bin size, and clip the empty tail so the bulk is legible.
  ```python
  fig.update_traces(marker_color="#4C6EF5", marker_line_width=0, width=0.22)
  fig.update_xaxes(range=[-0.15, 2.65], dtick=0.5, ticksuffix="★")
  ```
- **Note:** when the SQL already aggregates into bins (a "bar of counts"), keep
  `px.bar` — do NOT switch to `px.histogram`, which would re-bin already-binned data.

### "ValidationError" when the user runs the notebook, but it runs clean for you
- **Cause (most common):** stale / out-of-order kernel — a cell ran before the one
  that defines a variable it reads (e.g. a caption that reads `q1_sum`), or the
  Jupyter kernel points at a different environment than `uv`.
- **Don't:** assume it's your Plotly properties. A bad Plotly property raises a
  `ValueError`, not pydantic's `ValidationError`. `ValidationError` here points at
  settings/`AnalysisSettings()`, usually fine on a clean run.
- **Fix:** re-execute the whole notebook in the project venv (command above) to
  prove it's clean, then tell the user **Restart Kernel & Run All** with the `uv`
  kernel. Reproduce nothing with dummy data if the real data path is one command away.

### Unreadable violins (thin, squished, tiny inner boxes)
- **Symptom (user words):** "the violins aren't readable, can we scale them properly?"
- **Cause:** default px.violin with many groups, KDE tails extrapolated past the real
  data range, and (with very unequal n) `scalemode="count"` shrinking the small group.
- **Fix:** `scalemode="width"` (equal widths regardless of n — Q4 groups differ ~100×),
  `spanmode="hard"` (clip the KDE to the actual min/max, killing fake tails), `width=0.85`,
  `box_visible=True`, `meanline_visible=True`, and give the figure vertical room.
- **Best for a 2-way comparison: split violins.** One distribution on each half-violin —
  far cleaner than overlaying. Needs `go.Violin` (px can't split by colour):
  ```python
  fig = go.Figure()
  for tier, side in [("thin", "negative"), ("established", "positive")]:
      s = df[df.tier == tier]
      fig.add_trace(go.Violin(x=s.platform, y=s.rating, side=side, name=tier,
          scalemode="width", spanmode="hard", width=0.9, box_visible=True,
          meanline_visible=True, line_color=C[tier], fillcolor=C[tier], opacity=0.65))
  fig.update_layout(violinmode="overlay", violingap=0)
  ```

### Legend eats horizontal space
- **Fix:** move it above the plot: `fig.update_layout(legend=dict(orientation="h",
  yanchor="bottom", y=1.02, xanchor="right", x=1))`. Applied to every Q4 chart.

## Picking the metric: don't chase the mean when the signal is variance

The most valuable Q4 lesson, and a recurring analyst trap. When a hypothesis is framed as
"X inflates the rating" (sparse reviews, a cuisine, a price tier…), check the **dispersion
before committing to a mean comparison**:
- Compute mean **and** SD across the grouping. If the means are flat but the SD changes a
  lot, the story is **volatility/polarization, not level** — and a bar-of-means chart hides
  the entire finding (Q4: thin-review venues have ~equal means but ~2–3× the SD, with a 5★
  pile-up *and* a low tail).
- **Test it, don't eyeball it.** `scipy.stats.levene(a, b, center="median")` for the
  variance difference, `ttest_ind(a, b, equal_var=False)` for the mean. With large n a tiny
  mean gap is "significant" yet meaningless — report the **effect size** (SD ratio, %-extreme)
  alongside the p. (scipy is in the `analysis` extra.)
- **Push back on the framing if the data rejects it.** The original Q4 markdown claimed
  "higher sparse mean → inflation"; the data showed the opposite sign. Fix the narrative,
  don't decorate the wrong one.

## Binning a continuous driver: show the gradient, don't defend a threshold

When asked "2 buckets or 3? which cutoff?", the honest answer is usually **neither — plot
the gradient**:
- Aggregate the metric (e.g. SD) across ~6–7 ordered review-volume buckets and draw it as a
  line per series. A monotonic curve that *flattens* shows there's no magic threshold, and
  reveals where one tier ends (Q4: volatility plateaus ~100 reviews, so "≥20 = well-reviewed"
  is wrong — 20 is still in the steep part).
- If you still need discrete tiers, pick boundaries **where the curve bends** and give them
  honest names (`thin <20` / `moderate 20–99` / `established 100+`), not loaded ones
  ("sparse/well-reviewed"). Single-source them in `analysis.constants` (e.g.
  `REVIEW_VOLUME_TIERS`).
- Shade the tiers behind the gradient line with `fig.add_vrect(x0=..., x1=...,
  fillcolor=..., opacity=0.06, line_width=0, annotation_text=...)` to tie the two views
  together.

## Audit which signals actually vary before charting them (Q7)

When a question is "does X affect <quality/completeness>?", don't chart the first columns
you have — **measure each candidate's spread across the grouping first**:
- Compute the metric for each candidate signal in each group (e.g. center vs periphery) and
  rank by gap/ratio. Drop the ones that are **saturated or flat** — they carry no signal and
  pad the chart (Q7: photos are ~90% non-empty and phone ~84% present *everywhere*, so both
  are useless as completeness signals; websites 71%→50%, cuisine 48%→37%, listings and
  review volume are the real discriminators).
- Saying *why* a flat signal was dropped is itself a finding — put it in the caption
  ("photos/phones are saturated everywhere, so they carry no location signal").
- Beware signals your own pipeline created. Q7 excludes coordinates because Tripadvisor's
  were enriched downstream — they'd measure the pipeline, not the platform.

## "Quantity over space": colour-by-metric grid, not a point-density heatmap

A `px.density_map` shows where points *are*, not how a metric varies — two density maps of
"all venues" vs "richest venues" look nearly identical and answer nothing. To map a **rate
or score** over space, aggregate to a grid and colour by the metric:
```python
g = df.assign(glat=(df.lat / 0.009).round() * 0.009, glon=(df.lon / 0.013).round() * 0.013)
cell = g.groupby(["glat", "glon"], as_index=False).agg(n=("flag", "size"), rate=("flag", "mean"))
cell = cell[cell.n >= 4]                      # drop noisy near-empty cells
px.scatter_map(cell, lat="glat", lon="glon", color="rate", size="n",
               color_continuous_scale="RdYlGn", map_style="open-street-map", ...)
```
~0.009° lat / 0.013° lon ≈ 1 km at Milan's latitude. Map PNGs need basemap tiles at render
time — kaleido fetches them during `nbconvert`; in a standalone prototype use
`dangerouslyDisableSandbox` for the fetch.

**Colormap on a basemap — avoid the tiles' own colours.** OSM tiles already use green
(parks), red/orange (roads), blue (water) and grey (urban), so a green→red scale (`RdYlGn`)
fights the map and a *diverging* scale (`RdBu`) washes out its pale midpoint into the light
background — mid-value cells vanish. Use a high-saturation **sequential** scale whose hues
are absent from tiles: `Plotly3` (blue→magenta) and `Plasma` (purple→yellow) both read
cleanly; verified by rendering each and eyeballing. Also size markers by **count = how many
rows back the cell** (reliability), not by the metric — colour already encodes the metric,
and double-encoding hides the sample size. Shrink `size_max` (e.g. 15) so the dense centre
is a readable grid, not one blob.

## Composite "score" map + per-component grid of small maps (Q7)

When a metric is itself a **mean of several present-flags** (the report's
`quality_assessment` completeness = mean of per-field coverage), don't map just one field —
map the **composite** and then a **grid of the components** so the reader sees what drives it.

- **Composite per venue:** `geo["completeness"] = geo[[flag1, flag2, …]].mean(axis=1)`, then
  the same grid-cell recipe colours by `mean(completeness)`. Audit each candidate flag's
  group gap *first* and keep only the ones that vary — Q7 kept website/cuisine/on-TA/on-TF
  (gaps +12/+11/+10/+5) and dropped Google photos/phone/reviews (saturated, gap ≈0).
- **Per-component grid = real map subplots** (verified, plotly 6.8): `make_subplots` with
  `specs=[[{"type":"map"},…]]`, add a `go.Scattermap` per panel (px can't target a subplot),
  and crucially give **every** subplot its own map config or only the first renders:
  ```python
  _mk = dict(style="open-street-map", center=CENTER, zoom=10.6)
  figG.update_layout(map=_mk, map2=_mk, map3=_mk, map4=_mk)   # map, map2, map3, … per panel
  ```
  Show one shared colourbar (`showscale=(i==0)`, `colorbar=dict(x=1.02)`) and size markers by
  cell count, not the rate. Zoom out the small panels (~10.6) vs the headline map (~11.4).
- **Zoom the headline map in.** The default Milan view (zoom ~10.8, center 9.19) wastes frame
  on hinterland; `zoom=11.4, center={"lat":45.464,"lon":9.190}` fills it with the comune.

## Continuous "rate surface" that covers the whole area: per-venue Nadaraya–Watson, low mask

The histogram2d-then-`gaussian_filter` surface (an earlier Q7 fix) clips to the dense core
because the support mask (`_Ns > 1.5`) drops sparse peripheries — so northern quartieri
(Niguarda, Bicocca, Greco, Affori, Comasina) that *do* show on the cell map vanish.

- **Misdiagnosis (don't repeat):** thinking the surface needs "per-venue instead of
  aggregated" data — the histogram surface is already per-venue. The coverage limiter is the
  **mask threshold and bandwidth**, not aggregation.
- **Fix:** an explicit per-venue Gaussian kernel (Nadaraya–Watson) makes the bandwidth and
  support mask first-class. Loop a Gaussian over every venue for the **rate**, and a separate
  hard radius for a **footprint mask** — then mask where the *local venue count* is real, not
  on a fraction of the smoothed weight:
  ```python
  for i in range(len(lat)):
      w = np.exp(-0.5*(((gl-lat[i])/bw_lat)**2 + ((go-lon[i])/bw_lon)**2)); W += w; WY += w*y[i]
      N += (((gl-lat[i])/r_lat)**2 + ((go-lon[i])/r_lon)**2) <= 1.0   # ~550 m hard radius
  rate = (100*WY/np.maximum(W,1e-9)).reshape(LA.shape)
  m = N.reshape(LA.shape) >= 4        # render where ≥4 venues sit within ~550 m
  ```
  ~600 m bandwidth (`bw_lat≈0.006, bw_lon≈0.0082`) + a fine grid (≈0.002°) reads as smooth.
- **Don't mask on `W > W.max()*frac`** (a fraction of peak smoothed weight). It is
  density-relative, so it over-extends from the dense centre and the wash **bleeds into
  empty neighbouring municipalities** — the user will (rightly) ask "did we filter to the
  city?". A local-count footprint mask (`N >= k` within a fixed radius) is density-invariant:
  it hugs the actual venue footprint, keeps sparse-but-real quartieri, and drops empty
  hinterland. (The data was already city-filtered; only the *smoothing* bled.)
- **Make continuous surfaces more transparent than cell maps** — `opacity≈0.40` (vs ~0.62 for
  cells) so basemap street/label context survives under the wash; marker `size≈13` closes the
  grid gaps into a continuous sheet.

## Dumbbell for a two-group comparison across several metrics

Cleaner than grouped bars when comparing two groups (center/periphery, before/after) on
several signals: one row per signal, a grey connector, two coloured dots. Sort rows by value
so the eye reads the gaps. `go.Scatter` lines + two marker traces; widen the left margin for
the labels (`margin=dict(l=150)`).

## On-figure storytelling captions

Users often want a narrative paragraph drawn **on the image** (survives PNG export,
unlike a markdown cell). Recipe that has worked well:

```python
fig.add_annotation(
    xref="paper", yref="paper", x=0.97, y=0.95, xanchor="right", yanchor="top",
    align="left", showarrow=False, borderpad=8, borderwidth=1, bordercolor="#CED4DA",
    bgcolor="rgba(255,255,255,0.88)", font=dict(size=12, color="#343A40"),
    text=("<b>Headline.</b><br>Line two with the key numbers …<br>Line three."),
)
```

Guidelines:
- **Place it in the empty corner.** Histogram (mass on the left) → top-right.
  Cumulative/rising curve → bottom-right. Tall bars filling the height → add
  y-axis headroom (`range=[0, max*1.25]`) and put it top-left over the shortest bar.
- **Make the numbers data-driven**, not hard-coded, so they stay correct when data
  changes: pull from the result frame (e.g. the ROLLUP total row via
  `df.loc[df["restaurants"].idxmax()]`, or a lookup on a reshaped band table).
- Manual line breaks with `<br>`; `<b>`/`<i>` work in kaleido. Unicode `★ ≤ ≥ −`
  render fine in the default font (verified).
- Keep it 3–5 lines. If a caption needs a paragraph to explain the *encoding*, the
  encoding is probably wrong — fix the chart instead (see mean vs median).

## Mean vs median (skewed magnitude metrics)

For non-negative, right-skewed quantities with a heavy tail (e.g.
`|rating difference|`, spreads, counts), the **mean is dragged up by outliers**.
Push back on "just show the mean":
- **Median** = the better single "typical" value.
- **Mean** still carries signal — it's exactly what the extreme cases move.
- **Best: show both.** Bars = median, a diamond marker = mean. The gap between them
  *is* the skew, made visible — and it removes the need for a caption apologising
  that "the bar is only the mean".
  ```python
  fig.add_bar(x=xs, y=d["median_abs_diff"], name="median (typical gap)")
  fig.add_scatter(x=xs, y=d["mean_abs_diff"], mode="markers", name="mean (pulled up by outliers)",
                  marker=dict(symbol="diamond", size=13))
  ```
- Axis label: keep it plain (`"rating difference (stars)"`), not `mean |…|` clutter.

## Brand / platform logos as axis labels

Replacing text tick labels with brand logos (Google, Tripadvisor, TheFork) reads
much better. Verified approach:

- **Acquire** (network is sandboxed; use `dangerouslyDisableSandbox` for fetches):
  - Wikimedia Commons is reachable and reliable. Resolve a real thumbnail URL via
    the API (`action=query&prop=imageinfo&iiurlwidth=256`, even for SVG → PNG) —
    don't guess file paths. Clearbit/most other CDNs fail DNS in the sandbox.
  - If Wikimedia only has a wordmark (e.g. TheFork) and you need an icon-only mark,
    a company's GitHub org avatar is a clean square icon
    (`https://avatars.githubusercontent.com/u/<id>?s=280`). Ask the user for the URL
    if unsure — they may hand you the exact one.
- **Normalise** so all logos render the SAME visible size: trim each to its alpha
  bounding box and pad to a square. Different internal padding is why one logo looks
  smaller under `sizing="contain"`.
  ```python
  from PIL import Image  # project dep: pillow
  im = Image.open(path).convert("RGBA")
  c = im.crop(im.split()[3].getbbox())         # trim transparent margin
  w, h = c.size; s = max(w, h)
  sq = Image.new("RGBA", (s, s), (0, 0, 0, 0))
  sq.paste(c, ((s - w) // 2, (s - h) // 2), c)  # pad to square, keep aspect
  sq.save(path)
  ```
- **Embed** as base64 data URIs (self-contained for HTML export; no PIL needed at
  render time):
  ```python
  src = "data:image/png;base64," + base64.b64encode(Path(p).read_bytes()).decode()
  fig.add_layout_image(dict(source=src, xref="x", yref="paper",
      x=i, y=-0.04, sizex=0.26, sizey=0.13,
      xanchor="center", yanchor="top", sizing="contain", layer="above"))
  fig.update_xaxes(showticklabels=False)        # hide the text ticks
  fig.update_layout(margin=dict(b=130))          # room below for logos
  ```
- **For pairs** (two logos under one bar): offset `x ± 0.16` and centre a small
  `"vs"` annotation at the logos' vertical midpoint
  (logos span paper-y −0.04→−0.17 ⇒ put `"vs"` at `y=-0.105, yanchor="middle"`).
- Save the cleaned logos under `assets/logos/` for reuse; resolve the dir by walking
  up from CWD so it works from `notebooks/` or repo root.
- **Series identified by colour/legend (e.g. a line per platform), not by x-axis:** drop
  the legend (`showlegend=False`) and drop a logo at the **end of each line** instead —
  `add_layout_image(xref="x", yref="y", x=<last x + a bit>, y=<last value>,
  xanchor="center", yanchor="middle", sizing="contain")`, then widen the right margin and
  extend the x-range to make room. Cleaner than a colour legend and keeps the brand cue.
- Factor the helper (`logo_uri`, `add_xaxis_logos`) into the notebook's **setup cell** so
  every chart shares one definition instead of redefining it per cell.

## House style (this project's charts)

- Primary bar/line colour `#4C6EF5`; dark accent `#1B3A6B`; `template="plotly_white"`.
- Star ratings: `ticksuffix="★"`. Percentages: `ticksuffix="%"`.
- Caption box: `bgcolor="rgba(255,255,255,0.88)"`, `bordercolor="#CED4DA"`,
  `borderpad=8`, `font size 12 color #343A40`.
- Default static size is set once in the setup cell (1050×620). Pillow is a project
  dependency (used for logo trimming); the notebook itself loads logos via base64.
