# ==========================
#  BlackDog Systems - Server (SQLite Edition)
# ==========================

from flask import Flask, render_template, request, redirect, jsonify, session
from datetime import datetime
from pytz import timezone
from werkzeug.security import generate_password_hash, check_password_hash
import json, os, sqlite3

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "blackdog-super-secret")

# Cookies seguras
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ============================================================
# 🔧 Inyectar datetime
# ============================================================
@app.context_processor
def inject_datetime():
    tz = timezone("America/Argentina/Cordoba")
    now_local = datetime.now(tz)
    return {"datetime": datetime, "localtime": now_local}

# ============================================================
# 📂 Archivos y DB
# ============================================================
os.makedirs("data", exist_ok=True)
USERS_FILE = "data/users.json"
DB_FILE = "data/payments.db"

# ============================================================
# 🧩 Base de datos SQLite
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY,
            token TEXT,
            estado TEXT,
            nombre TEXT,
            monto REAL,
            fecha TEXT,
            fecha_local TEXT
        )
    """)
    conn.commit()
    conn.close()

def insert_payment(pago):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO payments (id, token, estado, nombre, monto, fecha, fecha_local)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        pago["id"], pago["token"], pago["estado"], pago["nombre"],
        pago["monto"], pago["fecha"], pago["fecha_local"]
    ))
    conn.commit()
    conn.close()

def get_payments(token):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT estado, fecha, fecha_local, id, monto, nombre FROM payments WHERE token=? ORDER BY fecha DESC", (token,))
    rows = cur.fetchall()
    conn.close()
    pagos = []
    for r in rows:
        pagos.append({
            "estado": r[0],
            "fecha": r[1],
            "fecha_local": r[2],
            "id": r[3],
            "monto": r[4],
            "nombre": r[5]
        })
    return pagos

# ============================================================
# 🧠 Utilidades
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

def is_logged_in(): 
    return "user_id" in session

def is_admin(): 
    return session.get("role") == "admin"

# ============================================================
# 🔑 LOGIN / LOGOUT
# ============================================================
@app.route("/")
def home():
    if is_logged_in():
        return redirect("/dashboard")
    return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    users = load_json(USERS_FILE, {})
    if request.method == "POST":
        user_input = request.form.get("id", "").strip()
        password = request.form.get("password", "").strip()

        user_id, user = None, None
        for uid, info in users.items():
            if uid.lower() == user_input.lower() or info.get("token", "").lower() == user_input.lower():
                user_id, user = uid, info
                break

        if user and user.get("active", True) and check_password_hash(user["password"], password):
            session["user_id"] = user_id
            session["role"] = user.get("role", "client")
            return redirect("/dashboard")

        return render_template("login.html", error="Credenciales inválidas")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ============================================================
# 📊 DASHBOARD
# ============================================================
@app.route("/dashboard")
def dashboard():
    if not is_logged_in():
        return redirect("/login")

    users = load_json(USERS_FILE, {})
    user_id = session["user_id"]
    role = session.get("role", "client")

    if role == "admin":
        negocios = [
            {**info, "id": uid} for uid, info in users.items() if info.get("role") != "admin"
        ]
        return render_template("admin_dashboard.html", user=users[user_id], negocios=negocios)

    negocio = users.get(user_id)
    if not negocio:
        return render_template("error.html", code=403, msg="Usuario no encontrado")

    token = negocio.get("token")
    pagos = get_payments(token)

    hoy = datetime.now().date()
    total_hoy = sum(p["monto"] for p in pagos if p["fecha"][:10] == str(hoy))
    total_semana = sum(p["monto"] for p in pagos)
    total_mes = total_semana

    return render_template("business_view.html",
                           negocio=negocio,
                           total_hoy=total_hoy,
                           total_semana=total_semana,
                           total_mes=total_mes,
                           pagos=pagos)

# ============================================================
# 🔌 API PARA ESP32
# ============================================================
@app.route("/api/add_payment")
def add_payment():
    token = request.args.get("token")
    monto = request.args.get("monto")
    nombre = request.args.get("nombre", "Cliente")
    estado = request.args.get("estado", "approved")

    if not token or not monto:
        return jsonify({"error": "Faltan parámetros"}), 400

    pago = {
        "id": f"{token}-{int(datetime.now().timestamp())}",
        "token": token,
        "estado": estado,
        "nombre": nombre,
        "monto": float(monto),
        "fecha": datetime.now().isoformat(),
        "fecha_local": datetime.now(timezone("America/Argentina/Cordoba")).strftime("%Y-%m-%d %H:%M:%S")
    }

    insert_payment(pago)
    return jsonify({"status": "ok", "msg": "Pago registrado", "pago": pago})

@app.route("/api/payments")
def api_payments():
    token = request.args.get("token")
    if not token:
        return jsonify({"error": "Token requerido"}), 400

    users = load_json(USERS_FILE, {})
    negocio = next((u for u in users.values() if u.get("token", "").lower() == token.lower()), None)
    if not negocio:
        return jsonify({"error": "Negocio no encontrado"}), 404

    pagos = get_payments(token)
    return jsonify({"negocio": negocio["name"], "pagos": pagos})

# ============================================================
# 🧱 ERRORES
# ============================================================
@app.errorhandler(403)
def _403(_e): return render_template("forbidden.html"), 403
@app.errorhandler(404)
def _404(_e): return render_template("error.html", code=404, msg="No encontrado"), 404
@app.errorhandler(500)
def _500(_e): return render_template("error.html", code=500, msg="Error interno"), 500

# ============================================================
# 🚀 MAIN
# ============================================================
if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
