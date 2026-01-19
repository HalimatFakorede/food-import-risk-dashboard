import streamlit as st
import pandas as pd
import requests
import altair as alt

API = st.secrets.get("API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="Food Import Risk Dashboard", layout="wide")
st.title("Food Import Risk Dashboard")
st.caption("Explore import-shock shortfalls and risk scores by country & commodity.")


# Helpers
@st.cache_data(ttl=60)
def get_json(url: str):
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        st.warning("API is waking up. Please wait a few seconds and refresh.")
        return {}

@st.cache_data(ttl=60)
def get_commodities():
    data = get_json(f"{API}/meta/commodities")
    return data.get("commodities", [])

@st.cache_data(ttl=60)
def get_cached_shocks():
    return get_json(f"{API}/meta/shocks_cached")

def fmt_millions(x):
    try:
        return round(float(x) / 1_000_000, 2)
    except Exception:
        return None


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
    if df.empty:
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

    shocks = get_cached_shocks().get("shocks")
    if not shocks:
        shocks = [0.2, 0.35, 0.5]


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
    commodity = st.selectbox("Commodity", commodities)

    n = st.slider("Top N results", 5, 200, 20, 5)


# Data loader
def load_top(shock_pct: float) -> pd.DataFrame:
    if mode.startswith("Cached"):
        url = f"{API}/risk/top_cached?n={n}&shock_pct={shock_pct}"
    else:
        url = f"{API}/risk/top?n={n}&shock_pct={shock_pct}"

    if commodity != "All":
        url += f"&commodity={requests.utils.quote(commodity)}"

    payload = get_json(url)
    df = pd.DataFrame(payload.get("records", []))

    # Keep note for display
    note = payload.get("note", "")
    return df, note


# Load data
df_a, note_a = load_top(shock_a)
df_a = apply_region(df_a, region)

df_b, note_b = (pd.DataFrame(), "")
if compare_mode and shock_b is not None:
    df_b, note_b = load_top(shock_b)
    df_b = apply_region(df_b, region)


# Top metrics
c1, c2, c3 = st.columns(3)
if shock_a is not None:
    c1.metric("Shock %", f"{shock_a:.2f}")
else:
    c1.metric("Shock %", "—")
c2.metric("Commodity", commodity)
c3.metric("Records returned", len(df_a))


# Compare mode
if compare_mode:
    st.subheader(f"Shock Comparison: {shock_a:.0%} → {shock_b:.0%}")
    st.caption("This compares the same country+commodity under two shocks.")
    if note_a:
        st.write(note_a)

    if df_a.empty or df_b.empty:
        st.warning("No records to compare. Try a different region/commodity/shock.")
    else:
        # Merge on country + commodity
        df = df_a.merge(df_b, on=["country", "commodity"], suffixes=("_a", "_b"))

        # numeric
        df["shortfall_abs_a"] = pd.to_numeric(df.get("shortfall_abs_a"), errors="coerce")
        df["shortfall_abs_b"] = pd.to_numeric(df.get("shortfall_abs_b"), errors="coerce")

        df["shortfall_diff_m"] = ((df["shortfall_abs_b"] - df["shortfall_abs_a"]) / 1_000_000).round(2)

        df_view = df[[
            "country", "commodity",
            "shortfall_diff_m",
            "risk_band_b"
        ]].sort_values("shortfall_diff_m", ascending=False)

        st.dataframe(df_view, use_container_width=True)

        # Chart
        chart = (
            alt.Chart(df_view)
            .mark_bar()
            .encode(
                x=alt.X("shortfall_diff_m:Q", title="Change in shortfall (million tonnes)"),
                y=alt.Y("country:N", sort="-x"),
                color=alt.Color("risk_band_b:N", title="risk_band (shock B)"),
                tooltip=["country", "commodity", "shortfall_diff_m", "risk_band_b"]
            )
            .properties(height=420)
        )
        st.altair_chart(chart, use_container_width=True)

    # Country Drilldown
    st.divider()
    st.caption("Detailed risk profile for the selected country across commodities.")
    st.subheader("Country Drilldown")

    # Use countries that exist in df_a
    countries = sorted(df_a["country"].dropna().unique().tolist()) if not df_a.empty else []
    if len(countries) == 0:
        st.info("No country names available for drilldown.")
    else:
        country_selected = st.selectbox("Select a country", countries)

        country_url = f"{API}/risk/country/{requests.utils.quote(country_selected)}"
        country_payload = get_json(country_url)
        country_df = pd.DataFrame(country_payload.get("records", []))

        if country_df.empty:
            st.info("No drilldown records returned for this country.")
        else:
            country_cols = [
                "country", "commodity",
                "risk_score", "risk_band",
                "mean_idr", "prod_vol_norm", "import_vol_norm",
                "year", "apparent_consumption",
                "import_dependency_ratio",
                "shortfall_pct", "shortfall_abs",
                "consumption_shocked"
            ]
            country_cols = [c for c in country_cols if c in country_df.columns]
            st.dataframe(country_df[country_cols], use_container_width=True)

    # Download
    if not df_a.empty:
        st.download_button(
            "Download CSV (shock A results)",
            df_a.to_csv(index=False).encode("utf-8"),
            file_name=f"top_{'cached' if mode.startswith('Cached') else 'live'}_shock_{int(shock_a*100)}_{commodity}.csv",
            mime="text/csv",
        )


# Single mode-
else:
    st.subheader("Countries Most Exposed to Import Shocks")
    st.caption("Countries ranked by absolute food shortfall under the selected import shock.")
    if note_a:
        st.write(note_a)

    if df_a.empty:
        st.warning("No records returned. Try increasing Top N or choosing a different commodity/shock.")
    else:
        df = df_a.copy()

        # numeric
        df["shortfall_abs"] = pd.to_numeric(df.get("shortfall_abs"), errors="coerce")
        df["shortfall_abs_m"] = (df["shortfall_abs"] / 1_000_000).round(2)

        # clean table
        df_view = df[[
            "country", "commodity",
            "shortfall_abs_m", "shortfall_pct",
            "risk_score", "risk_band",
            "import_dependency_ratio",
            "year"
        ]].copy()

        st.dataframe(df_view, use_container_width=True)

        # chart aggregated by country
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

    # Country Drilldown (single mode)
    st.divider()
    st.caption("Detailed risk profile for the selected country across commodities.")
    st.subheader("Country Drilldown")

    countries = sorted(df_a["country"].dropna().unique().tolist()) if not df_a.empty else []
    if len(countries) == 0:
        st.info("No country names available for drilldown.")
    else:
        country_selected = st.selectbox("Select a country", countries)

        country_url = f"{API}/risk/country/{requests.utils.quote(country_selected)}"
        country_payload = get_json(country_url)
        country_df = pd.DataFrame(country_payload.get("records", []))

        if country_df.empty:
            st.info("No drilldown records returned for this country.")
        else:
            country_cols = [
                "country", "commodity",
                "risk_score", "risk_band",
                "mean_idr", "prod_vol_norm", "import_vol_norm",
                "year", "apparent_consumption",
                "import_dependency_ratio",
                "shortfall_pct", "shortfall_abs",
                "consumption_shocked"
            ]
            country_cols = [c for c in country_cols if c in country_df.columns]
            st.dataframe(country_df[country_cols], use_container_width=True)

    # Download
    if not df_a.empty:
        st.download_button(
            "Download CSV",
            df_a.to_csv(index=False).encode("utf-8"),
            file_name=f"top_{'cached' if mode.startswith('Cached') else 'live'}_shock_{int(shock_a*100)}_{commodity}.csv",
            mime="text/csv",
        )
