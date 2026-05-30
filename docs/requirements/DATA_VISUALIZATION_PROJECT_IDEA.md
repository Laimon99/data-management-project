# Data Visualization Project Ideas  
## Restaurant Ratings – Multi-Platform Dataset

This document proposes **three independent data visualization projects** built on the **same integrated dataset** of restaurant ratings (Google Maps, Tripadvisor, TheFork).

Each project:
- answers a **different research question**
- targets a **different audience**
- emphasizes **different visualization strategies**
- is suitable as an **individual assignment**

---

## Shared Dataset (Context)

The dataset integrates:
- restaurant identity (name, address)
- geographic coordinates (latitude, longitude)
- ratings and review counts from:
  - Google Maps
  - Tripadvisor
  - TheFork

Entity resolution is handled upstream (LLM-based matching), so each project works on a **clean, unified table**.

---

# Project A — *Do rating platforms agree?*

## Research Question
**How consistent are restaurant ratings across different platforms?**

## Narrative Angle
Users often assume ratings are interchangeable across platforms.  
This project challenges that assumption by showing **systematic differences and disagreements**.

## Key Analyses
- Rating differences per restaurant:
  - Google vs Tripadvisor
  - Google vs TheFork
  - Tripadvisor vs TheFork
- Distribution of rating gaps
- Identification of:
  - high-consensus restaurants
  - high-disagreement restaurants

## Suggested Visualizations
- Scatter plots (platform vs platform)
- Difference distributions (histograms / density plots)
- Slope charts for selected restaurants
- Small multiples comparing platforms

## Visualization Focus
- Comparison
- Visual integrity (aligned scales)
- Avoiding misleading axes

## Audience
General users / food consumers

---

# Project B — *Where ratings diverge: a geographic perspective*

## Research Question
**Are rating discrepancies spatially distributed across the city?**

## Narrative Angle
Ratings are not only subjective — they may also reflect **local biases**, tourism density, or neighborhood dynamics.

## Key Analyses
- Average rating per area (per platform)
- Spatial clusters of disagreement
- Areas where:
  - Google ratings are systematically higher/lower
  - Tripadvisor dominates perception

## Suggested Visualizations
- Interactive maps (points or hexbin)
- Heatmaps of rating differences
- Side-by-side small maps (one per platform)
- Spatial clustering overlays

## Visualization Focus
- Map projections awareness
- Geographic uncertainty
- Color scale consistency

## Audience
Urban analysts / city planners / data-curious readers

---

# Project C — *Trust and popularity: the role of review volume*

## Research Question
**How does the number of reviews influence perceived rating reliability?**

## Narrative Angle
A 4.8 rating with 20 reviews does not mean the same as a 4.3 rating with 3,000 reviews.  
This project explores **confidence, popularity, and bias**.

## Key Analyses
- Rating vs number of reviews
- Platform-specific review volume distributions
- Identification of:
  - high-rating / low-review restaurants
  - stable high-confidence restaurants

## Suggested Visualizations
- Bubble charts (rating × reviews)
- Log-scaled scatter plots
- Confidence bands
- Annotated outliers

## Visualization Focus
- Communicating uncertainty
- Avoiding over-precision
- Humanizing numbers

## Audience
Data-literate users / analysts / reviewers

---

## Data Quality & Transparency (Common Section)

All projects explicitly address:
- missing ratings (`NULL` values)
- unmatched restaurants
- platform coverage imbalance
- uncertainty in entity matching

Suggested practices:
- annotations
- captions explaining data limits
- visual cues for missing data

---

## Tools & Implementation

Recommended tools (non-exclusive):
- Datawrapper
- Flourish
- Tableau Public
- RAWGraphs (for SVG-based charts)
- QGIS (for spatial analysis)

Static or interactive outputs are both acceptable, as long as:
- the narrative is clear
- chart choices are justified
- visual hierarchy is respected
