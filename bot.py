import time
import os
import requests
from datetime import datetime, timezone, timedelta
from fyers_apiv3 import fyersModel

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID         = os.environ.get("CHAT_ID")
FYERS_CLIENT_ID = os.environ.get("FYERS_CLIENT_ID")
FYERS_ACCESS_TOKEN = os.environ.get("FYERS_ACCESS_TOKEN")

# ════════════════════════════════
# ALL SYMBOLS
# ════════════════════════════════
INDICES = [
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTYBANK-INDEX",
    "NSE:FINNIFTY-INDEX",
    "NSE:NIFTYMIDCAP150-INDEX",
    "BSE:SENSEX-INDEX",
]

FNO_STOCKS = [
    "NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:HDFCBANK-EQ",
    "NSE:INFY-EQ", "NSE:ICICIBANK-EQ", "NSE:HINDUNILVR-EQ",
    "NSE:ITC-EQ", "NSE:SBIN-EQ", "NSE:BHARTIARTL-EQ",
    "NSE:AXISBANK-EQ", "NSE:KOTAKBANK-EQ", "NSE:LT-EQ",
    "NSE:HCLTECH-EQ", "NSE:WIPRO-EQ", "NSE:ULTRACEMCO-EQ",
    "NSE:BAJFINANCE-EQ", "NSE:TITAN-EQ", "NSE:ADANIENT-EQ",
    "NSE:MARUTI-EQ", "NSE:SUNPHARMA-EQ", "NSE:TATAMOTORS-EQ",
    "NSE:NTPC-EQ", "NSE:POWERGRID-EQ", "NSE:TECHM-EQ",
    "NSE:JSWSTEEL-EQ", "NSE:TATASTEEL-EQ", "NSE:HINDALCO-EQ",
    "NSE:COALINDIA-EQ", "NSE:DRREDDY-EQ", "NSE:CIPLA-EQ",
    "NSE:DIVISLAB-EQ", "NSE:BPCL-EQ", "NSE:ONGC-EQ",
    "NSE:IOC-EQ", "NSE:GRASIM-EQ", "NSE:ADANIPORTS-EQ",
    "NSE:APOLLOHOSP-EQ", "NSE:ASIANPAINT-EQ", "NSE:BAJAJFINSV-EQ",
    "NSE:BAJAJ-AUTO-EQ", "NSE:BRITANNIA-EQ", "NSE:EICHERMOT-EQ",
    "NSE:HEROMOTOCO-EQ", "NSE:M&M-EQ", "NSE:NESTLEIND-EQ",
    "NSE:SBILIFE-EQ", "NSE:HDFCLIFE-EQ", "NSE:INDUSINDBK-EQ",
    "NSE:TATACONSUM-EQ", "NSE:UPL-EQ",
]

TIMEFRAMES = ["15", "10", "60"]  # 15m, 10m, 1h

def send_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except:
        pass

def get_ist_time():
    utc_now = datetime.now(timezone.utc)
    return utc_now + timedelta(hours=5, minutes=30)

def is_market_open():
    ist = get_ist_time()
    if ist.weekday() > 4:
        return False
    # NSE hours: 9:15 AM to 3:30 PM IST
    market_open  = ist.replace(hour=9,  minute=15, second=0)
    market_close = ist.replace(hour=15, minute=30, second=0)
    return market_open <= ist <= market_close

def get_timestamp():
    ist = get_ist_time()
    return ist.strftime("%Y-%m-%d %H:%M IST")

def get_fyers():
    return fyersModel.FyersModel(
        client_id=FYERS_CLIENT_ID,
        token=FYERS_ACCESS_TOKEN,
        log_path=""
    )

def get_candles(symbol, timeframe):
    fyers = get_fyers()
    data = {
        "symbol": symbol,
        "resolution": timeframe,
        "date_format": "1",
        "range_from": (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d"),
        "range_to": datetime.now().strftime("%Y-%m-%d"),
        "cont_flag": "1"
    }
    response = fyers.history(data=data)
    if response.get("s") != "ok":
        raise Exception(f"Fyers error: {response}")

    candles = []
    for c in response["candles"]:
        candles.append({
            "open":  float(c[1]),
            "high":  float(c[2]),
            "low":   float(c[3]),
            "close": float(c[4]),
        })
    return candles[-20:]  # Last 20 candles

def detect_breaker_block(candles):
    """
    Bullish Breaker Block Detection:
    1. Find Swing High (Point B)
    2. Price drops below previous low (Point A - SSL Swept)
    3. Price reverses strongly upward
    4. Alert when price closes above Point B
    """
    if len(candles) < 10:
        return None

    # Find recent swing high (Point B)
    lookback = candles[-10:]
    swing_high_idx = 0
    swing_high = 0

    for i in range(1, len(lookback) - 1):
        if (lookback[i]["high"] > lookback[i-1]["high"] and
            lookback[i]["high"] > lookback[i+1]["high"]):
            if lookback[i]["high"] > swing_high:
                swing_high = lookback[i]["high"]
                swing_high_idx = i

    if swing_high == 0:
        return None

    # Find swing low before B (Point A)
    pre_b = lookback[:swing_high_idx]
    if not pre_b:
        return None

    swing_low = min(c["low"] for c in pre_b)

    # Check if price swept below A (SSL Swept)
    post_b = lookback[swing_high_idx:]
    ssl_swept = any(c["low"] < swing_low for c in post_b)

    if not ssl_swept:
        return None

    # Check if current candle closes above B (Point B breakout)
    current = candles[-1]
    prev    = candles[-2]

    # Alert: Current candle closes above swing high (Point B)
    if current["close"] > swing_high and prev["close"] <= swing_high:
        return {
            "type": "BREAKER_BLOCK_BREAKOUT",
            "point_b": swing_high,
            "point_a": swing_low,
            "entry": current["close"],
            "sl": swing_low,
            "tp": current["close"] + (current["close"] - swing_low),
        }

    # Alert: Breaker Block formed (SSL swept + strong reversal)
    if ssl_swept and current["close"] > swing_high * 0.999:
        return {
            "type": "BREAKER_BLOCK_FORMED",
            "point_b": swing_high,
            "point_a": swing_low,
            "entry": current["close"],
            "sl": swing_low,
            "tp": current["close"] + (current["close"] - swing_low),
        }

    return None

def build_message(symbol, timeframe, signal):
    tf_label = {
        "10": "10min",
        "15": "15min",
        "60": "1Hour"
    }.get(timeframe, timeframe)

    entry = signal["entry"]
    sl    = signal["sl"]
    tp    = signal["tp"]
    risk  = abs(entry - sl)
    rr    = round(abs(tp - entry) / risk, 2) if risk > 0 else 0

    signal_type = (
        "🚀 BREAKOUT ABOVE B"
        if signal["type"] == "BREAKER_BLOCK_BREAKOUT"
        else "📦 BREAKER BLOCK FORMED"
    )

    name = symbol.split(":")[1].replace("-EQ", "").replace("-INDEX", "")

    return (
        f"🟢 BULLISH BREAKER BLOCK\n"
        f"---------------\n"
        f"Symbol  : {name}\n"
        f"TF      : {tf_label}\n"
        f"Signal  : {signal_type}\n"
        f"Time    : {get_timestamp()}\n"
        f"---------------\n"
        f"Point B : {signal['point_b']}\n"
        f"Point A : {signal['point_a']}\n"
        f"---------------\n"
        f"Entry   : {entry}\n"
        f"SL      : {sl}\n"
        f"TP      : {tp}\n"
        f"RR      : 1:{rr}\n"
        f"---------------\n"
        f"Action  : BUY NOW!"
    )

def scan_all(last_signal_time):
    all_symbols = INDICES + FNO_STOCKS

    for symbol in all_symbols:
        for tf in TIMEFRAMES:
            key = f"{symbol}_{tf}"
            try:
                candles = get_candles(symbol, tf)
                signal  = detect_breaker_block(candles)

                if signal:
                    current_time = time.time()
                    if current_time - last_signal_time.get(key, 0) > 3600:
                        msg = build_message(symbol, tf, signal)
                        send_message(msg)
                        last_signal_time[key] = current_time

            except Exception as e:
                pass  # Silent fail for individual symbols

            time.sleep(1)  # Rate limit

    return last_signal_time

def main():
    send_message(
        "🟢 Breaker Block Bot Running!\n"
        "---------------\n"
        "Indices : Nifty BankNifty\n"
        "          FinNifty MidCap\n"
        "          Sensex\n"
        "FNO     : 50+ Stocks\n"
        "---------------\n"
        "TF      : 10m 15m 1h\n"
        "Setup   : Bullish Breaker\n"
        "Alert   : Close above B\n"
        "Hours   : 9:15AM-3:30PM IST"
    )

    last_signal_time = {}
    market_was_open  = False

    while True:
        if not is_market_open():
            ist = get_ist_time()
            if market_was_open:
                send_message(
                    "Market Closed!\nResume Monday 9:15AM IST"
                    if ist.weekday() == 4
                    else "Market Closed!\nResume Tomorrow 9:15AM IST"
                )
                market_was_open = False
            time.sleep(60)
            continue

        if not market_was_open:
            send_message(
                "🔔 Market Open!\n"
                "Breaker Block Bot Scanning..."
            )
            market_was_open = True

        last_signal_time = scan_all(last_signal_time)
        time.sleep(300)  # Scan every 5 minutes

if __name__ == "__main__":
    main()
