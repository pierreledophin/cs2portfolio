import io, os, base64, json, uuid, requests, pandas as pd, numpy as np, streamlit as st
from datetime import datetime, date

# ---------- Configuration ----------
st.set_page_config(page_title="CS2 Portfolio (CSFloat)", layout="wide")

# --- Style global ---
st.markdown("""
<style>
.block-container { padding-top: 1.6rem; padding-bottom: 1.6rem; }
h1, h2, h3 { letter-spacing: .2px; }
h1 { margin-bottom: .6rem !important; }
h2, h3 { margin-top: 1.0rem !important; margin-bottom: 1.6rem !important; }

/* Cards KPI (pastel très clair) */
.kpi-card {
  border-radius: 16px; padding: 16px 18px;
  border: 1px solid rgba(0,0,0,.05);
  box-shadow: 0 6px 20px rgba(0,0,0,.03);
  background: #ffffff; margin-bottom: 14px;
}
.kpi-title { font-size: 12px; color: #6b7280; margin-bottom: 6px; text-transform: uppercase; letter-spacing: .6px; }
.kpi-value { font-size: 22px; font-weight: 700; }

/* Segmented profil (radio) */
.stRadio { padding: 8px 10px; border-radius: 12px; border: 1px solid rgba(0,0,0,.06); background: #fafafa; margin-bottom: 12px; }
[data-testid="stHorizontalBlock"] .stRadio > label { font-weight: 600; }

/* Tabs */
[data-baseweb="tab-list"] { gap: 8px; margin-bottom: 8px; }

/* Table: plus d'air dans les cellules */
.stDataFrame td, .stDataFrame th { padding-top: 10px !important; padding-bottom: 10px !important; }

/* Petits espacers */
.section-gap { height: 12px; }
.section-gap-lg { height: 18px; }
</style>
""", unsafe_allow_html=True)

st.markdown("<h1 style='margin-bottom:0'>CS2 Portfolio Tracker TEST VERSION</h1>", unsafe_allow_html=True)

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
PATH_TRADES   = f"{DATA_DIR}/trades.csv"
PATH_HOLDINGS = f"{DATA_DIR}/holdings.csv"
PATH_HISTORY  = f"{DATA_DIR}/price_history.csv"

# ---------- FICHIERS FINANCE ----------
PATH_FINANCE       = f"{DATA_DIR}/finances.csv"            # DEPOSIT / WITHDRAW
PATH_CSFLOAT_SNAP  = f"{DATA_DIR}/csfloat_snapshot.csv"    # snapshots du solde CSFloat (manuel)
PATH_FIN_BASELINE  = f"{DATA_DIR}/finance_baseline.csv"    # baseline "capital net déposé (lifetime)"

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

# ---------- Init fichiers ----------
def ensure_trades_exists():
    if not os.path.exists(PATH_TRADES):
        pd.DataFrame(columns=["date","type","market_hash_name","qty","price_usd","note","trade_id"]).to_csv(PATH_TRADES, index=False)

def ensure_finance_files_exist():
    if not os.path.exists(PATH_FINANCE):
        pd.DataFrame(columns=["date","type","amount_usd","note","finance_id"]).to_csv(PATH_FINANCE, index=False)
    if not os.path.exists(PATH_CSFLOAT_SNAP):
        pd.DataFrame(columns=["snapshot_date","balance_usd"]).to_csv(PATH_CSFLOAT_SNAP, index=False)
    if not os.path.exists(PATH_FIN_BASELINE):
        # baseline par défaut = 0
        pd.DataFrame([{"baseline_date": date.today().strftime("%Y-%m-%d"),
                       "baseline_net_deposited_usd": 0.0,
                       "note": "init"}]).to_csv(PATH_FIN_BASELINE, index=False)

ensure_trades_exists()
ensure_finance_files_exist()

# ---------- Trades I/O ----------
def load_trades():
    try:
        return pd.read_csv(PATH_TRADES)
    except Exception:
        return pd.DataFrame(columns=["date","type","market_hash_name","qty","price_usd","note","trade_id"])

def save_trades(df, msg="update trades"):
    df.to_csv(PATH_TRADES, index=False)
    if GH_PAT and OWNER:
        _text, sha, _ = gh_get_file(PATH_TRADES)
        csv_buf = io.StringIO(); df.to_csv(csv_buf, index=False)
        resp = gh_put_file(PATH_TRADES, csv_buf.getvalue(), sha, msg)
        if 200 <= resp.status_code < 300:
            st.toast("Modifications sauvegardées sur GitHub.")
        else:
            st.error(f"Erreur GitHub: {resp.status_code}")

# ---------- Finance I/O ----------
def load_finances():
    try:
        return pd.read_csv(PATH_FINANCE)
    except Exception:
        return pd.DataFrame(columns=["date","type","amount_usd","note","finance_id"])

def save_finances(df, msg="update finances"):
    df.to_csv(PATH_FINANCE, index=False)
    if GH_PAT and OWNER:
        _text, sha, _ = gh_get_file(PATH_FINANCE)
        csv_buf = io.StringIO(); df.to_csv(csv_buf, index=False)
        resp = gh_put_file(PATH_FINANCE, csv_buf.getvalue(), sha, msg)
        if 200 <= resp.status_code < 300:
            st.toast("Mouvements financiers sauvegardés sur GitHub.")
        else:
            st.error(f"Erreur GitHub: {resp.status_code}")

def load_csfloat_snapshot():
    try:
        return pd.read_csv(PATH_CSFLOAT_SNAP)
    except Exception:
        return pd.DataFrame(columns=["snapshot_date","balance_usd"])

def save_csfloat_snapshot(df, msg="update csfloat snapshot"):
    df.to_csv(PATH_CSFLOAT_SNAP, index=False)
    if GH_PAT and OWNER:
        _text, sha, _ = gh_get_file(PATH_CSFLOAT_SNAP)
        csv_buf = io.StringIO(); df.to_csv(csv_buf, index=False)
        resp = gh_put_file(PATH_CSFLOAT_SNAP, csv_buf.getvalue(), sha, msg)
        if 200 <= resp.status_code < 300:
            st.toast("Snapshot CSFloat sauvegardé sur GitHub.")
        else:
            st.error(f"Erreur GitHub: {resp.status_code}")

def load_finance_baseline():
    try:
        return pd.read_csv(PATH_FIN_BASELINE)
    except Exception:
        return pd.DataFrame(columns=["baseline_date","baseline_net_deposited_usd","note"])

def save_finance_baseline(df, msg="update finance baseline"):
    df.to_csv(PATH_FIN_BASELINE, index=False)
    if GH_PAT and OWNER:
        _text, sha, _ = gh_get_file(PATH_FIN_BASELINE)
        csv_buf = io.StringIO(); df.to_csv(csv_buf, index=False)
        resp = gh_put_file(PATH_FIN_BASELINE, csv_buf.getvalue(), sha, msg)
        if 200 <= resp.status_code < 300:
            st.toast("Baseline (capital net déposé) sauvegardée sur GitHub.")
        else:
            st.error(f"Erreur GitHub: {resp.status_code}")

# ---------- Calcul holdings ----------
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
@st.cache_data(ttl=600)
def fetch_price(name):
    """Toujours basé sur le prix le plus bas."""
    if not CSFLOAT_API_KEY: return None
    params = {"market_hash_name": name, "limit": 1, "type": "buy_now", "sort_by": "lowest_price"}
    try:
        r = requests.get(CSFLOAT_API, headers=CSFLOAT_HEADERS, params=params, timeout=10)
        data = r.json()
        listings = data.get("data") or data
        if not listings: return None
        p = listings[0].get("price")
        return p/100 if p else None
    except Exception:
        return None

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
        if img.startswith("http"): return img
        return f"https://steamcommunity-a.akamaihd.net/economy/image/{img}/128fx128f"
    except Exception:
        return None

# ---------- Couleurs ----------
def _blend_to_pastel(hex_color, intensity):
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    wr, wg, wb = 255, 255, 255
    nr = int(wr + (r - wr) * intensity)
    ng = int(wg + (g - wg) * intensity)
    nb = int(wb + (b - wb) * intensity)
    return f"#{nr:02x}{ng:02x}{nb:02x}"

def _pnl_bg_color(value):
    base_green = "#22c55e"; base_red = "#ef4444"
    if value is None: return "#ffffff"
    if value >= 0: return _blend_to_pastel(base_green, min(0.15 + min(abs(value)/20000, 0.20), 0.45))
    return _blend_to_pastel(base_red, min(0.15 + min(abs(value)/20000, 0.20), 0.45))

def _pct_bg_color(pct):
    base_green = "#22c55e"; base_red = "#ef4444"
    try:
        if pct is None or pct == "" or pd.isna(pct) or not np.isfinite(pct) or abs(float(pct)) < 1e-4:
            return "#ffffff"
    except Exception:
        return "#ffffff"
    if pct >= 0:
        return _blend_to_pastel(base_green, 0.12 if pct < 5 else min(0.12 + pct/200, 0.40))
    ap = abs(pct)
    return _blend_to_pastel(base_red, 0.12 if ap < 5 else min(0.12 + ap/200, 0.40))

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

# ---------- Calculs "live" holdings + KPIs ----------
def enrich_holdings_live(holdings_df: pd.DataFrame):
    if holdings_df.empty:
        totals = {"total_val": 0.0, "total_cost": 0.0, "total_pnl": 0.0, "total_pct": 0.0}
        df = pd.DataFrame(columns=["market_hash_name","qty","buy_price_usd","buy_date","notes","Image","Prix actuel USD","valeur","gain","evolution_pct"])
        return df, totals
    df = holdings_df.copy()
    df["Image"] = df["market_hash_name"].apply(fetch_icon)
    df["Prix actuel USD"] = df["market_hash_name"].apply(fetch_price)
    df["valeur"] = df["Prix actuel USD"] * df["qty"]
    df["gain"] = (df["Prix actuel USD"] - df["buy_price_usd"]) * df["qty"]
    buy = pd.to_numeric(df["buy_price_usd"], errors="coerce")
    price_now = pd.to_numeric(df["Prix actuel USD"], errors="coerce")
    diff = price_now - buy
    evo_array = np.divide(diff.to_numpy(dtype="float64") * 100.0, buy.to_numpy(dtype="float64"),
                          out=np.full(diff.shape, np.nan, dtype="float64"),
                          where=(buy.to_numpy(dtype="float64") > 0))
    df["evolution_pct"] = pd.to_numeric(pd.Series(evo_array), errors="coerce").replace([np.inf, -np.inf], np.nan)
    total_val = df["valeur"].sum()
    total_cost = (df["buy_price_usd"] * df["qty"]).sum()
    total_pnl = total_val - total_cost
    total_pct = (total_pnl / total_cost * 100) if total_cost>0 else 0.0
    totals = {"total_val": float(total_val), "total_cost": float(total_cost), "total_pnl": float(total_pnl), "total_pct": float(total_pct)}
    return df, totals

# ---------- Calculs financiers globaux ----------
def compute_financials(trades_df: pd.DataFrame, finance_df: pd.DataFrame, snap_df: pd.DataFrame, baseline_df: pd.DataFrame):
    # Baseline (dernier enregistrement)
    baseline_df = baseline_df.copy()
    if not baseline_df.empty:
        baseline_df["baseline_date"] = pd.to_datetime(baseline_df["baseline_date"], errors="coerce")
        baseline_df = baseline_df.dropna(subset=["baseline_date"]).sort_values("baseline_date")
    baseline_val = float(baseline_df["baseline_net_deposited_usd"].iloc[-1]) if not baseline_df.empty else 0.0
    baseline_date = baseline_df["baseline_date"].iloc[-1] if not baseline_df.empty else None

    # Snapshot CSFloat (dernier)
    snap_df = snap_df.copy()
    if not snap_df.empty:
        snap_df["snapshot_date"] = pd.to_datetime(snap_df["snapshot_date"], errors="coerce")
        snap_df = snap_df.dropna(subset=["snapshot_date"]).sort_values("snapshot_date")
    snapshot_bal = float(snap_df["balance_usd"].iloc[-1]) if not snap_df.empty else 0.0
    snapshot_date = snap_df["snapshot_date"].iloc[-1] if not snap_df.empty else None

    # Achats/ventes depuis snapshot
    td = trades_df.copy()
    td["date"] = pd.to_datetime(td["date"], errors="coerce")
    if snapshot_date is not None:
        td = td[td["date"] >= snapshot_date]
    buys_usd  = (td[td["type"]=="BUY"]["qty"]  * td[td["type"]=="BUY"]["price_usd"]).sum()
    sells_usd = (td[td["type"]=="SELL"]["qty"] * td[td["type"]=="SELL"]["price_usd"]).sum()

    # Dépôts / retraits : somme "mouvements" (depuis toujours) et "depuis snapshot"
    fin = finance_df.copy()
    if not fin.empty:
        fin["date"] = pd.to_datetime(fin["date"], errors="coerce")

    def _mov_sum(df):
        if df.empty: return 0.0
        return df.apply(lambda r: r["amount_usd"] if r.get("type")=="DEPOSIT" else (-r["amount_usd"] if r.get("type")=="WITHDRAW" else 0.0), axis=1).sum()

    mov_all   = _mov_sum(fin) if not fin.empty else 0.0
    if snapshot_date is not None and not fin.empty:
        mov_since = _mov_sum(fin[fin["date"] >= snapshot_date])
    else:
        mov_since = mov_all

    # Capital net déposé (lifetime) = baseline + mouvements saisis dans l'app
    net_deposited_all = float(baseline_val + mov_all)
    net_deposited_since = float(mov_since)

    # Solde CSFloat attendu = snapshot + dépôts_nets_depuis_snapshot + ventes - achats
    csfloat_cash_expected = float(snapshot_bal + net_deposited_since + sells_usd - buys_usd)

    # P&L réalisé (WAC simplifié, info seulement)
    pnl_real = 0.0
    for _, row in trades_df[trades_df["type"]=="SELL"].iterrows():
        name = row["market_hash_name"]; qty_s = row["qty"]; price_s = row["price_usd"]
        sub = trades_df[(trades_df["market_hash_name"]==name)&(trades_df["type"]=="BUY")]
        cost = (sub["qty"]*sub["price_usd"]).sum(); q = sub["qty"].sum()
        pru = cost/q if q>0 else 0.0
        pnl_real += (price_s - pru)*qty_s

    return {
        "baseline_val": float(baseline_val),
        "baseline_date": baseline_date,
        "snapshot_date": snapshot_date,
        "snapshot_bal": float(snapshot_bal),
        "net_deposited_all": float(net_deposited_all),
        "net_deposited_since": float(net_deposited_since),
        "buys_usd_since": float(buys_usd),
        "sells_usd_since": float(sells_usd),
        "csfloat_cash_expected": float(csfloat_cash_expected),
        "pnl_realized": float(pnl_real),
    }

# ---------- Sidebar ----------
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
                st.error(f"Échec ({resp.status_code}) : {resp.text[:200]}")

# ---------- Data chargées en amont ----------
trades = load_trades()
holdings_base = rebuild_holdings(trades)
holdings_live, totals = enrich_holdings_live(holdings_base)
total_val  = totals["total_val"]
total_cost = totals["total_cost"]
total_pnl  = totals["total_pnl"]
total_pct  = totals["total_pct"]

# ---------- UI ----------
tab1, tab2, tab3, tab4 = st.tabs(["Portefeuille", "Achat / Vente", "Transactions", "Statistiques financières"])

# ---------- Onglet 1 : Portefeuille ----------
with tab1:
    st.subheader("Portefeuille actuel")
    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

    if holdings_live.empty:
        st.info("Aucune position.")
    else:
        col1, col2, col3, col4 = st.columns(4)
        col1.markdown(f"""
        <div class="kpi-card">
          <div class="kpi-title">Valeur portefeuille</div>
          <div class="kpi-value">${total_val:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
        col2.markdown(f"""
        <div class="kpi-card" style="background:{_blend_to_pastel('#3b82f6',0.10)}">
          <div class="kpi-title">Coût total</div>
          <div class="kpi-value">${total_cost:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
        col3.markdown(f"""
        <div class="kpi-card" style="background:{_pnl_bg_color(total_pnl)}">
          <div class="kpi-title">P&L latent</div>
          <div class="kpi-value">${total_pnl:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
        col4.markdown(f"""
        <div class="kpi-card" style="background:{_pct_bg_color(total_pct)}">
          <div class="kpi-title">% d’évolution</div>
          <div class="kpi-value">{total_pct:,.2f}%</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="section-gap-lg"></div>', unsafe_allow_html=True)

        to_show = holdings_live[["Image","market_hash_name","qty","buy_price_usd","Prix actuel USD","gain","evolution_pct"]].rename(
            columns={
                "market_hash_name":"Item",
                "qty":"Quantité",
                "buy_price_usd":"Prix achat USD",
                "Prix actuel USD":"Prix vente USD",
                "gain":"Gain latent USD",
                "evolution_pct":"% évolution"
            }
        )
        to_show["Image"] = to_show["Image"].fillna("").astype(str)

        def _evo_style(val):
            return f"background-color: {_pct_bg_color(val)};"

        styler = (
            to_show.style
            .format({
                "Prix achat USD": "${:,.2f}",
                "Prix vente USD": "${:,.2f}",
                "Gain latent USD": "${:,.2f}",
                "% évolution": "{:,.2f}%"
            })
            .map(lambda v: _evo_style(v), subset=["% évolution"])
        )

        st.dataframe(
            styler,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Image": st.column_config.ImageColumn("Image", width="small"),
                "Item": "Item",
                "Quantité": st.column_config.NumberColumn("Quantité", format="%d"),
                "Prix achat USD": st.column_config.NumberColumn("Prix achat USD", format="$%.2f"),
                "Prix vente USD": st.column_config.NumberColumn("Prix vente USD", format="$%.2f"),
                "Gain latent USD": st.column_config.NumberColumn("Gain latent USD", format="$%.2f"),
                "% évolution": st.column_config.NumberColumn("% évolution", format="%.2f%%"),
            }
        )

        st.markdown('<div class="section-gap-lg"></div>', unsafe_allow_html=True)

        st.markdown("### Évolution de la valeur du portefeuille")
        hist_df = load_price_history_df()
        ts = build_portfolio_timeseries(holdings_df=holdings_base, hist_df=hist_df)
        if ts.empty:
            st.info("Pas encore assez d’historique pour tracer la courbe.")
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
        st.metric("P&L réalisé cumulé (WAC)", f"${pnl_real:,.2f}")

        to_display = trades.sort_values("date", ascending=False)
        delete_id = st.text_input("ID de transaction à supprimer (trade_id)")
        if st.button("Supprimer"):
            if delete_id in trades["trade_id"].values:
                trades = trades[trades["trade_id"]!=delete_id]
                save_trades(trades, f"delete trade {delete_id}")
                st.success(f"Transaction {delete_id} supprimée."); st.cache_data.clear(); st.rerun()
            else:
                st.error("ID introuvable.")
        st.dataframe(to_display, use_container_width=True, hide_index=True)

# ---------- Onglet 4 : Statistiques financières ----------
with tab4:
    st.subheader("Statistiques financières")
    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

    finances = load_finances()
    cs_snap  = load_csfloat_snapshot()
    fin_base = load_finance_baseline()

    # ---- Baseline (capital net déposé lifetime) ----
    with st.expander("⚙️ Ajuster le capital net déposé (lifetime) — baseline"):
        current_baseline = float(fin_base["baseline_net_deposited_usd"].iloc[-1]) if not fin_base.empty else 0.0
        st.info(f"Baseline actuelle : ${current_baseline:,.2f}")
        bcol1, bcol2, bcol3 = st.columns(3)
        base_date = bcol1.date_input("Date baseline", value=date.today())
        base_val  = bcol2.number_input("NOUVELLE baseline (USD)", min_value=0.0, step=0.01)
        base_note = bcol3.text_input("Note (optionnel)")
        if st.button("Enregistrer la baseline"):
            df = fin_base.copy()
            row = {"baseline_date": pd.to_datetime(base_date).strftime("%Y-%m-%d"),
                   "baseline_net_deposited_usd": base_val,
                   "note": base_note}
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            save_finance_baseline(df, "update baseline net deposited")
            st.success("Baseline enregistrée."); st.rerun()

        if st.button("Baseliner sur les mouvements actuels (conseil: pour repartir propre)"):
            # met la baseline = somme actuelle des mouvements saisis (DEPOSIT-WITHDRAW)
            if finances.empty:
                new_val = 0.0
            else:
                finances["date"] = pd.to_datetime(finances["date"], errors="coerce")
                def _mov_sum(df):
                    return df.apply(lambda r: r["amount_usd"] if r["type"]=="DEPOSIT" else (-r["amount_usd"] if r["type"]=="WITHDRAW" else 0.0), axis=1).sum()
                new_val = float(_mov_sum(finances))
            df = fin_base.copy()
            row = {"baseline_date": date.today().strftime("%Y-%m-%d"),
                   "baseline_net_deposited_usd": new_val,
                   "note": "baseline = somme mouvements actuels"}
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            save_finance_baseline(df, "baseline set to current movements sum")
            st.success(f"Baseline mise à ${new_val:,.2f}."); st.rerun()

    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

    # ---- Snapshot CSFloat ----
    with st.expander("📌 Définir / Mettre à jour le snapshot CSFloat (solde constaté sur la plateforme)"):
        colA, colB = st.columns(2)
        snap_date = colA.date_input("Date du snapshot", value=date.today())
        snap_bal  = colB.number_input("Solde CSFloat constaté (USD)", min_value=0.0, step=0.01)
        if st.button("Enregistrer le snapshot CSFloat"):
            df = load_csfloat_snapshot()
            df = pd.concat([df, pd.DataFrame([{
                "snapshot_date": pd.to_datetime(snap_date).strftime("%Y-%m-%d"),
                "balance_usd": snap_bal
            }])], ignore_index=True)
            save_csfloat_snapshot(df, "add csfloat snapshot")
            st.success("Snapshot CSFloat enregistré."); st.rerun()

    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

    # ---- Mouvements d'argent ----
    with st.expander("💸 Ajouter un mouvement (DEPOSIT / WITHDRAW)"):
        fcol1, fcol2, fcol3 = st.columns(3)
        f_date = fcol1.date_input("Date", value=date.today())
        f_type = fcol2.radio("Type", ["DEPOSIT","WITHDRAW"], horizontal=True)
        f_amt  = fcol3.number_input("Montant USD", min_value=0.0, step=0.01)
        f_note = st.text_input("Note (optionnel)")
        if st.button("Enregistrer le mouvement"):
            if f_amt <= 0:
                st.error("Montant invalide.")
            else:
                new_fin = pd.DataFrame([{
                    "date": pd.to_datetime(f_date).strftime("%Y-%m-%d"),
                    "type": f_type,
                    "amount_usd": f_amt,
                    "note": f_note,
                    "finance_id": "fin_" + uuid.uuid4().hex[:8]
                }])
                finances = pd.concat([finances, new_fin], ignore_index=True)
                save_finances(finances, f"add {f_type} {f_amt}")
                st.success("Mouvement enregistré."); st.rerun()

    # ---- Calculs KPI ----
    fin = compute_financials(trades, finances, cs_snap, fin_base)

    account_equity = fin["csfloat_cash_expected"] + float(total_val)  # Cash attendu + valeur positions (live)
    true_profit    = account_equity - fin["net_deposited_all"]       # “vrai bénéfice” = Equity - capital net déposé (lifetime)

    # KPI cards
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(f"""
      <div class="kpi-card">
        <div class="kpi-title">Capital net déposé (lifetime)</div>
        <div class="kpi-value">${fin["net_deposited_all"]:,.2f}</div>
      </div>
    """, unsafe_allow_html=True)
    k2.markdown(f"""
      <div class="kpi-card">
        <div class="kpi-title">Cash CSFloat attendu</div>
        <div class="kpi-value">${fin["csfloat_cash_expected"]:,.2f}</div>
      </div>
    """, unsafe_allow_html=True)
    k3.markdown(f"""
      <div class="kpi-card">
        <div class="kpi-title">Equity (Cash + Valeur positions)</div>
        <div class="kpi-value">${account_equity:,.2f}</div>
      </div>
    """, unsafe_allow_html=True)
    k4.markdown(f"""
      <div class="kpi-card" style="background:{_pnl_bg_color(true_profit)}">
        <div class="kpi-title">Vrai bénéfice</div>
        <div class="kpi-value">${true_profit:,.2f}</div>
      </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

    # Détails et vérifications
    st.markdown("#### Détails & Reconcil")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Snapshot CSFloat", f"${fin['snapshot_bal']:,.2f}",
              delta=f"au {fin['snapshot_date'].date()}" if fin["snapshot_date"] is not None else None)
    c2.metric("Dépôts nets depuis snapshot", f"${fin['net_deposited_since']:,.2f}")
    c3.metric("Ventes depuis snapshot", f"${fin['sells_usd_since']:,.2f}")
    c4.metric("Achats depuis snapshot", f"${fin['buys_usd_since']:,.2f}")

    b1, b2, b3 = st.columns(3)
    b1.metric("Baseline (capital net déposé)", f"${fin['baseline_val']:,.2f}",
              delta=f"depuis {fin['baseline_date'].date()}" if fin["baseline_date"] is not None else None)
    contrib_mov = fin["net_deposited_all"] - fin["baseline_val"]
    b2.metric("Mouvements saisis (depuis toujours)", f"${contrib_mov:,.2f}")
    b3.metric("Equity - Net Deposited (= Vrai bénéfice)", f"${(account_equity - fin['net_deposited_all']):,.2f}")

    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

    # Tableau des mouvements + suppression
    st.markdown("### Mouvements enregistrés")
    if finances.empty:
        st.info("Aucun mouvement enregistré.")
    else:
        fin_display = finances.sort_values("date", ascending=False).copy()
        del_id = st.text_input("ID de mouvement à supprimer (finance_id)")
        if st.button("Supprimer le mouvement"):
            if del_id in finances["finance_id"].values:
                finances = finances[finances["finance_id"] != del_id]
                save_finances(finances, f"delete finance {del_id}")
                st.success(f"Mouvement {del_id} supprimé."); st.cache_data.clear(); st.rerun()
            else:
                st.error("ID introuvable.")
        st.dataframe(fin_display, use_container_width=True, hide_index=True)
