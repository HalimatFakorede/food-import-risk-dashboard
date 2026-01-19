import streamlit as st
import pandas as pd
import requests
import altair as alt
from io import BytesIO

st.set_page_config(page_title="Food Import Risk Dashboard", layout="wide")
st.title("Food Import Risk Dashboard")
st.caption("Explore import-shock shortfalls and risk scores by country & commodity.")
st.caption("Data source: GitHub Releases (parquet files)")


# GitHub Release file URLs
RISK_URL = "https://github.com/HalimatFakorede/food-import-risk-dashboard/releases/download/v1.0-data/risk_index_latest.parquet"

SHOCK_URLS = {
    0.10: "https://github.com/HalimatFakorede/food-import-risk-dashboard/releases/download/v1.0-data/shock_simulation_latest_importdrop10.parquet",
    0.20: "https://github.com/HalimatFakorede/food-import-risk-dashboard/releases/download/v1.0-data/shock_simulation_latest_importdrop20.parquet",
    0.35: "https://github.com/HalimatFakorede/food-import-risk-dashboard/releases/download/v1.0-data/shock_simulation_latest_importdrop35.parquet",
    0.50: "https://github.com/HalimatFakorede/food-import-risk-dashboard/releases/download/v1.0-data/shock_simulation_latest_importdrop50.parquet",
}


# Helpers
@st.cache_data(ttl=24 * 3600, show_spinner=True)
def load_parquet(url: str) -> pd.DataFrame:
    """
    Download parquet over HTTP and load into pandas.
    Cached in Streamlit so it won't re-download constantly.
    """
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return pd.read_parquet(BytesIO(r.content))


def add_shortfall_abs(df: pd.DataFrame) -> pd.DataFrame:
    if "shortfall_abs" not in df.columns:
        if "apparent_consumption" in df.columns and "consumption_shocked" in df.columns:
            df["shortfall_abs"] = (
                pd.to_numeric(df["apparent_consumption"], errors="coerce").fillna(0)
                - pd.to_numeric(df["consumption_shocked"], errors="coerce").fillna(0)
            ).clip(lower=0)
    return df


def safe_num(s):
    return pd.to_numeric(s, errors="coerce")


# Load core data
with st.spinner("Loading risk index..."):
    risk = load_parquet(RISK_URL)

# Region lists (simple)
AFRICA = {
    "Nigeria","Egypt","Algeria","Morocco","Tunisia","Kenya","Ethiopia",
    "Ghana","Senegal","South Africa"
}
EU = {
    "Germany","France","Italy","Spain","Netherlands","Belgium",
    "Poland","Portugal","Greece","Austria","Sweden","Finland"
}

def apply_region(df: pd.DataFrame, region: str) -> pd.DataFrame:
    if df.empty or "country" not in df.columns:
        return df
    if region == "Africa":
        return df[df["country"].isin(AFRICA)].copy()
    if region == "EU":
        return df[df["country"].isin(EU)].copy()
    return df

# Commodities from risk index
all_commodities = sorted(risk["commodity"].dropna().unique().tolist())


# Sidebar controls
with st.sidebar:
    st.header("Controls")

    region = st.selectbox("Region filter", ["All", "Africa", "EU"])

    compare_mode = st.checkbox("Compare two shocks")

    shocks = sorted(list(SHOCK_URLS.keys()))

    shock_a = st.selectbox(
        "Shock %",
        shocks,
        index=shocks.index(0.35) if 0.35 in shocks else 0
    )

    shock_b = None
    if compare_mode:
        choices = [s for s in shocks if s != shock_a]
        shock_b = st.selectbox("Compare with", choices)

    commodities = ["All"] + all_commodities
    commodity = st.selectbox("Commodity", commodities, index=0)

    n = st.slider("Top N results", 5, 200, 20, 5)


# Load shock parquet
def load_shock_df(shock_pct: float) -> pd.DataFrame:
    url = SHOCK_URLS[shock_pct]
    df = load_parquet(url)
    df = add_shortfall_abs(df)
    return df

with st.spinner("Loading shock simulation file(s)..."):
    sim_a = load_shock_df(shock_a)

sim_b = pd.DataFrame()
if compare_mode and shock_b is not None:
    with st.spinner("Loading comparison shock file..."):
        sim_b = load_shock_df(shock_b)


# Build top table function
def build_top(sim_df: pd.DataFrame) -> pd.DataFrame:
    # Merge risk score into simulation rows
    df = sim_df.merge(
        risk[["country", "commodity", "risk_score", "risk_band"]],
        on=["country", "commodity"],
        how="left"
    )

    # Filters
    df = apply_region(df, region)

    if commodity != "All":
        df = df[df["commodity"].str.lower() == commodity.lower()].copy()

    # Ensure numeric
    for col in ["shortfall_abs", "shortfall_pct", "risk_score", "import_dependency_ratio", "apparent_consumption"]:
        if col in df.columns:
            df[col] = safe_num(df[col])

    # ✅ SAFE SORT (only use columns that exist)
    sort_cols = [c for c in ["shortfall_abs", "risk_score", "apparent_consumption"] if c in df.columns]
    if not sort_cols:
        # If somehow none exist, just return empty (better than crashing)
        return pd.DataFrame()

    df = df.sort_values(
        sort_cols,
        ascending=[False] * len(sort_cols),
        na_position="last"
    ).head(n)

    # Shortfall in millions (only if shortfall_abs exists)
    if "shortfall_abs" in df.columns:
        df["shortfall_abs_m"] = (safe_num(df["shortfall_abs"]) / 1_000_000).round(2)
    else:
        df["shortfall_abs_m"] = None

    # Table columns
    preferred = [
        "country", "commodity",
        "shortfall_abs_m", "shortfall_pct",
        "risk_score", "risk_band",
        "import_dependency_ratio",
        "year"
    ]
    preferred = [c for c in preferred if c in df.columns]
    return df[preferred].copy()


df_a = build_top(sim_a)


# Top metrics
c1, c2, c3 = st.columns(3)
c1.metric("Shock %", f"{shock_a:.0%}")
c2.metric("Commodity", commodity)
c3.metric("Records returned", len(df_a))


# Compare mode
if compare_mode:
    st.subheader(f"Shock Comparison: {shock_a:.0%} → {shock_b:.0%}")
    st.caption("Positive values = larger shortfall under shock B.")

    if df_a.empty or sim_b.empty:
        st.warning("No records to compare. Try a different region/commodity/shock.")
    else:
        df_b_top = build_top(sim_b)

        merged = df_a.merge(
            df_b_top,
            on=["country", "commodity"],
            suffixes=("_a", "_b"),
            how="inner"
        )

        if merged.empty:
            st.warning("No overlapping country+commodity pairs found for comparison.")
        else:
            merged["shortfall_diff_m"] = (
                safe_num(merged.get("shortfall_abs_m_b")) - safe_num(merged.get("shortfall_abs_m_a"))
            ).round(2)

            view = merged[
                [c for c in [
                    "country", "commodity",
                    "shortfall_abs_m_a", "shortfall_abs_m_b",
                    "shortfall_diff_m",
                    "risk_band_b"
                ] if c in merged.columns]
            ].sort_values("shortfall_diff_m", ascending=False)

            st.dataframe(view, use_container_width=True)

            chart = (
                alt.Chart(view)
                .mark_bar()
                .encode(
                    x=alt.X("shortfall_diff_m:Q", title="Change in shortfall (million tonnes)"),
                    y=alt.Y("country:N", sort="-x"),
                    color=alt.Color("risk_band_b:N", title="Risk band (shock B)"),
                    tooltip=[c for c in ["country", "commodity", "shortfall_diff_m", "risk_band_b"] if c in view.columns]
                )
                .properties(height=420)
            )
            st.altair_chart(chart, use_container_width=True)

    st.divider()


# Single shock view & chart
st.subheader("Countries Most Exposed to Import Shocks")
st.caption("Countries ranked by absolute food shortfall under the selected import shock.")

if df_a.empty:
    st.warning("No records returned. Try increasing Top N or choosing a different commodity/shock.")
else:
    st.dataframe(df_a, use_container_width=True)

    # Chart (only if needed columns exist)
    if "risk_band" in df_a.columns and "shortfall_abs_m" in df_a.columns:
        chart_df = (
            df_a.groupby(["country", "risk_band"], as_index=False)
                .agg(shortfall_abs_m=("shortfall_abs_m", "sum"))
                .sort_values("shortfall_abs_m", ascending=False)
        )

        chart = (
            alt.Chart(chart_df)
            .mark_bar()
            .encode(
                x=alt.X("shortfall_abs_m:Q", title="Shortfall (million tonnes)"),
                y=alt.Y("country:N", sort="-x"),
                color=alt.Color("risk_band:N", title="Risk band"),
                tooltip=["country", "shortfall_abs_m", "risk_band"]
            )
            .properties(height=420)
        )
        st.altair_chart(chart, use_container_width=True)


# Country Drilldown
st.divider()
st.subheader("Country Drilldown")
st.caption("Pick a country from the current results and see its risk across commodities.")

countries = sorted(df_a["country"].dropna().unique().tolist()) if not df_a.empty and "country" in df_a.columns else []
if not countries:
    st.info("No country names available for drilldown.")
else:
    country_selected = st.selectbox("Select a country", countries)

    # Filter shock data for selected country
    drill = sim_a[sim_a["country"] == country_selected].copy() if "country" in sim_a.columns else pd.DataFrame()

    # Join risk index
    if not drill.empty:
        drill = drill.merge(
            risk[["country", "commodity", "risk_score", "risk_band"]],
            on=["country", "commodity"],
            how="left"
        )

        drill = add_shortfall_abs(drill)

        # Clean & add shortfall in millions
        if "shortfall_abs" in drill.columns:
            drill["shortfall_abs_m"] = (safe_num(drill["shortfall_abs"]) / 1_000_000).round(2)
        else:
            drill["shortfall_abs_m"] = None

        cols = [
            "country", "commodity",
            "risk_score", "risk_band",
            "import_dependency_ratio",
            "shortfall_pct", "shortfall_abs_m",
            "apparent_consumption",
            "consumption_shocked",
            "year"
        ]
        cols = [c for c in cols if c in drill.columns]

        drill = drill[cols].sort_values(
            [c for c in ["shortfall_abs_m", "risk_score"] if c in drill.columns],
            ascending=[False, False]
        )

        st.dataframe(drill, use_container_width=True)
    else:
        st.info("No drilldown records found for this selection.")


# Download
if not df_a.empty:
    st.download_button(
        "Download CSV (current table)",
        df_a.to_csv(index=False).encode("utf-8"),
        file_name=f"top_shock_{int(shock_a*100)}_{commodity}.csv",
        mime="text/csv",
    )
