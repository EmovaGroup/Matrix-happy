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
st.title("📊 Matrix — Ventes & Marge")

# ---------- Aide : dériver une "famille" depuis le libellé ----------
FAMILY_RULES = [
    ("Bouquet", "Bouquets"),
    ("Autre bouquet", "Bouquets"),
    ("Roses", "Roses"),
    ("Rose", "Roses"),
    ("Orchid", "Orchidées"),
    ("Plante", "Plantes"),
    ("Fleurs", "Fleurs"),
    ("Fleur", "Fleurs"),
    ("Composition", "Compositions"),
]
DEFAULT_FAMILY = "Autres"

def derive_family_from_label(label: str) -> str:
    if not isinstance(label, str):
        return DEFAULT_FAMILY
    L = label.lower()
    for pattern, family in FAMILY_RULES:
        if pattern.lower() in L:
            return family
    return DEFAULT_FAMILY

# ---------- Chargement des filtres de base ----------
@st.cache_data(ttl=300)
def load_filters():
    r1 = supabase.table("matrix_lignes").select("period_date").order("period_date", desc=False).limit(1).execute()
    r2 = supabase.table("matrix_lignes").select("period_date").order("period_date", desc=True).limit(1).execute()
    r3 = supabase.table("matrix_lignes").select("store_name").neq("store_name", "").execute()

    if not r1.data or not r2.data:
        return None, None, []

    dmin = pd.to_datetime(r1.data[0]["period_date"]).date()
    dmax = pd.to_datetime(r2.data[0]["period_date"]).date()
    stores = sorted({row["store_name"] for row in r3.data if row.get("store_name")})
    return dmin, dmax, stores

dmin, dmax, stores = load_filters()
if dmin is None:
    st.warning("Aucune donnée dans matrix_lignes.")
    st.stop()

# ---------- UI Filtres ----------
col_f1, col_f2 = st.columns([1, 2])
with col_f1:
    drange = st.date_input("Période", value=(dmin, dmax), min_value=dmin, max_value=dmax)
    if isinstance(drange, tuple):
        dstart, dend = drange
    else:
        dstart, dend = dmin, dmax

with col_f2:
    # Sélecteurs pour comparaison A vs B
    default_a = stores[0] if stores else None
    default_b = stores[1] if len(stores) >= 2 else (stores[0] if stores else None)
    store_a = st.selectbox("Magasin A", options=stores, index=stores.index(default_a) if default_a in stores else 0)
    store_b = st.selectbox("Magasin B", options=stores, index=stores.index(default_b) if default_b in stores else 0)

# Granularité pour la comparaison
granularity = st.radio("Granularité d’agrégation", ["Jour", "Semaine", "Mois"], horizontal=True)

st.caption("Astuce : choisis ta période, tes deux magasins à comparer, puis clique sur **Charger / Actualiser les données**.")

# ---------- Chargement des données selon filtres ----------
@st.cache_data(ttl=300)
def load_data(dstart: date, dend: date) -> pd.DataFrame:
    q = supabase.table("matrix_lignes").select(
        "store_name,period_date,code_article,libelle_article,qte,ventes_ht,ventes_ttc,marge_ht,marge_pct"
    ).gte("period_date", dstart.isoformat()).lte("period_date", dend.isoformat())

    res = q.execute()
    df = pd.DataFrame(res.data or [])
    if not df.empty:
        df["period_date"] = pd.to_datetime(df["period_date"])
        num_cols = ["qte","ventes_ht","ventes_ttc","marge_ht","marge_pct"]
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        # famille pour le camembert
        df["famille"] = df["libelle_article"].apply(derive_family_from_label)
    return df

if st.button("Charger / Actualiser les données", type="primary"):
    st.session_state["df"] = load_data(dstart, dend)

df = st.session_state.get("df")
if df is None:
    st.info("Clique sur **Charger / Actualiser les données** pour afficher le dashboard.")
    st.stop()

if df.empty:
    st.warning("Aucune ligne pour ces filtres.")
    st.stop()

# ---------- KPIs globaux (toute la période, tous magasins filtrés par la période) ----------
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("CA TTC", f"{df['ventes_ttc'].sum():,.2f} €".replace(",", " ").replace(".", ","))
with col2:
    st.metric("CA HT", f"{df['ventes_ht'].sum():,.2f} €".replace(",", " ").replace(".", ","))
with col3:
    st.metric("Marge HT", f"{df['marge_ht'].sum():,.2f} €".replace(",", " ").replace(".", ","))
with col4:
    pct = (df["marge_ht"].sum() / df["ventes_ht"].sum() * 100) if df["ventes_ht"].sum() else 0
    st.metric("Marge %", f"{pct:,.2f} %".replace(",", " ").replace(".", ","))

st.divider()

# ---------- Courbe comparative A vs B (CA TTC) avec granularité ----------
def aggregate(df_in: pd.DataFrame, granularity: str) -> pd.DataFrame:
    dfg = df_in.copy()
    if granularity == "Jour":
        dfg["bucket"] = dfg["period_date"].dt.date
    elif granularity == "Semaine":
        # ISO week start (Lundi) : on normalise à la semaine
        dfg["bucket"] = dfg["period_date"] - pd.to_timedelta(dfg["period_date"].dt.weekday, unit="D")
        dfg["bucket"] = dfg["bucket"].dt.date
    else:  # Mois
        dfg["bucket"] = dfg["period_date"].dt.to_period("M").dt.to_timestamp()
        dfg["bucket"] = dfg["bucket"].dt.date
    out = (dfg.groupby(["store_name","bucket"], as_index=False)
              .agg(ca_ttc=("ventes_ttc","sum"),
                   ca_ht=("ventes_ht","sum"),
                   marge=("marge_ht","sum"),
                   qte=("qte","sum")))
    return out

df_a = df[df["store_name"] == store_a]
df_b = df[df["store_name"] == store_b]

agg_a = aggregate(df_a, granularity)
agg_b = aggregate(df_b, granularity)

# Concat pour graphe
agg_a["magasin"] = store_a
agg_b["magasin"] = store_b
comp = pd.concat([agg_a, agg_b], ignore_index=True)

st.subheader(f"Comparaison {store_a} vs {store_b} — CA TTC ({granularity})")
line_comp = alt.Chart(comp).mark_line(point=True).encode(
    x=alt.X("bucket:T", title=f"Période ({granularity})"),
    y=alt.Y("ca_ttc:Q", title="CA TTC"),
    color=alt.Color("magasin:N", title="Magasin"),
    tooltip=["magasin","bucket:T","ca_ttc:Q","ca_ht:Q","marge:Q","qte:Q"]
).properties(height=320)
st.altair_chart(line_comp, use_container_width=True)

st.divider()

# ---------- Camembert : CA TTC par famille ----------
st.subheader("Répartition du CA TTC par famille (camembert)")
target_for_pie = st.selectbox(
    "Afficher le camembert pour :",
    options=[f"Tous magasins ({dstart} → {dend})", store_a, store_b],
    index=0
)

if target_for_pie == store_a:
    pie_df = df_a.copy()
elif target_for_pie == store_b:
    pie_df = df_b.copy()
else:
    pie_df = df.copy()

fam = (pie_df.groupby("famille", as_index=False)
              .agg(ca_ttc=("ventes_ttc","sum")))
fam["pct"] = fam["ca_ttc"] / fam["ca_ttc"].sum() * 100 if fam["ca_ttc"].sum() else 0

pie = alt.Chart(fam).mark_arc().encode(
    theta=alt.Theta(field="ca_ttc", type="quantitative", title="CA TTC"),
    color=alt.Color(field="famille", type="nominal", title="Famille"),
    tooltip=["famille","ca_ttc","pct"]
).properties(height=360)
st.altair_chart(pie, use_container_width=True)

st.divider()

# ---------- Top articles (CA TTC) ----------
topn = st.slider("Top articles (par CA TTC)", 5, 50, 15, step=5)
top_articles = (df.groupby(["code_article","libelle_article"], as_index=False)
                  .agg(qte=("qte","sum"), ca_ttc=("ventes_ttc","sum")))
top_articles = top_articles.sort_values("ca_ttc", ascending=False).head(topn)

bar = alt.Chart(top_articles).mark_bar().encode(
    x=alt.X("ca_ttc:Q", title="CA TTC"),
    y=alt.Y("libelle_article:N", sort="-x", title="Article"),
    tooltip=["code_article","libelle_article","qte","ca_ttc"]
).properties(height=28*topn)
st.altair_chart(bar, use_container_width=True)

# ---------- Table détaillée ----------
st.subheader("Détail des lignes (période sélectionnée)")
st.dataframe(
    df.sort_values(["period_date","store_name","libelle_article"]),
    use_container_width=True
)
