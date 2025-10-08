import io, os, base64, json, uuid, requests, pandas as pd, streamlit as st
from datetime import datetime

# ---------- Configuration ----------
st.set_page_config(page_title="CS2 Portfolio (CSFloat)", layout="wide")

# --- Style global : plus d'espaces + couleurs très douces ---
st.markdown("""
<style>
/* Container & espacements globaux */
.block-container { 
  padding-top: 1.6rem; 
  padding-bottom: 1.6rem; 
}

/* Titres & marges */
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
  margin-bottom: 14px; /* espace entre cartes et contenu suivant */
}
.kpi-title {
  font-size: 12px;
  color: #6b7280; /* slate-500 */
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: .6px;
}
.kpi-value {
  font-size: 22px;
  font-weight: 700;
}

/* Segmented profil (radio) + espacement autour */
.stRadio { 
  padding: 8px 10px;
  border-radius: 12px;
  border: 1px solid rgba(0,0,0,.06);
  background: #fafafa;
  margin-bottom: 12px;
}
[data-testid="stHorizontalBlock"] .stRadio > label { font-weight: 600; }

/* Tabs : un peu d'air */
[data-baseweb="tab-list"] { gap: 8px; margin-bottom: 8px; }

/* Table: léger padding de cellule via override */
.stDataFrame td, .stDataFrame th { padding-top: 10px !important; padding-bottom: 10px !important; }

/* Petits espacers entre sections */
.section-gap { height: 12px; }
.section-gap-lg { height: 18px; }
</style>
""", unsafe_allow_html=True)

st.markdown("<h1 style='margin-bottom:0'>CS2 Portfolio Tracker</h1>", unsafe_allow_html=True)

OWNER   = st.secrets.get("GH_OWNER", "")
REPO    = st.secrets.get("GH_REPO", "")
BRANCH  = st.secrets.get("GH_BRANCH", "main")
GH_PAT  = st.secrets.get("GH_PAT")  # pour écrire sur GitHub
CSFLOAT_API_KEY = st.secrets.get("CSFLOAT_API_KEY")
CSFLOAT_API = "https://csfloat.com/api/v1/listings"
CSFLOAT_HEADERS = {"Authorization": CSFLOAT_API_KEY} if CSFLOAT_API_KEY else {}

PROFILES = ["pierre", "elenocames"]

# ---- Profil : radio horizontale (non éditable) ----
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
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": BRANCH,
        "sha": sha,
    }
    r = requests.put(url, headers=_gh_headers(), data=json.dumps(payload), timeout=20)
    return r

# ---------- Initialisation trades ----------
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
    # push sur GitHub si PAT présent
    if GH_PAT and OWNER:
        text, sha, _ = gh_get_file(PATH_TRADES)
        csv_buf = io.StringIO()
        df.to_csv(csv_buf, index=False)
        resp = gh_put_file(PATH_TRADES, csv_buf.getvalue(), sha, msg)
        if 200 <= resp.status_code < 300:
            st.toast("Modifications sauvegardées sur GitHub.")
        else:
            st.error(f"Erreur GitHub: {resp.status_code}")

# ---------- Fonctions de calcul ----------
def rebuild_holdings(trades: pd.DataFrame):
    """Reconstruit holdings.csv à partir des trades."""
    if trades.empty:
        pd.DataFrame(columns=["market_hash_name","qty","buy_price_usd","buy_date","notes"]).to_csv(PATH_HOLDINGS,index=False)
        return pd.DataFrame()
    holdings = []
    grouped = trades.groupby("market_hash_name")
    for name, g in grouped:
        buys = g[g["type"]=="BUY"].copy()
        sells = g[g["type"]=="SELL"].copy()
        total_buy = buys["qty"].sum()
        total_sell = sells["qty"].sum()
        remaining = total_buy - total_sell
        if remaining > 0:
            # PRU moyen
            cost = (buys["qty"] * buys["price_usd"]).sum()
            pru = cost / total_buy if total_buy>0 else 0
            holdings.append([name, remaining, pru, buys.iloc[-1]["date"], ""])
    df = pd.DataFrame(holdings, columns=["market_hash_name","qty","buy_price_usd","buy_date","notes"])
    df.to_csv(PATH_HOLDINGS, index=False)
    return df

# ---------- API CSFloat ----------
@st.cache_data(ttl=3600)
def fetch_icon(name):
    if not CSFLOAT_API_KEY:
        return None
    params = {"market_hash_name": name, "limit": 1, "expand": "item"}
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

@st.cache_data(ttl=600)
def fetch_price(name):
    if not CSFLOAT_API_KEY:
        return None
    params = {"market_hash_name": name, "limit": 1, "type":"buy_now"}
    try:
        r = requests.get(CSFLOAT_API, headers=CSFLOAT_HEADERS, params=params, timeout=10)
        data = r.json()
        listings = data.get("data") or data
        if not listings: return None
        p = listings[0].get("price")
        return p/100 if p else None
    except Exception:
        return None

# ---------- Helpers UI (couleurs + plus clair) ----------
def _blend_to_pastel(hex_color, intensity):
    """
    Mélange une couleur hex avec du blanc pour rester très pastel.
    intensity ∈ [0,1] (0 = très clair, 1 = plus soutenu).
    """
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    wr, wg, wb = 255, 255, 255
    nr = int(wr + (r - wr) * intensity)
    ng = int(wg + (g - wg) * intensity)
    nb = int(wb + (b - wb) * intensity)
    return f"#{nr:02x}{ng:02x}{nb:02x}"

def _pnl_bg_color(value):
    # vert pour positif, rouge pour négatif — intensité plus faible (très pastel)
    base_green = "#22c55e"
    base_red   = "#ef4444"
    if value is None:
        return "#ffffff"
    if value >= 0:
        # cap entre 0.15 et 0.45 pour rester doux
        return _blend_to_pastel(base_green, min(0.15 + min(abs(value)/20000, 0.20), 0.45))
    else:
        return _blend_to_pastel(base_red, min(0.15 + min(abs(value)/20000, 0.20), 0.45))

def _pct_bg_color(pct):
    base_green = "#22c55e"
    base_red   = "#ef4444"
    if pct is None:
        return "#ffffff"
    # très clair si <5%, et globalement plus pastel
    if pct >= 0:
        return _blend_to_pastel(base_green, 0.12 if pct < 5 else min(0.12 + pct/200, 0.40))
    else:
        ap = abs(pct)
        return _blend_to_pastel(base_red, 0.12 if ap < 5 else min(0.12 + ap/200, 0.40))

# ---------- Interface ----------
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

    # % d'évolution (par ligne)
    holdings["evolution_pct"] = (
        (holdings["Prix actuel USD"] - holdings["buy_price_usd"]) / holdings["buy_price_usd"] * 100
    ).fillna(0.0)

    total_val = holdings["valeur"].sum()
    total_cost = (holdings["buy_price_usd"] * holdings["qty"]).sum()
    total_pnl = total_val - total_cost
    total_pct = (total_pnl / total_cost * 100) if total_cost>0 else 0

    # KPIs en encadrés, couleurs très claires
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

    # Tableau : % évolution + coloration très douce
    to_show = holdings[[
        "Image","market_hash_name","qty","buy_price_usd","Prix actuel USD","gain","evolution_pct"
    ]].rename(columns={
        "market_hash_name":"Item",
        "qty":"Quantité",
        "buy_price_usd":"Prix achat USD",
        "Prix actuel USD":"Prix vente USD",
        "gain":"Gain latent USD",
        "evolution_pct":"% évolution"
    })

    def _evo_style(val):
        bg = _pct_bg_color(val)
        return f"background-color: {bg};"

    styler = (to_show.style
              .format({
                  "Prix achat USD": "${:,.2f}",
                  "Prix vente USD": "${:,.2f}",
                  "Gain latent USD": "${:,.2f}",
                  "% évolution": "{:,.2f}%"
              })
              .applymap(_evo_style, subset=["% évolution"])
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
                "type": t_type,
                "market_hash_name": name,
                "qty": qty,
                "price_usd": price,
                "note": note,
                "trade_id": "trd_" + uuid.uuid4().hex[:8]
            }])
            trades = pd.concat([trades, new_trade], ignore_index=True)
            save_trades(trades, f"add {t_type} {name}")
            st.success("Transaction enregistrée.")
            st.cache_data.clear()
            st.rerun()

# ---------- Onglet 3 : Transactions ----------
with tab3:
    st.subheader("Historique des transactions")
    st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

    if trades.empty:
        st.info("Aucune transaction.")
    else:
        # Calcul P&L réalisé sur les ventes
        pnl_real = 0
        for _, row in trades[trades["type"]=="SELL"].iterrows():
            name = row["market_hash_name"]
            qty_s = row["qty"]
            price_s = row["price_usd"]
            # coût moyen à date de vente
            sub = trades[(trades["market_hash_name"]==name)&(trades["type"]=="BUY")]
            cost = (sub["qty"]*sub["price_usd"]).sum()
            q = sub["qty"].sum()
            pru = cost/q if q>0 else 0
            pnl_real += (price_s - pru)*qty_s

        st.metric("P&L réalisé cumulé", f"${pnl_real:,.2f}")
        st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)

        to_display = trades.copy()
        to_display = to_display.sort_values("date", ascending=False)
        delete_id = st.text_input("ID de transaction à supprimer (trade_id)")
        if st.button("Supprimer cette transaction"):
            if delete_id in trades["trade_id"].values:
                trades = trades[trades["trade_id"]!=delete_id]
                save_trades(trades, f"delete trade {delete_id}")
                st.success(f"Transaction {delete_id} supprimée.")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("ID introuvable.")

        st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
        st.dataframe(to_display, use_container_width=True, hide_index=True)
