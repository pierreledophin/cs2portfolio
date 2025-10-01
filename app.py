import io, time, requests, yaml
import pandas as pd
import streamlit as st
from datetime import datetime

st.set_page_config(page_title="CS2 Portfolio (CSFloat)", layout="wide")
st.title("CS2 Portfolio Tracker (CSFloat)")

# ---- config: qui est ton repo ?
OWNER = st.secrets.get("GH_OWNER", "<TON_USER_GH>")  # mets ton user GitHub dans les secrets Streamlit
REPO  = st.secrets.get("GH_REPO", "cs2-portfolio-csfloat")
BRANCH = "main"

RAW_HOLDINGS = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/data/holdings.csv"
RAW_HISTORY  = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/data/price_history.csv"

# ---- clé CSFloat (pour le bouton "update live", sans rien enregistrer)
CSFLOAT_API_KEY = st.secrets.get("CSFLOAT_API_KEY")
API = "https://csfloat.com/api/v1/listings"
HEADERS = {"Authorization": CSFLOAT_API_KEY} if CSFLOAT_API_KEY else {}

# ---- utils
@st.cache_data(ttl=120)
def read_csv_url(url: str) -> pd.DataFrame:
    r = requests.get(url, timeout=20)
    if r.status_code == 200 and r.text.strip():
        return pd.read_csv(io.StringIO(r.text))
    return pd.DataFrame()

def fetch_lowest_usd(name: str) -> float | None:
    if not CSFLOAT_API_KEY:
        return None
    params = {"market_hash_name": name, "sort_by": "lowest_price", "limit": 1}
    r = requests.get(API, headers=HEADERS, params=params, timeout=20)
    if r.status_code == 429:
        time.sleep(3)
        r = requests.get(API, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    return float(data[0]["price"]) / 100.0

# ---- charge les données
holdings = read_csv_url(RAW_HOLDINGS)
history  = read_csv_url(RAW_HISTORY)

# ---- si historique vide, affiche un message d’aide
if history.empty:
    st.info("Aucun historique pour le moment. Lance d’abord le workflow GitHub (onglet **Actions** → **fetch-prices** → **Run workflow**).")
else:
    # dernière observation par item
    last = (history.sort_values(["market_hash_name","ts_utc"])
                  .groupby("market_hash_name", as_index=False)
                  .tail(1)
                  .rename(columns={"price_usd":"last_price_usd"}))

    # merge avec holdings (pour calculer P&L)
    if holdings.empty:
        st.warning("Ton fichier `data/holdings.csv` est vide. Ajoute tes achats dans le dépôt GitHub.")
        portfolio = pd.DataFrame(columns=["market_hash_name","qty","buy_price_usd","last_price_usd"])
    else:
        portfolio = holdings.merge(last[["market_hash_name","last_price_usd"]], on="market_hash_name", how="left")

    # calculs
    if not portfolio.empty:
        portfolio["qty"] = pd.to_numeric(portfolio["qty"], errors="coerce").fillna(0)
        portfolio["buy_price_usd"] = pd.to_numeric(portfolio["buy_price_usd"], errors="coerce").fillna(0.0)
        portfolio["last_price_usd"] = pd.to_numeric(portfolio["last_price_usd"], errors="coerce")

        portfolio["cost_total"]   = portfolio["qty"] * portfolio["buy_price_usd"]
        portfolio["value_total"]  = portfolio["qty"] * portfolio["last_price_usd"]
        portfolio["pnl_abs"]      = portfolio["value_total"] - portfolio["cost_total"]
        portfolio["pnl_pct"]      = (portfolio["pnl_abs"] / portfolio["cost_total"]).replace([pd.NA, pd.NaT], 0.0)*100

        # résumé
        colA, colB, colC, colD = st.columns(4)
        colA.metric("Valeur portefeuille", f"${portfolio['value_total'].sum():,.2f}")
        colB.metric("Coût total",         f"${portfolio['cost_total'].sum():,.2f}")
        colC.metric("P&L total",          f"${portfolio['pnl_abs'].sum():,.2f}")
        total_pct = (portfolio['pnl_abs'].sum() / portfolio['cost_total'].sum() * 100) if portfolio['cost_total'].sum()>0 else 0
        colD.metric("P&L %",              f"{total_pct:,.2f}%")

        st.subheader("Détail par item")
        display_cols = ["market_hash_name","qty","buy_price_usd","last_price_usd","cost_total","value_total","pnl_abs","pnl_pct","buy_date","notes"]
        st.dataframe(portfolio[display_cols].sort_values("pnl_abs", ascending=False), use_container_width=True)

        st.subheader("Historique")
        item = st.selectbox("Choisis un item pour la courbe :", sorted(history["market_hash_name"].unique()))
        hist_item = history[history["market_hash_name"]==item].copy()
        hist_item["ts_utc"] = pd.to_datetime(hist_item["ts_utc"])
        st.line_chart(hist_item.set_index("ts_utc")["price_usd"])

# ---- zone actions
st.divider()
col1, col2 = st.columns([1.5, 2])
with col1:
    if st.button("🔁 Recharger les CSV depuis GitHub"):
        st.cache_data.clear()
        holdings = read_csv_url(RAW_HOLDINGS)
        history  = read_csv_url(RAW_HISTORY)
        st.success("Rechargé.")

with col2:
    if st.button("⚡ Update now (Live, non sauvegardé)"):
        if CSFLOAT_API_KEY is None:
            st.error("Ajoute `CSFLOAT_API_KEY` dans les **Secrets** Streamlit pour utiliser l’update live.")
        else:
            if holdings.empty:
                st.warning("Ajoute d’abord des items dans `data/holdings.csv`.")
            else:
                st.write("Récupération en cours…")
                rows = []
                for name in holdings["market_hash_name"].tolist():
                    try:
                        px = fetch_lowest_usd(name)
                        rows.append({"market_hash_name": name, "live_price_usd": px})
                    except Exception as e:
                        rows.append({"market_hash_name": name, "live_price_usd": None})
                live = pd.DataFrame(rows)
                st.success("Terminé (affichage live uniquement).")
                st.dataframe(live, use_container_width=True)
