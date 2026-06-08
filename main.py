import os
import time
from datetime import datetime, timedelta
import pytz
import requests
import pandas as pd

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

SYMBOLS = ["SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL"]

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
last_alert = {}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})

def get_bars(symbol):
    end = datetime.now(pytz.UTC) - timedelta(minutes=16)
    start = end - timedelta(days=2)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        feed=DataFeed.IEX
    )

    bars = client.get_stock_bars(request).df

    if bars.empty:
        return None

    df = bars.reset_index()
    df = df[df["symbol"] == symbol].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp")
    df = df.resample("5min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna()

    return df

def add_indicators(df):
    df["ema9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()

    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap"] = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()
    df["avg_volume"] = df["volume"].rolling(20).mean()

    return df

def check_signal(symbol):
    df = get_bars(symbol)

    if df is None or len(df) < 30:
        print(f"Not enough data for {symbol}")
        return

    df = add_indicators(df)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    candle_id = f"{symbol}-{df.index[-1]}"

    if last_alert.get(symbol) == candle_id:
        return

    bullish_candle = last["close"] > last["open"]
    bearish_candle = last["close"] < last["open"]
    volume_ok = last["volume"] > last["avg_volume"]

    long_signal = (
        last["close"] > last["vwap"]
        and last["ema9"] > last["ema20"]
        and bullish_candle
        and last["close"] > last["ema9"]
        and volume_ok
    )

    short_signal = (
        last["close"] < last["vwap"]
        and last["ema9"] < last["ema20"]
        and bearish_candle
        and last["close"] < last["ema9"]
        and volume_ok
    )

    entry = round(float(last["close"]), 2)

    if long_signal:
        stop = round(float(last["low"]), 2)
        risk = entry - stop
        target = round(entry + (risk * 2), 2)

        message = (
            f"🟢 LONG ALERT: {symbol}\n"
            f"Entry: ${entry}\n"
            f"Stop Loss: ${stop}\n"
            f"Target: ${target}\n"
            f"Risk/Reward: 1:2\n"
            f"Timeframe: 5-minute\n"
            f"Strategy: VWAP + EMA 9/20 + Volume"
        )

        send_telegram(message)
        last_alert[symbol] = candle_id
        print(message)

    elif short_signal:
        stop = round(float(last["high"]), 2)
        risk = stop - entry
        target = round(entry - (risk * 2), 2)

        message = (
            f"🔴 SHORT ALERT: {symbol}\n"
            f"Entry: ${entry}\n"
            f"Stop Loss: ${stop}\n"
            f"Target: ${target}\n"
            f"Risk/Reward: 1:2\n"
            f"Timeframe: 5-minute\n"
            f"Strategy: VWAP + EMA 9/20 + Volume"
        )

        send_telegram(message)
        last_alert[symbol] = candle_id
        print(message)

def main():
    send_telegram("✅ Alpaca Telegram Alert Bot is running. Alerts only. No trades will be placed.")

    while True:
        print("Checking signals...")
        for symbol in SYMBOLS:
            try:
                check_signal(symbol)
            except Exception as e:
                print(f"Error checking {symbol}: {e}")

        time.sleep(300)

if __name__ == "__main__":
    main()
