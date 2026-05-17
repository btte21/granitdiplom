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
        Fetches orders from Yandex Market and logs them.
        """
        filters = {}
        if status:
            filters["status"] = status

        try:
            orders_data = self.client.get_orders(filters=filters)
            orders = orders_data.get("orders", [])
            logger.info(f"Fetched {len(orders)} orders from Yandex Market.")

            for order in orders:
                logger.info(f"Processing Yandex Market Order: ID={order.get('id')}, Status={order.get('status')}")
                # Future: Map and save to local repository

            return orders_data
        except Exception as e:
            logger.error(f"Failed to fetch orders from Yandex Market: {e}")
            raise
