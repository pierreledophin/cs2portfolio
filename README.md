Ajout des skins à partir de "holdings.csv" 

à faire : 
- détection automatique des skins via API ResolveVanityURL, pour tracker auto l'inventaire steam. 
- Analyse J-1 J-7 J-30 par skin et au global

explication : 
1) Vue d’ensemble

Tu as 2 “sources” de prix qui alimentent l’app :

Live (dans Streamlit)

L’app appelle l’API CSFloat en direct pour afficher les prix les plus bas du moment (sans écrire de fichier).

Tu peux forcer le rafraîchissement avec le bouton “Actualiser les prix (Live)” dans la sidebar (ça vide le cache).

Robot GitHub (Actions)

Un workflow tourne 2× par jour (cron) et peut être lancé à la main.

Il exécute fetch_prices.py, qui lit tes holdings et écrit/append dans price_history.csv.

Ton app lit ce price_history.csv (via l’API GitHub) pour tracer la courbe d’évolution de la valeur du portefeuille.

Les deux utilisent CSFloat en type=buy_now + sort_by=lowest_price pour prendre le prix le plus bas.

2) Secrets requis (côté Streamlit & GitHub)
Streamlit (dans st.secrets)

GH_OWNER : ton utilisateur GitHub (ex: pierreledophin)

GH_REPO : nom du repo (ex: cs2portfolio)

GH_BRANCH : main (ou autre branche cible)

GH_PAT : Personal Access Token GitHub avec scope repo (sert à lire/écrire les CSV via l’API GitHub, et à déclencher le workflow)

CSFLOAT_API_KEY : clé d’API CSFloat

GitHub (dans Settings → Secrets and variables → Actions)

CSFLOAT_API_KEY : même clé, utilisée par le robot dans le workflow Actions

3) Organisation des données (par profil)

Tu gères plusieurs “profils” (ex: pierre, elenocames). Pour chaque profil :

data/<profil>/
  ├─ trades.csv           ← historique des transactions (input de l’app)
  ├─ holdings.csv         ← positions actuelles (reconstruit *par l’app* depuis trades)
  └─ price_history.csv    ← historique des prix (alimenté *par le robot*)


trades.csv est la source de vérité : quand tu ajoutes un BUY/SELL, l’app sauvegarde dans ce fichier (et commite via l’API GitHub).

holdings.csv est reconstruit automatiquement à partir de trades.csv (pas besoin d’y toucher).

price_history.csv est alimenté uniquement par le workflow (robot). L’app ne l’écrit pas, elle se contente de le lire pour tracer la courbe.

4) Fichiers et leur rôle
app.py (Streamlit)

Sélecteur Profil (radio en haut).

Sidebar

Actualiser les prix (Live) : vide le cache Streamlit → relance les appels API pour affichage (pas d’écriture).

Lancer MAJ GitHub (robot) : déclenche le workflow Actions fetch-prices.yml (écrit/append price_history.csv).

Onglet “Portefeuille”

Recompose les holdings depuis trades.csv.

Appelle CSFloat pour chaque item (fonction fetch_price, tri lowest_price).

Calcule : valeur, P&L latent, % d’évolution (safe: pas de division par 0/NaN).

Affiche le tableau (avec images via fetch_icon, KPI cards, et graph d’évolution à partir de price_history.csv).

Onglet “Achat / Vente”

Formulaire pour ajouter une transaction (BUY/SELL).

Sauvegarde dans data/<profil>/trades.csv local et via l’API GitHub (commit direct).

Recalcule les holdings et rafraîchit.

Onglet “Transactions”

Liste toutes les lignes de trades.csv.

Suppression par trade_id (utile en cas d’erreur) : mise à jour du CSV + recalcul holdings.

Affiche le P&L réalisé cumulé (SELL vs PRU de l’historique des BUY).

Points techniques clés dans app.py

Cache Streamlit :

@st.cache_data sur fetch_price (TTL 600s) et fetch_icon (TTL 3600s).

Bouton “Actualiser les prix (Live)” → st.cache_data.clear() + st.rerun().

Lecture price_history.csv : via GitHub API (gh_get_file), pour ne pas dépendre du filesystem de Streamlit Cloud.

Calcul % d’évolution :

evo_array = np.divide(
    (price_now - buy) * 100.0,
    buy,
    out=np.full(diff.shape, np.nan),
    where=(buy > 0)
)


→ jamais de division par 0/NaN.

Couleurs P&L et % : fonctions _pnl_bg_color et _pct_bg_color → pastels clairs graduels.

fetch_prices.py (Robot)

Lit data/<profil>/holdings.csv (le robot ne lit pas trades.csv, c’est l’app qui en dérive holdings.csv).

Pour chaque item, appelle CSFloat avec type=buy_now + sort_by=lowest_price + limit=1.

Écrit une ligne par item dans data/<profil>/price_history.csv :

colonnes : ts_utc, market_hash_name, price_usd

Respecte les pauses anti rate-limit, gère les 429, et skip s’il n’y a pas d’offre.

.github/workflows/fetch-prices.yml (Actions)

schedule : cron: "0 7,19 * * *" → 2×/jour.

workflow_dispatch : permet le bouton manuel ou l’appel via gh_dispatch_workflow depuis l’app.

Installe les deps, boucle sur data/*/holdings.csv, lance python fetch_prices.py <path>, puis commit/push les price_history.csv modifiés.

5) Flux de données complet

Tu ajoutes une transaction dans Onglet Achat/Vente → trades.csv est mis à jour (local + commit GitHub).

L’app reconstruit holdings.csv (quantité restante + PRU par item).

Affichage live : fetch_price récupère le lowest_price CSFloat pour chaque item → calcule P&L latent & %.

Historique : selon la planification (ou via le bouton “robot”), Actions lance fetch_prices.py → append dans price_history.csv.

Graph : l’app lit price_history.csv depuis GitHub → somme par jour des prix × quantités actuelles → line chart.

6) Ce que tu peux modifier facilement

Ajouter un profil : créer data/<nouveau>/trades.csv (vide) → il apparaîtra dans le sélecteur si tu ajoutes son nom dans PROFILES.

Changer la fréquence du robot : modifie cron dans le workflow.

Couleurs / style : ajuste les fonctions _pnl_bg_color, _pct_bg_color ou le CSS du haut.

Colonnes affichées : adapte to_show = holdings[[...]].rename(...).

7) Bons réflexes & dépannage

Rien ne s’affiche dans le graph : vérifie que le workflow a bien écrit data/<profil>/price_history.csv (fichier non vide, au moins 1 exécution).

Prix live “bizarres” : clique “Actualiser les prix (Live)” pour vider le cache; vérifie que CSFLOAT_API_KEY est présent coté Streamlit.

Échec commit/push du robot :

Vérifie les permissions dans le workflow (contents: write).

En cas de conflit : le workflow fait déjà git add + commit + push sur main.

Erreur division par zéro : résolue par le calcul robuste np.divide(..., where=buy>0).

Images “None” : soit pas de listing, soit pas d’icône dans la réponse; la cellule reste vide, c’est normal.

8) Sécurité / partage

Ne jamais commiter GH_PAT/CSFLOAT_API_KEY dans le code : garde-les dans secrets.

Si tu partages le repo :

Mets un README avec les secrets à définir.

Garde Actions en mode “read & write” pour que le robot puisse pousser les CSV.

Optionnel : mets une auth Streamlit (Community → config auth) si tu veux restreindre l’accès public.

9) Résumé ultra-rapide

Streamlit affiche live (lowest price) + enregistre les transactions → reconstruit holdings.

Actions écrit l’historique de prix 2×/jour via fetch_prices.py.

Le graph vient de price_history.csv, la table et les KPI viennent des appels live + de trades/holdings.

Tout est profile-based (data/<profil>/...).

Boutons : Live refresh (cache) et Robot (workflow).

Si tu veux, je te prépare un README.md clé-en-main à mettre dans le repo (avec copies-coller pour créer les secrets, lancer l’app, etc.).
