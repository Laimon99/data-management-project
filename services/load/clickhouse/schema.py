"""DDL for the four flat ClickHouse tables.

Each table uses ``MergeTree`` with the natural key as ``ORDER BY``. The loader
issues ``CREATE TABLE IF NOT EXISTS`` (idempotent) followed by ``TRUNCATE``
(full-reload semantics) on every run.

All tables live in the ``{db}`` database; the DDL strings use a ``{db}``
placeholder that the loader fills in from settings.
"""

INTEGRATED_DDL = """\
CREATE TABLE IF NOT EXISTS {db}.restaurants_integrated
(
    integrated_restaurant_id  String,
    -- Source join keys (enable JOINs back to cleaned tables)
    google_place_id           String,
    tripadvisor_source_url    String,
    thefork_source_id         String,
    -- Identity / geography (authoritative from Google seed)
    canonical_name            String,
    canonical_address         String,
    canonical_street          String,
    canonical_house_number    String,
    canonical_postal_code     String,
    canonical_city            String,
    latitude                  Float64,
    longitude                 Float64,
    coordinate_source         String,
    -- Platform membership
    has_google                UInt8,
    has_tripadvisor           UInt8,
    has_thefork               UInt8,
    has_all_three_platforms   UInt8,
    platform_count            UInt8,
    -- Comparable ratings (deliberately NOT resolved — kept separate for analysis)
    google_rating_5           Nullable(Float64),
    tripadvisor_rating_5      Nullable(Float64),
    thefork_rating_raw_10     Nullable(Float64),
    thefork_rating_5          Nullable(Float64),
    rating_platform_count     UInt8,
    rating_avg_5              Nullable(Float64),
    rating_range_5            Nullable(Float64),
    -- Comparable review counts
    google_review_count       Nullable(Int64),
    tripadvisor_review_count  Nullable(Int64),
    thefork_review_count      Nullable(Int64),
    -- Top-level contact / price (coerced to flat Strings)
    website                   String,
    website_source            String,
    website_match_status      String,
    phone_match_status        String,
    price_level               String,
    price_level_source        String,
    -- Audit
    integration_flags         Array(String),
    updated_at                DateTime
)
ENGINE = MergeTree
ORDER BY integrated_restaurant_id
"""

CLEAN_GOOGLE_DDL = """\
CREATE TABLE IF NOT EXISTS {db}.restaurants_clean_google
(
    place_id          String,
    name              String,
    latitude          Nullable(Float64),
    longitude         Nullable(Float64),
    address           String,
    street            String,
    house_number      String,
    postal_code       String,
    locality          String,
    province          String,
    country           String,
    city              String,
    city_out_of_area  UInt8,
    rating            Nullable(Float64),
    review_count      Nullable(Int64),
    has_rating        UInt8,
    low_review        UInt8,
    primary_type      String,
    types             Array(String),
    category_tier     String,
    is_dining         UInt8,
    is_operational    UInt8,
    business_status   String,
    photo_count       Int64,
    price_level       String,
    has_website       UInt8,
    has_phone         UInt8,
    website           String,
    phone             String,
    flags             Array(String)
)
ENGINE = MergeTree
ORDER BY place_id
"""

CLEAN_TRIPADVISOR_DDL = """\
CREATE TABLE IF NOT EXISTS {db}.restaurants_clean_tripadvisor
(
    source_url        String,
    ta_location_id    String,
    restaurant_name   String,
    rating            Nullable(Float64),
    total_review      Nullable(Int64),
    address           String,
    street            String,
    house_number      String,
    postal_code       String,
    city              String,
    latitude          Nullable(Float64),
    longitude         Nullable(Float64),
    has_coordinates   UInt8,
    photo_count       Nullable(Int64),
    price_band        String,
    price_tier_level  Nullable(Int64),
    cuisines          Array(String),
    has_rating        UInt8,
    has_review_count  UInt8,
    low_review        UInt8,
    has_address       UInt8,
    has_reviews       UInt8,
    has_hours         UInt8,
    has_phone         UInt8,
    has_website       UInt8,
    has_email         UInt8,
    website           String,
    phone             String,
    email             String,
    flags             Array(String)
)
ENGINE = MergeTree
ORDER BY source_url
"""

CLEAN_THEFORK_DDL = """\
CREATE TABLE IF NOT EXISTS {db}.restaurants_clean_thefork
(
    source_id               String,
    source                  String,
    tf_id                   String,
    restaurant_url          String,
    restaurant_name         String,
    latitude                Nullable(Float64),
    longitude               Nullable(Float64),
    address                 String,
    street                  String,
    house_number            String,
    postal_code             String,
    city                    String,
    rating                  Nullable(Float64),
    review_count            Nullable(Int64),
    has_rating              UInt8,
    has_review_count        UInt8,
    low_review              UInt8,
    avg_price_eur           Nullable(Int64),
    discount_pct            Nullable(Int64),
    has_discount            UInt8,
    cuisines                Array(String),
    dietary_options         Array(String),
    has_hours               UInt8,
    photo_count             Nullable(Int64),
    has_reviews             UInt8,
    sample_size             Int64,
    sample_avg_rating       Nullable(Float64),
    rating_sample_divergent UInt8,
    flags                   Array(String)
)
ENGINE = MergeTree
ORDER BY source_id
"""
