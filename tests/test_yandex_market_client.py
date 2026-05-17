import unittest
from unittest.mock import MagicMock, patch
from app.yandex_market_client import YandexMarketClient

class TestYandexMarketClient(unittest.TestCase):
    def setUp(self):
        self.client = YandexMarketClient(token="test-token", campaign_id="test-campaign")

    @patch("app.yandex_market_client.requests.Session.request")
    def test_update_stocks_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "OK"}
        mock_request.return_value = mock_response

        skus_stocks = [{"sku": "SKU1", "warehouseId": 123, "items": [{"count": 10, "type": "FIT"}]}]
        result = self.client.update_stocks(skus_stocks)

        self.assertEqual(result, {"status": "OK"})
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "PUT")
        self.assertIn("/campaigns/test-campaign/offers/stocks.json", args[1])
        self.assertEqual(kwargs["json"], {"skus": skus_stocks})

    @patch("app.yandex_market_client.requests.Session.request")
    def test_update_prices_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "OK"}
        mock_request.return_value = mock_response

        prices = [{"offerId": "SKU1", "price": {"value": 100.0, "currencyId": "RUR"}}]
        result = self.client.update_prices(prices)

        self.assertEqual(result, {"status": "OK"})
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(kwargs["json"], {"offers": prices})

    @patch("app.yandex_market_client.requests.Session.request")
    def test_get_orders_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"orders": []}
        mock_request.return_value = mock_response

        result = self.client.get_orders(filters={"status": "CANCELLED"})

        self.assertEqual(result, {"orders": []})
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(kwargs["json"], {"status": "CANCELLED"})

    @patch("app.yandex_market_client.time.sleep", return_value=None)
    @patch("app.yandex_market_client.requests.Session.request")
    def test_retry_on_429(self, mock_request, mock_sleep):
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {"Retry-After": "1"}

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"status": "OK"}

        mock_request.side_effect = [mock_429, mock_200]

        result = self.client.get_orders()

        self.assertEqual(result, {"status": "OK"})
        self.assertEqual(mock_request.call_count, 2)
        mock_sleep.assert_called_with(1)

if __name__ == "__main__":
    unittest.main()
