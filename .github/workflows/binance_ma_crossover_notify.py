import os
import ccxt
import pandas as pd
import numpy as np  # Added for np.isclose
import requests
from datetime import datetime

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

# --- RSI CALCULATION ---
def calculate_rsi(df, period):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# --- MAIN LOGIC ---
def main():
    dt = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    coins_with_unequal_rsi = []
    
    for symbol in COINS:
        try:
            # Fetch OHLCV data
            exchange = getattr(ccxt, EXCHANGE_ID)()
            df = exchange.fetch_ohlcv(symbol, INTERVAL, limit=LOOKBACK)
            df = pd.DataFrame(df, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['close'] = df['close'].astype(float)
            
            # Calculate RSI values
            rsi8 = calculate_rsi(df, 8).iloc[-1]
            rsi13 = calculate_rsi(df, 13).iloc[-1]
            rsi21 = calculate_rsi(df, 21).iloc[-1]
            
            # Check if all three RSI values are not equal
            if not (np.isclose(rsi8, rsi13) and np.isclose(rsi13, rsi21)):
                coins_with_unequal_rsi.append(symbol)
                
        except Exception as e:
            print(f"Error processing {symbol}: {e}")

    # Send Telegram notification
    if coins_with_unequal_rsi:
        coins_list = "\n".join(coins_with_unequal_rsi)
        message = (
            f"<b>Kucoin {INTERVAL.upper()} RSI Alert ({dt})</b>\n"
            f"Coins with unequal RSI (8,13,21):\n\n{coins_list}"
        )
        send_telegram_message(message)
    else:
        send_telegram_message("All coins have equal RSI values for 8,13,21 periods")

# --- TELEGRAM FUNCTION ---
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    })

if __name__ == "__main__":
    main()
