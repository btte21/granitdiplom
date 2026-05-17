from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from .security import get_repository
from .services import DatabaseConnectionError


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        try:
            user = get_repository().authenticate_user(email, password)
        except DatabaseConnectionError as exc:
            flash(str(exc), "danger")
            return render_template("login.html"), 503
        if user:
            session.clear()
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            next_url = request.args.get("next") or url_for("ui.dashboard")
            return redirect(next_url)
        flash("Неверные учетные данные или неактивный аккаунт.", "danger")
    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
