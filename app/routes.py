import json

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .security import current_user, get_repository, login_required, roles_required
from .services import InsufficientStockError, InvalidStatusTransitionError, ValidationError


ui_bp = Blueprint("ui", __name__)


def _parse_order_form(form):
    items_json = form.get("items_json", "[]")
    try:
        items = json.loads(items_json)
    except json.JSONDecodeError as exc:
        raise ValidationError("Order items must be valid JSON.") from exc

    normalized_items = []
    for item in items:
        normalized_items.append(
            {
                "product_id": int(item["product_id"]),
                "quantity": int(item["quantity"]),
            }
        )

    return {
        "order_number": form.get("order_number", "").strip(),
        "customer_name": form.get("customer_name", "").strip(),
        "customer_email": form.get("customer_email", "").strip(),
        "customer_phone": form.get("customer_phone", "").strip(),
        "priority": int(form.get("priority", "3")),
        "notes": form.get("notes", "").strip(),
        "items": normalized_items,
    }


@ui_bp.route("/")
def index():
    return redirect(url_for("ui.dashboard"))


@ui_bp.route("/dashboard")
@login_required
def dashboard():
    repo = get_repository()
    return render_template(
        "dashboard.html",
        summary=repo.get_dashboard_summary(),
        tasks=repo.list_shipping_tasks(),
        orders=repo.list_orders()[:5],
        warehouse_users=repo.list_users_by_role("WAREHOUSE"),
    )


@ui_bp.route("/products")
@login_required
def products():
    return render_template("products.html", products=get_repository().list_products_with_stock())


@ui_bp.route("/orders")
@login_required
def orders():
    repo = get_repository()
    return render_template(
        "orders.html",
        orders=repo.list_orders(),
        products=repo.list_products_with_stock(),
    )


@ui_bp.route("/orders", methods=["POST"])
@roles_required("ADMIN", "MANAGER")
def create_order():
    repo = get_repository()
    try:
        payload = _parse_order_form(request.form)
        repo.create_order(payload, current_user()["id"])
        flash("Order created and stock reserved successfully.", "success")
    except (ValidationError, InsufficientStockError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("ui.orders"))


@ui_bp.route("/orders/<int:order_id>/status", methods=["POST"])
@roles_required("ADMIN", "MANAGER", "WAREHOUSE")
def update_order_status(order_id: int):
    repo = get_repository()
    try:
        repo.update_order_status(order_id, request.form.get("status", ""), current_user()["id"])
        flash("Order status updated.", "success")
    except (ValidationError, InvalidStatusTransitionError) as exc:
        flash(str(exc), "danger")
    return redirect(request.referrer or url_for("ui.dashboard"))


@ui_bp.route("/orders/<int:order_id>/priority", methods=["POST"])
@roles_required("ADMIN", "MANAGER")
def update_order_priority(order_id: int):
    repo = get_repository()
    try:
        priority = int(request.form.get("priority", "3"))
        repo.update_order_priority(order_id, priority, current_user()["id"])
        flash("Order priority updated.", "success")
    except (ValidationError, ValueError) as exc:
        flash(str(exc), "danger")
    return redirect(request.referrer or url_for("ui.dashboard"))


@ui_bp.route("/tasks/<int:task_id>/assign", methods=["POST"])
@roles_required("ADMIN", "MANAGER")
def assign_task(task_id: int):
    repo = get_repository()
    try:
        assigned_to = int(request.form.get("assigned_to", "0"))
        repo.assign_shipping_task(task_id, assigned_to, current_user()["id"])
        flash("Shipping task assigned.", "success")
    except (ValidationError, ValueError) as exc:
        flash(str(exc), "danger")
    return redirect(request.referrer or url_for("ui.dashboard"))


@ui_bp.route("/warehouse")
@roles_required("ADMIN", "WAREHOUSE")
def warehouse():
    repo = get_repository()
    return render_template(
        "warehouse.html",
        tasks=repo.list_shipping_tasks(),
        products=repo.list_products_with_stock(),
    )


@ui_bp.route("/audit")
@roles_required("ADMIN")
def audit():
    return render_template("audit.html", logs=get_repository().list_audit_logs())
