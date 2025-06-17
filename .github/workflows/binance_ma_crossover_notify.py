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
INTERVAL = '1h'      # Candle timeframe
LOOKBACK = 500       # Number of candles to fetch (>= 200)
LEVERAGE = 10

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- INDICATOR PARAMETERS ---

KDJ_LENGTH = 5
KDJ_MA1 = 8
KDJ_MA2 = 8

RSI_PERIODS = [5, 13, 21]
WR_PERIODS = [8, 13, 50, 200]

# --- INDICATOR CALCULATION ---

def add_indicators(df):
    # EMAs and MAs
    df['EMA8'] = df['close'].ewm(span=8, adjust=False).mean()
    df['EMA13'] = df['close'].ewm(span=13, adjust=False).mean()
    df['EMA21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['MA50'] = df['close'].rolling(window=50).mean()
    df['MA200'] = df['close'].rolling(window=200).mean()

    # KDJ indicator
    df = add_kdj(df, length=KDJ_LENGTH, ma1=KDJ_MA1, ma2=KDJ_MA2)

    # RSI indicators
    for period in RSI_PERIODS:
        df[f'RSI{period}'] = rsi(df['close'], period)

    # Williams %R indicators
    for period in WR_PERIODS:
        df[f'WR{period}'] = williams_r(df['high'], df['low'], df['close'], period)

    return df

def add_kdj(df, length=5, ma1=8, ma2=8):
    low_min = df['low'].rolling(window=length, min_periods=1).min()
    high_max = df['high'].rolling(window=length, min_periods=1).max()
    rsv = (df['close'] - low_min) / (high_max - low_min).replace(0, 0.0001) * 100  # avoid div0

    k = rsv.ewm(alpha=1/ma1, adjust=False).mean()
    d = k.ewm(alpha=1/ma2, adjust=False).mean()
    j = 3 * k - 2 * d

    df['K'] = k
    df['D'] = d
    df['J'] = j
    return df

def rsi(series, period):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, 0.0001)  # avoid div0
    rsi = 100 - (100 / (1 + rs))
    return rsi

def williams_r(high, low, close, period):
    highest_high = high.rolling(window=period, min_periods=period).max()
    lowest_low = low.rolling(window=period, min_periods=period).min()
    wr = -100 * (highest_high - close) / (highest_high - lowest_low).replace(0, 0.0001)
    return wr

# --- TREND LOGIC ---

def analyze_trend(df):
    results = {}

    # Prerequisite condition:
    # price, EMA8, EMA13, EMA21, EMA50 all NOT above MA50, MA200, or EMA200
    cp = df['close'].iloc[-1]
    ema8 = df['EMA8'].iloc[-1]
    ema13 = df['EMA13'].iloc[-1]
    ema21 = df['EMA21'].iloc[-1]
    ema50 = df['EMA50'].iloc[-1]
    ma50 = df['MA50'].iloc[-1]
    ma200 = df['MA200'].iloc[-1]
    ema200 = df['EMA200'].iloc[-1]

    prereq = all([
        cp <= ma50, cp <= ma200, cp <= ema200,
        ema8 <= ma50, ema8 <= ma200, ema8 <= ema200,
        ema13 <= ma50, ema13 <= ma200, ema13 <= ema200,
        ema21 <= ma50, ema21 <= ma200, ema21 <= ema200,
        ema50 <= ma50, ema50 <= ma200, ema50 <= ema200
    ])

    if not prereq:
        return results  # Prerequisite not met, no trend identified

    # KDJ values
    K = df['K'].iloc[-1]
    D = df['D'].iloc[-1]
    J = df['J'].iloc[-1]

    # RSI values
    RSI5 = df['RSI5'].iloc[-1]
    RSI13 = df['RSI13'].iloc[-1]
    RSI21 = df['RSI21'].iloc[-1]

    # Williams %R values
    WR8 = df['WR8'].iloc[-1]
    WR13 = df['WR13'].iloc[-1]
    WR50 = df['WR50'].iloc[-1]
    WR200 = df['WR200'].iloc[-1]

    # Check KDJ trend condition
    kdj_up = (J > D > K)
    kdj_down = (K > D > J)

    # Check RSI trend condition
    rsi_up = (RSI5 > RSI13 > RSI21)
    rsi_down = (RSI21 > RSI13 > RSI5)

    # Check WR trend condition
    wr_up = (WR8 > WR13 > WR50 > WR200)
    wr_down = (WR200 > WR50 > WR13 > WR8)

    # Check if trend ended: 8 and 13 WR between 50 and 200 (neutral zone)
    wr_end = (50 <= WR8 <= 200) and (50 <= WR13 <= 200)

    # Identify trend start
    if kdj_up and rsi_up and wr_up and not wr_end:
        results['start'] = 'uptrend'
    elif kdj_down and rsi_down and wr_down and not wr_end:
        results['start'] = 'downtrend'

    # Identify trend end
    if wr_end:
        results['end'] = True

    # Include indicator values for debugging/alerts
    results['values'] = {
        'close': cp,
        'EMA8': ema8,
        'EMA13': ema13,
        'EMA21': ema21,
        'EMA50': ema50,
        'MA50': ma50,
        'MA200': ma200,
        'EMA200': ema200,
        'K': K,
        'D': D,
        'J': J,
        'RSI5': RSI5,
        'RSI13': RSI13,
        'RSI21': RSI21,
        'WR8': WR8,
        'WR13': WR13,
        'WR50': WR50,
        'WR200': WR200,
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
    df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)
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
        try:
            print(f"Fetching data for {symbol} at interval {INTERVAL}...")
            df = fetch_ohlcv_ccxt(symbol, INTERVAL, LOOKBACK)
            if len(df) < 200:
                print(f"Not enough data for {symbol}, skipping.")
                continue
            df = add_indicators(df)
            trades = backtest(df)
            trades_recent = filter_trades_last_4_days(trades, df)

            if trades_recent:
                entry_times = [df.index[t['entry_index']] for t in trades_recent]
                earliest_entry = min(entry_times)
                summary_msg = format_backtest_summary(symbol, trades_recent, df, INTERVAL)
                report_entries.append((earliest_entry, summary_msg))
            else:
                print(f"No trades in last 4 days for {symbol}, skipping report.")
        except Exception as e:
            print(f"Error processing {symbol}: {e}")

    # Sort the report entries chronologically by earliest trade entry
    report_entries.sort(key=lambda x: x[0])
    all_messages = [entry[1] for entry in report_entries]

    if all_messages:
        now = datetime.utcnow()
        four_days_ago = now - timedelta(days=14)
        header = (f"<b>Backtest results for the period:</b> "
                  f"{four_days_ago.strftime('%Y-%m-%d %H:%M')} UTC to {now.strftime('%Y-%m-%d %H:%M')} UTC\n\n")
        full_message = header + "\n\n".join(all_messages)
        send_telegram_message(full_message)
    else:
        send_telegram_message("No backtest results available for the past 4 days.")

if __name__ == "__main__":
    main()
