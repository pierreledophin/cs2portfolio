#!/usr/bin/env python3
import os, sys, csv, time, datetime, requests, pandas as pd
from typing import Optional, Tuple, List

CSFLOAT_API_KEY = os.getenv("CSFLOAT_API_KEY", "").strip()
CSFLOAT_API = "https://csfloat.com/api/v1/listings"
HEADERS = {"Authorization": CSFLOAT_API_KEY} if CSFLOAT_API_KEY else {}

ALLOW_FALLBACK_ALL_TYPES = True   # si buy_now vide, on réessaie sans 'type'
SLEEP_BETWEEN_CALLS = 0.3         # petite pause anti rate-limit

def read_holdings(path: str) -> pd.DataFrame:
    if not os.path.isfile(path):
        print(f"[WARN] holdings introuvable: {path}")
        return pd.DataFrame(columns=["market_hash_name","qty","buy_price_usd"])
    try:
        df = pd.read_csv(path)
        if "market_hash_name" not in df.columns:
            raise ValueError("Colonne 'market_hash_name' manquante dans holdings.csv")
        # normalisation légère
        df["market_hash_name"] = df["market_hash_name"].astype(str).str.strip()
        df = df[df["market_hash_name"].str.len() > 0]
        if "qty" not in df.columns:
            df["qty"] = 1
        print(f"[INFO] holdings: {len(df)} lignes, {df['market_hash_name'].nunique()} items uniques.")
        return df
    except Exception as e:
        print(f"[ERROR] lecture holdings: {e}")
        return pd.DataFrame(columns=["market_hash_name","qty","buy_price_usd"])

def _interpret_price(raw) -> Tuple[Optional[int], Optional[float]]:
    if raw is None:
        return None, None
    try:
        val = float(raw)
    except Exception:
        return None, None
    # décimal -> USD
    if abs(val - round(val)) > 1e-9:
        usd = round(val, 2)
        return int(round(usd * 100)), usd
    # entier -> cents
    cents = int(round(val))
    return cents, round(cents / 100.0, 2)

def _fetch_once(params: dict) -> Optional[Tuple[int, float]]:
    try:
        r = requests.get(CSFLOAT_API, headers=HEADERS, params=params, timeout=20)
        if r.status_code == 429:
            print("[RATE] 429; sleep 3s puis retry…")
            time.sleep(3)
            r = requests.get(CSFLOAT_API, headers=HEADERS, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        listings = data.get("data") if isinstance(data, dict) else data
        if not isinstance(listings, list) or not listings:
            return None
        raw = listings[0].get("price")
        cents, usd = _interpret_price(raw)
        if cents is None or usd is None:
            return None
        return cents, usd
    except Exception as e:
        print(f"[ERROR] API: {e}")
        return None

def fetch_lowest_price(name: str) -> Optional[Tuple[int, float]]:
    if not CSFLOAT_API_KEY:
        print("[WARN] CSFLOAT_API_KEY manquant; impossible de fetch.")
        return None
    base = {"market_hash_name": name, "sort_by": "lowest_price", "limit": 1}
    # 1) buy_now d'abord
    res = _fetch_once({**base, "type": "buy_now"})
    if res:
        return res
    print(f"[NO LISTING buy_now] {name}")
    # 2) fallback: toutes annonces
    if ALLOW_FALLBACK_ALL_TYPES:
        res = _fetch_once(base)  # sans 'type'
        if res:
            print(f"[FALLBACK ok] {name} -> {res[0]} cents (${res[1]:.2f})")
            return res
        print(f"[NO LISTING all-types] {name}")
    return None

def ensure_history_file(history_path: str):
    """Crée le fichier avec l'en-tête s'il n'existe pas (même sans données)."""
    os.makedirs(os.path.dirname(history_path), exist_ok=True)
    if not os.path.isfile(history_path):
        with open(history_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["ts_utc","market_hash_name","price_cents","price_usd"])
            writer.writeheader()
        print(f"[INIT] créé {history_path} (en-tête)")

def append_history(history_path: str, rows: List[dict]):
    ensure_history_file(history_path)
    if not rows:
        print("[INFO] aucune ligne à ajouter (pas de prix trouvé).")
        return
    with open(history_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ts_utc","market_hash_name","price_cents","price_usd"])
        for r in rows:
            writer.writerow(r)
    print(f"[DONE] {len(rows)} lignes ajoutées → {history_path}")

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

    df = read_holdings(holdings_path)
    if df.empty:
        print("[INFO] holdings vide; on crée quand même price_history.csv (en-tête).")
        ensure_history_file(history_path)
        sys.exit(0)

    names = sorted(df["market_hash_name"].dropna().unique().tolist())
    print(f"[INFO] {len(names)} items à traiter depuis {holdings_path}")

    ts = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    out: List[dict] = []
    for i, name in enumerate(names, 1):
        got = fetch_lowest_price(name)
        if got:
            cents, usd = got
            out.append({"ts_utc": ts, "market_hash_name": name, "price_cents": cents, "price_usd": usd})
            print(f"[OK] {i:02d}/{len(names)} {name} -> {cents} cents (${usd:.2f})")
        else:
            print(f"[SKIP] {i:02d}/{len(names)} {name} (aucun prix)")
        time.sleep(SLEEP_BETWEEN_CALLS)

    append_history(history_path, out)

if __name__ == "__main__":
    main()
