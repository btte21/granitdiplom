import logging
import time
from typing import Any, Dict, List, Optional

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

class YandexMarketClient:
    BASE_URL = "https://api.partner.market.yandex.ru/v2"

    def __init__(self, api_key: str, campaign_id: str, business_id: Optional[str] = None):
        self.api_key = api_key.strip() if api_key else ""
        self.campaign_id = campaign_id.strip() if campaign_id else ""
        self.business_id = business_id.strip() if business_id else None
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _request(self, method: str, path: str, json: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None, retries: int = 3) -> Dict[str, Any]:
        url = f"{self.BASE_URL}{path}"

        for attempt in range(retries):
            try:
                response = self.session.request(method, url, json=json, params=params)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 1))
                    logger.warning(f"Rate limit exceeded (429). Retrying in {retry_after} seconds... (Attempt {attempt + 1}/{retries})")
                    time.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    logger.warning(f"Server error ({response.status_code}). Retrying... (Attempt {attempt + 1}/{retries})")
                    time.sleep(2 ** attempt)
                    continue

                if not response.ok:
                    error_detail = ""
                    try:
                        error_data = response.json()
                        error_detail = f" - {error_data}"
                    except Exception:
                        error_detail = f" - {response.text}"

                    if response.status_code == 423:
                        logger.error(f"Error 423 (Locked): The method cannot be used for this store. Check Campaign ID and Store status.{error_detail}")

                    response.raise_for_status()

                return response.json()

            except RequestException as e:
                if attempt == retries - 1:
                    # Try to get more info from the response if it exists
                    msg = str(e)
                    if e.response is not None:
                        try:
                            msg = f"{e} - {e.response.json()}"
                        except Exception:
                            msg = f"{e} - {e.response.text}"
                    logger.error(f"Request failed after {retries} attempts: {msg}")
                    raise
                logger.warning(f"Request failed: {e}. Retrying... (Attempt {attempt + 1}/{retries})")
                time.sleep(2 ** attempt)

        raise RequestException("Max retries exceeded")

    def update_stocks(self, skus_stocks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Updates stocks for offers.
        API Docs: PUT /campaigns/{campaignId}/offers/stocks
        skus_stocks: List of dicts like {'sku': '...', 'warehouseId': ..., 'items': [{'count': ..., 'type': 'FIT', 'updatedAt': '...'}]}
        """
        path = f"/campaigns/{self.campaign_id}/offers/stocks.json"
        payload = {"skus": skus_stocks}
        return self._request("PUT", path, json=payload)

    def update_prices(self, prices: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Updates prices for offers.
        prices: List of dicts like {'offerId': '...', 'price': {'value': ..., 'currencyId': 'RUR'}}
        """
        path = f"/campaigns/{self.campaign_id}/offer-prices/updates.json"
        payload = {"offers": prices}
        return self._request("POST", path, json=payload)

    def get_orders(self, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Retrieves a list of orders.
        API Docs: POST /campaigns/{campaignId}/orders
        """
        path = f"/campaigns/{self.campaign_id}/orders.json"
        return self._request("POST", path, json=filters)
