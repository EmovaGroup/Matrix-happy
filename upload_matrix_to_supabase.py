import os
import csv
import glob
from datetime import datetime
from typing import List, Dict, Any

from dotenv import load_dotenv
from supabase import create_client, Client

# ------------- CONFIG via .env -------------
# SUPABASE_URL=https://xxxxx.supabase.co
# SUPABASE_SERVICE_ROLE=eyJhbGciOi...
# CSV_GLOB=csv_folder/matrix_*.csv
# TABLE_NAME=matrix_lignes
# DO_UPSERT=true
# BATCH_SIZE=500
# ------------------------------------------

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE = os.environ.get("SUPABASE_SERVICE_ROLE")
CSV_GLOB = os.environ.get("CSV_GLOB", "matrix_*.csv")
TABLE_NAME = os.environ.get("TABLE_NAME", "matrix_lignes")
DO_UPSERT = os.environ.get("DO_UPSERT", "true").lower() == "true"
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "500"))

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
    raise RuntimeError("Veuillez définir SUPABASE_URL et SUPABASE_SERVICE_ROLE dans le fichier .env.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)

# ---------- Helpers de parsing ----------

def parse_decimal_fr(value: str):
    if value is None:
        return None
    v = value.strip().replace("€", "").replace(" ", "")
    if not v:
        return None
    v = v.replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None

def parse_int(value: str):
    if value is None:
        return None
    v = value.strip().replace(" ", "")
    if v == "":
        return None
    try:
        return int(v)
    except ValueError:
        return None

def parse_date_fr(d: str):
    if not d:
        return None
    return datetime.strptime(d.strip(), "%d/%m/%Y").date().isoformat()

# mapping très tolérant sur noms de colonnes
HEADER_ALIASES = {
    "Nom du magasin": {"Nom du magasin", "Magasin", "Store", "Nom_du_magasin"},
    "Date de la période": {"Date de la période", "Date", "Période", "Date_periode"},
    "Code article": {"Code article", "Code", "Code_article"},
    "Libellé article": {"Libellé article", "Libelle article", "Libellé", "Libelle_article"},
    "Qté": {"Qté", "Qte", "Quantité", "Quantite"},
    "Achat HT facturation": {"Achat HT facturation", "Achat_HT_facturation", "Achat facturation HT"},
    "Achat HT cession": {"Achat HT cession", "Achat_HT_cession", "Achat cession HT"},
    "Ventes HT": {"Ventes HT", "Vente HT", "Ventes_HT"},
    "Ventes TTC": {"Ventes TTC", "Vente TTC", "Ventes_TTC"},
    "Marge HT": {"Marge HT", "Marge_HT"},
    "Marge %": {"Marge %", "Marge%", "Marge_pct"},
}

def pick(d: Dict[str, str], wanted: str, header_map: Dict[str, set]):
    # Cherche la clé qui correspond à "wanted" dans d, en s'appuyant sur HEADER_ALIASES
    if wanted in d:
        return d[wanted]
    for alias in header_map.get(wanted, {wanted}):
        if alias in d:
            return d[alias]
    # Essai insensible à la casse / espaces
    low = {k.lower().strip(): k for k in d.keys()}
    for alias in header_map.get(wanted, {wanted}):
        key = alias.lower().strip()
        if key in low:
            return d[low[key]]
    return None

def row_from_csv_dict(d: Dict[str, str], source_file: str) -> Dict[str, Any]:
    return {
        "store_name": (pick(d, "Nom du magasin", HEADER_ALIASES) or "").strip().strip('"'),
        "period_date": parse_date_fr(pick(d, "Date de la période", HEADER_ALIASES) or ""),
        "code_article": (pick(d, "Code article", HEADER_ALIASES) or "").strip().strip('"'),
        "libelle_article": (pick(d, "Libellé article", HEADER_ALIASES) or "").strip().strip('"'),
        "qte": parse_int(pick(d, "Qté", HEADER_ALIASES)),
        "achat_ht_facturation": parse_decimal_fr(pick(d, "Achat HT facturation", HEADER_ALIASES)),
        "achat_ht_cession": parse_decimal_fr(pick(d, "Achat HT cession", HEADER_ALIASES)),
        "ventes_ht": parse_decimal_fr(pick(d, "Ventes HT", HEADER_ALIASES)),
        "ventes_ttc": parse_decimal_fr(pick(d, "Ventes TTC", HEADER_ALIASES)),
        "marge_ht": parse_decimal_fr(pick(d, "Marge HT", HEADER_ALIASES)),
        "marge_pct": parse_decimal_fr(pick(d, "Marge %", HEADER_ALIASES)),
        "source_file": source_file,
    }

def read_csv_dicts_with_fallback(path: str):
    """Essaie encodages/délimiteurs et renvoie (rows, header, delimiter)."""
    # essais d'encodage
    encodings = ["utf-8-sig", "utf-8", "latin-1"]
    delimiters_to_try = [';', ',', '\t', '|']
    last_error = None

    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                sample = f.read(8192)
                # Détection délimiteur
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=''.join(delimiters_to_try))
                    delim = dialect.delimiter
                except Exception:
                    # fallback : priorise ';' puis ','
                    if ';' in sample:
                        delim = ';'
                    elif ',' in sample:
                        delim = ','
                    else:
                        delim = '\t'
                f.seek(0)
                reader = csv.DictReader(f, delimiter=delim)
                rows = list(reader)
                header = reader.fieldnames or []
                return rows, header, delim
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(f"Impossible de lire {path} (dernier essai: {last_error})")

# ---------- Upload ----------

def upload_rows(rows: List[Dict[str, Any]]):
    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i : i + BATCH_SIZE]
        if DO_UPSERT:
            supabase.table(TABLE_NAME).upsert(chunk).execute()
        else:
            supabase.table(TABLE_NAME).insert(chunk).execute()

def process_file(path: str):
    try:
        rows_dicts, header, delim = read_csv_dicts_with_fallback(path)
        if not rows_dicts:
            print(f"[INFO] Fichier vide ou en-têtes non reconnues : {path}")
            print(f"       Délimiteur: {repr(delim)} | Header détecté: {header}")
            return

        print(f"[DEBUG] {path} | delim={repr(delim)} | colonnes={header} | lignes={len(rows_dicts)}")
        rows = [row_from_csv_dict(d, os.path.basename(path)) for d in rows_dicts]

        bad_dates = sum(1 for r in rows if not r["period_date"])
        if bad_dates > 0:
            print(f"[WARN] {bad_dates} ligne(s) sans date jj/mm/aaaa) dans {path}")

        upload_rows(rows)
        print(f"[OK] Importé : {path} ({len(rows)} lignes)")
    except Exception as e:
        print(f"[ERREUR] {path} : {e}")

def main():
    files = sorted(glob.glob(CSV_GLOB))
    if not files:
        print(f"Aucun fichier trouvé avec le motif : {CSV_GLOB}")
        return
    for p in files:
        process_file(p)
    print("Terminé ✅")

if __name__ == "__main__":
    main()
