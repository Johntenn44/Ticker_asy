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
    results['values'] = {
        'close': cp,
        'MA50': ma50,
        'EMA200': ema200,
        'MA200': ma200
    }
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
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
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
    coins_between_mas = []
    coins_unequal_rsi = []
    coins_unequal_kdj = []

    for symbol in COINS:
        try:
            df = fetch_ohlcv_ccxt(symbol, INTERVAL, LOOKBACK)
            if len(df) < 200:
                print(f"Not enough data for {symbol}")
                continue

            df = add_indicators(df)
            trend = analyze_trend(df)

            # Check price between MAs
            if trend.get('price_between_mas'):
                coins_between_mas.append(symbol)

            # Calculate RSI for 8, 13, 21 periods
            rsi8 = calculate_rsi(df['close'], 8).iloc[-1]
            rsi13 = calculate_rsi(df['close'], 13).iloc[-1]
            rsi21 = calculate_rsi(df['close'], 21).iloc[-1]

            if not (np.isclose(rsi8, rsi13) and np.isclose(rsi13, rsi21)):
                coins_unequal_rsi.append(symbol)

            # Calculate KDJ with length=5, ma1=8, ma2=8
            k, d, j = calculate_kdj(df, length=5, ma1=8, ma2=8)
            k_last = k.iloc[-1]
            d_last = d.iloc[-1]
            j_last = j.iloc[-1]

            # Check if K, D, J are not all equal (allow small float tolerance)
            if not (np.isclose(k_last, d_last) and np.isclose(d_last, j_last)):
                coins_unequal_kdj.append(symbol)

        except Exception as e:
            print(f"Error processing {symbol}: {e}")

    # Send price-between-MAs alert
    if coins_between_mas:
        coins_list = "\n".join(coins_between_mas)
        msg = (
            f"<b>Kucoin {INTERVAL.upper()} Price Between MAs Alert ({dt})</b>\n"
            f"Coins with price between MA50, EMA200, and MA200:\n\n"
            f"{coins_list}"
        )
        send_telegram_message(msg)
    else:
        send_telegram_message("No coins have current price between MA50, EMA200, and MA200.")

    # Send RSI inequality alert
    if coins_unequal_rsi:
        coins_list = "\n".join(coins_unequal_rsi)
        msg = (
            f"<b>Kucoin {INTERVAL.upper()} RSI Alert ({dt})</b>\n"
            f"Coins where RSI(8), RSI(13), and RSI(21) are not equal:\n\n"
            f"{coins_list}"
        )
        send_telegram_message(msg)
    else:
        send_telegram_message("All coins have equal RSI values for periods 8, 13, and 21.")

    # Send KDJ inequality alert
    if coins_unequal_kdj:
        coins_list = "\n".join(coins_unequal_kdj)
        msg = (
            f"<b>Kucoin {INTERVAL.upper()} KDJ Alert ({dt})</b>\n"
            f"Coins where KDJ (K, D, J) values are not equal:\n\n"
            f"{coins_list}"
        )
        send_telegram_message(msg)
    else:
        send_telegram_message("All coins have equal KDJ values for parameters length=5, ma1=8, ma2=8.")

if __name__ == "__main__":
    main()
