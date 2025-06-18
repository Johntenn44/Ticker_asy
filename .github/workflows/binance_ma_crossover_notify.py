import os
import ccxt
import pandas as pd
import numpy as np
import requests
from datetime import datetime

# --- CONFIGURATION ---

COINS = [
    "XRP/USDT",
    "XMR/USDT",
    "GMX/USDT",
    "LUNA/USDT",
    "TRX/USDT",
    "EIGEN/USDT",
    "APE/USDT",
    "WAVES/USDT",
    "PLUME/USDT",
    "SUSHI/USDT",
    "DOGE/USDT",
    "VIRTUAL/USDT",
    "CAKE/USDT",
    "GRASS/USDT",
    "AAVE/USDT",
    "SUI/USDT",
    "ARB/USDT",
    "XLM/USDT",
    "MNT/USDT",
    "LTC/USDT",
    "NEAR/USDT",
]

EXCHANGE_ID = 'kucoin'
INTERVAL = '12h'      # 12-hour candles
LOOKBACK = 210       # Number of candles to fetch (>= 200)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- INDICATOR CALCULATION ---

def add_indicators(df):
    df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['MA50'] = df['close'].rolling(window=50).mean()
    df['MA200'] = df['close'].rolling(window=200).mean()
    return df

def calculate_rsi(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_kdj(df, length=5, ma1=8, ma2=8):
    low_min = df['low'].rolling(window=length, min_periods=1).min()
    high_max = df['high'].rolling(window=length, min_periods=1).max()
    rsv = (df['close'] - low_min) / (high_max - low_min) * 100
    k = rsv.ewm(span=ma1, adjust=False).mean()
    d = k.ewm(span=ma2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j

# --- TREND LOGIC ---

def analyze_trend(df):
    cp = df['close'].iloc[-1]
    ma50 = df['MA50'].iloc[-1]
    ema200 = df['EMA200'].iloc[-1]
    ma200 = df['MA200'].iloc[-1]

    low = min(ma50, ema200, ma200)
    high = max(ma50, ema200, ma200)

    results = {}
    results['price_between_mas'] = low <= cp <= high
    return results

# --- DATA FETCHING ---

def fetch_ohlcv_ccxt(symbol, timeframe, limit):
    exchange = getattr(ccxt, EXCHANGE_ID)()
    exchange.load_markets()
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(
        ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
    )
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)
    return df

# --- TELEGRAM NOTIFICATION ---

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    resp = requests.post(url, data=payload)
    resp.raise_for_status()

# --- MAIN LOGIC ---

def main():
    dt = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    coins_meeting_all = []
    trend_indications = {}

    for symbol in COINS:
        try:
            df = fetch_ohlcv_ccxt(symbol, INTERVAL, LOOKBACK)
            if len(df) < 200:
                print(f"Not enough data for {symbol}")
                continue

            df = add_indicators(df)
            trend = analyze_trend(df)
            if not trend.get('price_between_mas'):
                continue  # skip if price not between MAs

            # Calculate RSI values
            rsi8 = calculate_rsi(df['close'], 8).iloc[-1]
            rsi13 = calculate_rsi(df['close'], 13).iloc[-1]
            rsi21 = calculate_rsi(df['close'], 21).iloc[-1]

            # RSI equality check
            if np.isclose(rsi8, rsi13) and np.isclose(rsi13, rsi21):
                continue  # skip if RSI values equal

            # Determine RSI trend
            if rsi8 > rsi13 > rsi21:
                rsi_trend = "Uptrend"
            elif rsi8 < rsi13 < rsi21:
                rsi_trend = "Downtrend"
            else:
                rsi_trend = "No clear RSI trend"

            # KDJ check
            k, d, j = calculate_kdj(df, length=5, ma1=8, ma2=8)
            k_last, d_last, j_last = k.iloc[-1], d.iloc[-1], j.iloc[-1]
            if np.isclose(k_last, d_last) and np.isclose(d_last, j_last):
                continue  # skip if KDJ values equal

            coins_meeting_all.append(symbol)
            trend_indications[symbol] = rsi_trend

        except Exception as e:
            print(f"Error processing {symbol}: {e}")

    if coins_meeting_all:
        msg_lines = [f"<b>Kucoin {INTERVAL.upper()} Combined Alert ({dt})</b>",
                     "Coins satisfying all conditions (Price between MAs, RSI unequal, KDJ unequal):\n"]
        for coin in coins_meeting_all:
            msg_lines.append(f"{coin} - RSI Trend: {trend_indications.get(coin, 'N/A')}")
        msg = "\n".join(msg_lines)
        send_telegram_message(msg)
    else:
        send_telegram_message("No coins satisfy all conditions at this time.")

if __name__ == "__main__":
    main()
