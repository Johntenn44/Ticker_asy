import os
import ccxt
import pandas as pd
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
    # Add more symbols here
]

EXCHANGE_ID = 'kucoin'
INTERVAL = '12h'      # Use 12-hour candles
LOOKBACK = 210       # Number of candles to fetch (must be >= 200)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- INDICATOR CALCULATION ---

def add_indicators(df):
    df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['MA50'] = df['close'].rolling(window=50).mean()
    df['MA200'] = df['close'].rolling(window=200).mean()
    return df

# --- TREND LOGIC ---

def analyze_trend(df):
    cp = df['close'].iloc[-1]  # Current price
    ma50 = df['MA50'].iloc[-1]
    ema200 = df['EMA200'].iloc[-1]
    ma200 = df['MA200'].iloc[-1]

    # Check if current price is between the three moving averages in any order
    low = min(ma50, ema200, ma200)
    high = max(ma50, ema200, ma200)

    results = {}
    if low <= cp <= high:
        results['price_between_mas'] = True
    else:
        results['price_between_mas'] = False

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
    messages = []
    for symbol in COINS:
        try:
            df = fetch_ohlcv_ccxt(symbol, INTERVAL, LOOKBACK)
            if len(df) < 200:
                print(f"Not enough data for {symbol}")
                continue
            df = add_indicators(df)
            trend = analyze_trend(df)

            if trend.get('price_between_mas'):
                vals = trend['values']
                msg = (
                    f"<b>Kucoin {INTERVAL.upper()} Price Between MAs Alert ({dt})</b>\n"
                    f"<b>Symbol:</b> <code>{symbol}</code>\n"
                    f"Current price is <b>between</b> MA50, EMA200, and MA200.\n\n"
                    f"<code>Close={vals['close']:.5f}, MA50={vals['MA50']:.5f}, EMA200={vals['EMA200']:.5f}, MA200={vals['MA200']:.5f}</code>"
                )
                messages.append(msg)
        except Exception as e:
            print(f"Error processing {symbol}: {e}")

    if messages:
        for msg in messages:
            send_telegram_message(msg)
    else:
        send_telegram_message("No coins have current price between MA50, EMA200, and MA200.")

if __name__ == "__main__":
    main()
