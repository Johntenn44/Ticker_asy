import os
import ccxt
import pandas as pd
import requests
from datetime import datetime

# --- CONFIGURATION ---

COINS = [
    "BTC/USDT",
    "ETH/USDT",
    # Add more Binance symbols here
]

EXCHANGE_ID = 'binance'
INTERVAL = '1d'
LOOKBACK = 210  # Number of days to fetch
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- FUNCTIONS ---

def fetch_ohlcv_ccxt(symbol, timeframe, limit):
    exchange = getattr(ccxt, EXCHANGE_ID)()
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(
        ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
    )
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df['close'] = df['close'].astype(float)
    return df

def check_ma_crossover(df):
    df["MA50"] = df["close"].rolling(window=50).mean()
    df["MA200"] = df["close"].rolling(window=200).mean()
    last_two = df.iloc[-2:]
    return (last_two["MA200"] > last_two["MA50"]).all()

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
    notified_coins = []
    for symbol in COINS:
        try:
            df = fetch_ohlcv_ccxt(symbol, INTERVAL, LOOKBACK)
            if len(df) < 200:
                continue
            if check_ma_crossover(df):
                notified_coins.append(symbol)
        except Exception as e:
            print(f"Error processing {symbol}: {e}")

    if notified_coins:
        dt = datetime.utcnow().strftime('%Y-%m-%d')
        msg = (
            f"<b>Binance MA Crossover Alert ({dt})</b>\n"
            f"The following coins have had the 200-day MA above the 50-day MA for two consecutive days:\n"
            + "\n".join(f"• <code>{c}</code>" for c in notified_coins)
        )
        send_telegram_message(msg)
    else:
        print("No coins matched the MA crossover condition.")

if __name__ == "__main__":
    main()
