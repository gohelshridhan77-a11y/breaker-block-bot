import time
import os
import requests
from datetime import datetime, timezone, timedelta
from fyers_apiv3 import fyersModel
from token_manager import get_access_token

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID         = os.environ.get("CHAT_ID")
FYERS_CLIENT_ID = os.environ.get("FYERS_CLIENT_ID")

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
    "NSE:TATACONSUM-EQ", "NSE:UPL-EQ", "NSE:PIDILITIND-EQ",
    "NSE:SIEMENS-EQ", "NSE:HAVELLS-EQ", "NSE:VOLTAS-EQ",
    "NSE:MUTHOOTFIN-EQ", "NSE:CHOLAFIN-EQ",
]

TIMEFRAMES = ["10", "15", "60"]

ACCESS_TOKEN = None

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
    market_open  = ist.replace(hour=9,  minute=15, second=0)
    market_close = ist.replace(hour=15, minute=30, second=0)
    return market_open <= ist <= market_close

def get_timestamp():
    ist = get_ist_time()
    return ist.strftime("%Y-%m-%d %H:%M IST")

def get_fyers():
    return fyersModel.FyersModel(
        client_id=FYERS_CLIENT_ID,
        token=ACCESS_TOKEN,
        log_path=""
    )

def get_candles(symbol, timeframe):
    fyers = get_fyers()
    today = datetime.now()
    data = {
        "symbol": symbol,
        "resolution": timeframe,
        "date_format": "1",
        "range_from": (today - timedelta(days=5)).strftime("%Y-%m-%d"),
        "range_to": today.strftime("%Y-%m-%d"),
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
    return candles[-20:]

def detect_breaker_block(candles):
    if len(candles) < 10:
        return None

    lookback = candles[-15:]

    # Find swing high (Point B)
    swing_high = 0
    swing_high_idx = 0
    for i in range(2, len(lookback) - 2):
        if (lookback[i]["high"] > lookback[i-1]["high"] and
            lookback[i]["high"] > lookback[i-2]["high"] and
            lookback[i]["high"] > lookback[i+1]["high"] and
            lookback[i]["high"] > lookback[i+2]["high"]):
            if lookback[i]["high"] > swing_high:
                swing_high = lookback[i]["high"]
                swing_high_idx = i

    if swing_high == 0:
        return None

    # Find swing low before B (Point A)
    pre_b = lookback[:swing_high_idx]
    if len(pre_b) < 2:
        return None

    swing_low = min(c["low"] for c in pre_b)

    # Check SSL swept (price went below A after B)
    post_b = lookback[swing_high_idx+1:]
    if not post_b:
        return None

    ssl_swept = any(c["low"] < swing_low for c in post_b)
    if not ssl_swept:
        return None

    # Check current candle closes above B
    current = candles[-1]
    prev    = candles[-2]

    if current["close"] > swing_high and prev["close"] <= swing_high:
        sl = swing_low
        tp = current["close"] + (current["close"] - swing_low)
        rr = round(abs(tp - current["close"]) / abs(current["close"] - sl), 2)
        return {
            "type": "BREAKOUT",
            "point_b": round(swing_high, 2),
            "point_a": round(swing_low, 2),
            "entry":   round(current["close"], 2),
            "sl":      round(sl, 2),
            "tp":      round(tp, 2),
            "rr":      rr,
        }

    return None

def build_message(symbol, timeframe, signal):
    tf_label = {
        "10": "10min",
        "15": "15min",
        "60": "1Hour"
    }.get(timeframe, timeframe)

    name = symbol.split(":")[1]
    name = name.replace("-EQ", "").replace("-INDEX", "")

    return (
        f"🟢 BULLISH BREAKER BLOCK\n"
        f"---------------\n"
        f"Symbol : {name}\n"
        f"TF     : {tf_label}\n"
        f"Time   : {get_timestamp()}\n"
        f"---------------\n"
        f"Signal : Close above Point B!\n"
        f"Point B: {signal['point_b']}\n"
        f"Point A: {signal['point_a']}\n"
        f"---------------\n"
        f"Entry  : {signal['entry']}\n"
        f"SL     : {signal['sl']}\n"
        f"TP     : {signal['tp']}\n"
        f"RR     : 1:{signal['rr']}\n"
        f"---------------\n"
        f"Action : BUY NOW! 🚀"
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
                        send_message(build_message(symbol, tf, signal))
                        last_signal_time[key] = current_time
            except Exception:
                pass
            time.sleep(1)
    return last_signal_time

def main():
    global ACCESS_TOKEN
    try:
        ACCESS_TOKEN = get_access_token()
        send_message(
            "🟢 Breaker Block Bot Running!\n"
            "---------------\n"
            "Indices: Nifty BankNifty\n"
            "         FinNifty MidCap\n"
            "         Sensex\n"
            "Stocks : 55+ FNO Stocks\n"
            "---------------\n"
            "TF     : 10m 15m 1h\n"
            "Setup  : Bullish Breaker Block\n"
            "Alert  : Close above Point B\n"
            "Hours  : 9:15AM-3:30PM IST"
        )
    except Exception as e:
        send_message(f"Token error: {str(e)}")
        return

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
            send_message("🔔 Market Open!\nBreaker Block Bot Scanning...")
            market_was_open = True

        last_signal_time = scan_all(last_signal_time)
        time.sleep(300)

if __name__ == "__main__":
    main()
