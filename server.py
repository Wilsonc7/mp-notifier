# ==========================
#  BlackDog Systems - Server
# ==========================

from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from datetime import datetime
from pytz import timezone
import json
import os

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "blackdog-secret-key")

# ============================================================
# 🔧 Inyectar datetime y hora local en todas las plantillas Jinja
# ============================================================
@app.context_processor
def inject_datetime():
    """Inyecta objetos datetime en Jinja para uso global"""
    tz = timezone("America/Argentina/Cordoba")
    now_local = datetime.now(tz)
    return {
        "datetime": datetime,      # permite usar {{ datetime.utcnow().year }}
        "localtime": now_local     # permite usar {{ localtime.strftime('%H:%M') }}
    }

# ============================================================
# 📁 Funciones de manejo de JSON (usuarios, pagos, etc.)
# ============================================================
def load_json(file_path, default_data):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(default_data, f, indent=4)
        return default_data
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default_data

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ============================================================
# 🗂️ Archivos de datos
# ============================================================
USERS_FILE = "data/users.json"
PAYMENTS_FILE = "data/payments.json"
os.makedirs("data", exist_ok=True)

users_data = load_json(USERS_FILE, {
    "admin": {"password": "admin123", "role": "admin", "active": True}
})
payments_data = load_json(PAYMENTS_FILE, {})

# ============================================================
# 🔐 Verificaciones de sesión
# ============================================================
def is_logged_in():
    return "user_id" in session

def is_admin():
    return session.get("role") == "admin"

# ============================================================
# 🌐 Rutas principales
# ============================================================
@app.route("/")
def home():
    if "user_id" in session:
        return redirect("/dashboard")
    return redirect("/login")

# ============================================================
# 🔑 LOGIN / LOGOUT
# ============================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    users = load_json(USERS_FILE, {})
    if request.method == "POST":
        user_id = request.form.get("id")
        password = request.form.get("password")
        user = users.get(user_id)

        if user and user.get("password") == password and user.get("active", True):
            session["user_id"] = user_id
            session["role"] = user.get("role", "client")
            return redirect("/dashboard")
        else:
            return render_template("login.html", error="Credenciales inválidas o cuenta bloqueada")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ============================================================
# 📊 DASHBOARD (Admin / Cliente)
# ============================================================
@app.route("/dashboard")
def dashboard():
    if not is_logged_in():
        return redirect("/login")

    users = load_json(USERS_FILE, {})
    payments = load_json(PAYMENTS_FILE, {})
    user_id = session["user_id"]
    role = session.get("role", "client")

    if role == "admin":
        negocios = [u for u in users.values() if u.get("role") == "client"]
        return render_template("admin_dashboard.html", user=users[user_id], negocios=negocios)

    negocio = users.get(user_id)
    if not negocio:
        return render_template("error.html", code=403, msg="Usuario no encontrado")

    token = negocio.get("token")
    pagos = payments.get(token, [])

    hoy = datetime.now().date()
    semana = hoy.replace(day=max(1, hoy.day - 7))
    mes = hoy.replace(day=max(1, hoy.day - 30))

    total_hoy = sum(p["monto"] for p in pagos if p["fecha"][:10] == str(hoy))
    total_semana = sum(p["monto"] for p in pagos if p["fecha"][:10] >= str(semana))
    total_mes = sum(p["monto"] for p in pagos if p["fecha"][:10] >= str(mes))

    return render_template("business_view.html",
                           negocio=negocio,
                           total_hoy=total_hoy,
                           total_semana=total_semana,
                           total_mes=total_mes,
                           pagos=pagos)

# ============================================================
# ⚙️ ADMIN: GESTIÓN DE NEGOCIOS
# ============================================================
@app.route("/admin/users", methods=["GET", "POST"])
def admin_users():
    if not is_logged_in() or not is_admin():
        return render_template("forbidden.html"), 403

    users = load_json(USERS_FILE, {})

    if request.method == "POST":
        id = request.form.get("id")
        token = request.form.get("token")
        name = request.form.get("name")
        password = request.form.get("password")
        active = request.form.get("active") == "Sí"
        access_token = request.form.get("access_token")

        if id:
            users[id] = {
                "id": id,
                "token": token,
                "name": name,
                "password": password or users.get(id, {}).get("password", ""),
                "active": active,
                "access_token": access_token,
                "role": "client"
            }
            save_json(USERS_FILE, users)

    return render_template("admin_users.html", users=users)

@app.route("/admin/toggle/<user_id>")
def toggle_user(user_id):
    users = load_json(USERS_FILE, {})
    if user_id in users:
        users[user_id]["active"] = not users[user_id].get("active", True)
        save_json(USERS_FILE, users)
    return redirect("/admin/users")
    # ============================================================
# 🧾 ADMIN: DETALLE DE UN NEGOCIO (solo lectura)
# ============================================================
@app.route("/admin/business/<user_id>")
def admin_business_detail(user_id):
    if not is_logged_in() or not is_admin():
        return render_template("forbidden.html"), 403

    users = load_json(USERS_FILE, {})
    payments = load_json(PAYMENTS_FILE, {})

    negocio = users.get(user_id)
    if not negocio:
        return render_template("error.html", code=404, msg="Negocio no encontrado")

    token = negocio.get("token")
    movimientos = payments.get(token, [])

    # Totales
    total_hoy = sum(p["monto"] for p in movimientos if p["fecha"][:10] == str(datetime.now().date()))
    total_semana = sum(p["monto"] for p in movimientos)
    total_mes = total_semana  # En esta versión son iguales, podés ampliarlo luego

    return render_template(
        "business_detail.html",
        negocio=negocio,
        movimientos=movimientos,
        total_hoy=total_hoy,
        total_semana=total_semana,
        total_mes=total_mes
    )


# ============================================================
# 🔒 CAMBIO DE CONTRASEÑA
# ============================================================
@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if not is_logged_in():
        return redirect("/login")

    users = load_json(USERS_FILE, {})
    user = users.get(session["user_id"])
    msg = ""

    if request.method == "POST":
        old = request.form.get("old")
        new = request.form.get("new")
        if user["password"] == old:
            user["password"] = new
            save_json(USERS_FILE, users)
            msg = "Contraseña cambiada correctamente"
        else:
            msg = "Contraseña anterior incorrecta"

    return render_template("change_password.html", user=user, msg=msg)

# ============================================================
# ⚙️ CONFIGURACIÓN DE USUARIO
# ============================================================
@app.route("/config")
def config_user():
    if not is_logged_in():
        return redirect("/login")

    users = load_json(USERS_FILE, {})
    user = users.get(session["user_id"])
    return render_template("config_user.html", user=user)

# ============================================================
# 🔌 API PARA ESP32
# ============================================================
@app.route("/api/add_payment")
def add_payment():
    token = request.args.get("token")
    monto = request.args.get("monto")

    if not token or not monto:
        return jsonify({"error": "Faltan parámetros"}), 400

    payments = load_json(PAYMENTS_FILE, {})
    if token not in payments:
        payments[token] = []

    payments[token].append({
        "monto": float(monto),
        "fecha": datetime.now().isoformat()
    })
    save_json(PAYMENTS_FILE, payments)

    return jsonify({"status": "ok", "msg": "Pago registrado"})

@app.route("/api/payments")
def api_payments():
    token = request.args.get("token")
    if not token:
        return jsonify({"error": "Token requerido"}), 400

    users = load_json(USERS_FILE, {})
    negocio = next((u for u in users.values() if u.get("token") == token), None)

    if not negocio:
        return jsonify({"error": "Negocio no encontrado"}), 404

    payments = load_json(PAYMENTS_FILE, {}).get(token, [])
    return jsonify({"negocio": negocio["name"], "pagos": payments})

# ============================================================
# 🧱 ERRORES PERSONALIZADOS
# ============================================================
@app.errorhandler(403)
def _403(_e):
    return render_template("forbidden.html"), 403

@app.errorhandler(404)
def _404(_e):
    return render_template("error.html", code=404, msg="No encontrado"), 404

@app.errorhandler(500)
def _500(_e):
    return render_template("error.html", code=500, msg="Error interno"), 500

# ============================================================
# 🚀 EJECUCIÓN LOCAL / DEPLOY
# ============================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
