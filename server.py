from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import json, os, datetime, requests

app = Flask(__name__)
app.secret_key = "blackdog_key_secret_2025"

USERS_FILE = "data/users.json"

# ======================================================
#  UTILIDADES
# ======================================================
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_users(data):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def current_user():
    if "user" in session:
        users = load_users()
        u = users.get(session["user"])
        if u:
            u["id"] = session["user"]
            return u
    return None

# ======================================================
#  DECORADORES DE ROL
# ======================================================
def login_required(func):
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

def admin_required(func):
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u or u.get("role") != "admin":
            flash("Acceso denegado", "err")
            return redirect(url_for("dashboard"))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

# ======================================================
#  LOGIN / LOGOUT
# ======================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        token = request.form.get("token", "").strip()
        password = request.form.get("password", "").strip()

        data = load_users()
        for k, u in data.items():
            if u.get("token") == token or k == token:
                if u.get("password") == password:
                    session["user"] = k
                    flash("Sesión iniciada correctamente ✅", "ok")
                    return redirect(url_for("dashboard"))
                else:
                    flash("Contraseña incorrecta", "err")
                    break
        else:
            flash("Token o usuario no encontrado", "err")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Sesión cerrada", "ok")
    return redirect(url_for("login"))

# ======================================================
#  DASHBOARD
# ======================================================
@app.route("/")
@login_required
def dashboard():
    user = current_user()
    if user["role"] == "admin":
        return redirect(url_for("admin_users"))

    # Si está bloqueado, mostrar igual pero sin datos
    if not user.get("active", True):
        return render_template("dashboard.html", user=user, totals={
            "day": {"total": 0, "count": 0},
            "week": {"total": 0, "count": 0},
            "month": {"total": 0, "count": 0}
        }, resumen=[])

    token_mp = user.get("mp_access_token", "")
    if not token_mp:
        flash("err")
        return render_template("dashboard.html", user=user, totals={
            "day": {"total": 0, "count": 0},
            "week": {"total": 0, "count": 0},
            "month": {"total": 0, "count": 0}
        }, resumen=[])

    headers = {"Authorization": f"Bearer {token_mp}"}
    now = datetime.datetime.now()
    start_month = now.replace(day=1).isoformat()
    url = f"https://api.mercadopago.com/v1/payments/search?status=approved&sort=date_created&criteria=desc"

    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json().get("results", [])
    except Exception:
        flash("err")
        data = []

    pagos = [
        {"fecha": p["date_created"][:10], "monto": p["transaction_amount"]}
        for p in data if p.get("status") == "approved"
    ]

    resumen = {}
    for p in pagos:
        resumen.setdefault(p["fecha"], {"monto": 0, "cantidad": 0})
        resumen[p["fecha"]]["monto"] += p["monto"]
        resumen[p["fecha"]]["cantidad"] += 1

    total_dia = total_sem = total_mes = 0
    cant_dia = cant_sem = cant_mes = 0

    hoy = now.date()
    semana = hoy - datetime.timedelta(days=7)
    mes = hoy.replace(day=1)

    for f, v in resumen.items():
        fecha = datetime.date.fromisoformat(f)
        if fecha == hoy:
            total_dia += v["monto"]
            cant_dia += v["cantidad"]
        if fecha >= semana:
            total_sem += v["monto"]
            cant_sem += v["cantidad"]
        if fecha >= mes:
            total_mes += v["monto"]
            cant_mes += v["cantidad"]

    resumen_list = [
        {"fecha": f, "monto": v["monto"], "cantidad": v["cantidad"]}
        for f, v in sorted(resumen.items(), reverse=True)
    ]

    return render_template("dashboard.html", user=user, totals={
        "day": {"total": total_dia, "count": cant_dia},
        "week": {"total": total_sem, "count": cant_sem},
        "month": {"total": total_mes, "count": cant_mes}
    }, resumen=resumen_list)

# ======================================================
#  ADMINISTRADOR
# ======================================================
@app.route("/admin/users")
@admin_required
def admin_users():
    return render_template("admin_users.html", users=load_users())

@app.route("/admin/save", methods=["POST"])
@admin_required
def admin_save():
    users = load_users()
    uid = request.form.get("id").strip()
    name = request.form.get("name").strip()
    token = request.form.get("token").strip()
    password = request.form.get("password").strip()
    mp_token = request.form.get("mp_access_token").strip()
    active = request.form.get("active") == "true"

    if not uid:
        flash("Debe ingresar un ID", "err")
        return redirect(url_for("admin_users"))

    users[uid] = users.get(uid, {})
    users[uid].update({
        "role": "client",
        "name": name or uid,
        "token": token,
        "active": active,
        "mp_access_token": mp_token
    })
    if password:
        users[uid]["password"] = password

    save_users(users)
    flash("Negocio guardado correctamente ✅", "ok")
    return redirect(url_for("admin_users"))

@app.route("/admin/toggle/<neg_id>")
@admin_required
def admin_toggle(neg_id):
    data = load_users()
    if neg_id in data and data[neg_id].get("role") == "client":
        data[neg_id]["active"] = not data[neg_id].get("active", True)
        save_users(data)
        flash(f"Negocio '{neg_id}' {'activado' if data[neg_id]['active'] else 'desactivado'} ✅", "ok")
    else:
        flash("Negocio no encontrado", "err")
    return redirect(url_for("admin_users"))

# ======================================================
#  API PARA ESP32
# ======================================================
@app.route("/api/status")
def api_status():
    token = request.args.get("token", "")
    users = load_users()
    for k, u in users.items():
        if u.get("token") == token:
            return jsonify({"active": u.get("active", True)})
    return jsonify({"active": False}), 404

@app.route("/api/payments")
def api_payments():
    token = request.args.get("token", "")
    users = load_users()
    for k, u in users.items():
        if u.get("token") == token:
            if not u.get("active", True):
                return jsonify([])

            mp_token = u.get("mp_access_token", "")
            if not mp_token:
                return jsonify([])

            headers = {"Authorization": f"Bearer {mp_token}"}
            url = "https://api.mercadopago.com/v1/payments/search?status=approved&sort=date_created&criteria=desc"
            try:
                r = requests.get(url, headers=headers, timeout=15)
                r.raise_for_status()
                return jsonify(r.json().get("results", []))
            except Exception:
                return jsonify([])
    return jsonify([])

# ======================================================
#  MAIN
# ======================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
