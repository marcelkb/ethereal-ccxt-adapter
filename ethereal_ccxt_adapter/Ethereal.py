import asyncio
import math
import random
import time
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from uuid import UUID

import ccxt
from ccxt import (
    AuthenticationError,
    InvalidOrder,
    OrderNotFound, NotSupported,
)
from ccxt.base.types import (
    Market,
    Ticker,
    Trade,
    Order,
    Position,
    Balances,
    FundingRate, Int, Str,
)

from ethereal import AsyncRESTClient
from ethereal.models.mainnet.rest import SubaccountDto, SubaccountBalanceDto
from ethereal.models.rest import MarketPriceDto, MarketLiquidityDto

from ethereal_ccxt_adapter.const import EOrderSide, EOrderStatus


# ---------------------------------------------------------
# Async helper
# ---------------------------------------------------------
def run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        try:
            import nest_asyncio
            nest_asyncio.apply()
        except Exception:
            pass
    return loop.run_until_complete(coro)


# =========================================================
# ETHEREAL CCXT WRAPPER
# =========================================================
class Ethereal(ccxt.Exchange):
    id = "ethereal"
    name = "Ethereal"
    rateLimit = 1000
    base_url = "https://api.ethereal.trade"

    def __init__(self, config: Dict[str, Any] = {}):
        super().__init__(config)

        self.id = "ethereal"
        self.name = "Ethereal"

        self.walletAddress = self.safe_string(config, 'wallet_address', self.walletAddress)
        self.privateKey = self.safe_string(config, 'private_key', self.privateKey)
        self.l1WalletAddress = self.safe_string(config, 'l1_wallet_address')

        self.client: AsyncRESTClient = run(AsyncRESTClient.create({
            "base_url": "https://api.ethereal.trade",
            "chain_config": {
                "rpc_url": "https://rpc.ethereal.trade",
                "private_key": self.privateKey,
            }
        }))

        self.has.update({
            "spot": False,
            "margin": False,
            "swap": True,
            "future": False,
            "option": False,

            "fetchMarkets": True,
            "fetchTicker": True,
            "fetchTickers": True,
            "fetchOrderBook": True,
            "fetchOHLCV": False,

            "fetchBalance": True,
            "fetchTrades": True,
            "fetchMyTrades": True,

            "createOrder": True,
            "cancelOrder": True,
            "cancelAllOrders": True,
            "fetchOrder": True,
            "fetchOrders": True,
            "fetchOpenOrders": False,
            "fetchClosedOrders": True,

            "fetchPositions": True,
            "fetchPosition": True,

            "fetchFundingRate": True,
            "fetchFundingRates": True,
        })

        self.urls.update({
            "api": {
                "public": self.base_url,
                "private": self.base_url,
            },
            "www": "https://ethereal.trade",
            "doc": "https://meridianxyz.github.io/ethereal-py-sdk/",
        })

        self.options = self.deep_extend({
            "defaultType": "swap",
        }, self.options)

        self.fees.update({
            'swap': {
                'taker': self.parse_number('0.0003'),
                'maker': self.parse_number('0.0003'),
            },
            'spot': {
                'taker': self.parse_number('0.0003'),
                'maker': self.parse_number('0.0003'),
            },
        })

        self.name = "Ethereal"
        self.rateLimit = 1000

        account: SubaccountDto = self.main_account()
        self.main_account_id = account.id
        self.main_account_name = account.name

    # -----------------------------------------------------
    # Helpers
    # -----------------------------------------------------
    def ccxt_symbol(self, base, quote):
        return f"{base}/{quote}:{quote}"

    def market_id(self, symbol):
        return self.markets[symbol]["id"]

    def market_symbol(self, id):
        for market in self.markets.values():
            if str(market["id"]) == str(id):
                return market["symbol"]

    def _decimal_places(self, x):
        return int(-math.log10(float(x)))

    # -----------------------------------------------------
    # MARKETS
    # -----------------------------------------------------
    def fetch_markets(self, params={}) -> List[Market]:
        products = run(self.client.list_products())
        markets = []

        for p in products:
            symbol = self.ccxt_symbol(p.base_token_name, p.quote_token_name)

            markets.append({
                "id": p.id,
                "symbol": symbol,
                "base": p.base_token_name,
                "quote": p.quote_token_name,
                "settle": p.quote_token_name,

                "type": "swap",
                "spot": False,
                "swap": True,
                "contract": True,
                "linear": True,
                "inverse": False,
                "contractSize": 1,

                "precision": {
                    "price": self._decimal_places(p.min_price),
                    "amount": self._decimal_places(p.lot_size),
                },
                "limits": {
                    "amount": {
                        "min": p.min_quantity,
                        "max": p.max_quantity,
                    },
                },
                "info": p.model_dump(),
            })

        return markets

    # -----------------------------------------------------
    # TICKERS
    # -----------------------------------------------------
    def fetch_ticker(self, symbol: str, params={}) -> Ticker:
        self.load_markets()
        market = self.markets[symbol]

        id = market["id"]
        # liquidity:MarketLiquidityDto = run(self.client.get_market_liquidity(product_id=id))
        price: MarketPriceDto = run(self.client.list_market_prices(product_ids=[id]))[0]

        ts = self.milliseconds()
        return {
            'symbol': symbol,
            'timestamp': ts,
            'datetime': self.iso8601(ts),
            'high': 0,
            'low': 0,
            'bid': float(price.best_bid_price),
            'bidVolume': None,
            'ask': float(price.best_ask_price),
            'askVolume': None,
            'last': float(price.oracle_price),
            'average': None,
            'baseVolume': 0,
            'quoteVolume': 0,
            'price24hAgo': price.price24h_ago,
            'info': price.model_dump(),
        }

    def fetch_tickers(self, symbols=None, params={}):
        self.load_markets()
        return {s: self.fetch_ticker(s) for s in (symbols or self.markets)}

    def fetch_accounts(self, params={}):
        return run(self.client.list_subaccounts(sender=self.l1WalletAddress))

    # -----------------------------------------------------
    # TRADES
    # -----------------------------------------------------
    def fetch_trades(self, symbol: str, since=None, limit=100, params={}) -> List[Trade]:
        self.load_markets()
        if symbol is not None:
            market = self.markets[symbol]
            trades = run(
                self.client.list_fills(subaccount_id=self.main_account_id, product_ids=[market["id"]], limit=limit))
        else:
            trades = run(self.client.list_fills(subaccount_id=self.main_account_id, limit=limit))

        out = []

        for t in trades:
            out.append({
                "id": t.id,
                "timestamp": t.created_at,
                "datetime": self.iso8601(int(t.created_at)),
                "symbol": symbol,
                "side": str(t.side).lower(),
                "price": t.price,
                "amount": t.filled,
                "cost": float(t.price) * float(t.filled),
                "fee": t.fee_usd,
                "info": t.model_dump(),
            })
        return out

    def fetch_my_trades(self, symbol=None, since=None, limit=100, params={}):
        return self.fetch_trades(symbol, since, limit, params)

    def main_account(self) -> SubaccountDto:
        sub_accounts = run(self.client.list_subaccounts(sender=self.l1WalletAddress))
        return sub_accounts[0]

    # -----------------------------------------------------
    # BALANCE
    # -----------------------------------------------------
    def fetch_balance(self, params={}) -> Balances:
        balances: List[SubaccountBalanceDto] = run(
            self.client.get_subaccount_balances(subaccount_id=self.main_account_id))
        result = {
            "info": [b.model_dump() for b in balances]
        }
        for balance in balances:
            result[balance.token_name] = {
                "free": float(balance.available),
                "used": float(balance.total_used),
                "total": float(balance.amount),
            }

        return self.safe_balance(result)

    # -----------------------------------------------------
    # POSITIONS
    # -----------------------------------------------------
    def fetch_positions(self, symbols=None, params={}) -> List[Position]:
        positions = run(self.client.list_positions(subaccount_id=self.main_account_id, open=True))
        parsed = []

        for p in positions:
            symbol = self.market_symbol(p.product_id)
            price = self.fetch_ticker(symbol)

            side = "long" if float(p.size) > 0 else "short"
            notional = p.total_increase_notional

            parsed.append({
                "info": self.extend(p.model_dump(),
                                    {"unrealisedPnl": 0, "curRealisedPnl": p.realized_pnl, "size": p.size, "positionValue":notional}),
                "symbol": symbol,
                "side": side,
                "contracts": float(p.size),
                "entryPrice": 0,
                "markPrice": price,
                "notional": notional,
                "leverage": self.fetch_leverage(symbol),
                "unrealisedPnl": 0,
                "marginMode": "cross",
                "liquidationPrice": 0,
                "pnl": p.realized_pnl,
            })

        if symbols:
            parsed = [p for p in parsed if p["symbol"] in symbols]

        return parsed

    def fetch_position(self, symbol: str, params={}) -> Optional[Position]:
        positions = self.fetch_positions()
        for p in positions:
            if p["symbol"] == symbol:
                return p
        return None

    from datetime import datetime, timedelta

    def _calculate_since(
            self,
            timeframe: str,
            limit: int,
            end_timestamp: int,
    ) -> int:

        timeframe_deltas = {
            "1m": timedelta(minutes=1),
            "3m": timedelta(minutes=3),
            "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "2h": timedelta(hours=2),
            "4h": timedelta(hours=4),
            "6h": timedelta(hours=6),
            "12h": timedelta(hours=12),
            "1d": timedelta(days=1),
            "1w": timedelta(weeks=1),
            "1M": timedelta(weeks=4),
        }

        delta = timeframe_deltas[timeframe]
        end = datetime.fromtimestamp(end_timestamp)
        start = end - delta * limit

        return int(start.timestamp())

    def fetch_ohlcv(
            self,
            symbol: str,
            timeframe: str = "1m",
            since: Optional[int] = None,
            limit: Optional[int] = None,
            params: Dict = {},
    ) -> List[List[float]]:

        raise NotSupported(self.id + ' fetch_ohlcv() is not supported yet')

    # -----------------------------------------------------
    # FUNDING
    # -----------------------------------------------------
    def fetch_funding_rate(self, symbol: str, params={}) -> Optional[FundingRate]:
        self.load_markets()
        market = self.markets[symbol]

        rate = run(self.client.get_projected_funding(product_id=market["id"]))
        if not rate:
            return None

        funding = rate.funding_rate1h
        funding1Y = round(float(funding) * 24 * 365, 4)

        return {
            "info": self.extend(
                {"symbol": symbol, "fundingRate": funding, "interval": "1h", "fundingRateAnnualized": funding1Y},
                rate.model_dump()),
            "symbol": symbol,
            "fundingRate": funding,
            "fundingTimestamp": None,
            "fundingDatetime": None,
            "interval": "1h",
        }

    def fetch_funding_rates(self, symbols=None, params={}) -> Dict[str, FundingRate]:
        self.load_markets()
        out = {}

        for s in (symbols or self.markets):
            fr = self.fetch_funding_rate(s)
            if fr:
                out[s] = fr

        return out

    def round_to_step(self, value, step, rounding):
        return (value / step).to_integral_value(rounding=rounding) * step

    def normalize_order(self, market, price, amount, side):
        price = Decimal(str(price))
        amount = Decimal(str(amount))

        # PRICE
        price_precision = market["precision"]["price"]
        price_tick = Decimal("10") ** -price_precision
        price_rounding = ROUND_CEILING if side == "sell" else ROUND_FLOOR
        price = self.round_to_step(price, price_tick, price_rounding)

        # AMOUNT
        amount_precision = market["precision"]["amount"]
        lot_size = Decimal("10") ** -amount_precision
        amount = self.round_to_step(amount, lot_size, ROUND_FLOOR)

        return price, amount


    # -----------------------------------------------------
    # ORDERS
    # -----------------------------------------------------
    def create_order(
            self,
            symbol: str,
            type: str,
            side: str,
            amount: float,
            price: Optional[float] = None,
            params: Optional[Dict] = None,
    ) -> Order:

        if not self.privateKey:
            raise AuthenticationError("Private key required")

        params = params or {}
        self.load_markets()
        market = self.markets[symbol]

        # ----------------------------
        # Parse TP / SL (CCXT style)
        # ----------------------------
        tp_price = params.get("takeProfitPrice")
        sl_price = params.get("stopLossPrice")

        # alternative style
        if "tp" in params:
            tp_price = params["tp"].get("price")

        if "sl" in params:
            sl_price = params["sl"].get("price")

        reduce_only = params.get("reduceOnly", False)

        if side.upper() == EOrderSide.BUY.name:
            mapped_side = 0
        else:
            mapped_side = 1

        # TP / SL side must CLOSE position
        close_side = 0 if side.lower() == "buy" else 1

        # assert price is a multiple of tick size, exchange condition
        price = Decimal(str(price))
        amount = Decimal(str(amount))


        try:
            # ----------------------------
            # TAKE PROFIT
            # ----------------------------
            if tp_price is not None:
                tp_price, amount = self.normalize_order(market, tp_price, amount, close_side)
                order = run(self.client.create_order(
                    subaccount=self.main_account_name,
                    sender=self.walletAddress,
                    product_id=market["id"],
                    side=close_side,
                    order_type="MARKET",
                    quantity=amount,
                    stop_price=tp_price,
                    stop_type=0,
                    reduce_only=True,
                ))

            # ----------------------------
            # STOP LOSS
            # ----------------------------
            elif sl_price is not None:
                sl_price, amount = self.normalize_order(market, sl_price, amount, close_side)
                order = run(self.client.create_order(
                    subaccount=self.main_account_name,
                    sender=self.walletAddress,
                    product_id=market["id"],
                    side=close_side,
                    order_type="MARKET",
                    quantity=amount,
                    stop_price= sl_price,
                    stop_type=1,
                    reduce_only=True,
                ))
            else:
                # ----------------------------
                # Create MAIN order
                # ----------------------------
                price, amount = self.normalize_order(market, price, amount, side)
                order = run(self.client.create_order(
                    subaccount=self.main_account_name,
                    sender=self.walletAddress,
                    product_id=market["id"],
                    side=mapped_side,
                    order_type=type.upper(),
                    quantity=amount,
                    price= price,
                    reduce_only=reduce_only,
                ))
        except Exception as e:
            print(f"error occured: {e}")
            raise InvalidOrder(self.id + ' ' + str(e))
            return None

        if order.filled == amount:
            status = EOrderStatus.FILLED
        else:
            status = EOrderStatus.OPEN

        fee = float(self.fees["swap"]["taker"]) * float(amount) * float(price)

        return {
            "info": order,
            "id": order.id,
            'order': id,
            'clientOrderId': id,
            'timestamp': self.iso8601(int(time.time() * 1000)),
            'datetime': self.iso8601(int(time.time() * 1000)),
            "symbol": symbol,
            "type": type,
            "side": side,
            "price": float(price),
            "amount": float(amount),
            'cost': 0,
            'fees':
            {
                'cost': fee,
                'currency': 'USDC',
                'rate': 0.004
            },
            'fee':
                {
                    'cost': fee,
                    'currency': 'USDC',
                    'rate': 0.004
                },
            'average': None,
            'filled': None,
            'remaining': None,
            "status": status,
            'reduceOnly': params.get('reduceOnly', False) if params is not None else True,
        }

    def cancel_order(self, id: str, symbol=None, params={}) -> Order:
        try:
            run(self.client.cancel_orders(subaccount=self.main_account_name, sender=self.walletAddress, order_ids=[id]))
        except Exception:
            raise OrderNotFound(id)

        return {"id": id, "status": "canceled"}

    def cancel_all_orders(self, symbol=None, params={}):
        orders = self.fetch_orders(symbol)
        for o in orders:
            self.cancel_order(o["id"], o["symbol"])

    def fetch_orders(self, symbol: str = None, since: Int = None, limit: Int = None, params={}) -> List[Order]:
        orders = run(self.client.list_orders(subaccount_id=self.main_account_id))
        parsed = []

        for o in orders:
            sym = self.market_symbol(o.product_id)

            parsed.append({
                "id": str(o.id),
                "symbol": sym,
                "side": EOrderSide.BUY if o.side == 0 else EOrderSide.SELL,
                "type": str(o.type).lower(),
                "price": float(o.price),
                "amount": float(o.quantity),
                "filled": float(o.filled),
                "status": EOrderStatus.valueOf(str(o.status.value).lower()),
                "info": o.model_dump(),
            })

        if symbol:
            parsed = [o for o in parsed if o["symbol"] == symbol]

        return parsed

    def fetch_order(self, order_id, symbol=None, params=None):
        if order_id is not None:
            try:
                return self._parse_order(run(self.client.get_order(id=UUID(str(order_id)))))
            except Exception as e:
                if "Order not found" in str(e):
                    raise OrderNotFound(order_id)
                raise OrderNotFound(str(e))
        orders = self.fetch_orders(symbol)
        for o in orders:
            if o["id"] == order_id:
                return self._parse_order(o)
        raise OrderNotFound(order_id)

    def _parse_order(self, order):
        return {
            "id": order.id,
            "symbol": order.symbol,
            "status": order.status,
            "type": order.type,
            "side": order.side,
            "price": float(order.price or 0),
            "amount": float(order.quantity or 0),
            "filled": float(order.filled or 0),
            "remaining": float(order.remaining or 0),
            "info": order.to_dict(),
        }

    def fetch_leverage(self, symbol: str, params={}):
        return 10

    def fetch_margin_mode(self, symbol: str, params={}):
        return "cross"

    def close(self):
        return run(self.client.close())
