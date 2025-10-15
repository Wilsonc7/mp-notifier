# ============================================================
#  BlackDog Systems - MP Transfer Notifier (SQLite Secure Edition)
# ============================================================

from flask import Flask, render_template, request, redirect, jsonify, session
from datetime import datetime
from pytz import timezone
from werkzeug.security import generate_password_hash, check_password_hash
import json, os, time, threading, sqlite3, requests, base64
from cryptography.fernet import Fernet

# ------------------------------------------------------------
# 🔧 Configuración general Flask
# ------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "blackdog-super-secret")

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = True  # Render usa HTTPS
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ------------------------------------------------------------
# 🕒 Fecha local
# ------------------------------------------------------------
@app.context_processor
def inject_datetime():
    tz = timezone("America/Argentina/Cordoba")
    now_local = datetime.now(tz)
    return {"datetime": datetime, "localtime": now_local}

# ------------------------------------------------------------
# 📁 Archivos y rutas base
# ------------------------------------------------------------
os.makedirs("data", exist_ok=True)
USERS_FILE = "data/users.json"
DB_PATH = "data/payments.db"
KEY_FILE = "data/.key"

# ============================================================
# 🔐 Inicialización del sistema
# ============================================================
if not os.path.exists(KEY_FILE):
    with open(KEY_FILE, "wb") as f:
        f.write(Fernet.generate_key())
fernet = Fernet(open(KEY_FILE, "rb").read())

# ============================================================
# 📦 Funciones JSON
# ============================================================
def load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4)
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ============================================================
# 🧠 Sesión y roles
# ============================================================
def is_logged_in(): 
    return "user_id" in session

def is_admin(): 
    return session.get("role") == "admin"

# ============================================================
# 💾 SQLite: pagos
# ============================================================
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id TEXT PRIMARY KEY,
        negocio TEXT,
        nombre TEXT,
        monto REAL,
        estado TEXT,
        fecha_local TEXT
    )
    """)
    con.commit()
    con.close()

def add_payment(negocio, pago):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id FROM payments WHERE id=?", (pago["id"],))
    if cur.fetchone() is None:
        cur.execute("INSERT INTO payments VALUES (?, ?, ?, ?, ?, ?)",
                    (pago["id"], negocio, pago["nombre"], pago["monto"],
                     pago["estado"], pago["fecha_local"]))
        con.commit()
    con.close()

def get_payments_by_token(token):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id,nombre,monto,estado,fecha_local FROM payments WHERE negocio=? ORDER BY fecha_local DESC", (token,))
    rows = cur.fetchall()
    con.close()
    return [{"id": r[0], "nombre": r[1], "monto": r[2], "estado": r[3], "fecha_local": r[4]} for r in rows]

# ============================================================
# 🔐 Cifrado de tokens
# ============================================================
def encrypt_token(token: str) -> str:
    return fernet.encrypt(token.encode()).decode()

def decrypt_token(token_enc: str) -> str:
    try:
        return fernet.decrypt(token_enc.encode()).decode()
    except Exception:
        return ""

# ============================================================
# 🔄 Consultar Mercado Pago
# ============================================================
def fetch_movements_for_business(name, access_token):
    url = "https://api.mercadopago.com/v1/account/movements"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            for mov in data.get("results", []):
                if mov.get("type") in ["credited", "accredited"]:
                    pago = {
                        "id": mov.get("id", str(time.time())),
                        "nombre": mov.get("counterpart_name", "Cliente"),
                        "monto": mov.get("amount", 0.0),
                        "estado": mov.get("type"),
                        "fecha_local": mov.get("date_created", "")
                    }
                    add_payment(name, pago)
        else:
            print(f"[MP] {name} → Error {r.status_code}")
    except Exception as e:
        print(f"[MP] {name} → Fallo conexión:", e)

# ============================================================
# 🕓 Polling automático cada 20 segundos
# ============================================================
def polling_thread():
    while True:
        users = load_json(USERS_FILE, {})
        for user, info in users.items():
            if not info.get("active"): 
                continue
            access_token = decrypt_token(info.get("mp_access_token", ""))
            if access_token:
                fetch_movements_for_business(info.get("token"), access_token)
        time.sleep(20)

# ============================================================
# 🔑 LOGIN / LOGOUT
# ============================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    users = load_json(USERS_FILE, {})

    if request.method == "POST":
        user_input = request.form.get("id", "").strip()
        password = request.form.get("password", "").strip()

        if not user_input or not password:
            return render_template("login.html", error="Complete todos los campos")

        user_id, user = None, None
        for uid, info in users.items():
            if uid.lower() == user_input.lower() or info.get("token", "").lower() == user_input.lower():
                user_id, user = uid, info
                break

        if user and user.get("active", True) and check_password_hash(user["password"], password):
            session["user_id"] = user_id
            session["role"] = user.get("role", "client")
            return redirect("/dashboard")

        return render_template("login.html", error="Credenciales inválidas o cuenta bloqueada")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ============================================================
# 🖥️ DASHBOARD
# ============================================================
@app.route("/")
def home():
    if is_logged_in():
        return redirect("/dashboard")
    return redirect("/login")

@app.route("/dashboard")
def dashboard():
    if not is_logged_in():
        return redirect("/login")

    users = load_json(USERS_FILE, {})
    user_id = session["user_id"]
    role = session.get("role", "client")

    if role == "admin":
        negocios = []
        for uid, info in users.items():
            if info.get("role") != "admin":
                info["id"] = uid
                negocios.append(info)
        return render_template("admin_dashboard.html", user=users[user_id], negocios=negocios)

    negocio = users.get(user_id)
    token = negocio.get("token")
    pagos = get_payments_by_token(token)

    hoy = datetime.now().date()
    total_hoy = sum(p["monto"] for p in pagos if p["fecha_local"][:10] == str(hoy))
    total_total = sum(p["monto"] for p in pagos)

    return render_template("business_view.html",
                           negocio=negocio,
                           total_hoy=total_hoy,
                           total_total=total_total,
                           pagos=pagos)

# ============================================================
# 🧩 ADMINISTRACIÓN DE USUARIOS
# ============================================================
@app.route("/admin/users", methods=["GET", "POST"])
def admin_users():
    if not is_logged_in() or not is_admin():
        return render_template("forbidden.html"), 403

    users = load_json(USERS_FILE, {})

    if request.method == "POST":
        id = request.form.get("id", "").strip()
        name = request.form.get("name", "").strip()
        token = request.form.get("token", "").strip()
        mp_access = request.form.get("mp_access_token", "").strip()
        password = request.form.get("password", "").strip()

        if not id or not name:
            return render_template("error.html", code=400, msg="Datos incompletos")

        if id not in users or password:
            pw_hash = generate_password_hash(password)
        else:
            pw_hash = users[id]["password"]

        users[id] = {
            "password": pw_hash,
            "name": name,
            "token": token,
            "role": "client",
            "active": True,
            "mp_access_token": encrypt_token(mp_access)
        }

        save_json(USERS_FILE, users)

    return render_template("admin_users.html", users=users)

# ============================================================
# 📡 API para ESP32
# ============================================================
@app.route("/api/payments")
def api_payments():
    token = request.args.get("token")
    if not token:
        return jsonify({"error": "Token requerido"}), 400
    pagos = get_payments_by_token(token)
    return jsonify({"negocio": token, "pagos": pagos})

# ============================================================
# 🚀 INICIO
# ============================================================
if __name__ == "__main__":
    init_db()
    threading.Thread(target=polling_thread, daemon=True).start()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
