# ==========================
#  BlackDog Systems - Hash Passwords Utility
# ==========================

import json
import os
from werkzeug.security import generate_password_hash

USERS_FILE = "data/users.json"

def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def hash_passwords():
    users = load_json(USERS_FILE, {})
    changed = False

    for uid, info in users.items():
        pwd = info.get("password", "")
        # Detecta si ya está hasheado (los hashes empiezan con 'pbkdf2')
        if pwd and not pwd.startswith("pbkdf2:"):
            hashed = generate_password_hash(pwd)
            users[uid]["password"] = hashed
            changed = True
            print(f"✅ Contraseña de '{uid}' convertida a hash seguro")

    if changed:
        save_json(USERS_FILE, users)
        print("\n💾 Archivo 'users.json' actualizado con contraseñas seguras.")
    else:
        print("🔒 Todas las contraseñas ya estaban cifradas.")

if __name__ == "__main__":
    hash_passwords()
