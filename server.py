import os, json, datetime as dt
from functools import wraps
from collections import defaultdict
from flask import (
    Flask, request, jsonify, render_template, redirect,
    url_for, session, flash, send_from_directory
)
import requests

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change-me")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")

# ---------- Utilidades de seguridad ----------
def load_users():
    if not os.path.exists(USERS_FILE):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "admin": {
                    "password": "blackdog123",
                    "role": "admin",
                    "name": "BlackDog Admin",
                    "active": True
                },
                "BlackDog": {
                    "password": "1234",
                    "role": "client",
                    "name": "BlackDog Store",
                    "token": "BlackDog-ESP32-LOCAL",
                    "mp_access_token": os.environ.get("MP_ACCESS_TOKEN", ""),
                    "active": True
                }
            }, f, ensure_ascii=False, indent=2)
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_users(d):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def current_user():
    return session.get("user")

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def require_role(role):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            u = current_user()
            if not u:
                return redirect(url_for("login"))
            if u["role"] != role:
                flash("No tenés permiso para ver esto.", "err")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return wrapper
    return deco

def is_admin():
    u = current_user()
    return bool(u and u["role"] == "admin")

def effective_business_id():
    """Si el admin está impersonando, usamos ese; si no, usamos su id (si cliente)."""
    if is_admin() and session.get("impersonate"):
        return session["impersonate"]
    return session.get("business_id")

# ---------- Mercado Pago ----------
def mp_list_payments(access_token, limit=50):
    if not access_token:
        return []
    url = "https://api.mercadopago.com/v1/payments/search"
    params = {
        "sort": "date_created",
        "criteria": "desc",
        "limit": limit
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        if r.status_code != 200:
            app.logger.warning("MP error %s: %s", r.status_code, r.text)
            return []
        data = r.json()
        out = []
        for it in data.get("results", []):
            out.append({
                "id": str(it.get("id")),
                "estado": it.get("status"),
                "monto": float(it.get("transaction_amount", 0) or 0),
                "fecha": it.get("date_created"),
                "nombre": (it.get("payer", {}) or {}).get("first_name")
            })
        return out
    except Exception as e:
        app.logger.exception("MP list error: %s", e)
        return []

# ---------- Métricas ----------
def normalize_date(s):
    # ISO -> date
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        return dt.date.today()

def compute_metrics(rows):
    # Solo aprobados
    rows = [r for r in rows if (r.get("estado") == "approved")]
    today = dt.date.today()
    start_week = today - dt.timedelta(days=today.weekday())
    start_month = today.replace(day=1)

    def sum_count(since_date):
        total = 0.0
        count = 0
        for r in rows:
            d = normalize_date(r.get("fecha", ""))
            if d >= since_date:
                total += float(r.get("monto", 0) or 0)
                count += 1
        return total, count

    total_today, count_today = sum_count(today)
    total_week, count_week = sum_count(start_week)
    total_month, count_month = sum_count(start_month)

    # últimos 14 días
    daily = defaultdict(lambda: {"total": 0.0, "count": 0})
    for r in rows:
        d = normalize_date(r.get("fecha", ""))
        if (today - d).days <= 13:
            daily[d]["total"] += float(r.get("monto", 0) or 0)
            daily[d]["count"] += 1

    series = []
    for i in range(13, -1, -1):
        d = today - dt.timedelta(days=i)
        info = daily[d]
        series.append({
            "date": d.strftime("%d/%m"),
            "total": round(info["total"], 2),
            "count": info["count"]
        })

    return {
        "today": {"total": round(total_today, 2), "count": count_today},
        "week": {"total": round(total_week, 2), "count": count_week},
        "month": {"total": round(total_month, 2), "count": count_month},
        "series": series
    }

# ---------- Auth ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    token = request.form.get("token", "").strip()
    password = request.form.get("password", "").strip()
    users = load_users()

    # admin by id "admin" (sin token)
    if token.lower() == "admin":
        admin = users.get("admin")
        if not admin or not admin.get("active", True):
            flash("Admin deshabilitado.", "err")
            return redirect(url_for("login"))
        if password != admin.get("password"):
            flash("Contraseña incorrecta.", "err")
            return redirect(url_for("login"))
        session.clear()
        session["user"] = {"id": "admin", "role": "admin", "name": admin.get("name", "Admin")}
        flash("Sesión iniciada correctamente ✅", "ok")
        return redirect(url_for("admin_dashboard"))

    # buscar por token
    for biz_id, u in users.items():
        if biz_id == "admin":
            continue
        if not u.get("active", True):
            continue
        if u.get("token") == token and password == u.get("password"):
            session.clear()
            session["user"] = {"id": biz_id, "role": u.get("role", "client"), "name": u.get("name", biz_id)}
            session["business_id"] = biz_id
            flash("Sesión iniciada correctamente ✅", "ok")
            return redirect(url_for("dashboard"))

    flash("Credenciales inválidas.", "err")
    return redirect(url_for("login"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- Panel cliente (o admin en modo impersonate) ----------
@app.route("/")
@login_required
def dashboard():
    users = load_users()
    biz_id = effective_business_id()
    if is_admin() and not biz_id:
        # admin sin impersonate -> a panel admin
        return redirect(url_for("admin_dashboard"))
    user = users.get(biz_id) or {}
    payments = mp_list_payments(user.get("mp_access_token", ""))
    metrics = compute_metrics(payments)
    return render_template("dashboard.html",
                           metrics=metrics,
                           rows=payments[:100],
                           business_id=biz_id,
                           business_name=user.get("name", biz_id),
                           is_admin=is_admin(),
                           impersonating=is_admin() and bool(session.get("impersonate")))

# ---------- Admin: Dashboard Global ----------
@app.route("/admin")
@login_required
@require_role("admin")
def admin_dashboard():
    users = load_users()
    # ranking + métricas globales
    board = []
    global_rows = []
    for biz_id, u in users.items():
        if biz_id == "admin":
            continue
        if not u.get("active", True):
            continue
        rows = mp_list_payments(u.get("mp_access_token", ""))
        global_rows.extend(rows)
        m = compute_metrics(rows)
        board.append({
            "id": biz_id,
            "name": u.get("name", biz_id),
            "active": u.get("active", True),
            "today_total": m["today"]["total"],
            "week_total": m["week"]["total"],
            "month_total": m["month"]["total"]
        })
    global_metrics = compute_metrics(global_rows)
    board = sorted(board, key=lambda x: x["month_total"], reverse=True)
    return render_template("admin_dashboard.html",
                           board=board,
                           metrics=global_metrics)

# ---------- Admin: ver negocio específico ----------
@app.route("/admin/business/<biz_id>")
@login_required
@require_role("admin")
def admin_business_view(biz_id):
    users = load_users()
    u = users.get(biz_id)
    if not u:
        flash("Negocio no encontrado.", "err")
        return redirect(url_for("admin_dashboard"))
    rows = mp_list_payments(u.get("mp_access_token", ""))
    metrics = compute_metrics(rows)
    return render_template("business_view.html",
                           business_id=biz_id,
                           business=u,
                           rows=rows[:100],
                           metrics=metrics)

# ---------- Impersonación ----------
@app.route("/admin/impersonate/<biz_id>")
@login_required
@require_role("admin")
def admin_impersonate(biz_id):
    users = load_users()
    if biz_id not in users or biz_id == "admin":
        flash("Negocio inválido.", "err")
        return redirect(url_for("admin_dashboard"))
    session["impersonate"] = biz_id
    flash(f"Impersonando a {biz_id}.", "ok")
    return redirect(url_for("dashboard"))

@app.route("/admin/stop")
@login_required
@require_role("admin")
def admin_stop_impersonate():
    session.pop("impersonate", None)
    flash("Volviste al modo administrador.", "ok")
    return redirect(url_for("admin_dashboard"))

# ---------- Admin: activar / desactivar negocio (toggle) ----------
@app.route("/admin/toggle/<biz_id>", methods=["POST"])
@login_required
@require_role("admin")
def admin_toggle_business(biz_id):
    users = load_users()
    if biz_id not in users or biz_id == "admin":
        return jsonify({"ok": False, "msg": "Negocio inválido"})
    users[biz_id]["active"] = not users[biz_id].get("active", True)
    save_users(users)
    return jsonify({"ok": True, "active": users[biz_id]["active"]})

# ---------- Config usuario (clave) ----------
@app.route("/config/user", methods=["GET", "POST"])
@login_required
def config_user():
    users = load_users()
    if request.method == "GET":
        return render_template("config_user.html")
    newpass = request.form.get("password", "").strip()
    if not newpass:
        flash("Contraseña inválida", "err")
        return redirect(url_for("config_user"))
    uid = "admin" if is_admin() else session.get("business_id")
    users[uid]["password"] = newpass
    save_users(users)
    flash("Contraseña actualizada.", "ok")
    return redirect(url_for("config_user"))

# ---------- Assets ----------
@app.route("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(app.root_path, "static", "img"),
                               "ic_launcher.png")

# ---------- Ruta simple para el ESP32 (legacy) ----------
@app.route("/pagos")
def pagos_plain():
    """Conservamos /pagos simple para compatibilidad, usa el primer negocio activo."""
    users = load_users()
    # el primero que tenga access token
    for biz_id, u in users.items():
        if biz_id == "admin":
            continue
        if u.get("active", True) and u.get("mp_access_token"):
            return jsonify(mp_list_payments(u["mp_access_token"]))
    return jsonify([])

# ---------- Errores ----------
@app.errorhandler(403)
def _403(_e): return render_template("error.html", code=403, msg="Prohibido"), 403

@app.errorhandler(404)
def _404(_e): return render_template("error.html", code=404, msg="No encontrado"), 404

@app.errorhandler(500)
def _500(_e): return render_template("error.html", code=500, msg="Error interno"), 500

# ---------- App ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
