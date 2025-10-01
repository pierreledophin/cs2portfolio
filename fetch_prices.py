import os, time, requests, yaml, csv
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API = "https://csfloat.com/api/v1/listings"
API_KEY = os.environ.get("CSFLOAT_API_KEY")
if not API_KEY:
    raise SystemExit("Missing CSFLOAT_API_KEY")
HEADERS = {"Authorization": API_KEY}

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
CSV_PATH = DATA_DIR / "price_history.csv"
HOLDINGS_PATH = DATA_DIR / "holdings.csv"

def load_items():
    items = set()
    # 1) prendre les items que tu détiens vraiment
    if HOLDINGS_PATH.exists():
        with open(HOLDINGS_PATH, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                name = (row.get("market_hash_name") or "").strip()
                if name:
                    items.add(name)
    # 2) si rien en holdings, on retombe sur items.yaml (optionnel)
    if not items and Path("items.yaml").exists():
        with open("items.yaml", "r", encoding="utf-8") as f:
            items.update(yaml.safe_load(f)["items"])
    return sorted(items)

def lowest_price_cents(market_hash_name: str) -> int | None:
    params = {"market_hash_name": market_hash_name, "sort_by": "lowest_price", "limit": 1}
    r = requests.get(API, headers=HEADERS, params=params, timeout=20)
    if r.status_code == 429:
        time.sleep(3)
        r = requests.get(API, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    return int(data[0]["price"])

def ensure_csv_header():
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts_utc","market_hash_name","price_cents","price_usd"])

def run_once():
    ensure_csv_header()
    items = load_items()
    if not items:
        print("No items found in holdings.csv or items.yaml")
        return
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for name in items:
        try:
            cents = lowest_price_cents(name)
            if cents is not None:
                usd = f"{cents/100:.2f}"
                rows.append([ts, name, cents, usd])
                print(f"[OK] {name}: {usd} USD")
            else:
                print(f"[NO LISTING] {name}")
        except Exception as e:
            print(f"[ERROR] {name}: {e}")
    if rows:
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)

if __name__ == "__main__":
    run_once()
