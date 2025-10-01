import io
import base64
import requests
import pandas as pd
import streamlit as st

# ---------- Page setup ----------
st.set_page_config(page_title="CS2 Portfolio (CSFloat)", layout="wide")
st.markdown("<h1 style='margin-bottom:0'>CS2 Portfolio Tracker</h1>", unsafe_allow_html=True)
st.caption("Affichage à partir des CSV dans ton dépôt GitHub")

# ---------- Secrets / Repo config ----------
OWNER   = st.secrets.get("GH_OWNER", "")
REPO    = st.secrets.get("GH_REPO", "")
BRANCH  = st.secrets.get("GH_BRANCH", "main")
GH_PAT  = st.secrets.get("GH_PAT")  # requis si repo privé

PATH_HISTORY  = "data/price_history.csv"
PATH_HOLDINGS = "data/holdings.csv"

# ---------- Helpers pour lire les fichiers GitHub ----------
def _raw_url(path: str) -> str:
    return f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{path}"

def read_github_csv(path: str) -> tuple[pd.DataFrame, dict]:
    """
    Essaye d'abord par l'API GitHub (si GH_PAT présent) -> fonctionne même sur repo privé.
    Sinon, fallback sur raw.githubusercontent.com (repo public).
    Retourne (DataFrame ou df vide, dict_debug).
    """
    info = {"mode": None, "status": None, "bytes": 0, "path": path}

    # Mode API (privé/public) si PAT présent
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
                text = raw.decode("utf-8").strip()
                if text:
                    return pd.read_csv(io.StringIO(text)), info
                return pd.DataFrame(), info

    # Mode RAW (public)
    if OWNER and REPO and BRANCH:
        url = _raw_url(path)
        r = requests.get(url, timeout=20)
        info["mode"] = "raw"
        info["status"] = r.status_code
        if r.status_code == 200 and r.text.strip():
            info["bytes"] = len(r.text.encode("utf-8"))
            return pd.read_csv(io.StringIO(r.text)), info

    return pd.DataFrame(), info

@st.cache_data(ttl=120)
def load_all():
    hist, info_hist = read_github_csv(PATH_HISTORY)
    holds, info_holds = read_github_csv(PATH_HOLDINGS)
    return hist, holds, info_hist, info_holds

# ---------- UI: actions ----------
with st.sidebar:
    if st.button("Recharger les CSV depuis GitHub"):
        st.cache_data.clear()
        st.rerun()

# ---------- Charge les données ----------
hist, holds, info_hist, info_holds = load_all()

with st.expander("Debug (utile si rien ne s'affiche)"):
    st.write("price_history.csv →", info_hist)
    st.write("holdings.csv →", info_holds)
    st.write("Owner/Repo/Branch:", OWNER, REPO, BRANCH)

# ---------- Si pas d'historique ----------
if hist.empty:
    st.warning(
        "Aucun historique pour le moment.\n"
        "Vérifie : 1) le chemin `data/price_history.csv`, 2) les secrets GH_OWNER/GH_REPO/GH_BRANCH, "
        "3) si le repo est privé, ajoute `GH_PAT` dans les secrets Streamlit."
    )
    st.stop()

# ---------- Normalisation colonnes historiques ----------
# Attendues : ts_utc, market_hash_name, price_usd (ou price_cents)
if "price_usd" not in hist.columns and "price_cents" in hist.columns:
    hist["price_usd"] = pd.to_numeric(hist["price_cents"], errors="coerce") / 100.0

needed_hist_cols = {"ts_utc", "market_hash_name", "price_usd"}
if not needed_hist_cols.issubset(set(hist.columns)):
    st.info("Le CSV d'historique ne contient pas les colonnes attendues (ts_utc, market_hash_name, price_usd/price_cents).")
    st.stop()

# ---------- Dernier prix par item ----------
last = (
    hist.sort_values(["market_hash_name", "ts_utc"])
        .groupby("market_hash_name", as_index=False)
        .tail(1)
        .rename(columns={"price_usd": "latest_price_usd"})
)

# ---------- Portefeuille & P&L ----------
st.markdown("## Portefeuille (P&L)")

if holds.empty:
    st.info("Ton fichier `data/holdings.csv` est vide. Ajoute tes achats (market_hash_name, qty, buy_price_usd, …) dans le dépôt.")
else:
    # Cast num
    holds["qty"] = pd.to_numeric(holds.get("qty", 0), errors="coerce").fillna(0)
    holds["buy_price_usd"] = pd.to_numeric(holds.get("buy_price_usd", 0.0), errors="coerce").fillna(0.0)

    # Merge avec dernier prix
    df = holds.merge(last[["market_hash_name", "latest_price_usd"]], on="market_hash_name", how="left")

    # Calculs (on garde les colonnes demandées)
    df["pnl_abs"] = (df["latest_price_usd"] - df["buy_price_usd"]) * df["qty"]
    # % d'évolution unitaire (prix vs achat)
    denom = df["buy_price_usd"].replace(0, pd.NA)
    df["pnl_pct"] = ((df["latest_price_usd"] - df["buy_price_usd"]) / denom * 100).fillna(0)

    # Métriques globales
    total_val = (df["latest_price_usd"] * df["qty"]).sum()
    total_cost = (df["buy_price_usd"] * df["qty"]).sum()
    total_pnl = total_val - total_cost
    total_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    # ----- Cartes métriques sobres (fonds très clairs) -----
    def metric_card(label, value, color="#f7f9fb"):
        st.markdown(
            f"""
            <div style="
                background-color:{color};
                padding:18px;
                border-radius:12px;
                text-align:center;
                box-shadow: 0 1px 3px rgba(0,0,0,0.06);
                border: 1px solid rgba(0,0,0,0.04);
            ">
                <div style="font-size:15px; color:#555; margin-bottom:6px;">{label}</div>
                <div style="font-size:26px; font-weight:700; color:#1f2937;">{value}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        metric_card("Valeur portefeuille", f"${total_val:,.2f}", color="#eef7f2")   # vert très très pâle
    with col2:
        metric_card("Coût total", f"${total_cost:,.2f}", color="#eff3fb")           # bleu très pâle
    with col3:
        color_pnl = "#eef7f2" if total_pnl >= 0 else "#fbeeee"                      # vert clair si gain, rouge clair si perte
        metric_card("P&L total", f"${total_pnl:,.2f}", color=color_pnl)
    with col4:
        color_pct = "#eef7f2" if total_pct >= 0 else "#fbeeee"
        metric_card("% d’évolution", f"{total_pct:,.2f}%", color=color_pct)

    # Tableau demandé (sans quantité, colonnes renommées)
    display = pd.DataFrame({
        "Item": df["market_hash_name"],
        "prix achat USD": df["buy_price_usd"],
        "Prix vente USD": df["latest_price_usd"],
        "perte/gain": df["pnl_abs"],
        "% d’évolution": df["pnl_pct"],
    })

    # ----- Styles très clairs -----
    def color_pnl_abs(val):
        if pd.isna(val):
            return ""
        # Texte vert doux si gain, rouge doux si perte
        return "color: #157a3d;" if val > 0 else ("color: #c44545;" if val < 0 else "")

    def grad_pct(val):
        if pd.isna(val):
            return ""
        a = abs(val)
        # paliers extra-clairs : <5% / 5-10% / 10-20% / >=20%
        if val > 0:
            if a < 5:   bg = "#f3fbf7"   # vert très clair
            elif a < 10: bg = "#e9f7f0"
            elif a < 20: bg = "#ddf2e7"
            else:        bg = "#d0ecdD"
        elif val < 0:
            if a < 5:   bg = "#fdf3f3"   # rouge très clair
            elif a < 10: bg = "#fbeaea"
            elif a < 20: bg = "#f7dddd"
            else:        bg = "#f3d1d1"
        else:
            bg = ""
        return f"background-color: {bg};"

    styled = (
        display.style
        .format({
            "prix achat USD": "{:,.2f}",
            "Prix vente USD": "{:,.2f}",
            "perte/gain": "{:,.2f}",
            "% d’évolution": "{:,.2f}%"
        })
        .applymap(color_pnl_abs, subset=["perte/gain"])
        .applymap(grad_pct, subset=["% d’évolution"])
    )

    st.dataframe(styled, hide_index=True, use_container_width=True)

# ---------- Historique (courbe) ----------
st.markdown("## Historique")
items = sorted(hist["market_hash_name"].unique())
if items:
    item = st.selectbox("Choisis un item :", items)
    df_item = hist[hist["market_hash_name"] == item].copy()
    df_item["ts_utc"] = pd.to_datetime(df_item["ts_utc"])
    if "price_usd" not in df_item.columns and "price_cents" in df_item.columns:
        df_item["price_usd"] = pd.to_numeric(df_item["price_cents"], errors="coerce") / 100.0
    st.line_chart(df_item.set_index("ts_utc")["price_usd"])
else:
    st.info("Aucun item dans l'historique pour tracer une courbe.")
