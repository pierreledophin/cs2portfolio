import io, base64, requests, pandas as pd, streamlit as st

st.set_page_config(page_title="CS2 Portfolio (CSFloat)", layout="wide")
st.title("CS2 Portfolio Tracker (CSFloat)")

OWNER   = st.secrets.get("GH_OWNER", "")
REPO    = st.secrets.get("GH_REPO", "")
BRANCH  = st.secrets.get("GH_BRANCH", "main")
GH_PAT  = st.secrets.get("GH_PAT")  # facultatif (requis si repo privé)

PATH_HISTORY  = "data/price_history.csv"
PATH_HOLDINGS = "data/holdings.csv"

def _get_raw_url(path: str) -> str:
    return f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{path}"

def read_github_file(path: str) -> tuple[pd.DataFrame, dict]:
    """
    Tente d'abord via API GitHub (si GH_PAT présent, marche sur repo privé),
    sinon via raw.githubusercontent.com (repo public).
    Retourne (DataFrame ou df vide, infos_debug).
    """
    info = {"mode": None, "status": None, "bytes": 0, "path": path}

    # 1) API GitHub si PAT fourni (private/public)
    if GH_PAT and OWNER and REPO and BRANCH:
        url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}?ref={BRANCH}"
        headers = {"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github+json"}
        r = requests.get(url, headers=headers, timeout=20)
        info["mode"] = "github_api"
        info["status"] = r.status_code
        if r.status_code == 200:
            j = r.json()
            content = j.get("content")
            if content:
                raw = base64.b64decode(content)
                info["bytes"] = len(raw)
                if raw.strip():
                    return pd.read_csv(io.StringIO(raw.decode("utf-8"))), info
                else:
                    return pd.DataFrame(), info
        # si ça marche pas, on tombera sur le mode RAW plus bas

    # 2) RAW (public)
    if OWNER and REPO and BRANCH:
        url = _get_raw_url(path)
        r = requests.get(url, timeout=20)
        info["mode"] = "raw"
        info["status"] = r.status_code
        if r.status_code == 200 and r.text.strip():
            info["bytes"] = len(r.text.encode("utf-8"))
            return pd.read_csv(io.StringIO(r.text)), info

    # échec
    return pd.DataFrame(), info

def latest_prices(df_hist: pd.DataFrame) -> pd.DataFrame:
    if df_hist.empty:
        return df_hist
    # Normaliser colonnes attendues
    cols = {c.lower(): c for c in df_hist.columns}
    # on attend ts_utc, market_hash_name, price_usd
    # si price_usd pas présent mais price_cents oui, on le fabrique
    if "price_usd" not in cols and "price_cents" in cols:
        # créer price_usd à partir de price_cents
        df_hist["price_usd"] = pd.to_numeric(df_hist["price_cents"], errors="coerce") / 100.0
        cols = {c.lower(): c for c in df_hist.columns}

    ts_col = cols.get("ts_utc", "ts_utc")
    name_col = cols.get("market_hash_name", "market_hash_name")
    px_col = cols.get("price_usd", "price_usd")

    # garder uniquement les colonnes utiles si elles existent
    for need in [ts_col, name_col, px_col]:
        if need not in df_hist.columns:
            return pd.DataFrame()

    df = df_hist[[ts_col, name_col, px_col]].copy()
    df.columns = ["ts_utc", "market_hash_name", "price_usd"]
    # dernière observation par item
    df = (df.sort_values(["market_hash_name","ts_utc"])
             .groupby("market_hash_name", as_index=False)
             .tail(1)
             .sort_values("price_usd", ascending=False))
    return df

st.sidebar.header("Rechargement")
if st.sidebar.button("🔁 Recharger les CSV depuis GitHub"):
    st.cache_data.clear()
    st.rerun()

@st.cache_data(ttl=120)
def load_all():
    hist, info_hist = read_github_file(PATH_HISTORY)
    holds, info_holds = read_github_file(PATH_HOLDINGS)
    return hist, holds, info_hist, info_holds

hist, holds, info_hist, info_holds = load_all()

with st.expander("🔍 Debug (utile si rien ne s'affiche)"):
    st.write("history.csv →", info_hist)
    st.write("holdings.csv →", info_holds)
    st.write("Owner/Repo/Branch:", OWNER, REPO, BRANCH)

if hist.empty:
    st.warning("Aucun historique trouvé.\nVérifie : 1) le chemin `data/price_history.csv`, 2) les *secrets* GH_OWNER/GH_REPO/GH_BRANCH, 3) repo privé ⇒ ajoute GH_PAT.")
else:
    st.subheader("Dernière valeur par item")
    latest = latest_prices(hist)
    if latest.empty:
        st.info("Le CSV est présent mais ne contient pas les colonnes attendues (ts_utc, market_hash_name, price_usd/price_cents).")
    else:
        st.dataframe(latest, use_container_width=True)

    # Si holdings dispo → P&L
    if not holds.empty:
        # cast
        holds["qty"] = pd.to_numeric(holds.get("qty", 0), errors="coerce").fillna(0)
        holds["buy_price_usd"] = pd.to_numeric(holds.get("buy_price_usd", 0.0), errors="coerce").fillna(0.0)
        df = holds.merge(latest[["market_hash_name","price_usd"]], on="market_hash_name", how="left")
        df["cost_total"]  = df["qty"] * df["buy_price_usd"]
        df["value_total"] = df["qty"] * df["price_usd"]
        df["pnl_abs"]     = df["value_total"] - df["cost_total"]
        df["pnl_pct"]     = (df["pnl_abs"] / df["cost_total"]).replace([pd.NA, pd.NaT], 0.0) * 100

        st.subheader("Portefeuille (P&L)")
        show_cols = ["market_hash_name","qty","buy_price_usd","price_usd","cost_total","value_total","pnl_abs","pnl_pct"]
        st.dataframe(df[show_cols].sort_values("pnl_abs", ascending=False), use_container_width=True)

        tot_cost = df["cost_total"].sum()
        tot_val  = df["value_total"].sum()
        tot_pnl  = df["pnl_abs"].sum()
        pct = (tot_pnl / tot_cost * 100) if tot_cost > 0 else 0
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Valeur portefeuille", f"${tot_val:,.2f}")
        c2.metric("Coût total", f"${tot_cost:,.2f}")
        c3.metric("P&L total", f"${tot_pnl:,.2f}")
        c4.metric("P&L %", f"{pct:,.2f}%")

    # Courbe simple
    st.subheader("Historique")
    item = st.selectbox("Choisis un item :", sorted(hist["market_hash_name"].unique()))
    df_item = hist[hist["market_hash_name"] == item].copy()
    # normalise colonnes si besoin
    if "price_usd" not in df_item.columns and "price_cents" in df_item.columns:
        df_item["price_usd"] = pd.to_numeric(df_item["price_cents"], errors="coerce")/100.0
    if "ts_utc" in df_item.columns and "price_usd" in df_item.columns:
        df_item["ts_utc"] = pd.to_datetime(df_item["ts_utc"])
        st.line_chart(df_item.set_index("ts_utc")["price_usd"])
    else:
        st.info("Colonnes manquantes pour tracer l'historique.")
