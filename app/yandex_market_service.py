import logging
from typing import List, Optional
from .yandex_market_client import YandexMarketClient
from .yandex_market_models import SKUStock, StockItem, OfferPrice, PriceValue, to_dict
from .repository import PostgresRepository

logger = logging.getLogger(__name__)

class YandexMarketService:
    BATCH_SIZE = 500

    def __init__(self, client: YandexMarketClient, repository: PostgresRepository):
        self.client = client
        self.repository = repository

    def sync_stocks(self, warehouse_id: int):
        """
        Syncs all active products' stocks from the repository to Yandex Market.
        """
        products = self.repository.list_products_with_stock()
        sku_stocks = []

        for product in products:
            sku_stocks.append(SKUStock(
                sku=product["sku"],
                warehouseId=warehouse_id,
                items=[StockItem(count=max(0, product["available_qty"]))]
            ))

        results = []
        for i in range(0, len(sku_stocks), self.BATCH_SIZE):
            batch = sku_stocks[i:i + self.BATCH_SIZE]
            try:
                response = self.client.update_stocks([to_dict(s) for s in batch])
                logger.info(f"Successfully synced batch of {len(batch)} product stocks to Yandex Market.")
                results.append(response)
            except Exception as e:
                logger.error(f"Failed to sync batch of stocks to Yandex Market: {e}")
                raise
        return results

    def sync_prices(self):
        """
        Syncs all active products' prices from the repository to Yandex Market.
        """
        products = self.repository.list_products_with_stock()
        offer_prices = []

        for product in products:
            offer_prices.append(OfferPrice(
                offerId=product["sku"],
                price=PriceValue(value=float(product["unit_price"]))
            ))

        results = []
        for i in range(0, len(offer_prices), self.BATCH_SIZE):
            batch = offer_prices[i:i + self.BATCH_SIZE]
            try:
                response = self.client.update_prices([to_dict(p) for p in batch])
                logger.info(f"Successfully synced batch of {len(batch)} product prices to Yandex Market.")
                results.append(response)
            except Exception as e:
                logger.error(f"Failed to sync batch of prices to Yandex Market: {e}")
                raise
        return results

    def fetch_and_process_orders(self, status: Optional[str] = None):
        """
        Fetches orders from Yandex Market and creates them in the local repository.
        """
        filters = {}
        if status:
            filters["status"] = status

        try:
            orders_data = self.client.get_orders(filters=filters)
            orders = orders_data.get("orders", [])
            logger.info(f"Fetched {len(orders)} orders from Yandex Market.")

            created_count = 0
            skipped_count = 0
            error_count = 0

            for ym_order in orders:
                ym_id = ym_order.get("id")
                order_number = f"YM-{ym_id}"

                # Check if already exists
                existing = self.repository.get_order_by_number(order_number)
                if existing:
                    skipped_count += 1
                    continue

                try:
                    payload = self._map_ym_order_to_payload(ym_order)
                    # Use admin actor ID (1) for system-created orders
                    self.repository.create_order(payload, actor_id=1)
                    created_count += 1
                    logger.info(f"Created local order {order_number} from Yandex Market.")
                except Exception as e:
                    error_count += 1
                    logger.error(f"Failed to process Yandex Market Order {ym_id}: {e}")

            return {
                "fetched": len(orders),
                "created": created_count,
                "skipped": skipped_count,
                "errors": error_count
            }
        except Exception as e:
            logger.error(f"Failed to fetch orders from Yandex Market: {e}")
            raise

    def _map_ym_order_to_payload(self, ym_order: dict) -> dict:
        """
        Maps Yandex Market order data to local order payload.
        """
        ym_id = ym_order.get("id")
        buyer = ym_order.get("buyer", {})

        items = []
        for ym_item in ym_order.get("items", []):
            sku = ym_item.get("offerId")
            product = self.repository.get_product_by_sku(sku)
            if not product:
                raise ValueError(f"Product with SKU {sku} not found in local repository.")

            items.append({
                "product_id": product["id"],
                "quantity": ym_item.get("count", 1),
                "unit_price": float(ym_item.get("price", product["unit_price"]))
            })

        payload = {
            "order_number": f"YM-{ym_id}",
            "customer_name": f"{buyer.get('lastName', '')} {buyer.get('firstName', '')}".strip() or "Yandex Market Customer",
            "customer_email": buyer.get("email", "no-email@market.yandex.ru"),
            "customer_phone": buyer.get("phone", "no-phone"),
            "priority": 3,
            "notes": f"Yandex Market Order ID: {ym_id}",
            "items": items
        }
        return payload
