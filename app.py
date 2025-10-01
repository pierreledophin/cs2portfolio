import io
import base64
import json
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
GH_PAT  = st.secrets.get("GH_PAT")      # requis pour éditer/sauvegarder si repo privé (ou si on veut écrire)

# API CSFloat pour récupérer les miniatures (facultatif mais recommandé)
CSFLOAT_API_KEY = st.secrets.get("CSFLOAT_API_KEY")
CSFLOAT_API = "https://csfloat.com/api/v1/listings"
CSFLOAT_HEADERS = {"Authorization": CSFLOAT_API_KEY} if CSFLOAT_API_KEY else {}

PATH_HISTORY  = "data/price_history.csv"
PATH_HOLDINGS = "data/holdings.csv"

# ---------- GitHub helpers ----------
def _raw_url(path: str) -> str:
    return f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{path}"

def _gh_headers():
    return {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json",
    }

def gh_get_file(path: str):
    """Lit un fichier via l'API GitHub (retourne text, sha, status_code)."""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}?ref={BRANCH}"
    r = requests.get(url, headers=_gh_headers(), timeout=20)
    if r.status_code != 200:
        return "", None, r.status_code
    j = r.json()
    content_b64 = j.get("content") or ""
    sha = j.get("sha")
    try:
        raw = base64.b64decode(content_b64).decode("utf-8")
    except Exception:
        raw = ""
    return raw, sha, r.status_code

def gh_put_file(path: str, new_text: str, sha: str, message: str):
    """Ecrit/maj un fichier via l'API GitHub (PUT contents)."""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(new_text.encode("utf-8")).decode("ascii"),
        "branch": BRANCH,
        "sha": sha,  # requis pour update (évite l'écrasement)
    }
    r = requests.put(url, headers=_gh_headers(), data=json.dumps(payload), timeout=20)
    return r

def read_github_csv(path: str) -> tuple[pd.DataFrame, dict]:
    """
    Lecture CSV : si GH_PAT dispo -> API (privé/public), sinon -> RAW (public).
    Retourne (DataFrame, infos_debug).
    """
    info = {"mode": None, "status": None, "bytes": 0, "path": path}

    # Mode API si PAT (marche pour privé/public)
    if GH_PAT and OWNER and REPO and BRANCH:
        text, sha, status = gh_get_file(path)
        info["mode"] = "github_api"
        info["status"] = status
        info["sha"] = sha
        if status == 200 and text.strip():
            info["bytes"] = len(text.encode("utf-8"))
            return pd.read_csv(io.StringIO(text)), info

    # Fallback RAW (public)
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

# ---------- Sidebar ----------
with st.sidebar:
    if st.button("Recharger les CSV depuis GitHub"):
        st.cache_data.clear()
        st.rerun()

# ---------- Charge data ----------
hist, holds, info_hist, info_holds = load_all()

with st.expander("Debug (utile si rien ne s'affiche)"):
    st.write("price_history.csv →", info_hist)
    st.write("holdings.csv →", info_holds)
    st.write("Owner/Repo/Branch:", OWNER, REPO, BRANCH)
    st.write("CSFLOAT_API_KEY présent :", bool(CSFLOAT_API_KEY))
    st.write("GH_PAT présent (édition possible) :", bool(GH_PAT))

# ---------- Historique requis ----------
if hist.empty:
    st.warning(
        "Aucun historique. Vérifie : 1) `data/price_history.csv`, 2) GH_OWNER/GH_REPO/GH_BRANCH, "
        "3) si repo privé → ajouter GH_PAT (Streamlit secrets)."
    )
    st.stop()

# Normalisation colonnes historiques
if "price_usd" not in hist.columns and "price_cents" in hist.columns:
    hist["price_usd"] = pd.to_numeric(hist["price_cents"], errors="coerce") / 100.0
needed_hist_cols = {"ts_utc", "market_hash_name", "price_usd"}
if not needed_hist_cols.issubset(set(hist.columns)):
    st.info("price_history.csv ne contient pas ts_utc, market_hash_name, price_usd/price_cents.")
    st.stop()

# Dernier prix par item
last = (
    hist.sort_values(["market_hash_name", "ts_utc"])
        .groupby("market_hash_name", as_index=False)
        .tail(1)
        .rename(columns={"price_usd": "latest_price_usd"})
)

# ---------- Portefeuille (P&L) ----------
st.markdown("## Portefeuille (P&L)")

if holds.empty:
    st.info("`data/holdings.csv` est vide. Ajoute tes achats (market_hash_name, qty, buy_price_usd, …) dans le dépôt.")
else:
    # Cast num
    holds["qty"] = pd.to_numeric(holds.get("qty", 0), errors="coerce").fillna(0)
    holds["buy_price_usd"] = pd.to_numeric(holds.get("buy_price_usd", 0.0), errors="coerce").fillna(0.0)

    # Merge
    df = holds.merge(last[["market_hash_name", "latest_price_usd"]], on="market_hash_name", how="left")

    # Calculs
    df["pnl_abs"] = (df["latest_price_usd"] - df["buy_price_usd"]) * df["qty"]
    denom = df["buy_price_usd"].replace(0, pd.NA)
    df["pnl_pct"] = ((df["latest_price_usd"] - df["buy_price_usd"]) / denom * 100).fillna(0)

    # Métriques globales
    total_val = (df["latest_price_usd"] * df["qty"]).sum()
    total_cost = (df["buy_price_usd"] * df["qty"]).sum()
    total_pnl = total_val - total_cost
    total_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    # ----- Cartes métriques sobres -----
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
        metric_card("Valeur portefeuille", f"${total_val:,.2f}", color="#eef7f2")
    with col2:
        metric_card("Coût total", f"${total_cost:,.2f}", color="#eff3fb")
    with col3:
        color_pnl = "#eef7f2" if total_pnl >= 0 else "#fbeeee"
        metric_card("P&L total", f"${total_pnl:,.2f}", color=color_pnl)
    with col4:
        color_pct = "#eef7f2" if total_pct >= 0 else "#fbeeee"
        metric_card("% d’évolution", f"{total_pct:,.2f}%", color=color_pct)

    # Espace avant le tableau
    st.markdown("<div style='margin-top:25px'></div>", unsafe_allow_html=True)

    # ----- Colonne IMAGES (CSFloat) -----
    @st.cache_data(ttl=3600)
    def fetch_icon_url(market_hash_name: str) -> str | None:
        """
        On demande 1 listing avec expand=item pour obtenir l'icône.
        On reconstruit l'URL Steam CDN si l'API renvoie un chemin relatif.
        """
        if not CSFLOAT_API_KEY:
            return None
        params = {
            "market_hash_name": market_hash_name,
            "sort_by": "lowest_price",
            "type": "buy_now",
            "limit": 1,
            "expand": "item",  # inclut item.icon_url
        }
        try:
            r = requests.get(CSFLOAT_API, headers=CSFLOAT_HEADERS, params=params, timeout=15)
            if r.status_code == 429:
                return None
            r.raise_for_status()
            data = r.json()
        except Exception:
            return None

        listings = data.get("data") if isinstance(data, dict) else data
        if not isinstance(listings, list) or not listings:
            return None

        first = listings[0]
        img = first.get("image") or first.get("icon_url")
        if not img:
            item = first.get("item") or {}
            img = item.get("icon_url")

        if not img:
            return None

        if isinstance(img, str) and img.startswith("http"):
            return img

        # URL Steam CDN taille 128
        return f"https://steamcommunity-a.akamaihd.net/economy/image/{img}/128fx128f"

    if CSFLOAT_API_KEY:
        df["Image"] = df["market_hash_name"].apply(fetch_icon_url)
    else:
        df["Image"] = None

    # ----- Tableau P&L (avec images, sans quantité) -----
    table = pd.DataFrame({
        "Image": df["Image"],
        "Item": df["market_hash_name"],
        "prix achat USD": df["buy_price_usd"],
        "Prix vente USD": df["latest_price_usd"],
        "perte/gain": df["pnl_abs"],
        "% d’évolution": df["pnl_pct"],
    })

    def color_pnl_abs(val):
        if pd.isna(val): return ""
        return "color: #157a3d;" if val > 0 else ("color: #c44545;" if val < 0 else "")

    def grad_pct(val):
        if pd.isna(val): return ""
        a = abs(val)
        if val > 0:
            if a < 5:   bg = "#f3fbf7"
            elif a < 10: bg = "#e9f7f0"
            elif a < 20: bg = "#ddf2e7"
            else:        bg = "#d3ece0"
        elif val < 0:
            if a < 5:   bg = "#fdf3f3"
            elif a < 10: bg = "#fbeaea"
            elif a < 20: bg = "#f7dddd"
            else:        bg = "#f3d8d8"
        else:
            bg = ""
        return f"background-color: {bg};"

    styled = (
        table.style
        .format({
            "prix achat USD": "{:,.2f}",
            "Prix vente USD": "{:,.2f}",
            "perte/gain": "{:,.2f}",
            "% d’évolution": "{:,.2f}%"
        })
        .applymap(color_pnl_abs, subset=["perte/gain"])
        .applymap(grad_pct, subset=["% d’évolution"])
    )

    st.dataframe(
        styled,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Image": st.column_config.ImageColumn("Image", help="Miniature CSFloat/Steam", width="small")
        }
    )

# ---------- Éditeur de prix d'achat (bouton afficher/masquer) ----------
st.markdown("## Modifier prix d’achat")

# état du panneau
if "show_editor" not in st.session_state:
    st.session_state.show_editor = False

# bouton toggle
if st.session_state.show_editor:
    if st.button("Masquer l’éditeur"):
        st.session_state.show_editor = False
        st.rerun()
else:
    if st.button("Afficher l’éditeur"):
        st.session_state.show_editor = True
        st.rerun()

if st.session_state.show_editor:
    if not GH_PAT:
        st.info("Pour éditer et sauvegarder depuis la page, ajoute un secret Streamlit **GH_PAT** (Personal Access Token avec scope `repo` ou `public_repo`).")
    else:
        text, sha, status = gh_get_file(PATH_HOLDINGS)
        if status != 200 or not text:
            st.warning("Impossible de charger `data/holdings.csv` via l'API GitHub (vérifie GH_PAT, OWNER/REPO/BRANCH).")
        else:
            df_hold = pd.read_csv(io.StringIO(text))
            if "buy_price_usd" not in df_hold.columns or "market_hash_name" not in df_hold.columns:
                st.warning("`data/holdings.csv` doit contenir au minimum les colonnes: market_hash_name, buy_price_usd.")
            else:
                col_cfg = {
                    "market_hash_name": st.column_config.TextColumn("Item", disabled=True, width="large"),
                    "buy_price_usd": st.column_config.NumberColumn("prix achat USD", step=0.01, min_value=0.0),
                }
                for c in df_hold.columns:
                    if c not in col_cfg:
                        col_cfg[c] = st.column_config.TextColumn(c, disabled=True)

                st.caption("Édite la colonne **prix achat USD**, puis clique **Enregistrer**.")
                edited = st.data_editor(
                    df_hold,
                    use_container_width=True,
                    column_config=col_cfg,
                    num_rows="fixed",
                    disabled=[c for c in df_hold.columns if c != "buy_price_usd"],
                )

                if st.button("Enregistrer les prix d’achat dans GitHub"):
                    try:
                        edited["buy_price_usd"] = pd.to_numeric(edited["buy_price_usd"], errors="coerce").fillna(0.0)
                        csv_out = io.StringIO()
                        edited.to_csv(csv_out, index=False)
                        resp = gh_put_file(
                            PATH_HOLDINGS,
                            csv_out.getvalue(),
                            sha,
                            "chore(data): update buy_price_usd via Streamlit app",
                        )
                        if 200 <= resp.status_code < 300:
                            st.success("Sauvegardé. Le workflow GitHub se lancera s’il est configuré sur push.")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"Erreur GitHub API ({resp.status_code}) : {resp.text[:200]}")
                    except Exception as e:
                        st.error(f"Échec de la sauvegarde : {e}")

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
