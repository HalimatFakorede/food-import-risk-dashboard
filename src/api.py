from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
import pandas as pd
import numpy as np
from pathlib import Path
from src.simulate import simulate_import_shock
import re

app = FastAPI(title="Food Import Risk API", version="1.0")
print(">>> LOADED src/api.py VERSION = 2026-01-18 A <<<")

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"

RISK_FILE = PROCESSED / "risk_index_latest.parquet"
BASE_FILE = PROCESSED / "base_country_commodity_year.parquet"
SIM_FILE  = PROCESSED / "shock_simulation_latest_importdrop20.parquet"
SIM35_FILE = PROCESSED / "shock_simulation_latest_importdrop35.parquet"

_RISK = None
_BASE = None
_SIM = None


# Helpers
def _load_all():
    global _RISK, _BASE, _SIM

    if _RISK is None or _BASE is None or _SIM is None:
        missing = [p for p in [RISK_FILE, BASE_FILE, SIM_FILE] if not p.exists()]
        if missing:
            raise RuntimeError(f"Missing required files: {[str(m) for m in missing]}")

        _RISK = pd.read_parquet(RISK_FILE)
        _BASE = pd.read_parquet(BASE_FILE)
        _SIM  = pd.read_parquet(SIM_FILE)

    return _RISK, _BASE, _SIM


def _round_floats(records: list[dict], decimals: int = 6) -> list[dict]:
    out = []
    for r in records:
        rr = {}
        for k, v in r.items():
            if isinstance(v, (float, np.floating)) and pd.notna(v):
                rr[k] = round(float(v), decimals)
            else:
                rr[k] = v
        out.append(rr)
    return out


def _country_match(df: pd.DataFrame, country: str) -> pd.DataFrame:
    q = country.strip().lower()

    # exact match first
    exact = df[df["country"].str.lower() == q]
    if not exact.empty:
        return exact.copy()

    # partial match fallback
    contains = df[df["country"].str.lower().str.contains(q, na=False)]
    return contains.copy()


def _add_shortfall_abs(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds absolute shortfall = apparent_consumption - consumption_shocked.
    """
    if "apparent_consumption" in df.columns and "consumption_shocked" in df.columns:
        df["shortfall_abs"] = (
            pd.to_numeric(df["apparent_consumption"], errors="coerce").fillna(0)
            - pd.to_numeric(df["consumption_shocked"], errors="coerce").fillna(0)
        ).clip(lower=0)
    return df

def _shock_to_cached_file(shock_pct: float) -> Path:
    """
    Map shock_pct (0.35) -> shock_simulation_latest_importdrop35.parquet
    Only allows shocks that are actually cached.
    """
    k = int(round(shock_pct * 100)) 
    path = PROCESSED / f"shock_simulation_latest_importdrop{k}.parquet"

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"No cached file for shock_pct={shock_pct}. "
                f"Available cached shocks: /meta/shocks_cached . "
                f"Use /risk/top (live) for non-cached shocks."
            ),
        )
    return path


# Country filters for removing special areas or duplicates
_DROP_COUNTRY_SUBSTRINGS = [
    ", mainland",
    "Taiwan Province of",
    "(Kingdom of the)",
]

def _filter_special_areas(df: pd.DataFrame) -> pd.DataFrame:
    if "country" not in df.columns:
        return df
    out = df.copy()
    mask = pd.Series(False, index=out.index)
    for s in _DROP_COUNTRY_SUBSTRINGS:
        mask = mask | out["country"].str.contains(s, case=False, na=False)
    return out.loc[~mask].copy()


# Request model
class SimulationRequest(BaseModel):
    country: str = Field(..., description="Country name as in FAOSTAT (e.g., Malta)")
    shock_pct: float = Field(0.2, ge=0.0, le=1.0, description="Import shock fraction. 0.2 = 20% drop")


# Routes
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {
        "name": "Food Import Risk API",
        "version": "1.0",
        "docs": "/docs",
        "health": "/health",
        "examples": {
            "country_risk": "/risk/country/Malta",
            "simulate": "POST /risk/simulate  {country:'Malta', shock_pct:0.35}",
            "top": "/risk/top?n=20&shock_pct=0.35",
            "top_wheat": "/risk/top?n=20&shock_pct=0.35&commodity=Wheat",
        },
    }


@app.get("/risk/country/{country}")
def risk_by_country(country: str):
    risk, base, sim = _load_all()

    risk_c = _filter_special_areas(_country_match(risk, country))
    if risk_c.empty:
        raise HTTPException(status_code=404, detail=f"No risk data for country='{country}' (after cleaning)")

    base_c_latest = (
        _filter_special_areas(_country_match(base, country))
        .sort_values("year")
        .groupby(["country", "commodity"], as_index=False)
        .tail(1)
        .copy()
    )

    sim_c = _filter_special_areas(_country_match(sim, country))

    merged = (
        risk_c
        .merge(base_c_latest, on=["country", "commodity"], how="left")
        .merge(
            sim_c[[
                "country", "commodity",
                "shortfall_pct", "consumption_shocked",
                "flag_zero_consumption_after_shock"
            ]],
            on=["country", "commodity"],
            how="left"
        )
    )

    merged = _add_shortfall_abs(merged)

    cols = [
        "country", "commodity",
        "risk_score", "risk_band",
        "mean_idr", "prod_vol_norm", "import_vol_norm",
        "year",
        "production_qty", "import_qty", "export_qty",
        "apparent_consumption", "import_dependency_ratio",
        "shortfall_pct", "shortfall_abs",
        "consumption_shocked", "flag_zero_consumption_after_shock",
    ]
    merged = merged[[c for c in cols if c in merged.columns]].sort_values("risk_score", ascending=False)

    records = _round_floats(merged.to_dict(orient="records"), decimals=6)

    return {
        "country": merged["country"].iloc[0],
        "n_records": int(len(merged)),
        "records": records,
        "note": "shortfall_* / consumption_shocked come from the precomputed 20% import-drop simulation file.",
    }


@app.post("/risk/simulate")
def simulate_risk(req: SimulationRequest):
    risk, base, _sim = _load_all()
    country = req.country.strip()

    base_c = _filter_special_areas(_country_match(base, country))
    if base_c.empty:
        raise HTTPException(status_code=404, detail=f"No base data for country='{country}' (after cleaning)")

    latest_base = (
        base_c.sort_values("year")
              .groupby(["country", "commodity"], as_index=False)
              .tail(1)
              .copy()
    )

    sim = simulate_import_shock(latest_base, shock_pct=req.shock_pct)
    sim["flag_zero_consumption_after_shock"] = sim["consumption_shocked"].eq(0)

    if "shortfall_abs" not in sim.columns:
        sim = _add_shortfall_abs(sim)

    risk_c = _filter_special_areas(_country_match(risk, country))
    if risk_c.empty:
        risk_c = pd.DataFrame(columns=[
            "country", "commodity", "risk_score", "risk_band",
            "mean_idr", "prod_vol_norm", "import_vol_norm"
        ])

    merged = (
        sim.merge(
            risk_c[["country", "commodity", "risk_score", "risk_band", "mean_idr", "prod_vol_norm", "import_vol_norm"]],
            on=["country", "commodity"],
            how="left"
        )
    ).sort_values(["shortfall_abs", "risk_score"], ascending=[False, False])

    cols = [
        "country", "commodity",
        "risk_score", "risk_band",
        "mean_idr", "prod_vol_norm", "import_vol_norm",
        "year",
        "production_qty", "import_qty", "export_qty",
        "apparent_consumption", "import_dependency_ratio",
        "shortfall_pct", "shortfall_abs",
        "consumption_shocked", "idr_shocked",
        "flag_zero_consumption_after_shock",
    ]
    merged = merged[[c for c in cols if c in merged.columns]]

    records = _round_floats(merged.to_dict(orient="records"), decimals=6)

    return {
        "country": country,
        "shock_pct": round(float(req.shock_pct), 6),
        "n_records": int(len(records)),
        "records": records,
        "note": "This simulation is computed live from latest base-year data per commodity.",
    }


@app.get("/risk/top")
def top_risk(
    n: int = Query(20, ge=1, le=200),
    shock_pct: float = Query(0.20, ge=0.0, le=1.0),
    commodity: str | None = Query(default=None)
):
    print(">>> RUNNING NEW /risk/top (shock ranking by ABS shortfall) <<<")

    risk, base, _ = _load_all()

    latest_base = (
        base.sort_values("year")
            .groupby(["country", "commodity"], as_index=False)
            .tail(1)
            .copy()
    )

    if commodity:
        latest_base = latest_base[latest_base["commodity"].str.lower() == commodity.lower()].copy()
        risk = risk[risk["commodity"].str.lower() == commodity.lower()].copy()

    # clean before checking empties
    latest_base = _filter_special_areas(latest_base)
    risk = _filter_special_areas(risk)

    if latest_base.empty or risk.empty:
        raise HTTPException(status_code=404, detail="No rows match your filters after cleaning.")

    sim_live = simulate_import_shock(latest_base, shock_pct=shock_pct)
    sim_live["flag_zero_consumption_after_shock"] = sim_live["consumption_shocked"].eq(0)

    # Keep sim shortfall_abs if simulate.py provides it, else compute
    if "shortfall_abs" not in sim_live.columns:
        sim_live = _add_shortfall_abs(sim_live)

    sim_keep = [
        "country", "commodity",
        "shortfall_pct", "shortfall_abs",
        "consumption_shocked", "idr_shocked",
        "flag_zero_consumption_after_shock"
    ]

    merged = (
        risk.merge(latest_base, on=["country", "commodity"], how="inner")
            .merge(sim_live[sim_keep], on=["country", "commodity"], how="left")
    )

    # absolute loss first
    merged = merged.sort_values(
        ["shortfall_abs", "risk_score", "apparent_consumption"],
        ascending=[False, False, False]
    ).head(n)

    cols = [
        "country", "commodity",
        "risk_score", "risk_band",
        "mean_idr", "prod_vol_norm", "import_vol_norm",
        "year",
        "production_qty", "import_qty", "export_qty",
        "apparent_consumption", "import_dependency_ratio",
        "shortfall_pct", "shortfall_abs",
        "consumption_shocked", "idr_shocked",
        "flag_zero_consumption_after_shock"
    ]
    merged = merged[[c for c in cols if c in merged.columns]]

    records = _round_floats(merged.to_dict(orient="records"), decimals=6)

    return {
        "handler": "NEW_SHOCK_TOP_v2_ABS",
        "shock_pct": round(float(shock_pct), 6),
        "commodity": commodity,
        "n_records": int(len(records)),
        "records": records,
        "note": "Ranked by shortfall_abs DESC, then risk_score DESC, then apparent_consumption DESC (simulation computed live)."
    }


@app.get("/risk/top_cached")
def top_risk_cached(
    n: int = Query(20, ge=1, le=200),
    shock_pct: float = Query(0.35, ge=0.0, le=1.0),
    commodity: str | None = Query(default=None),
):
    """
    Cached ranking endpoint.
    Loads precomputed parquet for the requested shock_pct (must exist).
    Supports optional commodity filter.
    """
    cached_path = _shock_to_cached_file(shock_pct)

    df = pd.read_parquet(cached_path)

    # commodity filter
    if commodity:
        df = df[df["commodity"].str.lower() == commodity.lower()].copy()

    if df.empty:
        raise HTTPException(status_code=404, detail="No rows match your filters.")

    # ensure special areas filtered out
    df = _filter_special_areas(df)

    # Ensure shortfall_abs exists
    df = _add_shortfall_abs(df)

    # Sort absolute loss first
    df = df.sort_values(
        ["shortfall_abs", "risk_score", "apparent_consumption"],
        ascending=[False, False, False],
    ).head(n)

    cols = [
        "country", "commodity",
        "risk_score", "risk_band",
        "mean_idr", "prod_vol_norm", "import_vol_norm",
        "year",
        "production_qty", "import_qty", "export_qty",
        "apparent_consumption", "import_dependency_ratio",
        "shortfall_pct", "shortfall_abs",
        "consumption_shocked", "idr_shocked",
        "flag_zero_consumption_after_shock",
    ]
    df = df[[c for c in cols if c in df.columns]]

    records = _round_floats(df.to_dict(orient="records"), decimals=6)

    return {
        "handler": "CACHED_TOP_v2_AUTO",
        "shock_pct": round(float(shock_pct), 6),
        "commodity": commodity,
        "n_records": int(len(records)),
        "records": records,
        "note": f"Loaded from cached file: {cached_path.name} (precomputed).",
    }


@app.get("/meta/commodities")
def list_commodities():
    risk, _, _ = _load_all()
    items = sorted(risk["commodity"].dropna().unique().tolist())
    return {"n": len(items), "commodities": items}


@app.get("/meta/countries")
def list_countries(q: str | None = None):
    risk, _, _ = _load_all()
    countries = risk["country"].dropna().unique().tolist()

    # hide special areas in search results
    countries_df = pd.DataFrame({"country": countries})
    countries_df = _filter_special_areas(countries_df)
    countries = countries_df["country"].tolist()

    if q:
        ql = q.strip().lower()
        countries = [c for c in countries if ql in c.lower()]

    countries = sorted(countries)
    return {"n": len(countries), "countries": countries[:200]}


@app.get("/meta/shocks_cached")
def list_cached_shocks():
    """
    Lists which precomputed shock parquet files exist in /data/processed.
    Example files:
      shock_simulation_latest_importdrop10.parquet
      shock_simulation_latest_importdrop35.parquet
    """
    pattern = re.compile(r"shock_simulation_latest_importdrop(\d+)\.parquet$")

    files = []
    shocks = []

    for p in PROCESSED.glob("shock_simulation_latest_importdrop*.parquet"):
        m = pattern.search(p.name)
        if not m:
            continue
        k = int(m.group(1))          
        shocks.append(k / 100.0)   
        files.append(p.name)

    # sort by shock size
    shocks_sorted = sorted(shocks)
    files_sorted = sorted(files, key=lambda name: int(pattern.search(name).group(1)))

    return {
        "n": len(shocks_sorted),
        "shocks": shocks_sorted,
        "files": files_sorted
    }