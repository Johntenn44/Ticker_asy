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
LEVERAGE = 10

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- INDICATOR CALCULATION ---

def add_indicators(df):
    df['EMA8'] = df['close'].ewm(span=8, adjust=False).mean()
    df['EMA13'] = df['close'].ewm(span=13, adjust=False).mean()
    df['EMA21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['MA50'] = df['close'].rolling(window=50).mean()
    df['MA200'] = df['close'].rolling(window=200).mean()
    return df

# --- TREND LOGIC ---

def analyze_trend(df):
    if len(df) < 2:
        return {}

    cp1, cp2 = df['close'].iloc[-1], df['close'].iloc[-2]
    A1, B1, C1, D1, E1 = df['EMA8'].iloc[-1], df['EMA13'].iloc[-1], df['EMA21'].iloc[-1], df['EMA50'].iloc[-1], df['EMA200'].iloc[-1]
    MA50_1, MA200_1 = df['MA50'].iloc[-1], df['MA200'].iloc[-1]
    A2, B2, C2, D2, E2 = df['EMA8'].iloc[-2], df['EMA13'].iloc[-2], df['EMA21'].iloc[-2], df['EMA50'].iloc[-2], df['EMA200'].iloc[-2]
    MA50_2, MA200_2 = df['MA50'].iloc[-2], df['MA200'].iloc[-2]

    if (E1 > cp1 > A1 > B1 > C1 > D1 > MA50_1) and (cp1 < MA200_1) and \
       (E2 > cp2 > A2 > B2 > C2 > D2 > MA50_2) and (cp2 < MA200_2):
        return {'start': 'uptrend'}
    elif (E1 < cp1 < A1 < B1 < C1 < D1 < MA50_1) and (cp1 > MA200_1) and \
         (E2 < cp2 < A2 < B2 < C2 < D2 < MA50_2) and (cp2 > MA200_2):
        return {'start': 'downtrend'}
    return {}

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

# --- BACKTESTING ---

def backtest(df):
    trades = []
    position = None
    entry_price = 0.0
    entry_index = 0

    for i in range(200, len(df)):
        window_df = df.iloc[:i+1]
        trend = analyze_trend(window_df)

        if 'start' in trend:
            if position != trend['start']:
                if position is not None:
                    exit_price = df['close'].iloc[i-1]
                    profit = (exit_price - entry_price) if position == 'uptrend' else (entry_price - exit_price)
                    profit *= LEVERAGE
                    trades.append({
                        'entry_index': entry_index,
                        'exit_index': i-1,
                        'position': position,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'profit': profit
                    })
                position = trend['start']
                entry_price = df['close'].iloc[i]
                entry_index = i
        else:
            if position is not None:
                exit_price = df['close'].iloc[i]
                profit = (exit_price - entry_price) if position == 'uptrend' else (entry_price - exit_price)
                profit *= LEVERAGE
                trades.append({
                    'entry_index': entry_index,
                    'exit_index': i,
                    'position': position,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'profit': profit
                })
                position = None

    if position is not None:
        exit_price = df['close'].iloc[-1]
        profit = (exit_price - entry_price) if position == 'uptrend' else (entry_price - exit_price)
        profit *= LEVERAGE
        trades.append({
            'entry_index': entry_index,
            'exit_index': len(df)-1,
            'position': position,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'profit': profit
        })

    return trades

def filter_trades_last_4_days(trades, df):
    now = datetime.utcnow()
    four_days_ago = now - timedelta(days=4)
    return [t for t in trades if df.index[t['entry_index']] >= four_days_ago]

def format_backtest_summary(symbol, trades, df, interval):
    total_profit = sum(t['profit'] for t in trades)
    num_trades = len(trades)
    wins = sum(1 for t in trades if t['profit'] > 0)
    losses = num_trades - wins
    win_rate = (wins / num_trades * 100) if num_trades > 0 else 0

    msg = f"📊 <b>Backtest Summary for {symbol} ({interval})</b>\n"
    msg += f"🕒 Trades in last 4 days: <code>{num_trades}</code>\n"
    msg += f"✅ Wins: <b>{wins}</b> | ❌ Losses: <b>{losses}</b> | 🎯 Win Rate: <b>{win_rate:.2f}%</b>\n"
    msg += f"💰 Total Profit (price units): <code>{total_profit:.4f}</code>\n"
    msg += "📈 <b>Trades details:</b>\n"

    for i, t in enumerate(trades, 1):
        entry_date = df.index[t['entry_index']].strftime('%Y-%m-%d %H:%M')
        exit_date = df.index[t['exit_index']].strftime('%Y-%m-%d %H:%M')
        position_emoji = "📈" if t['position'] == 'uptrend' else "📉"
        msg += (f"{i}. {position_emoji} <b>{t['position'].capitalize()}</b> | "
                f"Entry: <code>{entry_date}</code> @ <code>{t['entry_price']:.4f}</code> | "
                f"Exit: <code>{exit_date}</code> @ <code>{t['exit_price']:.4f}</code> | "
                f"Profit: <code>{t['profit']:.4f}</code>\n")

    msg += "----------------------------------------"
    return msg

# --- MAIN ---

def main():
    report_entries = []

    for symbol in COINS:
        for interval in INTERVALS:
            try:
                print(f"Fetching data for {symbol} at interval {interval}...")
                df = fetch_ohlcv_ccxt(symbol, interval, LOOKBACK)
                if len(df) < 200:
                    print(f"Not enough data for {symbol} {interval}, skipping.")
                    continue
                df = add_indicators(df)
                trades = backtest(df)
                trades_recent = filter_trades_last_4_days(trades, df)

                if trades_recent:
                    entry_times = [df.index[t['entry_index']] for t in trades_recent]
                    earliest_entry = min(entry_times)
                    summary_msg = format_backtest_summary(symbol, trades_recent, df, interval)
                    report_entries.append((earliest_entry, summary_msg))
                else:
                    print(f"No trades in last 4 days for {symbol} {interval}, skipping report.")
            except Exception as e:
                print(f"Error processing {symbol} {interval}: {e}")

    # Sort the report entries chronologically by earliest trade entry
    report_entries.sort(key=lambda x: x[0])
    all_messages = [entry[1] for entry in report_entries]

    if all_messages:
        now = datetime.utcnow()
        four_days_ago = now - timedelta(days=4)
        header = (f"<b>Backtest results for the period:</b> "
                  f"{four_days_ago.strftime('%Y-%m-%d %H:%M')} UTC to {now.strftime('%Y-%m-%d %H:%M')} UTC\n\n")
        full_message = header + "\n\n".join(all_messages)
        send_telegram_message(full_message)
    else:
        send_telegram_message("No backtest results available for the past 4 days.")

if __name__ == "__main__":
    main()