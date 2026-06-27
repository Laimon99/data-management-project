---
name: plotly-chart-fixes
description: Battle-tested fixes for Plotly static-image (kaleido/PNG) charts in this project's notebooks — diagnosing "broken" charts, adding on-figure storytelling captions, choosing mean vs median, and placing platform/brand logos as axis labels. Use when a Plotly figure renders wrong (bars look horizontal, faint, squashed, axis stretched), when asked to add a narrative caption onto a chart, when a notebook cell raises an error on run, or when polishing the Q1–Q11 research-questions charts. Pairs with the `plotly` and `data-visualization` skills.
version: 1.0
license: MIT
---

# Plotly Chart Fixes (static PNG notebooks)

Concrete, verified fixes from real debugging sessions on
`notebooks/research_questions_analysis.ipynb`. This notebook renders Plotly as
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
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/research_questions_analysis.ipynb
# then extract a cell's image: json.load -> cells[i].outputs[*].data['image/png'] -> base64decode -> Read
```

Prereqs for this notebook: ClickHouse must be up and loaded
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

## House style (this project's charts)

- Primary bar/line colour `#4C6EF5`; dark accent `#1B3A6B`; `template="plotly_white"`.
- Star ratings: `ticksuffix="★"`. Percentages: `ticksuffix="%"`.
- Caption box: `bgcolor="rgba(255,255,255,0.88)"`, `bordercolor="#CED4DA"`,
  `borderpad=8`, `font size 12 color #343A40`.
- Default static size is set once in the setup cell (1050×620). Pillow is a project
  dependency (used for logo trimming); the notebook itself loads logos via base64.
