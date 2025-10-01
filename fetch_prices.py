import os, time, requests, yaml, csv, sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API = "https://csfloat.com/api/v1/listings"
API_KEY = os.environ.get("CSFLOAT_API_KEY")
if not API_KEY:
    print("❌ Missing CSFLOAT_API_KEY (secret GitHub absent ou mal nommé).", file=sys.stderr)
    sys.exit(1)

# Auth attendue: Authorization: <API-KEY> (sans 'Bearer')
# Doc: https://docs.csfloat.com/ (Authentication + Listings)
HEADERS = {
    "Authorization": API_KEY,
    "User-Agent": "cs2-portfolio-csfloat (+contact)",
}

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
CSV_PATH = DATA_DIR / "price_history.csv"
HOLDINGS_PATH = DATA_DIR / "holdings.csv"

def load_items():
    items = []
    if HOLDINGS_PATH.exists():
        with open(HOLDINGS_PATH, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            if not r.fieldnames or "market_hash_name" not in r.fieldnames:
                print(f"❌ En-tête invalide dans holdings.csv. Colonnes attendues: market_hash_name,qty,buy_price_usd,buy_date,notes", file=sys.stderr)
                print(f"   Colonnes détectées: {r.fieldnames}", file=sys.stderr)
                return []
            for row in r:
                name = (row.get("market_hash_name") or "").strip()
                if name:
                    items.append(name)
    # Fallback: items.yaml si vide
    if not items and Path("items.yaml").exists():
        with open("items.yaml", "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if isinstance(data, dict) and "items" in data:
                items.extend([str(x).strip() for x in data["items"] if str(x).strip()])
    # dédoublonne + nettoie
    return sorted({x for x in items if x})

def parse_listings_json(resp_json):
    """
    L'API peut renvoyer soit un tableau [...], soit {"data":[...]}.
    On retourne toujours une liste (peut être vide).
    """
    if isinstance(resp_json, dict):
        lst = resp_json.get("data", [])
        if isinstance(lst, list):
            return lst, "object[data]"
        else:
            return [], "object[unknown]"
    elif isinstance(resp_json, list):
        return resp_json, "array"
    else:
        return [], type(resp_json).__name__

def lowest_price_cents(market_hash_name: str) -> int | None:
    params = {
        "market_hash_name": market_hash_name,  # filtre exact
        "sort_by": "lowest_price",
        "type": "buy_now",                      # évite les enchères
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

    listings, shape = parse_listings_json(data)
    if not listings:
        print(f"[NO LISTING] {market_hash_name} (JSON={shape})")
        return None

    # on prend le premier (trié par lowest_price)
    first = listings[0]
    price_cents = first.get("price")
    if price_cents in (None, 0):
        # 0 n'est pas un prix valide ici → on considère 'pas de listing'
        print(f"[NO PRICE] {market_hash_name} (JSON={shape})")
        return None
    return int(price_cents)

def ensure_csv_header():
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts_utc","market_hash_name","price_cents","price_usd"])

def run_once():
    ensure_csv_header()
    items = load_items()
    print(f"🔎 Items détectés : {len(items)}")
    for i, it in enumerate(items, 1):
        print(f"  {i}. {it}")

    if not items:
        print("⚠️ Aucun item à relever (complète data/holdings.csv).")
        return

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for name in items:
        cents = lowest_price_cents(name)
        if cents is not None and cents > 0:
            usd = f"{cents/100:.2f}"
            rows.append([ts, name, cents, usd])
            print(f"[OK] {name} -> {usd} USD")
        else:
            # Si tu voyais avant "Error: ... : 0", on le remplace par un message clair:
            print(f"[SKIP] {name} (aucun prix 'buy_now' trouvé)")

    if rows:
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        print(f"✅ Lignes ajoutées : {len(rows)}")
    else:
        print("⚠️ 0 ligne ajoutée (aucune offre trouvée / noms non exacts / JSON vide).")

if __name__ == "__main__":
    run_once()
