import os
import ccxt
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- CONFIGURATION ---

COINS = [
    "XRP/USDT", "XMR/USDT", "GMX/USDT", "LUNA/USDT", "TRX/USDT",
    "EIGEN/USDT", "APE/USDT", "WAVES/USDT", "PLUME/USDT", "SUSHI/USDT",
    "DOGE/USDT", "VIRTUAL/USDT", "CAKE/USDT", "GRASS/USDT", "AAVE/USDT",
    "SUI/USDT", "ARB/USDT", "XLM/USDT", "MNT/USDT", "LTC/USDT", "NEAR/USDT",
]

EXCHANGE_ID = 'kucoin'
INTERVALS = ['4h', '6h', '12h']
LOOKBACK = 500

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- INDICATOR CALCULATIONS ---

def add_indicators(df):
    df['EMA8'] = df['close'].ewm(span=8, adjust=False).mean()
    df['EMA13'] = df['close'].ewm(span=13, adjust=False).mean()
    df['EMA21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['MA50'] = df['close'].rolling(window=50).mean()
    df['MA200'] = df['close'].rolling(window=200).mean()
    return df

# --- PREREQUISITE FILTER ---

def is_coin_eligible(df):
    last = df.iloc[-1]

    key_values = [last['EMA8'], last['EMA13'], last['EMA21'], last['EMA50'], last['close']]
    ma_values = [last['MA50'], last['MA200'], last['EMA200']]

    pairs = [(ma_values[0], ma_values[1]), (ma_values[0], ma_values[2]), (ma_values[1], ma_values[2])]

    count = 0
    for val in key_values:
        between_pairs = sum(1 for (low, high) in pairs if min(low, high) <= val <= max(low, high))
        if between_pairs >= 1:
            count += 1

    return count >= 2

# --- DATA FETCHING ---

def fetch_ohlcv_ccxt(symbol, timeframe, limit):
    exchange = getattr(ccxt, EXCHANGE_ID)()
    exchange.load_markets()
    symbol_api = symbol.replace('/', '-')
    if symbol_api not in exchange.symbols:
        print(f"Symbol {symbol_api} not found on {EXCHANGE_ID}, skipping.")
        return None
    ohlcv = exchange.fetch_ohlcv(symbol_api, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df['close'] = df['close'].astype(float)
    return df

# --- TELEGRAM NOTIFICATION ---

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bot token or chat ID not set in environment variables.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    resp = requests.post(url, data=payload)
    try:
        resp.raise_for_status()
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

# --- MAIN FUNCTION TO CHECK PREREQUISITE ONLY ---

def main_prerequisite_only():
    eligible_coins = set()

    for symbol in COINS:
        for interval in INTERVALS:
            try:
                print(f"Fetching data for {symbol} at interval {interval}...")
                df = fetch_ohlcv_ccxt(symbol, interval, LOOKBACK)
                if df is None or len(df) < 200:
                    print(f"Not enough data for {symbol} {interval}, skipping.")
                    continue
                df = add_indicators(df)

                if is_coin_eligible(df):
                    eligible_coins.add(f"{symbol} ({interval})")
                    print(f"{symbol} at {interval} meets the prerequisite.")
                else:
                    print(f"{symbol} at {interval} does NOT meet the prerequisite.")
            except Exception as e:
                print(f"Error processing {symbol} {interval}: {e}")

    if eligible_coins:
        message = "<b>Coins meeting EMA/MA prerequisite condition:</b>\n" + "\n".join(sorted(eligible_coins))
    else:
        message = "No coins met the EMA/MA prerequisite condition."

    send_telegram_message(message)

if __name__ == "__main__":
    main_prerequisite_only()
