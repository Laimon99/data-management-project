"""Shared setup for the per-question analysis notebooks.

Each ``notebooks/qNN_*.ipynb`` starts with a single ``from analysis.notebook import *``
cell. This module centralises everything those notebooks share: the third-party
imports (numpy/pandas/plotly/scipy), the query/geo/constants helpers from the
``analysis`` package, the read-only ClickHouse ``client`` plus ``run``/``publish``
helpers, the house palette and the brand-logo helpers — and it configures the static
PNG renderer so charts render in VS Code, GitHub's notebook viewer and exported HTML.

Importing this module opens the ClickHouse connection (clear error if unreachable),
mirroring the old all-in-one setup cell.
"""

from __future__ import annotations

import base64
import os
import pathlib

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from scipy import stats

from analysis import queries
from analysis.config import AnalysisSettings, clickhouse_client
from analysis.constants import CENTER_RADIUS_KM, REVIEW_VOLUME_TIERS, SPARSE_REVIEW_THRESHOLD
from analysis.export import to_csv, to_latex
from analysis.geo import assign_neighbourhood, classify_center_periphery, distance_to_duomo_km

# Static PNG by default so charts render everywhere: VS Code, GitHub's notebook
# viewer (which strips JavaScript, so interactive Plotly never shows there), and
# the exported HTML. Set DATAMAN_PLOTLY_RENDERER=notebook_connected for interactive HTML.
pio.renderers.default = os.environ.get("DATAMAN_PLOTLY_RENDERER", "png")
# Bigger, higher-DPI static images so the charts are readable.
_png = pio.renderers["png"]
_png.width, _png.height, _png.scale = 1050, 620, 1
pd.set_option("display.max_columns", None)

# Shared palettes (kept consistent across charts).
PLATFORM_COLORS = {"google": "#4C6EF5", "tripadvisor": "#E8590C", "thefork": "#2F9E44"}

# Platform logos (assets/logos/, embedded as data URIs). Resolve from CWD up so it works
# from notebooks/ or the repo root; shared by every chart that shows platforms.
LOGO_DIR = next((b / "assets" / "logos" for b in [pathlib.Path.cwd(), *pathlib.Path.cwd().parents]
                 if (b / "assets" / "logos" / "google.png").exists()), None)


def logo_uri(name):
    return "data:image/png;base64," + base64.b64encode((LOGO_DIR / f"{name}.png").read_bytes()).decode()


def add_xaxis_logos(fig, platforms, y=-0.05, size=0.16):
    """Replace a categorical platform x-axis's tick labels with brand logos (in order)."""
    fig.update_xaxes(showticklabels=False)
    for i, name in enumerate(platforms):
        fig.add_layout_image(dict(source=logo_uri(name), xref="x", yref="paper",
            x=i, y=y, sizex=size, sizey=0.11, xanchor="center", yanchor="top",
            sizing="contain", layer="above"))
    fig.update_layout(margin=dict(b=95))


settings = AnalysisSettings()
client = clickhouse_client(settings)  # clear error if ClickHouse is unreachable


def run(sql: str) -> pd.DataFrame:
    """Execute a read-only SELECT and return a pandas DataFrame."""
    return client.query_df(sql)


def publish(df: pd.DataFrame, name: str, caption: str) -> pd.DataFrame:
    """Export a result table to CSV + LaTeX under report/final/tables/ and return it."""
    to_csv(df, name)
    to_latex(df, name, caption=caption, label=f"tab:{name}")
    return df


print(f"Connected to ClickHouse db='{settings.clickhouse_db}' at "
      f"{settings.clickhouse_host}:{settings.clickhouse_port}")

__all__ = [
    # third-party
    "np", "pd", "px", "go", "pio", "stats",
    # analysis package helpers
    "queries", "to_csv", "to_latex",
    "CENTER_RADIUS_KM", "REVIEW_VOLUME_TIERS", "SPARSE_REVIEW_THRESHOLD",
    "assign_neighbourhood", "classify_center_periphery", "distance_to_duomo_km",
    # notebook infrastructure
    "settings", "client", "run", "publish",
    "PLATFORM_COLORS", "LOGO_DIR", "logo_uri", "add_xaxis_logos",
]
