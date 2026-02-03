# data-management-project

---

## Project title (WIP)

**Consistency and Quality of Online Restaurant Reviews in the Milan Area**

![Image](https://www.mapaplan.com/travel-map/milan-city-top-tourist-attractions-printable-street-plan-guide/high-resolution/milan-top-tourist-attractions-map-23-best-restaurants-dining-central-district-area-outline-layout-best-locations-visit-high-resolution.jpg)

![Image](https://images.squarespace-cdn.com/content/v1/5876d8d6e3df28c4d83ae377/1753791038525-ZICT8ERD8HT385S6MX4O/milan-milano-italy-brera-centro-storico-ip-03.jpg)

![Image](https://www.explore-italian-culture.com/images/osteria-di-brera-milan.jpg)

![Image](https://www.thetrainline.com/cms/media/5793/empty-seats-at-restaurant-in-milan-italy.jpg?height=440\&mode=crop\&quality=70\&width=660)

---

## 1️⃣ Domain & research questions

### Domain

Online restaurant review platforms provide ratings that strongly influence consumer behavior. However, ratings may differ across platforms due to **data quality issues**, **sampling bias**, or **integration errors**.

The project focuses on restaurants located in **Milan and surrounding municipalities**.

### Main research questions

1. **How consistent are restaurant ratings across different online platforms?**
2. **Which restaurants show the highest disagreement between platforms?**
3. **Is rating inconsistency related to data quality issues** (e.g. number of reviews,, outdated information)?
4. **Can low-quality or sparse data inflate perceived restaurant quality?**

### Secondary questions

* Are certain platforms systematically more optimistic/pessimistic?
* Does inconsistency increase for smaller or less popular restaurants?
* Does geographic location (center vs periphery) affect data completeness?

---

## 2️⃣ Data sources (FAQ 5 – acquisition)

❗❗❗**UP FOR DEBATE** ❗❗❗

### Source A — Google Maps (scraping) - may be hard to scrape, but first source that comes to mind

* **Type**: Web scraping
* **Data**:

  * Restaurant name
  * Address
  * Coordinates (lat/lon)
  * Rating
  * Number of reviews
  * Category (Italian, pizza, sushi…)
* **Why**:

  * High coverage in Milan
  * Rich metadata
* **Tools**:

  * Selenium / Playwright
  * Requests + BeautifulSoup (for lightweight pages)

### Source B — Yelp Fusion API - ❗❗❗❗❗❗ PAID ❗❗❗❗❗❗

* **Type**: Official API
* **Data**:

  * Business name
  * Address
  * Rating
  * Review count
  * Price range
  * Categories
* **Why**:

  * Clean structured API
  * Different user base → meaningful comparison

### (Optional) Source C — TripAdvisor (scraping)

Used only if time allows, as an **additional enrichment** source.

---

## 3️⃣ Data storage & modeling (FAQ 6)

### Database choice


### Core schema (simplified)

**restaurants_raw_google**

* google_id
* name
* address
* lat, lon
* rating
* review_count
* category

**restaurants_raw_yelp**

* yelp_id
* name
* address
* lat, lon
* rating
* review_count
* price_range

**restaurants_integrated**

* unified_restaurant_id
* google_id
* yelp_id
* canonical_name
* canonical_address
* lat, lon
* google_rating
* yelp_rating
* rating_difference
* data_quality_score

### Mandatory queries (examples)

* Restaurants with **rating difference > 1 star**
* Average rating per platform by area
* Correlation between review count and rating variance

---

## 4️⃣ Data profiling & quality assessment 



### Profiling before integration

For each source:

* **Completeness**:

  * % missing addresses
  * % missing coordinates
* **Consistency**:

  * Rating ranges
* **Timeliness** (if available):

  * Last review date

### Profiling after integration

* % restaurants matched successfully
* % ambiguous matches
* % unmatched records

### Data quality dimensions used

* Completeness
* Consistency
* Accuracy (proxy via cross-platform agreement)
* Timeliness
* Uniqueness (duplicates)

---

## 5️⃣ Data integration & enrichment

### Core challenge: entity matching (record linkage)

Restaurants do **not share IDs** → you must resolve them.

### Matching strategy (automated)

1. **Blocking**:

   * Same city
   * Distance < 200 meters
2. **Similarity metrics**:

   * Name similarity (Levenshtein / Jaro-Winkler)
   * Address similarity
3. **Composite matching score**
4. **Threshold-based decision**:

   * Match
   * No match
   * Uncertain

### Measuring integration errors

* False matches
* Missed matches
* Ambiguous matches


---

## 6️⃣ Data quality improvement

Concrete, visible improvements:

* Remove duplicates
* Normalize restaurant names
* Address standardization
* Filter restaurants with too few reviews
* Weighted ratings based on review count

We can show **before vs after**:

* Rating variance
* Number of extreme outliers

---

## 7️⃣ Analysis & results

### Analyses you can present

* Distribution of rating differences
* Platform bias comparison
* Rating stability vs review volume
* Spatial visualization of inconsistent restaurants

### Example insights (expected)

* Restaurants with <20 reviews show higher variance
* Yelp ratings tend to be more conservative
* Peripheral areas have lower data completeness
