import unittest
from unittest.mock import MagicMock, patch

from requests.exceptions import HTTPError

from app.yandex_market_client import YandexMarketClient


class TestYandexMarketClient(unittest.TestCase):
    def setUp(self):
        self.client = YandexMarketClient(api_key="test-api-key", campaign_id="test-campaign")

    def test_client_sets_api_key_header(self):
        self.assertEqual(self.client.session.headers["Api-Key"], "test-api-key")
        self.assertEqual(self.client.session.headers["Accept"], "application/json")

    @patch("app.yandex_market_client.requests.Session.request")
    def test_update_stocks_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"status":"OK"}'
        mock_response.json.return_value = {"status": "OK"}
        mock_request.return_value = mock_response

        skus_stocks = [{"sku": "SKU1", "warehouseId": 123, "items": [{"count": 10, "type": "FIT"}]}]
        result = self.client.update_stocks(skus_stocks)

        self.assertEqual(result, {"status": "OK"})
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "PUT")
        self.assertIn("/campaigns/test-campaign/offers/stocks", args[1])
        self.assertEqual(kwargs["json"], {"skus": skus_stocks})
        self.assertEqual(kwargs["timeout"], 30)

    @patch("app.yandex_market_client.requests.Session.request")
    def test_update_prices_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"status":"OK"}'
        mock_response.json.return_value = {"status": "OK"}
        mock_request.return_value = mock_response

        prices = [{"offerId": "SKU1", "price": {"value": 100.0, "currencyId": "RUR"}}]
        result = self.client.update_prices(prices)

        self.assertEqual(result, {"status": "OK"})
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertIn("/campaigns/test-campaign/offer-prices/updates", args[1])
        self.assertEqual(kwargs["json"], {"offers": prices})

    @patch("app.yandex_market_client.requests.Session.request")
    def test_update_prices_uses_business_endpoint_when_available(self, mock_request):
        client = YandexMarketClient(
            api_key="test-api-key",
            campaign_id="test-campaign",
            business_id="test-business",
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"status":"OK"}'
        mock_response.json.return_value = {"status": "OK"}
        mock_request.return_value = mock_response

        prices = [{"offerId": "SKU1", "price": {"value": 100.0, "currencyId": "RUR"}}]
        result = client.update_prices(prices)

        self.assertEqual(result, {"status": "OK"})
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertIn("/businesses/test-business/offer-prices/updates", args[1])
        self.assertEqual(kwargs["json"], {"offers": prices})

    @patch("app.yandex_market_client.requests.Session.request")
    def test_get_orders_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"orders":[]}'
        mock_response.json.return_value = {"orders": []}
        mock_request.return_value = mock_response

        result = self.client.get_orders(filters={"status": "CANCELLED"})

        self.assertEqual(result, {"orders": []})
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "GET")
        self.assertIn("/campaigns/test-campaign/orders", args[1])
        self.assertEqual(kwargs["params"], {"statuses": ["CANCELLED"]})

    @patch("app.yandex_market_client.requests.Session.request")
    def test_get_orders_uses_business_endpoint_when_available(self, mock_request):
        client = YandexMarketClient(
            api_key="test-api-key",
            campaign_id="test-campaign",
            business_id="test-business",
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"orders":[]}'
        mock_response.json.return_value = {"orders": []}
        mock_request.return_value = mock_response

        result = client.get_orders(filters={"status": "PROCESSING"})

        self.assertEqual(result, {"orders": []})
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertIn("/businesses/test-business/orders", args[1])
        self.assertEqual(kwargs["json"], {"statuses": ["PROCESSING"]})

    @patch("app.yandex_market_client.time.sleep", return_value=None)
    @patch("app.yandex_market_client.requests.Session.request")
    def test_retry_on_429(self, mock_request, mock_sleep):
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {"Retry-After": "1"}

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.content = b'{"status":"OK"}'
        mock_200.json.return_value = {"status": "OK"}

        mock_request.side_effect = [mock_429, mock_200]

        result = self.client.get_orders()

        self.assertEqual(result, {"status": "OK"})
        self.assertEqual(mock_request.call_count, 2)
        mock_sleep.assert_called_with(1)

    @patch("app.yandex_market_client.requests.Session.request")
    def test_http_error_includes_market_details(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 423
        mock_response.content = b'{"status":"ERROR"}'
        mock_response.json.return_value = {
            "status": "ERROR",
            "errors": [
                {"code": "UNAUTHORIZED", "message": "Credentials are not specified"},
            ],
        }
        mock_request.return_value = mock_response

        with self.assertRaises(HTTPError) as exc:
            self.client.update_prices([])

        self.assertIn("UNAUTHORIZED: Credentials are not specified", str(exc.exception))

    @patch("app.yandex_market_client.requests.Session.request")
    def test_get_token_info_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"permissions":["pricing"]}'
        mock_response.json.return_value = {"permissions": ["pricing"]}
        mock_request.return_value = mock_response

        result = self.client.get_token_info()

        self.assertEqual(result, {"permissions": ["pricing"]})
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertIn("/auth/token", args[1])

    @patch("app.yandex_market_client.requests.Session.request")
    def test_get_stocks_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"result":{"skus":[]}}'
        mock_response.json.return_value = {"result": {"skus": []}}
        mock_request.return_value = mock_response

        result = self.client.get_stocks(page_token="next-page", limit=50, stocks_warehouse_id=2058655)

        self.assertEqual(result, {"result": {"skus": []}})
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertIn("/campaigns/test-campaign/offers/stocks", args[1])
        self.assertEqual(kwargs["params"], {"limit": 50, "pageToken": "next-page"})
        self.assertEqual(kwargs["json"], {"archived": False, "stocksWarehouseId": 2058655})


if __name__ == "__main__":
    unittest.main()
