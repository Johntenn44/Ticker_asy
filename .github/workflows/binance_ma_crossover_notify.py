import os
import ccxt
import pandas as pd
import requests
from datetime import datetime
import ta  # pip install ta

# --- CONFIGURATION ---

COINS = [
    "XRP/USDT", "XMR/USDT", "GMX/USDT", "LUNA/USDT", "TRX/USDT",
    # Add more symbols here
]

EXCHANGE_ID = 'kucoin'
INTERVAL = '12h'
LOOKBACK = 300  # enough for longest indicator window
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- INDICATOR CALCULATION ---

def calculate_kdj(df, n=9, k_period=3, d_period=3):
    low_min = df['low'].rolling(window=n).min()
    high_max = df['high'].rolling(window=n).max()
    rsv = (df['close'] - low_min) / (high_max - low_min) * 100

    k = rsv.ewm(alpha=1/k_period, adjust=False).mean()
    d = k.ewm(alpha=1/d_period, adjust=False).mean()
    j = 3 * k - 2 * d
    df['K'] = k
    df['D'] = d
    df['J'] = j
    return df

def add_indicators(df):
    df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['MA50'] = df['close'].rolling(window=50).mean()
    df['MA200'] = df['close'].rolling(window=200).mean()

    # RSI
    df['RSI5'] = ta.momentum.RSIIndicator(df['close'], window=5).rsi()
    df['RSI13'] = ta.momentum.RSIIndicator(df['close'], window=13).rsi()
    df['RSI21'] = ta.momentum.RSIIndicator(df['close'], window=21).rsi()

    # Williams %R (note: ta library's WilliamsR returns negative values, so invert sign)
    df['WR8'] = -ta.momentum.WilliamsRIndicator(df['high'], df['low'], df['close'], lbp=8).williams_r()
    df['WR13'] = -ta.momentum.WilliamsRIndicator(df['high'], df['low'], df['close'], lbp=13).williams_r()
    df['WR50'] = -ta.momentum.WilliamsRIndicator(df['high'], df['low'], df['close'], lbp=50).williams_r()
    df['WR200'] = -ta.momentum.WilliamsRIndicator(df['high'], df['low'], df['close'], lbp=200).williams_r()

    df = calculate_kdj(df)
    return df

# --- TREND LOGIC ---

def analyze_trend(df):
    # Use last row for analysis
    last = df.iloc[-1]

    # EMA/MA prerequisite example: current price between MA50 and EMA200 (customize as needed)
    price = last['close']
    mas = [last['MA50'], last['EMA200'], last['MA200']]
    low_ma, high_ma = min(mas), max(mas)
    ema_ma_condition = low_ma <= price <= high_ma

    # Uptrend conditions
    uptrend = (last['J'] > last['D'] > last['K']) and \
              (last['RSI5'] > last['RSI13'] > last['RSI21']) and \
              (last['WR8'] >= last['WR13'] >= last['WR50'] >= last['WR200']) and \
              ema_ma_condition

    # Downtrend conditions
    downtrend = (last['K'] > last['D'] > last['J']) and \
                (last['RSI21'] > last['RSI13'] > last['RSI5']) and \
                (last['WR200'] >= last['WR50'] >= last['WR13'] >= last['WR8']) and \
                ema_ma_condition

    # Trend end condition
    wr8, wr13, wr50, wr200 = last['WR8'], last['WR13'], last['WR50'], last['WR200']
    trend_end = (wr50 <= wr8 <= wr200 or wr200 <= wr8 <= wr50) and \
                (wr50 <= wr13 <= wr200 or wr200 <= wr13 <= wr50)

    result = {
        'uptrend': uptrend,
        'downtrend': downtrend,
        'trend_end': trend_end,
        'values': last[['close', 'K', 'D', 'J', 'RSI5', 'RSI13', 'RSI21', 'WR8', 'WR13', 'WR50', 'WR200', 'MA50', 'EMA200', 'MA200']].to_dict()
    }
    return result

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
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    resp = requests.post(url, data=payload)
    resp.raise_for_status()

# --- MAIN ---

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

            if trend['uptrend']:
                msg = (
                    f"<b>Uptrend Signal ({dt})</b>\n"
                    f"<b>{symbol}</b>\n"
                    f"KDJ: J={trend['values']['J']:.2f} > D={trend['values']['D']:.2f} > K={trend['values']['K']:.2f}\n"
                    f"RSI: 5={trend['values']['RSI5']:.2f} > 13={trend['values']['RSI13']:.2f} > 21={trend['values']['RSI21']:.2f}\n"
                    f"WR: 8={trend['values']['WR8']:.2f} >= 13={trend['values']['WR13']:.2f} >= 50={trend['values']['WR50']:.2f} >= 200={trend['values']['WR200']:.2f}\n"
                    f"Price={trend['values']['close']:.5f}, MA50={trend['values']['MA50']:.5f}, EMA200={trend['values']['EMA200']:.5f}, MA200={trend['values']['MA200']:.5f}"
                )
                messages.append(msg)

            elif trend['downtrend']:
                msg = (
                    f"<b>Downtrend Signal ({dt})</b>\n"
                    f"<b>{symbol}</b>\n"
                    f"KDJ: K={trend['values']['K']:.2f} > D={trend['values']['D']:.2f} > J={trend['values']['J']:.2f}\n"
                    f"RSI: 21={trend['values']['RSI21']:.2f} > 13={trend['values']['RSI13']:.2f} > 5={trend['values']['RSI5']:.2f}\n"
                    f"WR: 200={trend['values']['WR200']:.2f} >= 50={trend['values']['WR50']:.2f} >= 13={trend['values']['WR13']:.2f} >= 8={trend['values']['WR8']:.2f}\n"
                    f"Price={trend['values']['close']:.5f}, MA50={trend['values']['MA50']:.5f}, EMA200={trend['values']['EMA200']:.5f}, MA200={trend['values']['MA200']:.5f}"
                )
                messages.append(msg)

            elif trend['trend_end']:
                msg = (
                    f"<b>Trend End Signal ({dt})</b>\n"
                    f"<b>{symbol}</b>\n"
                    f"WR8 and WR13 are between WR50 and WR200.\n"
                    f"WR8={trend['values']['WR8']:.2f}, WR13={trend['values']['WR13']:.2f}, WR50={trend['values']['WR50']:.2f}, WR200={trend['values']['WR200']:.2f}\n"
                    f"Price={trend['values']['close']:.5f}"
                )
                messages.append(msg)

        except Exception as e:
            print(f"Error processing {symbol}: {e}")

    if messages:
        for msg in messages:
            send_telegram_message(msg)
    else:
        send_telegram_message("No trend signals detected.")

if __name__ == "__main__":
    main()
