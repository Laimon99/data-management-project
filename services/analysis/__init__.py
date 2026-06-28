"""Read-only analytics layer (pipeline Stage 7).

Helpers backing the per-question analysis notebooks (``notebooks/qNN_*.ipynb``,
each starting with ``from analysis.notebook import *``): ClickHouse connection
settings, geographic classification, sparse-data thresholds, SQL query builders,
and table exporters. This package performs **no** writes to MongoDB or ClickHouse.
"""
