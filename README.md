# Food Import Risk Dashboard

## Why this project exists

Many countries depend on food imports to feed their population.
When imports are disrupted by conflict, climate shocks, or trade restrictions, food supply can drop fast.

This project answers one clear question:

> **If food imports fall, which countries are most exposed, and by how much?**

The dashboard simulates import shocks (10%, 20%, 35%, 50%) and shows how food availability changes across countries and commodities.

This is built for **analysis and understanding**, not predictions.

---

## What the dashboard shows

### 1. Import shock simulation

For each country and commodity, the system uses:

* apparent food consumption
* import volumes
* import dependency

It then simulates what happens when imports fall.

Example:

> A 35% import shock means 35% of imports disappear, not total food supply.

The result is a food shortfall, shown in:

* absolute terms (million tonnes)
* percentage of consumption

---

### 2. Structural risk score

Each country–commodity pair has a risk score (0–1) based on:

* how dependent the country is on imports
* how volatile imports are
* how volatile production is

Risk levels are grouped into:

* **Low**
* **Medium**
* **High**

This helps separate:

* countries that can absorb shocks
* countries that are structurally fragile

---

### 3. Countries most exposed

Countries are ranked by:

* **absolute food shortfall (million tonnes)**

This answers a practical question:

> “Where does the biggest food gap appear if imports fail?”

---

### 4. Country drilldown

You can select a country and see:

* all major food commodities
* risk score per commodity
* import dependency
* how different shocks affect consumption

This makes the dashboard useful for policy thinking, not just charts.

---

### 5. Shock comparison

You can compare two shocks, for example 10% vs 20% or 20% vs 35%.

This shows:

* how fast shortages grow
* which countries deteriorate most quickly

Example insight:

> “At 10%, the system absorbs the shock.
> At 35%, the situation becomes serious.”

---

### 6. Region filters

You can focus on:

* **Africa**
* **EU**
* **All countries**

This supports regional analysis and clear storytelling.

---

## Data sources

* **FAOSTAT** (production, trade, consumption data)
* Latest available global year in the dataset

The data is cleaned and processed into country–commodity snapshots before simulation.

---

## How the dashboard is built

### Data processing

* Food production, imports, and consumption are cleaned and merged
* Import shocks are simulated using clear, transparent rules
* Results are saved as parquet files

These parquet files are published using GitHub Releases and act as the data source.

---

### Dashboard (Streamlit)

* Loads data directly from GitHub Releases
* No backend server required
* Cached to avoid repeated downloads
* Interactive tables and charts
* Shock comparison and region filters
* CSV export for further analysis

This keeps the system simple, fast, and free to deploy.

---

## Project structure

```
app.py        Streamlit dashboard
simulate.py  import shock simulation logic
notebooks/   data preparation and shock generation
assets/      screenshots for this README
```

---

## Run locally

```bash
streamlit run app.py
```

Then open:

```
http://localhost:8501
```

No database or API setup needed.

---

## How to read the results (example)

**Japan – Maize**

* import dependency ≈ 100%
* a 35% import shock removes ~35% of maize supply
* ~5.3 million tonnes shortfall
* **Medium–High risk**

Meaning:

> Japan’s food system works in normal conditions,
> but it is very fragile if imports are disrupted.

---

## Screenshots

### Countries most exposed

Shows countries ranked by food shortfall.

`assets/dashboard_main_table.png`

---

### Exposure under a single shock

Shows how shortfalls are distributed across countries.

`assets/dashboard_exposure_chart.png`

---

### Shock comparison

Shows how shortages increase between two shock levels.

`assets/dashboard_shock_comparison.png`

---

### Country drilldown

Shows commodity-level risk and exposure for one country.

`assets/dashboard_country_drilldown.png`

---

## Why this project matters

Food shocks are already happening.

This project shows:

* where food systems break first
* which countries are most vulnerable
* how quickly risk escalates

It demonstrates how data can be used to understand risks, not just build models.

