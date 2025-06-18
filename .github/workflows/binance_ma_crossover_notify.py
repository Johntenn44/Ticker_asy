import os
import ccxt
import pandas as pd
import requests
from datetime import datetime
import ta  # pip install ta

# --- CONFIGURATION ---

COINS = [
    "XRP/USDT", "XMR/USDT", "GMX/USDT", "LUNA/USDT", "TRX/USDT",
    "EIGEN/USDT", "APE/USDT", "WAVES/USDT", "PLUME/USDT", "SUSHI/USDT",
    "DOGE/USDT", "VIRTUAL/USDT", "CAKE/USDT", "GRASS/USDT", "AAVE/USDT",
    "SUI/USDT", "ARB/USDT", "XLM/USDT", "MNT/USDT", "LTC/USDT", "NEAR/USDT"
]

EXCHANGE_ID = 'kucoin'
INTERVAL = '12h'
LOOKBACK = 300  # enough for indicator warm-up + backtest period
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- INDICATOR CALCULATION ---

def add_indicators(df):
    df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['MA50'] = df['close'].rolling(window=50).mean()
    df['MA200'] = df['close'].rolling(window=200).mean()

    df['RSI5'] = ta.momentum.RSIIndicator(df['close'], window=5).rsi()
    df['RSI13'] = ta.momentum.RSIIndicator(df['close'], window=13).rsi()
    df['RSI21'] = ta.momentum.RSIIndicator(df['close'], window=21).rsi()

    # Williams %R returns negative values, invert sign for convenience
    df['WR8'] = -ta.momentum.WilliamsRIndicator(df['high'], df['low'], df['close'], lbp=8).williams_r()
    df['WR13'] = -ta.momentum.WilliamsRIndicator(df['high'], df['low'], df['close'], lbp=13).williams_r()
    df['WR50'] = -ta.momentum.WilliamsRIndicator(df['high'], df['low'], df['close'], lbp=50).williams_r()
    df['WR200'] = -ta.momentum.WilliamsRIndicator(df['high'], df['low'], df['close'], lbp=200).williams_r()

    return df

# --- TREND LOGIC WITH PRICE BETWEEN MA FILTER, NO KDJ ---

def analyze_trend(df):
    last = df.iloc[-1]
    price = last['close']
    ma50 = last['MA50']
    ema200 = last['EMA200']
    ma200 = last['MA200']

    low_ma = min(ma50, ema200, ma200)
    high_ma = max(ma50, ema200, ma200)

    # Filter: price must be between min and max of these MAs
    price_between_mas = low_ma <= price <= high_ma

    if not price_between_mas:
        # No trend signal if price outside MA range
        return {'uptrend': False, 'downtrend': False, 'trend_end': False, 'values': last.to_dict()}

    # Check trend conditions only if price is between MAs
    uptrend = (last['RSI5'] > last['RSI13'] > last['RSI21']) and \
              (last['WR8'] >= last['WR13'] >= last['WR50'] >= last['WR200'])

    downtrend = (last['RSI21'] > last['RSI13'] > last['RSI5']) and \
                (last['WR200'] >= last['WR50'] >= last['WR13'] >= last['WR8'])

    wr8, wr13, wr50, wr200 = last['WR8'], last['WR13'], last['WR50'], last['WR200']
    trend_end = ((wr50 <= wr8 <= wr200 or wr200 <= wr8 <= wr50) and
                 (wr50 <= wr13 <= wr200 or wr200 <= wr13 <= wr50))

    return {
        'uptrend': uptrend,
        'downtrend': downtrend,
        'trend_end': trend_end,
        'values': last[['close', 'RSI5', 'RSI13', 'RSI21',
                        'WR8', 'WR13', 'WR50', 'WR200', 'MA50', 'EMA200', 'MA200']].to_dict()
    }

# --- DATA FETCHING ---

def fetch_ohlcv_ccxt(symbol, timeframe, limit):
    exchange = getattr(ccxt, EXCHANGE_ID)()
    exchange.load_markets()
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df.astype(float)
    return df

# --- TELEGRAM NOTIFICATION ---

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not set, skipping message.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    resp = requests.post(url, data=payload)
    resp.raise_for_status()

# --- BACKTEST FUNCTION ---

def backtest_trend_signals(symbol, interval, days=14):
    candles_per_day = {
        '1m': 60*24,
        '5m': 12*24,
        '15m': 4*24,
        '30m': 2*24,
        '1h': 24,
        '2h': 12,
        '4h': 6,
        '6h': 4,
        '12h': 2,
        '1d': 1
    }
    limit = candles_per_day.get(interval, 2) * days + 250  # extra for warm-up

    df = fetch_ohlcv_ccxt(symbol, interval, limit)
    df = add_indicators(df)

    uptrend_count = 0
    downtrend_count = 0
    trend_end_count = 0

    start_idx = 250 if len(df) > 250 else 0

    for i in range(start_idx, len(df)):
        df_slice = df.iloc[:i+1]
        trend = analyze_trend(df_slice)
        if trend['uptrend']:
            uptrend_count += 1
        if trend['downtrend']:
            downtrend_count += 1
        if trend['trend_end']:
            trend_end_count += 1

    return {
        'symbol': symbol,
        'uptrend_signals': uptrend_count,
        'downtrend_signals': downtrend_count,
        'trend_end_signals': trend_end_count,
        'total_candles': len(df) - start_idx
    }

# --- MAIN ---

def main():
    results = []
    for symbol in COINS:
        try:
            res = backtest_trend_signals(symbol, INTERVAL, days=14)
            results.append(res)
            print(f"{symbol} - Uptrend: {res['uptrend_signals']}, Downtrend: {res['downtrend_signals']}, Trend End: {res['trend_end_signals']}")
        except Exception as e:
            print(f"Error backtesting {symbol}: {e}")

    summary = "\n".join(
        f"{r['symbol']}: Uptrend={r['uptrend_signals']}, Downtrend={r['downtrend_signals']}, Trend End={r['trend_end_signals']}"
        for r in results
    )
    send_telegram_message(f"<b>14-Day Backtest Summary ({INTERVAL})</b>\n{summary}")

if __name__ == "__main__":
    main()
