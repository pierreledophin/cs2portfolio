import io, os, base64, json, uuid, requests, pandas as pd, numpy as np, streamlit as st
import streamlit.components.v1 as components
from datetime import datetime

# ---------- Configuration ----------
st.set_page_config(page_title="CS2 Portfolio (CSFloat)", layout="wide")

# ---------- Style global ----------
st.markdown("""
<style>
.block-container { padding-top: 1.6rem; padding-bottom: 1.6rem; }
h1, h2, h3 { letter-spacing: .2px; }
h1 { margin-bottom: .6rem !important; }
h2, h3 { margin-top: 1.0rem !important; margin-bottom: .6rem !important; }

/* Cards KPI */
.kpi-card {
  border-radius: 16px;
  padding: 16px 18px;
  border: 1px solid rgba(0,0,0,.05);
  box-shadow: 0 6px 20px rgba(0,0,0,.03);
  background: #ffffff;
  margin-bottom: 14px;
}
.kpi-title {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: .6px;
}
.kpi-value {
  font-size: 22px;
  font-weight: 700;
}
.stRadio {
  padding: 8px 10px;
  border-radius: 12px;
  border: 1px solid rgba(0,0,0,.06);
  background: #fafafa;
  margin-bottom: 12px;
}
[data-testid="stHorizontalBlock"] .stRadio > label { font-weight: 600; }

[data-baseweb="tab-list"] { gap: 8px; margin-bottom: 8px; }

/* Table custom */
.table-wrap { width: 100%; overflow-x: auto; }
.table-positions {
  width: 100%; border-collapse: collapse;
  font-size: 14px; margin-top: 6px;
}
.table-positions thead th {
  background: #f8fafc;
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid #e5e7eb;
  font-weight: 600;
  color: #334155;
}
.table-positions tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}
.table-positions tbody tr:hover td { background: #fafafa; }
.img-cell img {
  width: 40px; height: 40px;
  object-fit: cover; border-radius: 8px;
  border: 1px solid rgba(0,0,0,.06);
}
.badge {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 10px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.cell-right { text-align: right; }
.section-gap { height: 12px; }
.section-gap-lg { height: 18px; }
</style>
""", unsafe_allow_html=True)

st.markdown("<h1 style='margin-bottom:0'>CS2 Portfolio Tracker</h1>", unsafe_allow_html=True)

# ---------- Secrets & API ----------
OWNER   = st.secrets.get("GH_OWNER", "")
REPO    = st.secrets.get("GH_REPO", "")
BRANCH  = st.secrets.get("GH_BRANCH", "main")
GH_PAT  = st.secrets.get("GH_PAT")
CSFLOAT_API_KEY = st.secrets.get("CSFLOAT_API_KEY")
CSFLOAT_API = "https://csfloat.com/api/v1/listings"
CSFLOAT_HEADERS = {"Authorization": CSFLOAT_API_KEY} if CSFLOAT_API_KEY else {}

# ---------- Profil ----------
PROFILES = ["pierre", "elenocames"]
profile = st.radio("Profil", PROFILES, horizontal=True, key="profile_select")

DATA_DIR = f"data/{profile}"
os.makedirs(DATA_DIR, exist_ok=True)
PATH_TRADES = f"{DATA_DIR}/trades.csv"
PATH_HOLDINGS = f"{DATA_DIR}/holdings.csv"
PATH_HISTORY = f"{DATA_DIR}/price_history.csv"

# ---------- Fonctions GitHub ----------
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
    payload = {"message": message, "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
               "branch": BRANCH, "sha": sha}
    return requests.put(url, headers=_gh_headers(), data=json.dumps(payload), timeout=20)

# ---------- Fichiers locaux ----------
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
        csv_buf = io.StringIO()
        df.to_csv(csv_buf, index=False)
        gh_put_file(PATH_TRADES, csv_buf.getvalue(), sha, msg)

# ---------- Fonctions principales ----------
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

# ---------- API CSFloat ----------
@st.cache_data(ttl=600)
def fetch_price(name):
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
        if isinstance(img, str) and img.startswith("http"): return img
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
    if value >= 0: return _blend_to_pastel(base_green, 0.2)
    return _blend_to_pastel(base_red, 0.2)

def _pct_bg_color(pct):
    base_green = "#22c55e"; base_red = "#ef4444"
    try:
        if pct is None or pct == "" or pd.isna(pct) or not np.isfinite(pct) or abs(float(pct)) < 1e-4:
            return "#ffffff"
    except Exception:
        return "#ffffff"
    if pct >= 0:
        return _blend_to_pastel(base_green, 0.12 if pct < 5 else 0.3)
    ap = abs(pct)
    return _blend_to_pastel(base_red, 0.12 if ap < 5 else 0.3)

# ---------- Rendu HTML ----------
def render_positions_table(df: pd.DataFrame):
    cols = ["Image","Item","Quantité","Prix achat USD","Prix vente USD","Gain latent USD","% évolution"]
    if not all(c in df.columns for c in cols):
        st.warning("Colonnes manquantes pour le rendu du tableau.")
        return
    rows_html = []
    for _, r in df.iterrows():
        img = r["Image"] if isinstance(r["Image"], str) else ""
        evo = r["% évolution"]
        bg = _pct_bg_color(evo)
        evo_txt = f"{evo:,.2f}%" if (pd.notna(evo) and np.isfinite(evo)) else "—"
        rows_html.append(f"""
        <tr>
          <td class="img-cell">{f'<img src="{img}" alt="">' if img else ''}</td>
          <td>{r["Item"]}</td>
          <td class="cell-right">{r["Quantité"]}</td>
          <td class="cell-right">${r["Prix achat USD"]:,.2f}</td>
          <td class="cell-right">${r["Prix vente USD"]:,.2f}</td>
          <td class="cell-right">${r["Gain latent USD"]:,.2f}</td>
          <td class="cell-right"><span class="badge" style="background:{bg}">{evo_txt}</span></td>
        </tr>
        """)
    html = f"""
    <div class="table-wrap">
      <table class="table-positions">
        <thead>
          <tr>
            <th>Image</th><th>Item</th><th>Quantité</th>
            <th>Prix achat USD</th><th>Prix vente USD</th><th>Gain latent USD</th><th>% évolution</th>
          </tr>
        </thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
    </div>
    """
    components.html(html, height=500, scrolling=True)

# ---------- UI ----------
tab1, tab2, tab3 = st.tabs(["Portefeuille", "Achat / Vente", "Transactions"])
trades = load_trades()

with tab1:
    st.subheader("Portefeuille actuel")
    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

    holdings = rebuild_holdings(trades)
    if holdings.empty:
        st.info("Aucune position.")
        st.stop()

    holdings["Image"] = holdings["market_hash_name"].apply(fetch_icon)
    holdings["Prix actuel USD"] = holdings["market_hash_name"].apply(fetch_price)
    holdings["valeur"] = holdings["Prix actuel USD"] * holdings["qty"]
    holdings["gain"] = (holdings["Prix actuel USD"] - holdings["buy_price_usd"]) * holdings["qty"]

    buy = pd.to_numeric(holdings["buy_price_usd"], errors="coerce")
    price_now = pd.to_numeric(holdings["Prix actuel USD"], errors="coerce")
    diff = price_now - buy
    evo_array = np.divide(diff*100, buy, out=np.full(diff.shape, np.nan), where=(buy>0))
    holdings["evolution_pct"] = pd.to_numeric(evo_array, errors="coerce").replace([np.inf, -np.inf], np.nan)

    total_val = holdings["valeur"].sum()
    total_cost = (holdings["buy_price_usd"] * holdings["qty"]).sum()
    total_pnl = total_val - total_cost
    total_pct = (total_pnl / total_cost * 100) if total_cost>0 else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(f"<div class='kpi-card'><div class='kpi-title'>Valeur portefeuille</div><div class='kpi-value'>${total_val:,.2f}</div></div>", unsafe_allow_html=True)
    col2.markdown(f"<div class='kpi-card' style='background:{_blend_to_pastel('#3b82f6',0.10)})'><div class='kpi-title'>Coût total</div><div class='kpi-value'>${total_cost:,.2f}</div></div>", unsafe_allow_html=True)
    col3.markdown(f"<div class='kpi-card' style='background:{_pnl_bg_color(total_pnl)}'><div class='kpi-title'>P&L latent</div><div class='kpi-value'>${total_pnl:,.2f}</div></div>", unsafe_allow_html=True)
    col4.markdown(f"<div class='kpi-card' style='background:{_pct_bg_color(total_pct)}'><div class='kpi-title'>% d’évolution</div><div class='kpi-value'>{total_pct:,.2f}%</div></div>", unsafe_allow_html=True)

    st.markdown('<div class="section-gap-lg"></div>', unsafe_allow_html=True)

    to_show = holdings[["Image","market_hash_name","qty","buy_price_usd","Prix actuel USD","gain","evolution_pct"]].rename(
        columns={
            "market_hash_name": "Item",
            "qty": "Quantité",
            "buy_price_usd": "Prix achat USD",
            "Prix actuel USD": "Prix vente USD",
            "gain": "Gain latent USD",
            "evolution_pct": "% évolution",
        }
    ).copy()
    to_show["Image"] = to_show["Image"].fillna("").astype(str)
    render_positions_table(to_show)
