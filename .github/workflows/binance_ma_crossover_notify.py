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

# --- INDICATOR CALCULATIONS ---

def add_indicators(df):
    df['EMA8'] = df['close'].ewm(span=8, adjust=False).mean()
    df['EMA13'] = df['close'].ewm(span=13, adjust=False).mean()
    df['EMA21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['MA50'] = df['close'].rolling(window=50).mean()
    df['MA200'] = df['close'].rolling(window=200).mean()

    df = calculate_kdj(df)
    df = calculate_rsi(df)
    df = calculate_wr(df)

    return df

def calculate_kdj(df, length=5, ma1=8, ma2=8):
    low_min = df['low'].rolling(window=length).min()
    high_max = df['high'].rolling(window=length).max()
    rsv = 100 * (df['close'] - low_min) / (high_max - low_min)
    df['K'] = rsv.ewm(alpha=1/ma1, adjust=False).mean()
    df['D'] = df['K'].ewm(alpha=1/ma2, adjust=False).mean()
    df['J'] = 3 * df['K'] - 2 * df['D']
    return df

def calculate_rsi(df, periods=[5, 13, 21]):
    for period in periods:
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        df[f'RSI_{period}'] = rsi
    return df

def calculate_wr(df, periods=[8, 13, 50, 200]):
    for period in periods:
        highest_high = df['high'].rolling(window=period).max()
        lowest_low = df['low'].rolling(window=period).min()
        wr = -100 * (highest_high - df['close']) / (highest_high - lowest_low)
        df[f'WR_{period}'] = wr
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

# --- TREND IDENTIFICATION ---

def identify_trend(df):
    if len(df) < 1:
        return None

    last = df.iloc[-1]

    if not is_coin_eligible(df):
        return None

    # KDJ condition
    k, d, j = last['K'], last['D'], last['J']
    kdj_up = j > d > k
    kdj_down = k > d > j

    # RSI condition
    rsi5, rsi13, rsi21 = last['RSI_5'], last['RSI_13'], last['RSI_21']
    rsi_up = rsi5 > rsi13 > rsi21
    rsi_down = rsi21 > rsi13 > rsi5

    # WR condition
    wr8, wr13, wr50, wr200 = last['WR_8'], last['WR_13'], last['WR_50'], last['WR_200']
    wr_up = wr8 > wr13 > wr50 > wr200
    wr_down = wr200 > wr50 > wr13 > wr8

    # Trend ended condition
    wr_8_13_between = (min(wr50, wr200) <= wr8 <= max(wr50, wr200)) and (min(wr50, wr200) <= wr13 <= max(wr50, wr200))

    if wr_8_13_between:
        return {'end': True}

    if kdj_up and rsi_up and wr_up:
        return {'start': 'uptrend'}
    elif kdj_down and rsi_down and wr_down:
        return {'start': 'downtrend'}

    return None

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

# --- BACKTESTING ---

def backtest(df):
    trades = []
    position = None
    entry_price = 0.0
    entry_index = 0

    for i in range(200, len(df)):
        window_df = df.iloc[:i+1]
        trend = identify_trend(window_df)

        if trend is None:
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
            continue

        if 'end' in trend:
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
            continue

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
    eligible_coins = set()
    indicator_coins = set()
    report_entries = []

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
                    eligible_coins.add(symbol)
                else:
                    print(f"{symbol} at {interval} does not meet EMA/MA positioning criteria, skipping.")
                    continue

                trades = backtest(df)
                trades_recent = filter_trades_last_4_days(trades, df)

                if trades_recent:
                    indicator_coins.add(symbol)
                    entry_times = [df.index[t['entry_index']] for t in trades_recent]
                    earliest_entry = min(entry_times)
                    summary_msg = format_backtest_summary(symbol, trades_recent, df, interval)
                    report_entries.append((earliest_entry, summary_msg))
                else:
                    print(f"No trades in last 4 days for {symbol} {interval}, skipping report.")
            except Exception as e:
                print(f"Error processing {symbol} {interval}: {e}")

    report_entries.sort(key=lambda x: x[0])
    all_messages = [entry[1] for entry in report_entries]

    eligible_list = ", ".join(sorted(eligible_coins)) if eligible_coins else "None"
    indicator_list = ", ".join(sorted(indicator_coins)) if indicator_coins else "None"

    summary_msg = (
        f"<b>Coins passing EMA/MA prerequisite:</b>\n{eligible_list}\n\n"
        f"<b>Coins with indicator-based trends/trades:</b>\n{indicator_list}\n\n"
    )

    if all_messages:
        now = datetime.utcnow()
        four_days_ago = now - timedelta(days=4)
        header = (f"<b>Backtest results for the period:</b> "
                  f"{four_days_ago.strftime('%Y-%m-%d %H:%M')} UTC to {now.strftime('%Y-%m-%d %H:%M')} UTC\n\n")
        full_message = header + summary_msg + "\n\n".join(all_messages)
        send_telegram_message(full_message)
    else:
        send_telegram_message("No backtest results available for the past 4 days.\n\n" + summary_msg)

if __name__ == "__main__":
    main()
