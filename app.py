import streamlit as st
import pandas as pd
import requests
import altair as alt

API = st.secrets.get("API_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="Food Import Risk Dashboard", layout="wide")
st.title("Food Import Risk Dashboard")
st.caption("Explore import-shock shortfalls and risk scores by country & commodity.")
st.caption(f"API in use: {API}")


# Helpers
@st.cache_data(ttl=60)
def get_json(url: str):
    """
    Safe GET JSON helper.
    - Returns dict on success
    - Returns {} on any failure (so app won't crash)
    """
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException:
        return {}

def api_ok() -> bool:
    health = get_json(f"{API}/health")
    return bool(health)

API_IS_OK = api_ok()
if not API_IS_OK:
    st.warning("API is waking up (free hosting). Wait ~20–60 seconds and refresh.")

@st.cache_data(ttl=300)
def get_commodities():
    data = get_json(f"{API}/meta/commodities")
    return data.get("commodities", [])

@st.cache_data(ttl=300)
def get_cached_shocks():
    data = get_json(f"{API}/meta/shocks_cached")
    return data.get("shocks", [])

def safe_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default


# Region lists
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


# Sidebar controls
with st.sidebar:
    st.header("Controls")

    mode = st.radio("Mode", ["Cached (fast)", "Live (any shock)"], horizontal=True)
    region = st.selectbox("Region filter", ["All", "Africa", "EU"])
    compare_mode = st.checkbox("Compare two shocks")

    # Shocks
    shocks = get_cached_shocks()
    if not shocks:
        shocks = [0.1, 0.2, 0.35, 0.5]

    shock_a = st.selectbox(
        "Shock %",
        shocks,
        index=shocks.index(0.35) if 0.35 in shocks else 0
    )

    shock_b = None
    if compare_mode:
        choices = [s for s in shocks if s != shock_a]
        shock_b = st.selectbox("Compare with", choices)

    commodities = ["All"] + get_commodities()
    if len(commodities) == 1:  # only "All"
        # API likely sleeping or /meta/commodities failing temporarily
        st.info("Commodities loading… (refresh in a bit)")
    commodity = st.selectbox("Commodity", commodities)

    n = st.slider("Top N results", 5, 200, 20, 5)


# Data loader 
def load_top(shock_pct: float) -> tuple[pd.DataFrame, str]:
    """
    Loads top results.
    If cached endpoint is missing on deployed API, fallback to /risk/top.
    """
    shock_pct = safe_float(shock_pct, 0.35)

    # Build preferred URL
    if mode.startswith("Cached"):
        url_primary = f"{API}/risk/top_cached?n={n}&shock_pct={shock_pct}"
        url_fallback = f"{API}/risk/top?n={n}&shock_pct={shock_pct}"
    else:
        url_primary = f"{API}/risk/top?n={n}&shock_pct={shock_pct}"
        url_fallback = None

    if commodity != "All":
        q = requests.utils.quote(commodity)
        url_primary += f"&commodity={q}"
        if url_fallback:
            url_fallback += f"&commodity={q}"

    # Try primary first
    payload = get_json(url_primary)

    # If primary failed (empty), try fallback
    if not payload and url_fallback:
        payload = get_json(url_fallback)
        if payload:
            payload["note"] = (payload.get("note", "") + " (Cached endpoint not available on this deployment; using live.)").strip()

    records = payload.get("records", [])
    note = payload.get("note", "")

    return pd.DataFrame(records), note


# Load data
df_a, note_a = load_top(shock_a)
df_a = apply_region(df_a, region)

df_b, note_b = (pd.DataFrame(), "")
if compare_mode and shock_b is not None:
    df_b, note_b = load_top(shock_b)
    df_b = apply_region(df_b, region)


# Top metrics
c1, c2, c3 = st.columns(3)
c1.metric("Shock %", f"{float(shock_a):.2f}")
c2.metric("Commodity", commodity)
c3.metric("Records returned", len(df_a))


# Compare mode
if compare_mode:
    st.subheader(f"Shock Comparison: {shock_a:.0%} → {shock_b:.0%}")
    st.caption("This compares the same country + commodity under two shocks.")
    if note_a:
        st.write(note_a)

    if df_a.empty or df_b.empty:
        st.error("No records to compare. This usually means the API call failed (or is still waking up). Refresh in ~30–60s.")
    else:
        # Merge on country + commodity
        if "country" not in df_a.columns or "commodity" not in df_a.columns:
            st.error("Unexpected API response (missing country/commodity fields).")
        else:
            df = df_a.merge(df_b, on=["country", "commodity"], suffixes=("_a", "_b"))

            df["shortfall_abs_a"] = pd.to_numeric(df.get("shortfall_abs_a"), errors="coerce")
            df["shortfall_abs_b"] = pd.to_numeric(df.get("shortfall_abs_b"), errors="coerce")

            df["shortfall_diff_m"] = ((df["shortfall_abs_b"] - df["shortfall_abs_a"]) / 1_000_000).round(2)

            # prefer risk band from shock B if exists, else from A
            risk_col = "risk_band_b" if "risk_band_b" in df.columns else ("risk_band_a" if "risk_band_a" in df.columns else None)

            view_cols = ["country", "commodity", "shortfall_diff_m"] + ([risk_col] if risk_col else [])
            df_view = df[view_cols].sort_values("shortfall_diff_m", ascending=False)

            st.dataframe(df_view, use_container_width=True)

            color_enc = alt.Color(risk_col + ":N") if risk_col else alt.value("steelblue")

            chart = (
                alt.Chart(df_view)
                .mark_bar()
                .encode(
                    x=alt.X("shortfall_diff_m:Q", title="Change in shortfall (million tonnes)"),
                    y=alt.Y("country:N", sort="-x"),
                    color=color_enc,
                    tooltip=df_view.columns.tolist()
                )
                .properties(height=420)
            )
            st.altair_chart(chart, use_container_width=True)

    # Drilldown
    st.divider()
    st.subheader("Country Drilldown")
    st.caption("Pick a country from the current results and see risk by commodity.")

    countries = sorted(df_a["country"].dropna().unique().tolist()) if (not df_a.empty and "country" in df_a.columns) else []
    if not countries:
        st.info("No country names available for drilldown (API still waking up or returned no records).")
    else:
        country_selected = st.selectbox("Select a country", countries)
        country_payload = get_json(f"{API}/risk/country/{requests.utils.quote(country_selected)}")
        country_df = pd.DataFrame(country_payload.get("records", []))

        if country_df.empty:
            st.info("No drilldown records returned for this country.")
        else:
            keep = [
                "country", "commodity",
                "risk_score", "risk_band",
                "mean_idr", "prod_vol_norm", "import_vol_norm",
                "year", "apparent_consumption",
                "import_dependency_ratio",
                "shortfall_pct", "shortfall_abs",
                "consumption_shocked"
            ]
            keep = [c for c in keep if c in country_df.columns]
            st.dataframe(country_df[keep], use_container_width=True)

    # Download
    if not df_a.empty:
        st.download_button(
            "Download CSV (shock A results)",
            df_a.to_csv(index=False).encode("utf-8"),
            file_name=f"top_shock_{int(float(shock_a)*100)}_{commodity}.csv",
            mime="text/csv",
        )


# Single mode
else:
    st.subheader("Countries Most Exposed to Import Shocks")
    st.caption("Countries ranked by absolute food shortfall under the selected import shock.")
    if note_a:
        st.write(note_a)

    if df_a.empty:
        st.error("No records returned. API may be waking up. Refresh in ~30–60s.")
    else:
        df = df_a.copy()

        if "shortfall_abs" in df.columns:
            df["shortfall_abs"] = pd.to_numeric(df["shortfall_abs"], errors="coerce")
            df["shortfall_abs_m"] = (df["shortfall_abs"] / 1_000_000).round(2)
        else:
            df["shortfall_abs_m"] = None

        view_cols = [
            "country", "commodity",
            "shortfall_abs_m", "shortfall_pct",
            "risk_score", "risk_band",
            "import_dependency_ratio",
            "year"
        ]
        view_cols = [c for c in view_cols if c in df.columns]
        df_view = df[view_cols].copy()

        st.dataframe(df_view, use_container_width=True)

        if "country" in df_view.columns and "risk_band" in df_view.columns:
            chart_df = (
                df_view
                .groupby(["country", "risk_band"], as_index=False)
                .agg(shortfall_abs_m=("shortfall_abs_m", "sum"))
                .sort_values("shortfall_abs_m", ascending=False)
            )

            risk_color = alt.Color(
                "risk_band:N",
                scale=alt.Scale(
                    domain=["Low", "Medium", "High"],
                    range=["#2ecc71", "#f1c40f", "#e74c3c"]
                ),
                title="risk_band"
            )

            chart = (
                alt.Chart(chart_df)
                .mark_bar()
                .encode(
                    x=alt.X("shortfall_abs_m:Q", title="Shortfall (million tonnes)"),
                    y=alt.Y("country:N", sort="-x"),
                    color=risk_color,
                    tooltip=["country", "shortfall_abs_m", "risk_band"]
                )
                .properties(height=420)
            )
            st.altair_chart(chart, use_container_width=True)

            st.caption(
                "Bars show total food shortfall under the selected import shock. "
                "Longer bars indicate higher exposure to external supply disruptions."
            )

    # Drilldown
    st.divider()
    st.subheader("Country Drilldown")
    st.caption("Pick a country from the current results and see risk by commodity.")

    countries = sorted(df_a["country"].dropna().unique().tolist()) if (not df_a.empty and "country" in df_a.columns) else []
    if not countries:
        st.info("No country names available for drilldown (API still waking up or returned no records).")
    else:
        country_selected = st.selectbox("Select a country", countries)
        country_payload = get_json(f"{API}/risk/country/{requests.utils.quote(country_selected)}")
        country_df = pd.DataFrame(country_payload.get("records", []))

        if country_df.empty:
            st.info("No drilldown records returned for this country.")
        else:
            keep = [
                "country", "commodity",
                "risk_score", "risk_band",
                "mean_idr", "prod_vol_norm", "import_vol_norm",
                "year", "apparent_consumption",
                "import_dependency_ratio",
                "shortfall_pct", "shortfall_abs",
                "consumption_shocked"
            ]
            keep = [c for c in keep if c in country_df.columns]
            st.dataframe(country_df[keep], use_container_width=True)

    # Download
    if not df_a.empty:
        st.download_button(
            "Download CSV",
            df_a.to_csv(index=False).encode("utf-8"),
            file_name=f"top_shock_{int(float(shock_a)*100)}_{commodity}.csv",
            mime="text/csv",
        )
