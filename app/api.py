from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, jsonify, request, current_app
from .security import current_user, get_repository, login_required, roles_required
from .services import InsufficientStockError, InvalidStatusTransitionError, ValidationError
from .yandex_market_client import YandexMarketClient
from .yandex_market_service import YandexMarketService


api_bp = Blueprint("api", __name__)


def _json_ready(value):
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


@api_bp.get("/products")
@login_required
def api_products():
    return jsonify(_json_ready(get_repository().list_products_with_stock()))


@api_bp.get("/orders")
@login_required
def api_orders():
    return jsonify(_json_ready(get_repository().list_orders()))


@api_bp.get("/orders/<int:order_id>")
@login_required
def api_order_detail(order_id: int):
    order = get_repository().get_order(order_id)
    if not order:
        return jsonify({"error": "Заказ не найден"}), 404
    return jsonify(_json_ready(order))


@api_bp.post("/orders")
@roles_required("ADMIN", "MANAGER")
def api_create_order():
    payload = request.get_json(silent=True) or {}
    try:
        order = get_repository().create_order(payload, current_user()["id"])
        return jsonify(_json_ready(order)), 201
    except (ValidationError, InsufficientStockError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.patch("/orders/<int:order_id>/status")
@roles_required("ADMIN", "MANAGER", "WAREHOUSE")
def api_update_order_status(order_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        order = get_repository().update_order_status(order_id, payload.get("status", ""), current_user()["id"])
        return jsonify(_json_ready(order))
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 404
    except InvalidStatusTransitionError as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.patch("/orders/<int:order_id>/priority")
@roles_required("ADMIN", "MANAGER")
def api_update_order_priority(order_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        order = get_repository().update_order_priority(order_id, int(payload.get("priority", 0)), current_user()["id"])
        return jsonify(_json_ready(order))
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/dashboard/tasks")
@login_required
def api_tasks():
    return jsonify(
        _json_ready(
        {
            "summary": get_repository().get_dashboard_summary(),
            "tasks": get_repository().list_shipping_tasks(),
        }
        )
    )


@api_bp.post("/yandex-market/sync")
@roles_required("ADMIN")
def api_yandex_sync():
    config = current_app.config
    token = config.get("YANDEX_MARKET_TOKEN")
    campaign_id = config.get("YANDEX_MARKET_CAMPAIGN_ID")
    warehouse_id = config.get("YANDEX_MARKET_WAREHOUSE_ID", 1)

    if not token or not campaign_id:
        return jsonify({"error": "API Яндекс Маркета не настроено"}), 400

    client = YandexMarketClient(token=token, campaign_id=campaign_id)
    service = YandexMarketService(client=client, repository=get_repository())

    try:
        stocks_res = service.sync_stocks(warehouse_id=warehouse_id)
        prices_res = service.sync_prices()
        return jsonify({
            "message": "Синхронизация завершена",
            "stocks_results": stocks_res,
            "prices_results": prices_res
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
