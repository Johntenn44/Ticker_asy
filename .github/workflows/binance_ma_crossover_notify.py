import os
import ccxt
import pandas as pd
import pandas_ta as ta
import requests
from datetime import datetime
import numpy as np

# --- CONFIGURATION ---

COINS = [
    "XRP/USDT", "XMR/USDT", "GMX/USDT", "LUNA/USDT", "TRX/USDT",
    "EIGEN/USDT", "APE/USDT", "WAVES/USDT", "PLUME/USDT", "SUSHI/USDT",
    "DOGE/USDT", "VIRTUAL/USDT", "CAKE/USDT", "GRASS/USDT", "AAVE/USDT",
    "SUI/USDT", "ARB/USDT", "XLM/USDT", "MNT/USDT", "LTC/USDT", "NEAR/USDT"
]

EXCHANGE_ID = 'kucoin'
INTERVAL = '12h'
LOOKBACK = 210

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- DATA FETCHING ---

def fetch_ohlcv_ccxt(symbol, timeframe, limit):
    exchange = getattr(ccxt, EXCHANGE_ID)()
    exchange.load_markets()
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df['close'] = df['close'].astype(float)
    return df

# --- INDICATOR CALCULATION ---

def add_indicators(df):
    # KDJ (using pandas_ta's stochrsi as proxy for KDJ)
    # pandas_ta has a built-in kdj indicator:
    kdj = ta.kdj(df['high'], df['low'], df['close'])
    df = pd.concat([df, kdj], axis=1)

    # RSI
    df['RSI5'] = ta.rsi(df['close'], length=5)
    df['RSI13'] = ta.rsi(df['close'], length=13)
    df['RSI21'] = ta.rsi(df['close'], length=21)

    # Williams %R
    df['WR8'] = ta.willr(df['high'], df['low'], df['close'], length=8)
    df['WR13'] = ta.willr(df['high'], df['low'], df['close'], length=13)
    df['WR50'] = ta.willr(df['high'], df['low'], df['close'], length=50)
    df['WR200'] = ta.willr(df['high'], df['low'], df['close'], length=200)

    # EMA and MA for prerequisite
    df['EMA8'] = ta.ema(df['close'], length=8)
    df['EMA13'] = ta.ema(df['close'], length=13)
    df['EMA21'] = ta.ema(df['close'], length=21)
    df['EMA50'] = ta.ema(df['close'], length=50)
    df['EMA200'] = ta.ema(df['close'], length=200)
    df['MA50'] = ta.sma(df['close'], length=50)
    df['MA200'] = ta.sma(df['close'], length=200)

    return df

# --- HELPER FUNCTIONS ---

def is_between_any_two(val, a, b, c):
    pairs = [(a, b), (a, c), (b, c)]
    return any(min(x, y) <= val <= max(x, y) for x, y in pairs)

def ema_ma_prerequisite(df):
    cp = df['close'].iloc[-1]
    ema8 = df['EMA8'].iloc[-1]
    ema13 = df['EMA13'].iloc[-1]
    ema21 = df['EMA21'].iloc[-1]
    ema50 = df['EMA50'].iloc[-1]
    ema200 = df['EMA200'].iloc[-1]
    ma50 = df['MA50'].iloc[-1]
    ma200 = df['MA200'].iloc[-1]

    # Check for NaN to avoid false positives
    values = [cp, ema8, ema13, ema21, ema50, ema200, ma50, ma200]
    if any(pd.isna(v) for v in values):
        return False

    for val in [cp, ema8, ema13, ema21, ema50]:
        if not is_between_any_two(val, ema200, ma200, ma50):
            return False
    return True

# --- TREND ANALYSIS ---

def analyze_trend(df):
    results = {}

    # Check EMA/MA prerequisite first
    if not ema_ma_prerequisite(df):
        return results

    # Extract last values for indicators
    try:
        K = df['K_9_3_3'].iloc[-1]
        D = df['D_9_3_3'].iloc[-1]
        J = df['J_9_3_3'].iloc[-1]
        RSI5 = df['RSI5'].iloc[-1]
        RSI13 = df['RSI13'].iloc[-1]
        RSI21 = df['RSI21'].iloc[-1]
        WR8 = df['WR8'].iloc[-1]
        WR13 = df['WR13'].iloc[-1]
        WR50 = df['WR50'].iloc[-1]
        WR200 = df['WR200'].iloc[-1]
    except KeyError as e:
        print(f"Missing indicator data: {e}")
        return results

    # Check for NaN values (incomplete data)
    if any(pd.isna(x) for x in [K, D, J, RSI5, RSI13, RSI21, WR8, WR13, WR50, WR200]):
        return results

    # Uptrend condition
    if (J > D > K) and (RSI5 > RSI13 > RSI21) and (WR8 > WR13 >= WR50 >= WR200):
        results['start'] = 'uptrend'

    # Downtrend condition
    elif (K > D > J) and (RSI21 > RSI13 > RSI5) and (WR200 >= WR50 >= WR13 > WR8):
        results['start'] = 'downtrend'

    # Trend end condition
    elif (min(WR50, WR200) <= WR8 <= max(WR50, WR200)) and (min(WR50, WR200) <= WR13 <= max(WR50, WR200)):
        results['start'] = 'trend_end'

    results['values'] = {
        'K': K, 'D': D, 'J': J,
        'RSI5': RSI5, 'RSI13': RSI13, 'RSI21': RSI21,
        'WR8': WR8, 'WR13': WR13, 'WR50': WR50, 'WR200': WR200
    }

    return results

# --- TELEGRAM NOTIFICATION ---

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bot token or chat ID not set.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, data=payload)
        resp.raise_for_status()
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

# --- MAIN EXECUTION ---

def main():
    dt = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    messages = []

    for symbol in COINS:
        try:
            df = fetch_ohlcv_ccxt(symbol, INTERVAL, LOOKBACK)
            if len(df) < 200:
                print(f"Not enough data for {symbol}")
                continue

            df = add_indicators(df)
            trend = analyze_trend(df)

            if 'start' in trend:
                vals = trend['values']
                msg = (
                    f"<b>Kucoin {INTERVAL.upper()} Trend Alert ({dt})</b>\n"
                    f"<b>Symbol:</b> <code>{symbol}</code>\n"
                    f"Signal: <b>{trend['start']}</b>\n"
                    f"\n<code>"
                    f"K={vals['K']:.2f}, D={vals['D']:.2f}, J={vals['J']:.2f}\n"
                    f"RSI5={vals['RSI5']:.2f}, RSI13={vals['RSI13']:.2f}, RSI21={vals['RSI21']:.2f}\n"
                    f"WR8={vals['WR8']:.2f}, WR13={vals['WR13']:.2f}, WR50={vals['WR50']:.2f}, WR200={vals['WR200']:.2f}"
                    f"</code>"
                )
                messages.append(msg)

        except Exception as e:
            print(f"Error processing {symbol}: {e}")

    if messages:
        for msg in messages:
            send_telegram_message(msg)
    else:
        send_telegram_message("No trend signals for any coin.")

if __name__ == "__main__":
    main()
