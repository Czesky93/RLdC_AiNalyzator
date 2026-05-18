from __future__ import annotations

from unittest.mock import patch

from backend.binance_client import BinanceClient


class _FakeBinanceApiClient:
    def __init__(self, *args, **kwargs):
        self.timestamp_offset = 0
        self.created_orders = []

    def get_server_time(self):
        return {"serverTime": 1_000_000}

    def get_exchange_info(self):
        return {
            "symbols": [
                {
                    "symbol": "AAVEUSDC",
                    "baseAsset": "AAVE",
                    "quoteAsset": "USDC",
                    "status": "TRADING",
                    "permissions": ["SPOT"],
                    "filters": [
                        {
                            "filterType": "LOT_SIZE",
                            "minQty": "0.001",
                            "maxQty": "900000.000",
                            "stepSize": "0.001",
                        },
                        {
                            "filterType": "NOTIONAL",
                            "minNotional": "5.0",
                            "maxNotional": "0.0",
                            "applyMinToMarket": True,
                        },
                    ],
                }
            ]
        }

    def get_account(self, recvWindow=5000):
        return {
            "balances": [
                {"asset": "AAVE", "free": "0.5474794", "locked": "0"},
                {"asset": "USDC", "free": "120.0", "locked": "0"},
            ]
        }

    def create_order(self, **kwargs):
        self.created_orders.append(kwargs)
        return {
            "symbol": kwargs["symbol"],
            "orderId": 12345,
            "status": "NEW",
            "executedQty": str(kwargs.get("quantity", "0")),
            "fills": [],
        }


@patch("backend.binance_client.Client", _FakeBinanceApiClient)
def test_sell_quantity_is_capped_to_free_balance_and_step_size():
    client = BinanceClient(api_key="x", api_secret="y")

    prepared = client.prepare_sell_quantity("AAVEUSDC", 0.548)
    assert prepared["ok"] is True
    assert prepared["base_asset"] == "AAVE"
    assert prepared["free_qty"] == 0.5474794
    assert prepared["prepared_qty"] == 0.547

    result = client.place_order("AAVEUSDC", "SELL", quantity=0.548)
    assert result is not None
    assert result.get("_error") is not True
    assert client.client.created_orders, "create_order should be called"

    order_kwargs = client.client.created_orders[-1]
    assert order_kwargs["symbol"] == "AAVEUSDC"
    assert order_kwargs["side"] == "SELL"
    assert float(order_kwargs["quantity"]) == 0.547
