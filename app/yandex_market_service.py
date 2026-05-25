import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .repository import PostgresRepository
from .yandex_market_client import YandexMarketClient
from .yandex_market_models import OfferPrice, PriceValue, SKUStock, StockItem, to_dict


logger = logging.getLogger(__name__)


class YandexMarketService:
    BATCH_SIZE = 500
    IMPORT_PAGE_SIZE = 200

    def __init__(self, client: YandexMarketClient, repository: PostgresRepository):
        self.client = client
        self.repository = repository

    def import_nomenclature(self) -> dict[str, int]:
        """
        Imports the Yandex Market assortment into the local products table.
        """
        imported_count = 0
        created_count = 0
        updated_count = 0
        page_token: Optional[str] = None

        while True:
            response = self.client.get_offer_mappings(page_token=page_token, limit=self.IMPORT_PAGE_SIZE)
            result = response.get("result", {})
            offer_mappings = result.get("offerMappings", [])
            if not offer_mappings:
                break

            mapped_products = [self._map_offer_mapping_to_product(offer) for offer in offer_mappings]
            sync_result = self.repository.upsert_market_products(mapped_products)

            imported_count += len(mapped_products)
            created_count += sync_result["created"]
            updated_count += sync_result["updated"]

            page_token = result.get("paging", {}).get("nextPageToken")
            if not page_token:
                break

        return {
            "imported": imported_count,
            "created": created_count,
            "updated": updated_count,
        }

    def import_stocks(self, stocks_warehouse_id: Optional[int] = None) -> dict[str, int]:
        """
        Imports stock balances from Yandex Market into the local warehouse table.
        """
        page_token: Optional[str] = None
        stock_by_sku: dict[str, dict[str, int | str]] = {}
        fetched_rows = 0

        while True:
            response = self.client.get_stocks(
                page_token=page_token,
                limit=self.IMPORT_PAGE_SIZE,
                stocks_warehouse_id=stocks_warehouse_id,
            )
            result = response.get("result", {})
            warehouses = result.get("warehouses", [])
            if not warehouses:
                break

            page_rows = 0
            for warehouse in warehouses:
                for offer_row in warehouse.get("offers", []):
                    aggregated = self._aggregate_stock_offer(offer_row)
                    if not aggregated:
                        continue

                    page_rows += 1
                    existing = stock_by_sku.get(aggregated["sku"])
                    if not existing:
                        stock_by_sku[aggregated["sku"]] = aggregated
                    else:
                        existing["on_hand_qty"] += aggregated["on_hand_qty"]
                        existing["reserved_qty"] += aggregated["reserved_qty"]

            fetched_rows += page_rows
            if page_rows == 0:
                break

            page_token = result.get("paging", {}).get("nextPageToken")
            if not page_token:
                break

        placeholder_products = []
        for sku in stock_by_sku:
            if not self.repository.get_product_by_sku(sku):
                placeholder_products.append(
                    {
                        "sku": sku,
                        "name": f"Yandex Market SKU {sku}",
                        "technical_specs": {"source": "yandex_market_stock"},
                        "unit_price": 0,
                    }
                )

        product_sync = {"created": 0, "updated": 0}
        if placeholder_products:
            product_sync = self.repository.upsert_market_products(placeholder_products)

        stock_sync = self.repository.upsert_market_stocks(list(stock_by_sku.values()))
        return {
            "fetched": fetched_rows,
            "sku_count": len(stock_by_sku),
            "products_created": product_sync["created"],
            "products_updated": product_sync["updated"],
            "stocks_created": stock_sync["created"],
            "stocks_updated": stock_sync["updated"],
        }

    def sync_stocks(self, warehouse_id: int):
        """
        Syncs all active products' stocks from the repository to Yandex Market.
        """
        products = self.repository.list_products_with_stock()
        sku_stocks = []

        for product in products:
            sku_stocks.append(
                SKUStock(
                    sku=product["sku"],
                    warehouseId=warehouse_id,
                    items=[StockItem(count=max(0, product["available_qty"]))],
                )
            )

        results = []
        for i in range(0, len(sku_stocks), self.BATCH_SIZE):
            batch = sku_stocks[i : i + self.BATCH_SIZE]
            try:
                response = self.client.update_stocks([to_dict(s) for s in batch])
                logger.info(f"Successfully synced batch of {len(batch)} product stocks to Yandex Market.")
                results.append(response)
            except Exception as exc:
                logger.error(f"Failed to sync batch of stocks to Yandex Market: {exc}")
                raise
        return results

    def sync_prices(self):
        """
        Syncs all active products' prices from the repository to Yandex Market.
        """
        products = self.repository.list_products_with_stock()
        offer_prices = []

        for product in products:
            offer_prices.append(
                OfferPrice(
                    offerId=product["sku"],
                    price=PriceValue(value=float(product["unit_price"])),
                )
            )

        results = []
        for i in range(0, len(offer_prices), self.BATCH_SIZE):
            batch = offer_prices[i : i + self.BATCH_SIZE]
            try:
                response = self.client.update_prices([to_dict(p) for p in batch])
                logger.info(f"Successfully synced batch of {len(batch)} product prices to Yandex Market.")
                results.append(response)
            except Exception as exc:
                logger.error(f"Failed to sync batch of prices to Yandex Market: {exc}")
                raise
        return results

    def fetch_and_process_orders(self, status: Optional[str] = None):
        """
        Fetches orders from Yandex Market and creates them in the local repository.
        """
        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status

        try:
            orders = self._fetch_all_orders(filters)
            logger.info(f"Fetched {len(orders)} orders from Yandex Market.")

            created_count = 0
            skipped_count = 0
            error_count = 0

            for ym_order in orders:
                ym_id = self._extract_order_id(ym_order)
                order_number = self._build_market_order_number(ym_order)

                existing = self.repository.get_order_by_number(order_number)
                if existing:
                    skipped_count += 1
                    continue

                try:
                    payload = self._map_ym_order_to_payload(ym_order)
                    self.repository.create_external_order(payload, actor_id=1)
                    created_count += 1
                    logger.info(f"Created local order {order_number} from Yandex Market.")
                except Exception as exc:
                    error_count += 1
                    logger.error(f"Failed to process Yandex Market Order {ym_id}: {exc}")

            return {
                "fetched": len(orders),
                "created": created_count,
                "skipped": skipped_count,
                "errors": error_count,
            }
        except Exception as exc:
            logger.error(f"Failed to fetch orders from Yandex Market: {exc}")
            raise

    def _fetch_all_orders(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        page_token: Optional[str] = None
        orders: list[dict[str, Any]] = []

        while True:
            response = self.client.get_orders(filters=filters, page_token=page_token, limit=self.IMPORT_PAGE_SIZE)
            result = response.get("result", response)
            page_orders = result.get("orders", [])
            if not page_orders:
                break

            orders.extend(page_orders)
            page_token = result.get("paging", {}).get("nextPageToken")
            if not page_token:
                break

        return orders

    def _aggregate_stock_offer(self, offer_row: dict[str, Any]) -> Optional[dict[str, int | str]]:
        sku = offer_row.get("offerId") or offer_row.get("sku") or offer_row.get("shopSku")
        if not sku:
            return None

        total_fit = 0
        total_freeze = 0
        total_available = 0

        for item in offer_row.get("stocks", []):
            count = int(item.get("count", 0) or 0)
            stock_type = str(item.get("type", "")).upper()

            if stock_type == "FIT":
                total_fit += count
            elif stock_type == "FREEZE":
                total_freeze += count
            elif stock_type == "AVAILABLE":
                total_available += count

        on_hand_qty = total_fit if total_fit else total_available + total_freeze
        reserved_qty = min(total_freeze, on_hand_qty)

        return {
            "sku": sku,
            "on_hand_qty": max(on_hand_qty, 0),
            "reserved_qty": max(reserved_qty, 0),
        }

    def _map_offer_mapping_to_product(self, offer_mapping: dict[str, Any]) -> dict[str, Any]:
        offer = offer_mapping.get("offer", {})
        mapping = offer_mapping.get("mapping", {})
        prices = offer_mapping.get("prices", {})
        basic_price = prices.get("basicPrice", {})

        sku = offer.get("offerId") or offer.get("shopSku") or mapping.get("shopSku") or mapping.get("offerId")
        if not sku:
            raise ValueError("Offer mapping does not contain a usable SKU.")

        name = (
            offer.get("name")
            or mapping.get("name")
            or mapping.get("marketSkuName")
            or offer.get("shopSku")
            or sku
        )

        technical_specs = {
            "source": "yandex_market",
            "vendor": offer.get("vendor"),
            "category": offer.get("category"),
            "market_category": mapping.get("marketCategoryName"),
            "market_sku": mapping.get("marketSku"),
            "barcodes": offer.get("barcodes", []),
        }

        return {
            "sku": sku,
            "name": name,
            "technical_specs": {key: value for key, value in technical_specs.items() if value not in (None, "", [], {})},
            "unit_price": float(basic_price.get("value") or 0),
        }

    def _extract_order_id(self, ym_order: dict[str, Any]) -> str:
        order_id = ym_order.get("id") or ym_order.get("orderId")
        if order_id is None:
            raise ValueError("Yandex Market order does not contain an id.")
        return str(order_id)

    def _build_market_order_number(self, ym_order: dict[str, Any]) -> str:
        order_id = self._extract_order_id(ym_order)
        order_date = self._extract_order_date(ym_order)
        return f"YM-{order_date}-{order_id}"

    def _extract_order_date(self, ym_order: dict[str, Any]) -> str:
        raw_date = ym_order.get("creationDate") or ym_order.get("createdAt") or ym_order.get("creationDateTime")
        if not raw_date:
            return datetime.now(timezone.utc).date().isoformat()

        normalized = raw_date.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return datetime.now(timezone.utc).date().isoformat()

        return parsed.date().isoformat()

    def _map_ym_order_to_payload(self, ym_order: dict) -> dict:
        """
        Maps Yandex Market order data to local order payload.
        """
        ym_id = self._extract_order_id(ym_order)
        buyer = ym_order.get("buyer", {})
        recipient = ym_order.get("delivery", {}).get("recipient", {})
        recipient_person = recipient.get("person", {}) if isinstance(recipient, dict) else {}

        items = []
        for ym_item in ym_order.get("items", []):
            sku = ym_item.get("offerId") or ym_item.get("shopSku")
            product = self._ensure_product_for_order_item(ym_item, sku)

            items.append(
                {
                    "product_id": product["id"],
                    "quantity": ym_item.get("count", 1),
                    "unit_price": self._extract_item_price(ym_item, product["unit_price"]),
                }
            )

        payload = {
            "order_number": self._build_market_order_number(ym_order),
            "customer_name": self._extract_customer_name(buyer, recipient_person),
            "customer_email": buyer.get("email", "no-email@market.yandex.ru"),
            "customer_phone": buyer.get("phone") or recipient.get("phone", "no-phone"),
            "priority": 3,
            "notes": f"Yandex Market Order ID: {ym_id}",
            "items": items,
        }
        return payload

    def _extract_customer_name(self, buyer: dict[str, Any], recipient_person: dict[str, Any]) -> str:
        buyer_name = f"{buyer.get('lastName', '')} {buyer.get('firstName', '')}".strip()
        recipient_name = (
            recipient_person.get("fullName")
            or f"{recipient_person.get('lastName', '')} {recipient_person.get('firstName', '')}".strip()
        )
        return buyer_name or recipient_name or "Yandex Market Customer"

    def _extract_item_price(self, ym_item: dict[str, Any], fallback_price: Any) -> float:
        raw_price = (
            ym_item.get("price")
            or ym_item.get("buyerPrice")
            or ym_item.get("prices", {}).get("payment", {}).get("value")
            or fallback_price
        )
        return float(raw_price)

    def _ensure_product_for_order_item(self, ym_item: dict[str, Any], sku: Optional[str]) -> dict[str, Any]:
        if not sku:
            raise ValueError("Yandex Market order item does not contain SKU.")

        product = self.repository.get_product_by_sku(sku)
        if product:
            return product

        price = self._extract_item_price(ym_item, 0)
        technical_specs = {
            "source": "yandex_market_order",
            "offer_name": ym_item.get("offerName") or ym_item.get("name"),
            "ware_md5": ym_item.get("wareMd5"),
        }
        self.repository.upsert_market_products(
            [
                {
                    "sku": sku,
                    "name": ym_item.get("offerName") or ym_item.get("name") or f"Yandex Market SKU {sku}",
                    "technical_specs": {key: value for key, value in technical_specs.items() if value not in (None, "", [], {})},
                    "unit_price": price,
                }
            ]
        )
        product = self.repository.get_product_by_sku(sku)
        if not product:
            raise ValueError(f"Product with SKU {sku} not found in local repository.")
        return product
