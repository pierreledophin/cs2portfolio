#!/usr/bin/env python3
import os, sys, csv, time, json, datetime, requests, pandas as pd
from typing import Optional, Tuple

CSFLOAT_API_KEY = os.getenv("CSFLOAT_API_KEY", "").strip()
CSFLOAT_API = "https://csfloat.com/api/v1/listings"
HEADERS = {"Authorization": CSFLOAT_API_KEY} if CSFLOAT_API_KEY else {}

# Usage:
#   python fetch_prices.py data/pierre/holdings.csv
#   -> écrit/append dans data/pierre/price_history.csv

def read_holdings(path: str) -> pd.DataFrame:
    if not os.path.isfile(path):
        print(f"[WARN] holdings introuvable: {path}")
        return pd.DataFrame(columns=["market_hash_name","qty","buy_price_usd"])
    try:
        df = pd.read_csv(path)
        if "market_hash_name" not in df.columns:
            raise ValueError("Colonne 'market_hash_name' manquante dans holdings.csv")
        if "qty" not in df.columns:
            df["qty"] = 1
        n = len(df.index)
        u = df["market_hash_name"].dropna().nunique()
        print(f"[INFO] holdings: {n} lignes, {u} items uniques.")
        return df
    except Exception as e:
        print(f"[ERROR] lecture holdings: {e}")
        return pd.DataFrame(columns=["market_hash_name","qty","buy_price_usd"])

def _interpret_price(raw_price) -> Tuple[Optional[int], Optional[float]]:
    if raw_price is None:
        return None, None
    try:
        val = float(raw_price)
    except Exception:
        return None, None
    if abs(val - round(val)) > 1e-9:  # décimal -> USD
        usd = round(val, 2)
        cents = int(round(usd * 100))
        return cents, usd
    cents = int(round(val))           # entier -> cents
    usd = round(cents / 100.0, 2)
    return cents, usd

def fetch_lowest_price(name: str) -> Tuple[Optional[int], Optional[float]]:
    if not CSFLOAT_API_KEY:
        print("[WARN] CSFLOAT_API_KEY manquant; impossible de fetch.")
        return None, None
    params = {
        "market_hash_name": name,
        "type": "buy_now",
        "sort_by": "lowest_price",
        "limit": 1
    }
    try:
        r = requests.get(CSFLOAT_API, headers=HEADERS, params=params, timeout=20)
        if r.status_code == 429:
            print("[RATE] 429 rate-limited; sleep 3s")
            time.sleep(3)
            return fetch_lowest_price(name)
        r.raise_for_status()
        data = r.json()
        listings = data.get("data") if isinstance(data, dict) else data
        if not isinstance(listings, list) or not listings:
            print(f"[NO LISTING] {name}")
            return None, None
        raw = listings[0].get("price")
        cents, usd = _interpret_price(raw)
        if cents is None or usd is None:
            print(f"[WARN] {name}: prix invalide ({raw})")
            return None, None
        return cents, usd
    except Exception as e:
        print(f"[ERROR] {name}: {e}")
        return None, None

def append_history(history_path: str, rows: list[dict]):
    file_exists = os.path.isfile(history_path)
    fieldnames = ["ts_utc", "market_hash_name", "price_cents", "price_usd"]
    os.makedirs(os.path.dirname(history_path), exist_ok=True)
    with open(history_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)

def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch_prices.py <path/to/holdings.csv>")
        sys.exit(1)

    holdings_path = sys.argv[1]
    base_dir = os.path.dirname(holdings_path)
    history_path = os.path.join(base_dir, "price_history.csv")

    if not CSFLOAT_API_KEY:
        print("[FATAL] CSFLOAT_API_KEY manquant (secret GitHub).")
        sys.exit(1)

    holds = read_holdings(holdings_path)
    if holds.empty:
        print("[INFO] Aucun item dans holdings; rien à faire.")
        sys.exit(0)

    names = sorted(holds["market_hash_name"].dropna().unique().tolist())
    print(f"[INFO] {len(names)} items à traiter depuis {holdings_path}")

    ts = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    out_rows = []
    for i, name in enumerate(names, start=1):
        cents, usd = fetch_lowest_price(name)
        if usd is not None and cents is not None:
            out_rows.append({"ts_utc": ts, "market_hash_name": name, "price_cents": cents, "price_usd": usd})
            print(f"[OK] {i:02d}/{len(names)} {name} -> {cents} cents (${usd:.2f})")
        else:
            print(f"[SKIP] {i:02d}/{len(names)} {name} (aucun prix)")

        time.sleep(0.3)

    if out_rows:
        append_history(history_path, out_rows)
        print(f"[DONE] {len(out_rows)} lignes ajoutées → {history_path}")
    else:
        print("[WARN] Aucune ligne ajoutée (noms invalides, pas d'offres buy_now, ou API vide).")

if __name__ == "__main__":
    main()
