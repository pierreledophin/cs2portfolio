import os, time, requests, csv, sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API = "https://csfloat.com/api/v1/listings"
API_KEY = os.environ.get("CSFLOAT_API_KEY")
if not API_KEY:
    print("❌ Missing CSFLOAT_API_KEY (secret GitHub absent ou mal nommé).", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "Authorization": API_KEY,   # pas "Bearer"
    "User-Agent": "cs2-portfolio-csfloat (+contact)",
}

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
CSV_PATH = DATA_DIR / "price_history.csv"
HOLDINGS_PATH = DATA_DIR / "holdings.csv"

def load_items_from_holdings():
    if not HOLDINGS_PATH.exists():
        print("❌ data/holdings.csv introuvable. Attendu: market_hash_name,qty,buy_price_usd,buy_date,notes", file=sys.stderr)
        return []
    with open(HOLDINGS_PATH, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if not r.fieldnames or "market_hash_name" not in r.fieldnames:
            print("❌ En-tête invalide dans holdings.csv.", file=sys.stderr)
            print(f"   Colonnes détectées: {r.fieldnames}", file=sys.stderr)
            print("   Attendu (exact): market_hash_name,qty,buy_price_usd,buy_date,notes", file=sys.stderr)
            return []
        items = []
        for row in r:
            name = (row.get("market_hash_name") or "").strip()
            if name:
                items.append(name)
        return sorted({x for x in items if x})

def parse_listings_json(resp_json):
    # L'API peut retourner {"data":[...]} ou directement [...]
    if isinstance(resp_json, dict):
        lst = resp_json.get("data", [])
        return lst if isinstance(lst, list) else []
    return resp_json if isinstance(resp_json, list) else []

def lowest_price_cents(market_hash_name: str) -> int | None:
    params = {
        "market_hash_name": market_hash_name,
        "sort_by": "lowest_price",
        "type": "buy_now",
        "limit": 1
    }
    try:
        r = requests.get(API, headers=HEADERS, params=params, timeout=20)
        if r.status_code == 429:
            time.sleep(3)
            r = requests.get(API, headers=HEADERS, params=params, timeout=20)
        r.raise_for_status()
    except requests.HTTPError as e:
        code = getattr(e.response, "status_code", None)
        print(f"[HTTP ERROR] {market_hash_name}: {e} (status={code})", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[NET ERROR] {market_hash_name}: {e}", file=sys.stderr)
        return None

    try:
        data = r.json()
    except Exception as e:
        print(f"[PARSE ERROR] {market_hash_name}: {e}", file=sys.stderr)
        return None

    listings = parse_listings_json(data)
    if not listings:
        print(f"[NO LISTING] {market_hash_name}")
        return None

    price_cents = listings[0].get("price")
    if not price_cents or int(price_cents) <= 0:
        print(f"[NO PRICE] {market_hash_name}")
        return None
    return int(price_cents)

def ensure_csv_header():
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["ts_utc","market_hash_name","price_cents","price_usd"])

def run_once():
    ensure_csv_header()
    items = load_items_from_holdings()
    print(f"🔎 Items détectés depuis holdings.csv : {len(items)}")
    for i, it in enumerate(items, 1):
        print(f"  {i}. {it}")

    if not items:
        print("⚠️ Aucun item à relever. Corrige data/holdings.csv (entête exact, séparateur virgule).")
        return

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for name in items:
        cents = lowest_price_cents(name)
        if cents is not None:
            usd = f"{cents/100:.2f}"
            rows.append([ts, name, cents, usd])
            print(f"[OK] {name} -> {usd} USD")
        else:
            print(f"[SKIP] {name}")

    if rows:
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        print(f"✅ Lignes ajoutées : {len(rows)}")
    else:
        print("⚠️ 0 ligne ajoutée (noms mauvais / aucune offre 'buy_now' dispo).")

if __name__ == "__main__":
    run_once()
