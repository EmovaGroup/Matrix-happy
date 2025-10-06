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

# ---------- Utilisateurs autorisés ----------
ALLOWED = {
    "o.ginoux@emova-group.com",
    "d.decarriere@emova-group.com",
    "dsi@emova-group.com",
    "sa.ouni@emova-group.com",
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
    "dsi@emova-group.com": "DSI"
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

    # ✅ ordre STABLE pour la pagination
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
    # ✅ ordres STABLES avant pagination pour éviter les “lignes perdues”
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
col1, col2, col3, col4 = st.columns(4)
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
with col1:
    st.markdown(kpi_card("CA TTC", f"{df['ventes_ttc'].sum():,.2f} €".replace(",", " ").replace(".", ","), "💰"), unsafe_allow_html=True)
with col2:
    st.markdown(kpi_card("CA HT", f"{df['ventes_ht'].sum():,.2f} €".replace(",", " ").replace(".", ","), "📊"), unsafe_allow_html=True)
with col3:
    st.markdown(kpi_card("Marge HT", f"{df['marge_ht'].sum():,.2f} €".replace(",", " ").replace(".", ","), "🏦"), unsafe_allow_html=True)
with col4:
    pct = (df["marge_ht"].sum() / df["ventes_ht"].sum() * 100) if df["ventes_ht"].sum() else 0
    st.markdown(kpi_card("Marge %", f"{pct:,.2f} %".replace(",", " ").replace(".", ","), "🔥"), unsafe_allow_html=True)

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
        color=alt.Color("magasin:N", title="Magasin"),
        tooltip=["magasin","bucket_label","ca_ttc","ca_ht","marge","qte"]
    ).properties(height=320)
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

pie = alt.Chart(fam).mark_arc().encode(
    theta=alt.Theta(field="ca_ttc", type="quantitative", title="CA TTC"),
    color=alt.Color(field="famille_finale", type="nominal", title="Famille"),
    tooltip=["famille_finale","ca_ttc","pct"]
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

# ---------- Table détaillée ----------
st.markdown("<p style='font-size:22px; font-weight:700;'>📋 Détail des lignes (période sélectionnée)</p>", unsafe_allow_html=True)
st.dataframe(
    df.sort_values(["period_date", "store_name", "libelle_final"]),
    use_container_width=True
)