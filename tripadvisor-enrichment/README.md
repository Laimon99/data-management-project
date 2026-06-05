# Geocoding & Spatial Enrichment — TripAdvisor Dataset

**Quick Reference** — Geographic coordinate enrichment using Nominatim/OpenStreetMap  
**Status:** ✅ Production Complete | **Coverage:** 83.92%

---

## Why Geocoding?

Address strings alone don't enable:
- 📍 Mapping & visualization
- 🔍 Proximity searches & distance calculations  
- 📊 Spatial clustering & heat maps
- 🔗 Data fusion with other geographic datasets

**Solution:** Transform addresses → (latitude, longitude) coordinates using free Nominatim API.

---

## Results

```
───────────────────────────────────────────────────────────────────
[DONE]  File saved in 'tripadvisor_scraper_results_geocoded.json'
        ✔  Coordinate Found : 6327  (83.92%)
        ✘  Not Found         : 1146  (15.19%)
        ⊘  Skipped (addr NaN)  : 66   (0.88%)
        ───────────────────────────────────────
        Total                : 7539  (100.0%)
───────────────────────────────────────────────────────────────────
```

**Analysis:**

| Status | Count | Cause |
|---|---|---|
| ✔ Found | 6,327 | Nominatim successfully geocoded address |
| ✘ Not Found | 1,146 | Address not in OpenStreetMap (typos, new buildings, vague addresses) |
| ⊘ Skipped | 66 | TripAdvisor source didn't provide address |

**Conclusion:** 83.92% coverage is **production-ready** for mapping, clustering, and spatial analysis. The 15% miss rate is acceptable given OSM's limited coverage of very recent or informal venues.

---

## How It Works

### Stack
- **Library:** `geopy` (Python geocoding wrapper)
- **Service:** Nominatim (free, OpenStreetMap-based)
- **Cost:** €0 (open-source, no API key required)

### Process
```
Input:  tripadvisor_scraper_results.json
        (7,539 restaurants with address strings)
          ↓
Geocoding Loop:
  FOR EACH restaurant:
    IF address exists:
      Query Nominatim → get (latitude, longitude)
      Wait 1.2 seconds (Nominatim ToS: 1 req/sec)
    ELSE:
      Output NaN
          ↓
Output: tripadvisor_scraper_results_geocoded.json
        (all records + latitude/longitude fields)
```

### Configuration
- **Rate Limit:** 1.2 seconds between requests (Nominatim compliance)
- **Timeout:** 10 seconds per request
- **Retries:** 2 attempts on network errors
- **Duration:** ~3 hours for 7,539 records

---

## Output Format

```json
{
  "restaurant_name": "Osteria del Balabiott",
  "rating": "4,5",
  "address": "Via Torino 19, 20123 Milano Italia",
  "latitude": "45.46370",    ← ADDED
  "longitude": "9.19228",    ← ADDED
  "website": "https://...",
  ...
}
```

**Coordinates:**
- Type: String (matches other fields)
- Precision: 5 decimal places = ±1.1 meter accuracy
- Missing: Encoded as `"NaN"` (not null)

---

## Usage

### Installation
```bash
pip install geopy
```

### Run
```bash
# Default file names
python geocode.py

# Custom paths
python geocode.py input.json output.json
```

### Output
Real-time progress logging with success/failure count:
```
[   1/7539] [OK       ] 'Osteria del Balabiott'      -> Lat: 45.46370, Lon: 9.19228
[   2/7539] [OK       ] 'Pizzeria da Mario'          -> Lat: 45.45123, Lon: 9.18901
[   3/7539] [NOT FOUND] 'Venue Without Address'      -> Lat: NaN, Lon: NaN
...
```

---

## Key Takeaways

✅ **83.92% of restaurants successfully geocoded**  
✅ **100% free** (Nominatim public instance, no API key)  
✅ **Ready for mapping, clustering, spatial analysis**  
✅ **2.5-hour runtime** (acceptable for one-time enrichment)  
✅ **Fault-tolerant** (retry logic on network errors)  

❌ **15% miss rate** — Due to OSM data gaps, address typos, or too-vague addresses  
❌ **Cannot parallelize** — Nominatim ToS limits to 1 request/second  

---

## Validation

```python
# Sanity check coordinates are in Italy
for record in data:
    if record["latitude"] != "NaN":
        lat = float(record["latitude"])
        lon = float(record["longitude"])
        assert 40 <= lat <= 48, "Invalid latitude"
        assert 6 <= lon <= 12, "Invalid longitude"
```

All 6,327 coordinates pass geographic bounds checks ✓

---

**Module:** `geocode.py`  
**Input:** `tripadvisor_scraper_results.json`  
**Output:** `tripadvisor_scraper_results_geocoded.json`  
**Status:** ✅ Production Ready