import os
import ccxt
import pandas as pd
import requests
from datetime import datetime
import ta

# --- CONFIGURATION ---

COINS = [
    "XRP/USDT", "XMR/USDT", "GMX/USDT", "LUNA/USDT", "TRX/USDT",
    "EIGEN/USDT", "APE/USDT", "WAVES/USDT", "PLUME/USDT", "SUSHI/USDT",
    "DOGE/USDT", "VIRTUAL/USDT", "CAKE/USDT", "GRASS/USDT", "AAVE/USDT",
    "SUI/USDT", "ARB/USDT", "XLM/USDT", "MNT/USDT", "LTC/USDT", "NEAR/USDT",
]

EXCHANGE_ID = 'kucoin'
INTERVAL = '4h'
LOOKBACK = 210

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Single chat ID as string

# --- INDICATOR CALCULATION ---

def add_indicators(df):
    df['EMA8'] = df['close'].ewm(span=8, adjust=False).mean()
    df['EMA13'] = df['close'].ewm(span=13, adjust=False).mean()
    df['EMA21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['MA50'] = df['close'].rolling(window=50).mean()
    df['MA200'] = df['close'].rolling(window=200).mean()

    bb = ta.volatility.BollingerBands(close=df['close'], window=50, window_dev=2)
    df['BB_MID'] = bb.bollinger_mavg()
    df['BB_UPPER'] = bb.bollinger_hband()
    df['BB_LOWER'] = bb.bollinger_lband()

    psar = ta.trend.PSARIndicator(high=df['high'], low=df['low'], close=df['close'], step=0.02, max_step=0.2)
    df['SAR'] = psar.psar()

    return df

# --- TREND LOGIC ---

def analyze_trend(df):
    results = {}
    if len(df) < 3:
        return results

    cp1 = df['close'].iloc[-1]
    cp2 = df['close'].iloc[-2]

    A1 = df['EMA8'].iloc[-1]
    B1 = df['EMA13'].iloc[-1]
    C1 = df['EMA21'].iloc[-1]
    D1 = df['EMA50'].iloc[-1]
    E1 = df['EMA200'].iloc[-1]
    MA50_1 = df['MA50'].iloc[-1]
    MA200_1 = df['MA200'].iloc[-1]

    A2 = df['EMA8'].iloc[-2]
    B2 = df['EMA13'].iloc[-2]
    C2 = df['EMA21'].iloc[-2]
    D2 = df['EMA50'].iloc[-2]
    E2 = df['EMA200'].iloc[-2]
    MA50_2 = df['MA50'].iloc[-2]
    MA200_2 = df['MA200'].iloc[-2]

    detected_trend = None
    confirmed_trend = None

    # Uptrend condition + SAR confirmation
    if (E1 > cp1 > A1 > B1 > C1 > D1 > MA50_1) and (cp1 < MA200_1) and \
       (E2 > cp2 > A2 > B2 > C2 > D2 > MA50_2) and (cp2 < MA200_2):
        detected_trend = 'uptrend'
        sar_confirm = all(
            df['SAR'].iloc[-i] > df['BB_UPPER'].iloc[-i]
            for i in range(1, 4)
        )
        if sar_confirm:
            confirmed_trend = 'uptrend'

    # Downtrend condition + SAR confirmation
    elif (E1 < cp1 < A1 < B1 < C1 < D1 < MA50_1) and (cp1 > MA200_1) and \
         (E2 < cp2 < A2 < B2 < C2 < D2 < MA50_2) and (cp2 > MA200_2):
        detected_trend = 'downtrend'
        sar_confirm = all(
            df['SAR'].iloc[-i] < df['BB_LOWER'].iloc[-i]
            for i in range(1, 4)
        )
        if sar_confirm:
            confirmed_trend = 'downtrend'

    if detected_trend:
        results['detected_trend'] = detected_trend
    if confirmed_trend:
        results['confirmed_trend'] = confirmed_trend

    results['values'] = {
        'cp1': cp1,
        'cp2': cp2,
    }
    return results

# --- DATA FETCHING ---

def fetch_ohlcv_ccxt(symbol, timeframe, limit):
    exchange = getattr(ccxt, EXCHANGE_ID)()
    exchange.load_markets()
    symbol_api = symbol.replace('/', '-')
    ohlcv = exchange.fetch_ohlcv(symbol_api, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
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
        print(f"Message sent to chat ID {TELEGRAM_CHAT_ID}")
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

# --- REPORT FORMAT ---

def format_trend_report(symbol, trend, dt, interval):
    vals = trend['values']
    detected = trend.get('detected_trend', 'None')
    confirmed = trend.get('confirmed_trend', 'None')
    msg = (
        f"<b>Kucoin {interval.upper()} Trend Alert ({dt})</b>\n"
        f"<b>Symbol:</b> <code>{symbol}</code>\n"
        f"Detected Trend: <b>{detected}</b>\n"
        f"Confirmed Trend: <b>{confirmed}</b>\n"
        f"<code>cp1={vals['cp1']:.5f}, cp2={vals['cp2']:.5f}</code>"
    )
    return msg

# --- MAIN ---

def main():
    dt = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    for symbol in COINS:
        try:
            df = fetch_ohlcv_ccxt(symbol, INTERVAL, LOOKBACK)
            if len(df) < 200:
                print(f"Not enough data for {symbol}")
                continue
            df = add_indicators(df)
            trend = analyze_trend(df)
            if 'detected_trend' in trend:
                msg = format_trend_report(symbol, trend, dt, INTERVAL)
                send_telegram_message(msg)
        except Exception as e:
            print(f"Error processing {symbol}: {e}")

if __name__ == "__main__":
    main()
