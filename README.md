![Python Version](https://img.shields.io/badge/python-3.13+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

# Ethereal CCXT Adapter

A CCXT-compatible adapter/wrapper for the Ethereal Python SDK. It maps Ethereal SDK methods onto familiar CCXT interfaces.

- CCXT: https://github.com/ccxt/ccxt
- Ethereal SDK (Python): https://pypi.org/project/ethereal-sdk/

# Features

- CCXT-style API backed by the Ethereal SDK
- Simple environment-based configuration
- Python 3.13+ support

## Installation

For installation and inclusion in another projects use

```
pip install {localpath}\ethereal_ccxt_adapter      
or
pip install git+https://github.com/marcelkb/ethereal-ccxt-adapter.git  
```

```
pip install ethereal-sdk
git clone git@github.com:meridianxyz/ethereal-py-sdk.git
```

## Environment Setup

Create a `.env` file in the project root with the following variables:

```
PRIVATE_KEY= Your Api private key
WALLET_ADDRESS= Your Api puplic wallet address
L1_WALLET_ADDRESS= Your Ethereal main wallet Adddress
```

## Usage

```
from ethereal_ccxt_adapter import Ethereal
from ethereal_ccxt_adapter.const import EOrderSide, EOrderType

    load_dotenv(env.ethereal)
    PRIVATE_KEY = os.environ.get("PRIVATE_KEY")
    WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS")
    L1_WALLET_ADDRESS = os.environ.get("L1_WALLET_ADDRESS")

    exchange = Ethereal({
        'l1_wallet_address': L1_WALLET_ADDRESS,
        "private_key": PRIVATE_KEY,
        "wallet_address": WALLET_ADDRESS,
    })
    
    symbol = 'SOL/USD:USD'  # market symbol
    AMOUNT = 0.1

    ticker = exchange.fetch_ticker(symbol)
    print(f"{symbol} price: {ticker['last']}")
    
    position = exchange.fetch_position(symbol)
    print(f"{position['info']['unrealisedPnl']} {position['info']['curRealisedPnl']} {position['info']['size']}")
    
    print(f"Creating LIMIT BUY order for {symbol}")
    print(exchange.create_order(symbol, EOrderType.LIMIT.value, EOrderSide.BUY.value, AMOUNT, ticker['last'] * 0.5))
  
    print(f"Creating TAKE PROFIT MARKET SELL order for {symbol}")
    print(exchange.create_order(
        symbol,
        EOrderType.MARKET.value,
        EOrderSide.SELL.value,
        AMOUNT,
        ticker['last'] * 1.01,
        params={'takeProfitPrice': '250', 'reduceOnly': True}
    ))
    
    print(f"Creating STOP LOSS MARKET SELL order for {symbol}")
    print(exchange.create_order(
        symbol,
        EOrderType.MARKET.value,
        EOrderSide.SELL.value,
        AMOUNT,
        ticker['last'] * 1.01,
        params={'stopLossPrice': '100', 'reduceOnly': True}
    ))

```
