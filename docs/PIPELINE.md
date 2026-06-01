# Restaurant Ratings Integration Project

IMPORTANT!!!! THIS IS JUST ROUGH IDEA AND NOT MRD OR REAL IMPLEMENTATION PLAN. ESPECIALLY REGARDING THE ARCHITECTURE AND FLOW. THOSE ARE SUBJECTS TO CHANGE!!!!

## Project Overview

This project aims to **compare restaurant ratings across multiple online platforms** by building a unified dataset that integrates data scraped from:

* **Google Maps** (reference dataset and geographic seed)
* **Tripadvisor**
* **TheFork**

The core objective is to **analyze rating consistency and discrepancies** across platforms by resolving entity matching issues using **LLM-based semantic matching**, while also enabling **geographic analysis** through latitude and longitude coordinates.

---

## High-Level Architecture

```
Google Maps (seed + geo)
        │
        ▼
Restaurant List (name, address, lat, lon)
        │
        ├──► Tripadvisor Scraper
        ├──► TheFork Scraper
        │
        ▼
Platform-specific tables
        │
        ▼
LLM-based Entity Matching
        │
        ▼
Unified Ratings Table (+ geo analysis)
```

---

## Step 1 – Restaurant List Acquisition (Seed)

### Why Google Maps

Google Maps is used as the **reference source** because it provides:

* the **most complete coverage** of restaurants
* consistent availability of **name + address**
* direct access to **geographic coordinates**
* a stable geographic scope (e.g. city-level search)

### Seed Collection Strategy

Restaurants are collected by performing **area-based searches** (e.g. by city zones or neighborhoods).
For each restaurant, the following attributes are extracted directly from the Google Maps page.

### Output

**`restaurants_seed`**

| restaurant_id | name | address | city | latitude | longitude |
| ------------- | ---- | ------- | ---- | -------- | --------- |

This table defines the **universe of restaurants** and serves as the **geographic backbone** of the project.

> Geographic coordinates are extracted directly during the seed scraping phase and are not obtained via external geocoding APIs.

---

## Step 2 – Web Scraping (Per Platform)

For each restaurant in `restaurants_seed`, targeted scraping is performed on:

### Google Maps

* rating
* number of reviews

### Tripadvisor

* rating (when available)
* number of reviews

### TheFork

* rating (when available)
* number of reviews

Each platform generates its **own table**, without assuming perfect name or address matching.

**Tables:**

* `google_maps_reviews`
* `tripadvisor_reviews`
* `thefork_reviews`

| platform_id | scraped_name | scraped_address | rating | review_count |
| ----------- | ------------ | --------------- | ------ | ------------ |

---

## Step 3 – Entity Resolution Problem

Direct joins are **not reliable** because:

* restaurant names differ across platforms
* addresses may be abbreviated or formatted differently
* chains and branches introduce ambiguity

This creates a **classic entity resolution problem**, even when geographic proximity is available.

---

## Step 4 – LLM-Based Matching

Entity resolution is performed using **LLM APIs** (e.g. OpenAI models).

### Matching Logic

For each restaurant in `restaurants_seed`, candidate rows from each platform are compared using:

* name similarity
* address similarity
* geographic proximity (latitude / longitude)
* contextual consistency

The LLM outputs:

* `MATCH`
* `NO MATCH`
* optional confidence score

LLMs are used **only for decision support**, not for data generation.

---

## Step 5 – Unified Dataset Construction

**`restaurants_ratings_final`**

| restaurant_id | name | address | latitude | longitude | google_rating | tripadvisor_rating | thefork_rating |
| ------------- | ---- | ------- | -------- | --------- | ------------- | ------------------ | -------------- |

This table enables:

* cross-platform rating comparison
* statistical analysis of rating divergence
* geographic aggregation (zones, clusters, heatmaps)

---

## Exploratory Data Analysis (EDA)

Exploratory Data Analysis is performed on both **single-source** and **integrated datasets**.

### Single-source EDA

* rating distribution per platform
* distribution of number of reviews
* detection of outliers (very high / low ratings)

### Integrated EDA

* pairwise rating differences between platforms
* variance of ratings per restaurant
* correlation between rating and review count
* geographic visualization of average ratings (heatmaps)

EDA allows identifying **systematic differences** and **platform-specific behaviors**.

---

## Data Quality Assessment & Improvement

Data quality is evaluated and improved after integration.

### Selected Quality Dimensions

#### 1. Completeness

* percentage of missing ratings per platform
* restaurant coverage across platforms

**Improvement actions:**

* preservation of NULL values
* completeness-aware analysis

#### 2. Consistency

* rating divergence across platforms
* identification of conflicting evaluations

**Improvement actions:**

* exclusion of low-confidence matches
* normalization of restaurant identifiers

---

## Methodological Notes

* Google Maps is used **only as a seed and geographic reference**
* Platforms are treated as **independent sources**
* LLMs are used **exclusively for entity resolution**
* Coordinates are not re-geocoded
* Data quality is explicitly measured and improved

---

## Key Concepts Covered

* Web scraping
* Multi-source data integration
* Entity resolution with LLMs
* Exploratory Data Analysis
* Data quality assessment
* Geographic analysis

---

## Possible Extensions

* Geographic clustering of restaurants
* Weighting ratings by review count
* Hybrid rule-based + LLM matching
* Temporal analysis of reviews
