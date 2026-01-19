import numpy as np
import pandas as pd

def simulate_import_shock(latest_base: pd.DataFrame, shock_pct: float = 0.20) -> pd.DataFrame:
    """
    Simulate an import shock using apparent_consumption and import_qty.

    - We only shock the portion of imports that could realistically contribute to consumption.
      So imports_used = min(import_qty, apparent_consumption)

    Outputs added for clarity:
    - imports_used, imports_shocked, shortfall_abs
    - idr_shocked_raw (before clipping), idr_shocked (clipped)
    - flag_imports_exceed_consumption, flag_idr_over_1
    """
    df = latest_base.copy()

    # Validate shock range
    if not (0 <= shock_pct <= 1):
        raise ValueError("shock_pct must be between 0 and 1")

    # Required columns
    required = ["apparent_consumption", "import_qty"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Clean numeric inputs
    df["apparent_consumption"] = pd.to_numeric(df["apparent_consumption"], errors="coerce").fillna(0).clip(lower=0)
    df["import_qty"] = pd.to_numeric(df["import_qty"], errors="coerce").fillna(0).clip(lower=0)

    C = df["apparent_consumption"]
    imp = df["import_qty"]

    # Flag weird data situations
    df["flag_imports_exceed_consumption"] = imp.gt(C)

    # Only imports that can be "inside" consumption
    df["imports_used"] = np.minimum(imp, C)

    # Imports after shock (only used portion is shocked)
    df["imports_shocked"] = df["imports_used"] * (1 - shock_pct)

    # Consumption after shock
    df["consumption_shocked"] = (C - shock_pct * df["imports_used"]).clip(lower=0)

    # Shortfall (absolute + percent)
    df["shortfall_abs"] = (C - df["consumption_shocked"]).clip(lower=0)
    df["shortfall_pct"] = np.where(C > 0, df["shortfall_abs"] / C, np.nan)

    # Import dependency after shock (raw,  clipped)
    df["idr_shocked_raw"] = np.where(
        df["consumption_shocked"] > 0,
        df["imports_shocked"] / df["consumption_shocked"],
        np.nan
    )

    df["flag_idr_over_1"] = df["idr_shocked_raw"].gt(1)

    df["idr_shocked"] = df["idr_shocked_raw"].clip(0, 1)

    return df
