# generate_hashes.py
import bcrypt
import getpass

def hash_password(clear_pwd: str) -> str:
    # génère un hash bcrypt et renvoie la chaîne décodée
    return bcrypt.hashpw(clear_pwd.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def main():
    print("Générateur de hashes bcrypt")
    print("Tu peux entrer plusieurs mots de passe (appuie sur Entrée sans rien pour terminer).")
    results = []
    while True:
        # getpass masque la saisie du mot de passe dans le terminal
        pwd = getpass.getpass("Mot de passe à hasher (vide = terminer) : ")
        if not pwd:
            break
        h = hash_password(pwd)
        results.append((pwd, h))
        print(" -> hash généré :", h)
        print("")

    if results:
        print("\n--- Récapitulatif (copie/colle les hash côté Streamlit Secrets) ---")
        for i, (_, h) in enumerate(results, start=1):
            print(f"{i}. {h}")
    else:
        print("Aucun mot de passe saisi. Fin.")

if __name__ == "__main__":
    main()
