from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import json, os, datetime

app = Flask(__name__)
app.secret_key = "blackdog_secret"

# =====================
# ARCHIVOS DE DATOS
# =====================
USERS_FILE = "data/users.json"
PAYMENTS_FILE = "data/payments.json"

# =====================
# FUNCIONES AUXILIARES
# =====================
def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_users():
    return load_json(USERS_FILE)

def save_users(data):
    save_json(USERS_FILE, data)

def load_payments():
    return load_json(PAYMENTS_FILE)

def save_payments(data):
    save_json(PAYMENTS_FILE, data)

# =====================
# RUTA PRINCIPAL
# =====================
@app.route("/")
def home():
    if "user_id" in session:
        return redirect("/dashboard")
    return redirect("/login")

# =====================
# LOGIN / LOGOUT
# =====================
@app.route("/login", methods=["GET", "POST"])
def login():
    users = load_users()
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

# =====================
# DASHBOARD
# =====================
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    users = load_users()
    payments = load_payments()
    user_id = session["user_id"]
    role = session.get("role", "client")

    # ADMIN → puede ver todos los negocios
    if role == "admin":
        negocios = [u for u in users.values() if u["role"] == "client"]
        return render_template("admin_dashboard.html", user=users[user_id], negocios=negocios)

    # CLIENTE → sólo su negocio
    negocio = users.get(user_id)
    if not negocio:
        return render_template("error.html", code=403, msg="Usuario no encontrado")

    token = negocio.get("token")
    pagos = payments.get(token, [])

    hoy = datetime.date.today()
    semana = hoy - datetime.timedelta(days=7)
    mes = hoy - datetime.timedelta(days=30)

    total_hoy = sum(p["monto"] for p in pagos if datetime.date.fromisoformat(p["fecha"][:10]) == hoy)
    total_semana = sum(p["monto"] for p in pagos if datetime.date.fromisoformat(p["fecha"][:10]) >= semana)
    total_mes = sum(p["monto"] for p in pagos if datetime.date.fromisoformat(p["fecha"][:10]) >= mes)

    return render_template("business_view.html",
                           negocio=negocio,
                           total_hoy=total_hoy,
                           total_semana=total_semana,
                           total_mes=total_mes,
                           pagos=pagos)

# =====================
# ADMIN: GESTIÓN DE NEGOCIOS
# =====================
@app.route("/admin/users", methods=["GET", "POST"])
def admin_users():
    if "user_id" not in session or session.get("role") != "admin":
        return render_template("forbidden.html"), 403

    users = load_users()

    if request.method == "POST":
        id = request.form.get("id")
        token = request.form.get("token")
        name = request.form.get("name")
        password = request.form.get("password")
        active = request.form.get("active") == "Sí"
        role = "client"
        access_token = request.form.get("access_token")

        if id:
            users[id] = {
                "id": id,
                "token": token,
                "name": name,
                "password": password or users.get(id, {}).get("password", ""),
                "active": active,
                "access_token": access_token,
                "role": role
            }
            save_users(users)

    return render_template("admin_users.html", users=users)

@app.route("/admin/toggle/<user_id>")
def toggle_user(user_id):
    users = load_users()
    if user_id in users:
        users[user_id]["active"] = not users[user_id].get("active", True)
        save_users(users)
    return redirect("/admin/users")

# =====================
# CAMBIO DE CONTRASEÑA
# =====================
@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if "user_id" not in session:
        return redirect("/login")

    users = load_users()
    user = users.get(session["user_id"])
    msg = ""

    if request.method == "POST":
        old = request.form.get("old")
        new = request.form.get("new")
        if user["password"] == old:
            user["password"] = new
            save_users(users)
            msg = "Contraseña cambiada correctamente"
        else:
            msg = "Contraseña anterior incorrecta"

    return render_template("change_password.html", user=user, msg=msg)

# =====================
# CONFIGURACIÓN DE USUARIO
# =====================
@app.route("/config")
def config_user():
    if "user_id" not in session:
        return redirect("/login")

    users = load_users()
    user = users.get(session["user_id"])
    return render_template("config_user.html", user=user)

# =====================
# API PARA ESP32
# =====================
@app.route("/api/add_payment")
def add_payment():
    token = request.args.get("token")
    monto = request.args.get("monto")

    if not token or not monto:
        return jsonify({"error": "Faltan parámetros"}), 400

    payments = load_payments()
    if token not in payments:
        payments[token] = []

    payments[token].append({
        "monto": float(monto),
        "fecha": datetime.datetime.now().isoformat()
    })
    save_payments(payments)

    return jsonify({"status": "ok", "msg": "Pago registrado"})

@app.route("/api/payments")
def api_payments():
    token = request.args.get("token")
    if not token:
        return jsonify({"error": "Token requerido"}), 400

    users = load_users()
    negocio = next((u for u in users.values() if u.get("token") == token), None)

    if not negocio:
        return jsonify({"error": "Negocio no encontrado"}), 404

    payments = load_payments().get(token, [])

    return jsonify({
        "negocio": negocio["name"],
        "pagos": payments
    })

# =====================
# MANEJO DE ERRORES
# =====================
@app.errorhandler(403)
def _403(_e):
    return render_template("forbidden.html"), 403

@app.errorhandler(404)
def _404(_e):
    return render_template("error.html", code=404, msg="No encontrado"), 404

@app.errorhandler(500)
def _500(_e):
    return render_template("error.html", code=500, msg="Error interno"), 500

# =====================
# EJECUCIÓN LOCAL / DEPLOY
# =====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
