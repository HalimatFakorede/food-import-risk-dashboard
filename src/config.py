from pathlib import Path

# PROJECT ROOT
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# DATA FOLDERS
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

# Ensure folders exist
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# AOSTAT BULK DOWNLOAD LINKS
PRODUCTION_ZIP_URL = (
    "https://fenixservices.fao.org/faostat/static/bulkdownloads/"
    "Production_Crops_Livestock_E_All_Data_(Normalized).zip"
)

TRADE_ZIP_URL = (
    "https://bulks-faostat.fao.org/production/"
    "Trade_CropsLivestock_E_All_Data_(Normalized).zip"
)

# Commodities
COMMODITIES = [
    "Rice, paddy (rice milled equivalent)",
    "Wheat",
    "Maize (corn)"
]

# Year range
START_YEAR = 2000
END_YEAR = 2100 
