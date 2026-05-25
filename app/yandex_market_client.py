import logging
import time
from typing import Any, Dict, List, Optional

import requests
from requests.exceptions import HTTPError, RequestException


logger = logging.getLogger(__name__)


class YandexMarketClient:
    BASE_URL = "https://api.partner.market.yandex.ru/v2"
    BUSINESS_BASE_URL = "https://api.partner.market.yandex.ru/v1"

    def __init__(self, api_key: str, campaign_id: str, business_id: Optional[str] = None):
        self.api_key = (api_key or "").strip()
        self.campaign_id = str(campaign_id or "").strip()
        self.business_id = str(business_id).strip() if business_id else None
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Api-Key": self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        retries: int = 3,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = f"{base_url or self.BASE_URL}{path}"

        for attempt in range(retries):
            try:
                response = self.session.request(method, url, json=json, params=params, timeout=30)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 1))
                    logger.warning(
                        f"Rate limit exceeded (429). Retrying in {retry_after} seconds... "
                        f"(Attempt {attempt + 1}/{retries})"
                    )
                    time.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    logger.warning(f"Server error ({response.status_code}). Retrying... (Attempt {attempt + 1}/{retries})")
                    time.sleep(2 ** attempt)
                    continue

                if response.status_code >= 400:
                    raise HTTPError(self._format_http_error(response, url), response=response)

                if not response.content:
                    return {}

                return response.json()

            except RequestException as exc:
                if attempt == retries - 1:
                    logger.error(f"Request failed after {retries} attempts: {exc}")
                    raise
                logger.warning(f"Request failed: {exc}. Retrying... (Attempt {attempt + 1}/{retries})")
                time.sleep(2 ** attempt)

        raise RequestException("Max retries exceeded")

    def _format_http_error(self, response: requests.Response, url: str) -> str:
        details = self._extract_error_details(response)
        return f"{response.status_code} Client Error: {details or 'Unknown error'} for url: {url}"

    def _extract_error_details(self, response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return (response.text or "").strip()

        errors = payload.get("errors") or []
        if errors:
            return "; ".join(
                f'{error.get("code", "ERROR")}: {error.get("message", "Unknown error")}'
                for error in errors
            )

        return payload.get("message") or payload.get("status") or ""

    def update_stocks(self, skus_stocks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Updates stocks for offers.
        API Docs: PUT /campaigns/{campaignId}/offers/stocks
        skus_stocks: List of dicts like {'sku': '...', 'warehouseId': ..., 'items': [{'count': ..., 'type': 'FIT', 'updatedAt': '...'}]}
        """
        path = f"/campaigns/{self.campaign_id}/offers/stocks"
        payload = {"skus": skus_stocks}
        return self._request("PUT", path, json=payload)

    def update_prices(self, prices: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Updates prices for offers.
        prices: List of dicts like {'offerId': '...', 'price': {'value': ..., 'currencyId': 'RUR'}}
        """
        if self.business_id:
            path = f"/businesses/{self.business_id}/offer-prices/updates"
        else:
            path = f"/campaigns/{self.campaign_id}/offer-prices/updates"
        payload = {"offers": prices}
        return self._request("POST", path, json=payload)

    def get_token_info(self) -> Dict[str, Any]:
        """
        Returns information about the transmitted Api-Key token.
        API Docs: POST /auth/token
        """
        return self._request("POST", "/auth/token")

    def get_offer_mappings(
        self,
        page_token: Optional[str] = None,
        limit: int = 100,
        archived: bool = False,
    ) -> Dict[str, Any]:
        """
        Returns the catalog assortment for the business.
        API Docs: POST /v2/businesses/{businessId}/offer-mappings
        """
        if not self.business_id:
            raise ValueError("business_id is required to fetch Yandex Market nomenclature.")

        params: Dict[str, Any] = {"limit": limit}
        if page_token:
            params["pageToken"] = page_token

        payload = {"archived": archived}
        path = f"/businesses/{self.business_id}/offer-mappings"
        return self._request("POST", path, json=payload, params=params)

    def get_stocks(
        self,
        page_token: Optional[str] = None,
        limit: int = 200,
        archived: bool = False,
        stocks_warehouse_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Returns stock balances for the campaign.
        API Docs: POST /v2/campaigns/{campaignId}/offers/stocks
        """
        params: Dict[str, Any] = {"limit": limit}
        if page_token:
            params["pageToken"] = page_token

        payload: Dict[str, Any] = {"archived": archived}
        if stocks_warehouse_id is not None:
            payload["stocksWarehouseId"] = stocks_warehouse_id

        path = f"/campaigns/{self.campaign_id}/offers/stocks"
        return self._request("POST", path, json=payload, params=params)

    def get_orders(
        self,
        filters: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Retrieves a list of orders.
        API Docs:
          - POST /v1/businesses/{businessId}/orders
          - GET /v2/campaigns/{campaignId}/orders
        """
        normalized_filters = self._normalize_order_filters(filters)

        if self.business_id:
            path = f"/businesses/{self.business_id}/orders"
            params: Dict[str, Any] = {}
            if page_token:
                params["pageToken"] = page_token
            if limit is not None:
                params["limit"] = limit
            return self._request("POST", path, json=normalized_filters, params=params, base_url=self.BUSINESS_BASE_URL)

        path = f"/campaigns/{self.campaign_id}/orders"
        campaign_params = self._business_filters_to_campaign_params(normalized_filters)
        if page_token:
            campaign_params["page_token"] = page_token
        if limit is not None:
            campaign_params["limit"] = limit
        return self._request("GET", path, params=campaign_params)

    def _normalize_order_filters(self, filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        normalized = dict(filters or {})
        status = normalized.pop("status", None)
        statuses = normalized.get("statuses")
        if status and not statuses:
            normalized["statuses"] = [status]
        return normalized

    def _business_filters_to_campaign_params(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        params: Dict[str, Any] = {}

        statuses = filters.get("statuses")
        if statuses:
            params["statuses"] = statuses

        substatuses = filters.get("substatuses")
        if substatuses:
            params["substatuses"] = substatuses

        order_ids = filters.get("orderIds")
        if order_ids:
            params["orderIds"] = order_ids

        fake = filters.get("fake")
        if fake is not None:
            params["fake"] = fake

        return params
