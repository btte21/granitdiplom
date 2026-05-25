from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, current_app, jsonify, request

from .security import current_user, get_repository, login_required, roles_required
from .services import InsufficientStockError, InvalidStatusTransitionError, ValidationError
from .yandex_market_client import YandexMarketClient
from .yandex_market_service import YandexMarketService


api_bp = Blueprint("api", __name__)


def _is_missing_market_config(value):
    normalized = str(value or "").strip().lower()
    return normalized in {
        "",
        "your-api-key",
        "your-campaign",
        "your-campaign-id",
        "your-business",
        "your-business-id",
    }


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


def _build_yandex_market_service():
    config = current_app.config
    api_key = config.get("YANDEX_MARKET_API_KEY")
    campaign_id = config.get("YANDEX_MARKET_CAMPAIGN_ID")
    business_id = config.get("YANDEX_MARKET_BUSINESS_ID")

    if _is_missing_market_config(api_key) or _is_missing_market_config(campaign_id):
        return None, jsonify({"error": "API Яндекс Маркета не настроено: укажите YANDEX_MARKET_API_KEY и YANDEX_MARKET_CAMPAIGN_ID."}), 400

    client = YandexMarketClient(
        api_key=api_key,
        campaign_id=campaign_id,
        business_id=None if _is_missing_market_config(business_id) else business_id,
    )
    return YandexMarketService(client=client, repository=get_repository()), None, None


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
    service, error_response, status_code = _build_yandex_market_service()
    if error_response:
        return error_response, status_code

    try:
        products_res = service.import_nomenclature()
        orders_res = service.fetch_and_process_orders()
        return jsonify(
            {
                "message": "Синхронизация завершена",
                "products_results": products_res,
                "orders_results": orders_res,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@api_bp.post("/yandex-market/products/sync")
@roles_required("ADMIN")
def api_yandex_sync_products():
    service, error_response, status_code = _build_yandex_market_service()
    if error_response:
        return error_response, status_code

    try:
        products_res = service.import_nomenclature()
        return jsonify(
            {
                "message": "Номенклатура из Яндекс Маркета загружена.",
                "products_results": products_res,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@api_bp.post("/yandex-market/stocks/sync")
@roles_required("ADMIN")
def api_yandex_sync_stocks():
    service, error_response, status_code = _build_yandex_market_service()
    if error_response:
        return error_response, status_code

    try:
        warehouse_id = current_app.config.get("YANDEX_MARKET_WAREHOUSE_ID")
        stocks_res = service.import_stocks(stocks_warehouse_id=warehouse_id)
        return jsonify(
            {
                "message": "Остатки из Яндекс Маркета загружены.",
                "stocks_results": stocks_res,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@api_bp.post("/yandex-market/orders/sync")
@roles_required("ADMIN")
def api_yandex_sync_orders():
    service, error_response, status_code = _build_yandex_market_service()
    if error_response:
        return error_response, status_code

    try:
        products_res = service.import_nomenclature()
        orders_res = service.fetch_and_process_orders()
        return jsonify(
            {
                "message": "Заказы из Яндекс Маркета загружены.",
                "products_results": products_res,
                "orders_results": orders_res,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
