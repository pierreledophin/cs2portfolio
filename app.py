import io, os, base64, json, uuid, requests, pandas as pd, numpy as np, streamlit as st
from datetime import datetime

# ---------- Configuration ----------
st.set_page_config(page_title="CS2 Portfolio (CSFloat)", layout="wide")

# --- Style global ---
st.markdown("""
<style>
.block-container { padding-top: 1.6rem; padding-bottom: 1.6rem; }
h1, h2, h3 { letter-spacing: .2px; }
h1 { margin-bottom: .6rem !important; }
h2, h3 { margin-top: 1.0rem !important; margin-bottom: .6rem !important; }
.kpi-card { border-radius: 16px; padding: 16px 18px; border: 1px solid rgba(0,0,0,.05); box-shadow: 0 6px 20px rgba(0,0,0,.03); background: #ffffff; margin-bottom: 14px; }
.kpi-title { font-size: 12px; color: #6b7280; margin-bottom: 6px; text-transform: uppercase; letter-spacing: .6px; }
.kpi-value { font-size: 22px; font-weight: 700; }
.stRadio { padding: 8px 10px; border-radius: 12px; border: 1px solid rgba(0,0,0,.06); background: #fafafa; margin-bottom: 12px; }
[data-testid="stHorizontalBlock"] .stRadio > label { font-weight: 600; }
[data-baseweb="tab-list"] { gap: 8px; margin-bottom: 8px; }
.stDataFrame td, .stDataFrame th { padding-top: 10px !important; padding-bottom: 10px !important; }
.section-gap { height: 12px; }
.section-gap-lg { height: 18px; }
</style>
""", unsafe_allow_html=True)

st.markdown("<h1 style='margin-bottom:0'>CS2 Portfolio Tracker</h1>", unsafe_allow_html=True)

OWNER   = st.secrets.get("GH_OWNER", "")
REPO    = st.secrets.get("GH_REPO", "")
BRANCH  = st.secrets.get("GH_BRANCH", "main")
GH_PAT  = st.secrets.get("GH_PAT")  # requis pour écrire/trigger workflow
CSFLOAT_API_KEY = st.secrets.get("CSFLOAT_API_KEY")
CSFLOAT_API = "https://csfloat.com/api/v1/listings"
CSFLOAT_HEADERS = {"Authorization": CSFLOAT_API_KEY} if CSFLOAT_API_KEY else {}

PROFILES = ["pierre", "elenocames"]
profile = st.radio("Profil", PROFILES, horizontal=True, key="profile_select")

DATA_DIR = f"data/{profile}"
os.makedirs(DATA_DIR, exist_ok=True)
PATH_TRADES = f"{DATA_DIR}/trades.csv"
PATH_HOLDINGS = f"{DATA_DIR}/holdings.csv"
PATH_HISTORY = f"{DATA_DIR}/price_history.csv"

# ---------- GitHub helpers ----------
def _gh_headers():
    return {"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github+json"}

def gh_get_file(path):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}?ref={BRANCH}"
    r = requests.get(url, headers=_gh_headers(), timeout=20)
    if r.status_code != 200:
        return "", None, r.status_code
    j = r.json()
    try:
        raw = base64.b64decode(j["content"]).decode("utf-8")
    except Exception:
        raw = ""
    return raw, j.get("sha"), r.status_code

def gh_put_file(path, content, sha, message):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}"
    payload = {"message": message, "content": base64.b64encode(content.encode("utf-8")).decode("ascii"), "branch": BRANCH, "sha": sha}
    r = requests.put(url, headers=_gh_headers(), data=json.dumps(payload), timeout=20)
    return r

def gh_dispatch_workflow(workflow_file="fetch-prices.yml"):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{workflow_file}/dispatches"
    payload = {"ref": BRANCH}
    r = requests.post(url, headers=_gh_headers(), data=json.dumps(payload), timeout=20)
    return r

# ---------- Init trades ----------
def ensure_trades_exists():
    if not os.path.exists(PATH_TRADES):
        df = pd.DataFrame(columns=["date","type","market_hash_name","qty","price_usd","note","trade_id"])
        df.to_csv(PATH_TRADES, index=False)
ensure_trades_exists()

def load_trades():
    try:
        return pd.read_csv(PATH_TRADES)
    except Exception:
        return pd.DataFrame(columns=["date","type","market_hash_name","qty","price_usd","note","trade_id"])

def save_trades(df, msg="update trades"):
    df.to_csv(PATH_TRADES, index=False)
    if GH_PAT and OWNER:
        text, sha, _ = gh_get_file(PATH_TRADES)
        csv_buf = io.StringIO(); df.to_csv(csv_buf, index=False)
        resp = gh_put_file(PATH_TRADES, csv_buf.getvalue(), sha, msg)
        if 200 <= resp.status_code < 300:
            st.toast("Modifications sauvegardées sur GitHub.")
        else:
            st.error(f"Erreur GitHub: {resp.status_code}")

# ---------- Calculs ----------
def rebuild_holdings(trades: pd.DataFrame):
    if trades.empty:
        pd.DataFrame(columns=["market_hash_name","qty","buy_price_usd","buy_date","notes"]).to_csv(PATH_HOLDINGS,index=False)
        return pd.DataFrame()
    holdings = []
    for name, g in trades.groupby("market_hash_name"):
        buys = g[g["type"]=="BUY"].copy()
        sells = g[g["type"]=="SELL"].copy()
        total_buy = buys["qty"].sum()
        total_sell = sells["qty"].sum()
        remaining = total_buy - total_sell
        if remaining > 0:
            cost = (buys["qty"] * buys["price_usd"]).sum()
            pru = cost / total_buy if total_buy>0 else 0
            holdings.append([name, remaining, pru, buys.iloc[-1]["date"], ""])
    df = pd.DataFrame(holdings, columns=["market_hash_name","qty","buy_price_usd","buy_date","notes"])
    df.to_csv(PATH_HOLDINGS, index=False)
    return df

# ---------- CSFloat ----------
@st.cache_data(ttl=3600)
def fetch_icon(name):
    if not CSFLOAT_API_KEY: return None
    params = {"market_hash_name": name, "limit": 1, "expand": "item", "sort_by": "lowest_price"}
    try:
        r = requests.get(CSFLOAT_API, headers=CSFLOAT_HEADERS, params=params, timeout=15)
        if r.status_code != 200: return None
        data = r.json()
        listings = data.get("data") or data
        if not listings: return None
        first = listings[0]
        img = first.get("image") or first.get("icon_url") or first.get("item",{}).get("icon_url")
        if not img: return None
        if isinstance(img, str) and img.startswith("http"): return img
        return f"https://steamcommunity-a.akamaihd.net/economy/image/{img}/128fx128f"
    except Exception:
        return None

@st.cache_data(ttl=600)
def fetch_price(name):
    """
    IMPORTANT : on fixe sort_by=lowest_price pour obtenir bien le prix le plus bas
    et type=buy_now pour ignorer les enchères/offres.
    """
    if not CSFLOAT_API_KEY: return None
    params = {
        "market_hash_name": name,
        "limit": 1,
        "type": "buy_now",
        "sort_by": "lowest_price",   # <- FIX ICI
    }
    try:
        r = requests.get(CSFLOAT_API, headers=CSFLOAT_HEADERS, params=params, timeout=10)
        data = r.json()
        listings = data.get("data") or data
        if not listings: return None
        p = listings[0].get("price")
        return p/100 if p else None
    except Exception:
        return None

# ---------- Couleurs ----------
def _blend_to_pastel(hex_color, intensity):
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    wr, wg, wb = 255, 255, 255
    nr = int(wr + (r - wr) * intensity); ng = int(wg + (g - wg) * intensity); nb = int(wb + (b - wb) * intensity)
    return f"#{nr:02x}{ng:02x}{nb:02x}"

def _pnl_bg_color(value):
    base_green = "#22c55e"; base_red = "#ef4444"
    if value is None: return "#ffffff"
    if value >= 0: return _blend_to_pastel(base_green, min(0.15 + min(abs(value)/20000, 0.20), 0.45))
    return _blend_to_pastel(base_red, min(0.15 + min(abs(value)/20000, 0.20), 0.45))

def _pct_bg_color(pct):
    base_green = "#22c55e"; base_red = "#ef4444"
    if pct is None or pct == "" or pd.isna(pct) or not np.isfinite(pct) or abs(pct) < 1e-4: return "#ffffff"
    if pct >= 0: return _blend_to_pastel(base_green, 0.12 if pct < 5 else min(0.12 + pct/200, 0.40))
    ap = abs(pct); return _blend_to_pastel(base_red, 0.12 if ap < 5 else min(0.12 + ap/200, 0.40))

# ---------- Lecture price_history ----------
def load_price_history_df() -> pd.DataFrame:
    text, _sha, status = gh_get_file(PATH_HISTORY)
    if status == 200 and text.strip():
        try:
            return pd.read_csv(io.StringIO(text))
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

def build_portfolio_timeseries(holdings_df: pd.DataFrame, hist_df: pd.DataFrame) -> pd.DataFrame:
    if holdings_df.empty or hist_df.empty: return pd.DataFrame()
    if "price_usd" not in hist_df.columns and "price_cents" in hist_df.columns:
        hist_df["price_usd"] = pd.to_numeric(hist_df["price_cents"], errors="coerce") / 100.0
    needed = {"ts_utc", "market_hash_name", "price_usd"}
    if not needed.issubset(set(hist_df.columns)): return pd.DataFrame()

    hist = hist_df.copy()
    hist["ts_utc"] = pd.to_datetime(hist["ts_utc"], errors="coerce")
    hist = hist.dropna(subset=["ts_utc"])
    hist["date"] = hist["ts_utc"].dt.floor("D")

    items = holdings_df[holdings_df["qty"] > 0]["market_hash_name"].unique().tolist()
    if not items: return pd.DataFrame()
    hist = hist[hist["market_hash_name"].isin(items)]

    daily_last = (
        hist.sort_values(["market_hash_name", "date", "ts_utc"])
            .groupby(["market_hash_name", "date"], as_index=False)
            .tail(1)[["market_hash_name", "date", "price_usd"]]
    )
    pivot = daily_last.pivot(index="date", columns="market_hash_name", values="price_usd").sort_index().ffill()
    qty_map = holdings_df.set_index("market_hash_name")["qty"].to_dict()
    for col in pivot.columns:
        pivot[col] = pivot[col] * float(qty_map.get(col, 0))
    pivot["total_value_usd"] = pivot.sum(axis=1)
    ts = pivot[["total_value_usd"]].copy(); ts.index.name = "date"; ts.reset_index(inplace=True)
    return ts

# ---------- Sidebar actions ----------
with st.sidebar:
    if st.button("Actualiser les prix (Live)"):
        st.cache_data.clear()
        st.success("Prix Live rafraîchis.")
        st.rerun()

    if st.button("Lancer MAJ GitHub (robot)"):
        if not GH_PAT:
            st.error("GH_PAT manquant dans les secrets Streamlit.")
        else:
            resp = gh_dispatch_workflow("fetch-prices.yml")
            if resp.status_code in (201, 204):
                st.success("Workflow GitHub déclenché.")
            else:
                st.error(f"Échec du déclenchement ({resp.status_code}) : {resp.text[:200]}")

# ---------- UI ----------
tab1, tab2, tab3 = st.tabs(["Portefeuille", "Achat / Vente", "Transactions"])
trades = load_trades()

# ---------- Onglet 1 : Portefeuille ----------
with tab1:
    st.subheader("Portefeuille actuel")
    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
    holdings = rebuild_holdings(trades)
    if holdings.empty:
        st.info("Aucune position. Ajoute un achat pour commencer.")
        st.stop()

    holdings["Image"] = holdings["market_hash_name"].apply(fetch_icon)
    holdings["Prix actuel USD"] = holdings["market_hash_name"].apply(fetch_price)
    holdings["valeur"] = holdings["Prix actuel USD"] * holdings["qty"]
    holdings["gain"] = (holdings["Prix actuel USD"] - holdings["buy_price_usd"]) * holdings["qty"]
    holdings["evolution_pct"] = np.where(
        holdings["buy_price_usd"] > 0,
        (holdings["Prix actuel USD"] - holdings["buy_price_usd"]) / holdings["buy_price_usd"] * 100,
        np.nan
    ).replace([np.inf, -np.inf], np.nan)

    total_val = holdings["valeur"].sum()
    total_cost = (holdings["buy_price_usd"] * holdings["qty"]).sum()
    total_pnl = total_val - total_cost
    total_pct = (total_pnl / total_cost * 100) if total_cost>0 else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(f"""<div class="kpi-card"><div class="kpi-title">Valeur portefeuille</div>
    <div class="kpi-value">${total_val:,.2f}</div></div>""", unsafe_allow_html=True)
    col2.markdown(f"""<div class="kpi-card" style="background:{_blend_to_pastel('#3b82f6',0.10)}">
    <div class="kpi-title">Coût total</div><div class="kpi-value">${total_cost:,.2f}</div></div>""", unsafe_allow_html=True)
    col3.markdown(f"""<div class="kpi-card" style="background:{_pnl_bg_color(total_pnl)}">
    <div class="kpi-title">P&L latent</div><div class="kpi-value">${total_pnl:,.2f}</div></div>""", unsafe_allow_html=True)
    col4.markdown(f"""<div class="kpi-card" style="background:{_pct_bg_color(total_pct)}">
    <div class="kpi-title">% d’évolution</div><div class="kpi-value">{total_pct:,.2f}%</div></div>""", unsafe_allow_html=True)

    st.markdown('<div class="section-gap-lg"></div>', unsafe_allow_html=True)

    to_show = holdings[["Image","market_hash_name","qty","buy_price_usd","Prix actuel USD","gain","evolution_pct"]].rename(columns={
        "market_hash_name":"Item","qty":"Quantité","buy_price_usd":"Prix achat USD",
        "Prix actuel USD":"Prix vente USD","gain":"Gain latent USD","evolution_pct":"% évolution"
    })

    def _evo_style(val): return f"background-color: {_pct_bg_color(val)};"
    styler = (to_show.style.format({
        "Prix achat USD": "${:,.2f}","Prix vente USD": "${:,.2f}",
        "Gain latent USD": "${:,.2f}","% évolution": "{:,.2f}%"
    }).applymap(_evo_style, subset=["% évolution"]))

    st.dataframe(styler, use_container_width=True, hide_index=True, column_config={
        "Image": st.column_config.ImageColumn("Image", width="small"),
        "Item": "Item","Quantité": st.column_config.NumberColumn("Quantité", format="%d"),
        "Prix achat USD": st.column_config.NumberColumn("Prix achat USD", format="$%.2f"),
        "Prix vente USD": st.column_config.NumberColumn("Prix vente USD", format="$%.2f"),
        "Gain latent USD": st.column_config.NumberColumn("Gain latent USD", format="$%.2f"),
        "% évolution": st.column_config.NumberColumn("% évolution", format="%.2f%%"),
    })

    # ---- Graphique d'évolution (quotidien) ----
    st.markdown('<div class="section-gap-lg"></div>', unsafe_allow_html=True)
    st.subheader("Évolution de la valeur du portefeuille")
    hist_df = load_price_history_df()
    ts = build_portfolio_timeseries(holdings_df=holdings, hist_df=hist_df)
    if ts.empty:
        st.info("Pas encore assez d'historique pour tracer la courbe (ou `price_history.csv` introuvable).")
    else:
        ts = ts.sort_values("date").set_index("date")
        st.line_chart(ts["total_value_usd"])

# ---------- Onglet 2 : Achat / Vente ----------
with tab2:
    st.subheader("Nouvelle transaction")
    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
    t_type = st.radio("Type", ["BUY","SELL"], horizontal=True)
    name = st.text_input("Nom exact (market_hash_name)")
    qty = st.number_input("Quantité", min_value=1, step=1)
    price = st.number_input("Prix unitaire USD", min_value=0.0, step=0.01)
    note = st.text_input("Note (facultatif)")
    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
    if st.button("Enregistrer la transaction"):
        if not name:
            st.error("Nom requis.")
        else:
            new_trade = pd.DataFrame([{
                "date": datetime.now().strftime("%Y-%m-%d"),
                "type": t_type,"market_hash_name": name,"qty": qty,
                "price_usd": price,"note": note,"trade_id": "trd_" + uuid.uuid4().hex[:8]
            }])
            trades = pd.concat([trades, new_trade], ignore_index=True)
            save_trades(trades, f"add {t_type} {name}")
            st.success("Transaction enregistrée."); st.cache_data.clear(); st.rerun()

# ---------- Onglet 3 : Transactions ----------
with tab3:
    st.subheader("Historique des transactions")
    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
    if trades.empty:
        st.info("Aucune transaction.")
    else:
        pnl_real = 0
        for _, row in trades[trades["type"]=="SELL"].iterrows():
            name = row["market_hash_name"]; qty_s = row["qty"]; price_s = row["price_usd"]
            sub = trades[(trades["market_hash_name"]==name)&(trades["type"]=="BUY")]
            cost = (sub["qty"]*sub["price_usd"]).sum(); q = sub["qty"].sum()
            pru = cost/q if q>0 else 0
            pnl_real += (price_s - pru)*qty_s
        st.metric("P&L réalisé cumulé", f"${pnl_real:,.2f}")
        st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
        to_display = trades.sort_values("date", ascending=False)
        delete_id = st.text_input("ID de transaction à supprimer (trade_id)")
        if st.button("Supprimer cette transaction"):
            if delete_id in trades["trade_id"].values:
                trades = trades[trades["trade_id"]!=delete_id]
                save_trades(trades, f"delete trade {delete_id}")
                st.success(f"Transaction {delete_id} supprimée."); st.cache_data.clear(); st.rerun()
            else:
                st.error("ID introuvable.")
        st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
        st.dataframe(to_display, use_container_width=True, hide_index=True)

