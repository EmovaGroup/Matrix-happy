import os
import pandas as pd
import altair as alt
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import date

# ---------- Config ----------
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    st.error("⚠️ SUPABASE_URL et SUPABASE_ANON_KEY doivent être définis dans .env")
    st.stop()

@st.cache_resource
def get_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

supabase = get_client()

st.set_page_config(page_title="Matrix Dashboard", layout="wide")

# 👉 À coller juste après st.set_page_config(...)
st.markdown("""
<style>
/* === Boutons uniquement (bleu Manceau) === */
div.stButton > button,
div.stDownloadButton > button,
.stForm button[type="submit"],
button[kind="primary"],
button[kind="secondary"] {
    background-color: #1F7A8C !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 6px !important;
    box-shadow: none !important;
}
div.stButton > button:hover,
div.stDownloadButton > button:hover,
.stForm button[type="submit"]:hover,
button[kind="primary"]:hover,
button[kind="secondary"]:hover {
    background-color: #166272 !important;
    color: #FFFFFF !important;
}
/* Focus accessible (optionnel) */
div.stButton > button:focus,
div.stDownloadButton > button:focus,
.stForm button[type="submit"]:focus,
button[kind="primary"]:focus,
button[kind="secondary"]:focus {
    outline: 2px solid #1F7A8C !important;
    outline-offset: 2px !important;
}
</style>
""", unsafe_allow_html=True)

# ---------- Utilisateurs autorisés ----------
ALLOWED = {
    "o.ginoux@emova-group.com",
    "d.decarriere@emova-group.com",
    "dsi@emova-group.com",
    "sa.ouni@emova-group.com",
    "n.dubois@emova-group.com",
    "s.maslaga@emova-group.com",
    "ym.gille@emova-group.com",
    "t.vernageau@emova-group.com",
    "m.laghouanem@emova-group.com",
}

# ---------- Auth ----------
if "auth" not in st.session_state:
    st.session_state["auth"] = {"user": None, "session": None, "error": None}

if st.session_state["auth"]["user"] is None:
    st.subheader("🔑 Connexion sécurisée")
    email = st.text_input("Email")
    password = st.text_input("Mot de passe", type="password")
    if st.button("Se connecter"):
        try:
            auth_res = supabase.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            user = auth_res.user
            if user and user.email in ALLOWED:
                st.session_state["auth"]["user"] = user
                st.session_state["auth"]["session"] = auth_res.session
                st.rerun()
            else:
                st.error("🚫 Vous n'avez pas accès à ce dashboard.")
        except Exception as e:
            st.error(f"❌ Identifiants invalides : {e}")
    st.stop()

user = st.session_state["auth"]["user"]
st.sidebar.success(f"✅ Connecté : {user.email}")
if st.sidebar.button("Se déconnecter"):
    st.session_state["auth"] = {"user": None, "session": None, "error": None}
    st.rerun()

# ---------- Message de bienvenue personnalisé ----------
USER_NAMES = {
    "sa.ouni@emova-group.com": "Salah Ouni",
    "o.ginoux@emova-group.com": "Olivier Ginoux",
    "d.decarriere@emova-group.com": "David Decarrière",
    "dsi@emova-group.com": "DSI",
    "n.dubois@emova-group.com": "Nicolas Dubois",
    "s.maslaga@emova-group.com": "Saloua Maslaga",
    "ym.gille@emova-group.com": "Yves-Marie Gille",
    "t.vernageau@emova-group.com": "Thierry Vernageau",
    "m.laghouanem@emova-group.com": "Malek Laghouanem"
}

email = user.email.lower()
display_name = USER_NAMES.get(email, email)

st.markdown(
    f"<h2 style='color:#1a73e8;'>👋 Bienvenue {display_name} !</h2>",
    unsafe_allow_html=True
)

# ---------- Dashboard ----------
st.title("📊 Matrix — Ventes & Marge")

# ---------- Chargement des filtres de base ----------
@st.cache_data(ttl=300)
def load_filters():
    r1 = supabase.table("v_matrix").select("period_date").order("period_date", desc=False).limit(1).execute()
    r2 = supabase.table("v_matrix").select("period_date").order("period_date", desc=True).limit(1).execute()

    table = (
        supabase.table("v_matrix")
        .select("store_name")
        .neq("store_name", "")
        .order("store_name", desc=False)
    )
    batch_size = 1000
    offset = 0
    all_stores = []
    while True:
        res = table.range(offset, offset + batch_size - 1).execute()
        if not res.data:
            break
        all_stores.extend(res.data)
        offset += batch_size

    if not r1.data or not r2.data:
        return None, None, []

    dmin = pd.to_datetime(r1.data[0]["period_date"]).date()
    dmax = pd.to_datetime(r2.data[0]["period_date"]).date()
    stores = sorted({row["store_name"] for row in all_stores if row.get("store_name")})
    return dmin, dmax, stores

dmin, dmax, stores = load_filters()
if dmin is None:
    st.warning("Aucune donnée dans v_matrix.")
    st.stop()

# ---------- Chargement des données ----------
@st.cache_data(ttl=300)
def load_data(dstart: date, dend: date) -> pd.DataFrame:
    table = (
        supabase.table("v_matrix")
        .select("store_name,period_date,code_article,libelle_final,famille_finale,qte,ventes_ht,ventes_ttc,marge_ht,marge_pct")
        .gte("period_date", dstart.isoformat())
        .lte("period_date", dend.isoformat())
        .order("period_date", desc=False)
        .order("store_name", desc=False)
        .order("code_article", desc=False)
    )

    batch_size = 1000
    offset = 0
    all_data = []
    while True:
        res = table.range(offset, offset + batch_size - 1).execute()
        if not res.data:
            break
        all_data.extend(res.data)
        offset += batch_size

    df = pd.DataFrame(all_data or [])
    if not df.empty:
        df["period_date"] = pd.to_datetime(df["period_date"])
        num_cols = ["qte","ventes_ht","ventes_ttc","marge_ht","marge_pct"]
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

# ---------- UI Filtres ----------
col_filters = st.columns([2, 2, 3])
with col_filters[0]:
    st.markdown("<p style='font-size:18px; font-weight:600; margin-bottom:-8px;'>📅 Période</p>", unsafe_allow_html=True)
    drange = st.date_input("", value=(dmin, dmax), min_value=dmin, max_value=dmax, label_visibility="collapsed")
if isinstance(drange, tuple) and len(drange) == 2:
    dstart, dend = drange
elif hasattr(drange, "year"):
    dstart, dend = drange, drange
else:
    st.stop()

with col_filters[1]:
    st.markdown("<p style='font-size:18px; font-weight:600; margin-bottom:-8px;'>⏱️ Granularité</p>", unsafe_allow_html=True)
    granularity = st.radio("", ["Jour", "Semaine", "Mois"], horizontal=True, label_visibility="collapsed")
with col_filters[2]:
    st.markdown("<p style='font-size:18px; font-weight:600; margin-bottom:-8px;'>🏬 Magasins à comparer</p>", unsafe_allow_html=True)
    store_options = ["Tous les magasins"] + stores
    selected_stores = st.multiselect("", store_options, default=["Tous les magasins"], label_visibility="collapsed")

if st.button("⚡ Charger / Actualiser les données", type="primary"):
    st.session_state["stores_selected"] = selected_stores
    st.session_state["df"] = load_data(dstart, dend)

st.caption("Astuce : choisis 📅 la période, ⏱️ la granularité et 🏬 les magasins, puis clique sur ⚡ Charger.")

# ---------- Récupération ----------
df = st.session_state.get("df")
stores_selected = st.session_state.get("stores_selected", [])
if df is None:
    st.info("Clique sur ⚡ Charger / Actualiser les données pour afficher le dashboard.")
    st.stop()
if df.empty:
    st.warning("Aucune ligne pour ces filtres.")
    st.stop()

# ---------- KPIs ----------

def kpi_card(title, value, emoji):
    return f"""
    <div style="border: 3px solid red; border-radius: 12px; padding: 20px; text-align: center;
    background-color: #fff; height: 120px; display: flex; flex-direction: column;
    justify-content: center; align-items: center;">
        <div style="font-size: 18px; font-weight: 600; color: #b00000; margin-bottom: 8px;">
            {emoji} {title}
        </div>
        <div style="font-size: 32px; font-weight: bold; color: #000;">
            {value}
        </div>
    </div>
    """

# ================================
# 🔵 LIGNE 1 — KPI principaux
# ================================
row1_col1, row1_col2, row1_col3 = st.columns(3)

# 1️⃣ CA TTC
with row1_col1:
    st.markdown(
        kpi_card(
            "CA TTC",
            f"{df['ventes_ttc'].sum():,.2f} €".replace(",", " ").replace(".", ","),
            "💰"
        ),
        unsafe_allow_html=True
    )

# 2️⃣ Articles vendus (quantité totale)
with row1_col2:
    articles_total = df["qte"].sum()
    st.markdown(
        kpi_card(
            "Nombre d'articles vendus",
            f"{articles_total:,.0f}".replace(",", " "),
            "🛒"
        ),
        unsafe_allow_html=True
    )

# 3️⃣ Prix moyen d’un article vendu
with row1_col3:
    total_ca = df["ventes_ttc"].sum()
    prix_moyen = total_ca / articles_total if articles_total else 0
    st.markdown(
        kpi_card(
            "Prix moyen d'article",
            f"{prix_moyen:,.2f} €".replace(",", " ").replace(".", ","),
            "📦"
        ),
        unsafe_allow_html=True
    )
st.markdown("<div style='height:25px;'></div>", unsafe_allow_html=True)
# ================================
# 🔵 LIGNE 2 — KPI complémentaires
# ================================
row2_col1, row2_col2, row2_col3 = st.columns(3)

# 4️⃣ CA HT
with row2_col1:
    st.markdown(
        kpi_card(
            "CA HT",
            f"{df['ventes_ht'].sum():,.2f} €".replace(",", " ").replace(".", ","),
            "📊"
        ),
        unsafe_allow_html=True
    )

# 5️⃣ Marge HT
with row2_col2:
    st.markdown(
        kpi_card(
            "Marge HT",
            f"{df['marge_ht'].sum():,.2f} €".replace(",", " ").replace(".", ","),
            "🏦"
        ),
        unsafe_allow_html=True
    )

# 6️⃣ Marge %
with row2_col3:
    pct = (df["marge_ht"].sum() / df["ventes_ht"].sum() * 100) if df["ventes_ht"].sum() else 0
    st.markdown(
        kpi_card(
            "Marge %",
            f"{pct:,.2f} %".replace(",", " ").replace(".", ","),
            "🔥"
        ),
        unsafe_allow_html=True
    )

st.divider()

# ---------- Courbe comparative ----------
def aggregate(df_in: pd.DataFrame, granularity: str, by_store=True) -> pd.DataFrame:
    dfg = df_in.copy()
    if granularity == "Jour":
        dfg["bucket"] = dfg["period_date"].dt.date
        dfg["bucket_label"] = dfg["bucket"].astype(str)
    elif granularity == "Semaine":
        dfg["bucket_start"] = dfg["period_date"] - pd.to_timedelta(dfg["period_date"].dt.weekday, unit="D")
        dfg["bucket_end"] = dfg["bucket_start"] + pd.to_timedelta(6, unit="D")
        dfg["bucket"] = dfg["bucket_start"]
        dfg["bucket_label"] = "du " + dfg["bucket_start"].dt.strftime("%d/%m/%Y") + " au " + dfg["bucket_end"].dt.strftime("%d/%m/%Y")
    else:  # Mois
        dfg["bucket"] = dfg["period_date"].dt.to_period("M").dt.to_timestamp()
        dfg["bucket_label"] = dfg["bucket"].dt.strftime("%b %Y")

    group_cols = ["bucket", "bucket_label"]
    if by_store:
        group_cols.insert(0, "store_name")

    out = (dfg.groupby(group_cols, as_index=False)
              .agg(ca_ttc=("ventes_ttc", "sum"),
                   ca_ht=("ventes_ht", "sum"),
                   marge=("marge_ht", "sum"),
                   qte=("qte", "sum")))
    return out

if stores_selected:
    comp_list = []
    if "Tous les magasins" in stores_selected:
        agg_all = aggregate(df, granularity, by_store=False)
        agg_all["magasin"] = "Tous les magasins"
        comp_list.append(agg_all)
    for store in [s for s in stores_selected if s != "Tous les magasins"]:
        df_store = df[df["store_name"] == store]
        agg_store = aggregate(df_store, granularity, by_store=True)
        agg_store["magasin"] = store
        comp_list.append(agg_store)
    comp = pd.concat(comp_list, ignore_index=True)

    st.markdown(f"<p style='font-size:22px; font-weight:700;'>📈 Comparaison des magasins — CA TTC ({granularity})</p>", unsafe_allow_html=True)
    line_comp = alt.Chart(comp).mark_line(point=True).encode(
    x=alt.X("bucket_label:N", title=f"Période ({granularity})", sort=None),
    y=alt.Y("ca_ttc:Q", title="CA TTC"),
    color=alt.Color("magasin:N", title="Magasin", scale=alt.Scale(scheme="category20")),  # ✅ category20
    tooltip=["magasin","bucket_label",
             alt.Tooltip("ca_ttc:Q", format=".2f"),
             alt.Tooltip("ca_ht:Q", format=".2f"),
             alt.Tooltip("marge:Q", format=".2f"),
             alt.Tooltip("qte:Q", format=".0f")]
    ).properties(height=320).configure_mark(strokeWidth=3)
    st.altair_chart(line_comp, use_container_width=True)

st.divider()

# ---------- Camembert ----------
st.markdown("<p style='font-size:22px; font-weight:700;'>🥧 Répartition du CA TTC par famille</p>", unsafe_allow_html=True)

target_for_pie = st.selectbox(
    "Choisir le magasin pour le camembert",
    options=[f"Tous magasins ({dstart} → {dend})"] + stores_selected,
    index=0
)
if target_for_pie == f"Tous magasins ({dstart} → {dend})":
    pie_df = df.copy()
else:
    pie_df = df[df["store_name"] == target_for_pie].copy()

fam = (pie_df.groupby("famille_finale", as_index=False)
              .agg(ca_ttc=("ventes_ttc", "sum")))
fam["pct"] = fam["ca_ttc"] / fam["ca_ttc"].sum() * 100 if fam["ca_ttc"].sum() else 0

# Trier du plus grand au plus petit
fam = fam.sort_values("pct", ascending=False)

# Ajouter famille + % pour la légende
fam["label"] = fam.apply(lambda x: f"{x['famille_finale']} ({x['pct']:.1f}%)", axis=1)

# Définir un ordre explicite (pour légende ET dessin du camembert)
order = fam["label"].tolist()

# Camembert
pie = alt.Chart(fam).mark_arc().encode(
    theta=alt.Theta(field="ca_ttc", type="quantitative", title="CA TTC", sort="descending"),
    color=alt.Color(field="label", type="nominal", title="Famille",
                    sort=order,  # ordre légende
                    scale=alt.Scale(scheme="category20", domain=order)),  # ordre couleurs
    tooltip=[
        "famille_finale",
        alt.Tooltip("ca_ttc:Q", format=".2f"),
        alt.Tooltip("pct:Q", format=".1f")
    ]
).properties(height=360)

st.altair_chart(pie, use_container_width=True)

st.divider()

# ---------- Top articles ----------
st.markdown("<p style='font-size:22px; font-weight:700;'>🏆 Top articles (par CA TTC)</p>", unsafe_allow_html=True)
topn = st.slider(label="", min_value=5, max_value=50, value=15, step=5, label_visibility="collapsed")

df_for_top = df.copy()
if stores_selected and "Tous les magasins" not in stores_selected:
    df_for_top = df_for_top[df_for_top["store_name"].isin(stores_selected)]

top_articles = (df_for_top.groupby(["code_article", "libelle_final"], as_index=False)
                .agg(qte=("qte", "sum"),
                     ca_ttc=("ventes_ttc", "sum")))
top_articles["article"] = top_articles.apply(
    lambda r: f"{r['libelle_final']} [{r['code_article']}]",
    axis=1
)

top_articles = top_articles.sort_values("ca_ttc", ascending=False).head(topn)

bar = alt.Chart(top_articles).mark_bar().encode(
    x=alt.X("ca_ttc:Q", title="CA TTC"),
    y=alt.Y("article:N", sort="-x", title="Article"),
    tooltip=["code_article", "libelle_final", "qte", "ca_ttc"]
).properties(height=max(280, 28*len(top_articles)))
st.altair_chart(bar, use_container_width=True)

# ---------- Synthèse Tickets & CA TTC ----------
st.markdown("## 📊 Synthèse Articles & CA TTC")

JOURS = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]
JOURS_MAP = {0:"Lundi",1:"Mardi",2:"Mercredi",3:"Jeudi",4:"Vendredi",5:"Samedi",6:"Dimanche"}

# Détecter thème actif
theme_base = st.get_option("theme.base")  # "light" ou "dark"

if theme_base == "dark":
    table_bg = "#1e1e1e"
    sticky_bg = "#2b2b2b"
    header_bg = "#3a3a3a"
    text_color = "#f5f5f5"
    color_above = "#234d20"
    color_below = "#5c1a1a"
    color_equal = "#444444"
else:
    table_bg = "#ffffff"
    sticky_bg = "#f2f2f2"
    header_bg = sticky_bg
    text_color = "#000000"
    color_above = "#d4edda"
    color_below = "#f8d7da"
    color_equal = "#fff3cd"

# Injecter CSS dynamique
st.markdown(f"""
<style>
.scrollable-table {{
    overflow-x: auto;
    max-width: 100%;
}}
.scrollable-table table {{
    border-collapse: collapse;
    width: 100%;
    background-color: transparent !important;
}}
.scrollable-table thead th,
.scrollable-table tbody td {{
    color: {text_color};
    text-align: center;
    white-space: nowrap;
}}
.scrollable-table thead th {{
    position: sticky;
    top: 0;
    background: {header_bg} !important;
    color: {text_color} !important;
    z-index: 3;
    font-weight: bold;
    border-radius: 8px;   /* ✅ arrondi uniforme */
    padding: 6px 12px;    /* ✅ même hauteur que les valeurs */
}}
.scrollable-table thead th:first-child,
.scrollable-table tbody td:first-child {{
    position: sticky;
    left: 0;
    background: {sticky_bg} !important;
    z-index: 5;
    min-width: 90px;
    border-right: 2px solid #444;
    font-weight: bold;
    border-radius: 8px;
}}
.scrollable-table thead th:last-child,
.scrollable-table tbody td:last-child {{
    position: sticky;
    right: 0;
    background: {sticky_bg} !important;
    z-index: 5;
    min-width: 100px;
    border-left: 2px solid #444;
    font-weight: bold;
    border-radius: 8px;
}}
.scrollable-table tbody td {{
    padding: 4px 8px;
    text-align: center;
}}
.scrollable-table tbody td div {{
    border-radius: 8px !important;   /* ✅ capsules arrondies */
    padding: 6px 12px !important;    /* ✅ cohérence hauteur */
}}
body[data-theme="dark"] .scrollable-table tbody td:empty {{
    background-color: #2b2b2b !important;
}}
</style>
""", unsafe_allow_html=True)

# --- Fonction formatage cellule ---
def format_cell(val, mean, euro=False):
    if pd.isna(val):
        return ""
    try:
        num_val = float(val)
    except Exception:
        return str(val)

    if num_val > mean:
        color, arrow = color_above, "▲"
    elif num_val < mean:
        color, arrow = color_below, "▼"
    else:
        color, arrow = color_equal, "━"

    if euro:
        text = f"{num_val:,.0f} €".replace(",", " ").replace(".", ",")
    else:
        text = f"{int(round(num_val))}"

    return f"<div style='background-color:{color}; border-radius:8px; padding:6px 12px; text-align:center; color:{text_color};'>{text} {arrow}</div>"

# --- Fonction utilitaire pour affichage tableau ---
def render_table(df, euro=False):
    fmt = df.copy().astype(object)
    for idx in df.index:
        base = df.loc[idx, "Moyenne"]
        for col in df.columns:
            if col == "Jour":
                fmt.loc[idx, col] = df.loc[idx, col]
            elif col == "Moyenne":
                if euro:
                    fmt.loc[idx, col] = f"{df.loc[idx, col]:,.2f} €".replace(",", " ").replace(".", ",")
                else:
                    fmt.loc[idx, col] = f"{df.loc[idx, col]:.2f}"
            else:
                fmt.loc[idx, col] = format_cell(df.loc[idx, col], base, euro=euro)

    html_table = fmt.to_html(escape=False, index=False, border=0)
    return f"<div class='scrollable-table'>{html_table}</div>"

# --- Fonction export CSV ---
def get_csv_download_link(df, filename):
    csv = df.to_csv(index=False, sep=";", encoding="utf-8")
    return st.download_button(
        label=f"📥 Télécharger {filename}",
        data=csv,
        file_name=f"{filename}.csv",
        mime="text/csv"
    )

# --- Tickets ---
tickets = df.assign(
    semaine=df["period_date"].dt.isocalendar().week.astype(int),
    jour=df["period_date"].dt.weekday.map(JOURS_MAP)
).groupby(["jour","semaine"])["code_article"].count().unstack().reindex(JOURS)

tickets.columns.name = None
tickets = tickets.rename(columns=lambda c: f"Semaine {c}" if str(c).isdigit() else c)

week_cols = list(tickets.columns)[::-1]
tickets = tickets[week_cols]

tickets.insert(0, "Jour", tickets.index)
tickets["Moyenne"] = tickets[week_cols].mean(axis=1)

totals_row_t = tickets[week_cols].sum()
totals_row_t["Jour"] = "TOTAL"
totals_row_t["Moyenne"] = totals_row_t[week_cols].mean()
tickets = pd.concat([tickets, totals_row_t.to_frame().T], ignore_index=True)

st.markdown("### 🎟️ Synthèse Articles par semaine")
st.markdown(render_table(tickets, euro=False), unsafe_allow_html=True)
get_csv_download_link(tickets, "tickets")

# --- CA TTC ---
ca = df.assign(
    semaine=df["period_date"].dt.isocalendar().week.astype(int),
    jour=df["period_date"].dt.weekday.map(JOURS_MAP)
).groupby(["jour","semaine"])["ventes_ttc"].sum().unstack().reindex(JOURS)

ca.columns.name = None
ca = ca.rename(columns=lambda c: f"Semaine {c}" if str(c).isdigit() else c)

week_cols_ca = list(ca.columns)[::-1]
ca = ca[week_cols_ca]

ca.insert(0, "Jour", ca.index)
ca["Moyenne"] = ca[week_cols_ca].mean(axis=1)

totals_row_c = ca[week_cols_ca].sum()
totals_row_c["Jour"] = "TOTAL"
totals_row_c["Moyenne"] = totals_row_c[week_cols_ca].mean()
ca = pd.concat([ca, totals_row_c.to_frame().T], ignore_index=True)

st.markdown("### 💶 Synthèse Ca ttc par semaine")
st.markdown(render_table(ca, euro=True), unsafe_allow_html=True)
get_csv_download_link(ca, "ca_ttc")

# --- Panier moyen ---
panier = df.assign(
    semaine=df["period_date"].dt.isocalendar().week.astype(int),
    jour=df["period_date"].dt.weekday.map(JOURS_MAP)
).groupby(["jour","semaine"]).agg(
    tickets=("code_article", "count"),
    ca_ttc=("ventes_ttc", "sum")
).reset_index()

# Calcul du panier moyen = CA / tickets
panier["panier_moyen"] = panier["ca_ttc"] / panier["tickets"]

# Pivot table comme les autres
panier_tab = panier.pivot(index="jour", columns="semaine", values="panier_moyen").reindex(JOURS)

panier_tab.columns.name = None
panier_tab = panier_tab.rename(columns=lambda c: f"Semaine {c}" if str(c).isdigit() else c)

week_cols_pm = list(panier_tab.columns)[::-1]
panier_tab = panier_tab[week_cols_pm]

panier_tab.insert(0, "Jour", panier_tab.index)
panier_tab["Moyenne"] = panier_tab[week_cols_pm].mean(axis=1)

# Ligne TOTAL
totals_row_pm = pd.Series(dtype="float64")
totals_row_pm["Jour"] = "TOTAL"
totals_row_pm["Moyenne"] = panier_tab[week_cols_pm].mean().mean()
for col in week_cols_pm:
    totals_row_pm[col] = panier_tab[col].mean()
panier_tab = pd.concat([panier_tab, totals_row_pm.to_frame().T], ignore_index=True)

# Affichage
st.markdown("### 🛒 Synthèse Prix moyen d'article par semaine")
st.markdown(render_table(panier_tab.round(2), euro=True), unsafe_allow_html=True)
get_csv_download_link(panier_tab.round(2), "panier_moyen")

# ---------- Graphiques comparatifs par semaine (3 dernières + Moyenne) ----------

def _last_weeks_list(weeks, n=3):
    uniq = sorted([int(w) for w in pd.Series(weeks).dropna().unique()])
    if not uniq:
        return []
    return uniq[-n:] if len(uniq) >= n else uniq

# Liste ordonnée des jours
JOURS = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]
JOURS_MAP = {0:"Lundi",1:"Mardi",2:"Mercredi",3:"Jeudi",4:"Vendredi",5:"Samedi",6:"Dimanche"}

# Dernières semaines présentes
_all_weeks = df["period_date"].dt.isocalendar().week.astype(int)
LAST_WEEKS = _last_weeks_list(_all_weeks, n=3)

# Couleur spéciale Moyenne
MOYENNE_COLOR = "#1F7A8C"  # Bleu Manceau Fleurs
ORDER_DOMAIN = [str(w) for w in LAST_WEEKS] + ["Moyenne"]
ORDER_RANGE = ["#1f77b4","#2ca02c","#ff7f0e",MOYENNE_COLOR]

if len(LAST_WEEKS) == 0:
    st.info("Pas de semaines disponibles sur la période choisie.")
else:
    # =========================
    # 1) Tickets
    # =========================
    tickets_base = df.assign(
        semaine=df["period_date"].dt.isocalendar().week.astype(int),
        jour=df["period_date"].dt.weekday.map(JOURS_MAP)
    ).groupby(["semaine","jour"])["code_article"].count().reset_index()

    moy_tickets = tickets_base.groupby("jour", as_index=False)["code_article"].mean()
    moy_tickets["semaine"] = "Moyenne"

    tickets_sel = tickets_base[tickets_base["semaine"].isin(LAST_WEEKS)].copy()
    tickets_sel["semaine"] = tickets_sel["semaine"].astype(str)
    tickets_chart = pd.concat([tickets_sel, moy_tickets], ignore_index=True)

    tickets_chart["jour"] = pd.Categorical(tickets_chart["jour"], categories=JOURS, ordered=True)
    tickets_chart = tickets_chart.sort_values(by=["semaine","jour"])  # 🔑 tri semaine + jour

    st.markdown("### 📈 Évolution des Articles par semaine (3 dernières + Moyenne)")

    base_tickets = alt.Chart(tickets_chart[tickets_chart["semaine"]!="Moyenne"]).mark_line(
        point=alt.OverlayMarkDef(size=70)
    ).encode(
        x=alt.X("jour:N", sort=JOURS, title="Jour de la semaine"),
        y=alt.Y("code_article:Q", title="Nombre d'articles"),
        color=alt.Color("semaine:N", title="Semaine",
                        scale=alt.Scale(domain=ORDER_DOMAIN, range=ORDER_RANGE)),
        tooltip=["semaine","jour",alt.Tooltip("code_article:Q", format=".0f")]
    )

    moy_line_tickets = alt.Chart(tickets_chart[tickets_chart["semaine"]=="Moyenne"]).mark_line(
        point=alt.OverlayMarkDef(size=70),
        strokeDash=[5,5],
        strokeWidth=3
    ).encode(
        x=alt.X("jour:N", sort=JOURS),
        y="code_article:Q",
        color=alt.Color("semaine:N", scale=alt.Scale(domain=ORDER_DOMAIN, range=ORDER_RANGE)),
        tooltip=["semaine","jour",alt.Tooltip("code_article:Q", format=".0f")]
    )

    fig_tickets = (base_tickets + moy_line_tickets).properties(
        height=400, width=750, title="Tickets par jour et par semaine"
    ).configure_mark(strokeWidth=3)

    st.altair_chart(fig_tickets, use_container_width=True)


    # =========================
    # 2) CA TTC
    # =========================
    ca_base = df.assign(
        semaine=df["period_date"].dt.isocalendar().week.astype(int),
        jour=df["period_date"].dt.weekday.map(JOURS_MAP)
    ).groupby(["semaine","jour"])["ventes_ttc"].sum().reset_index()

    moy_ca = ca_base.groupby("jour", as_index=False)["ventes_ttc"].mean()
    moy_ca["semaine"] = "Moyenne"

    ca_sel = ca_base[ca_base["semaine"].isin(LAST_WEEKS)].copy()
    ca_sel["semaine"] = ca_sel["semaine"].astype(str)
    ca_chart_df = pd.concat([ca_sel, moy_ca], ignore_index=True)

    ca_chart_df["jour"] = pd.Categorical(ca_chart_df["jour"], categories=JOURS, ordered=True)
    ca_chart_df = ca_chart_df.sort_values(by=["semaine","jour"])  # 🔑 tri semaine + jour

    st.markdown("### 📈 Évolution du CA TTC par semaine (3 dernières + Moyenne)")

    base_ca = alt.Chart(ca_chart_df[ca_chart_df["semaine"]!="Moyenne"]).mark_line(
        point=alt.OverlayMarkDef(size=70)
    ).encode(
        x=alt.X("jour:N", sort=JOURS, title="Jour de la semaine"),
        y=alt.Y("ventes_ttc:Q", title="CA TTC (€)"),
        color=alt.Color("semaine:N", title="Semaine",
                        scale=alt.Scale(domain=ORDER_DOMAIN, range=ORDER_RANGE)),
        tooltip=["semaine","jour",alt.Tooltip("ventes_ttc:Q", format=".2f")]
    )

    moy_line_ca = alt.Chart(ca_chart_df[ca_chart_df["semaine"]=="Moyenne"]).mark_line(
        point=alt.OverlayMarkDef(size=70),
        strokeDash=[5,5],
        strokeWidth=3
    ).encode(
        x=alt.X("jour:N", sort=JOURS),
        y="ventes_ttc:Q",
        color=alt.Color("semaine:N", scale=alt.Scale(domain=ORDER_DOMAIN, range=ORDER_RANGE)),
        tooltip=["semaine","jour",alt.Tooltip("ventes_ttc:Q", format=".2f")]
    )

    fig_ca = (base_ca + moy_line_ca).properties(
        height=400, width=750, title="CA TTC par jour et par semaine"
    ).configure_mark(strokeWidth=3)

    st.altair_chart(fig_ca, use_container_width=True)


    # =========================
    # 3) Panier moyen
    # =========================
    panier_chart = panier.copy()

    moy_pm = panier_chart.groupby("jour", as_index=False)["panier_moyen"].mean()
    moy_pm["semaine"] = "Moyenne"

    pm_sel = panier_chart[panier_chart["semaine"].isin(LAST_WEEKS)].copy()
    pm_sel["semaine"] = pm_sel["semaine"].astype(str)
    panier_chart_df = pd.concat([pm_sel[["semaine","jour","panier_moyen"]], moy_pm], ignore_index=True)

    panier_chart_df["jour"] = pd.Categorical(panier_chart_df["jour"], categories=JOURS, ordered=True)
    panier_chart_df = panier_chart_df.sort_values(by=["semaine","jour"])  # 🔑 tri semaine + jour

    st.markdown("### 📈 Évolution du Prix moyen d'article par semaine (3 dernières + Moyenne)")

    base_pm = alt.Chart(panier_chart_df[panier_chart_df["semaine"]!="Moyenne"]).mark_line(
        point=alt.OverlayMarkDef(size=70)
    ).encode(
        x=alt.X("jour:N", sort=JOURS, title="Jour de la semaine"),
        y=alt.Y("panier_moyen:Q", title="Prix moyen d'article (€)"),
        color=alt.Color("semaine:N", title="Semaine",
                        scale=alt.Scale(domain=ORDER_DOMAIN, range=ORDER_RANGE)),
        tooltip=["semaine","jour",alt.Tooltip("panier_moyen:Q", format=".2f")]
    )

    moy_line_pm = alt.Chart(panier_chart_df[panier_chart_df["semaine"]=="Moyenne"]).mark_line(
        point=alt.OverlayMarkDef(size=70),
        strokeDash=[5,5],
        strokeWidth=3
    ).encode(
        x=alt.X("jour:N", sort=JOURS),
        y="panier_moyen:Q",
        color=alt.Color("semaine:N", scale=alt.Scale(domain=ORDER_DOMAIN, range=ORDER_RANGE)),
        tooltip=["semaine","jour",alt.Tooltip("panier_moyen:Q", format=".2f")]
    )

    fig_panier = (base_pm + moy_line_pm).properties(
        height=400, width=750, title="Prix moyen d'article (€) par jour et par semaine"
    ).configure_mark(strokeWidth=3)

    st.altair_chart(fig_panier, use_container_width=True)

# ---------- Table détaillée ----------
st.markdown("<p style='font-size:22px; font-weight:700;'>📋 Détail des lignes (période sélectionnée)</p>", unsafe_allow_html=True)
st.dataframe(
    df.sort_values(["period_date", "store_name", "libelle_final"]),
    use_container_width=True
)
