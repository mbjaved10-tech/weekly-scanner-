import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, timedelta

st.set_page_config(page_title="PSX Weekly Swing Scanner", page_icon="📈", layout="wide")
st.title("📈 PSX Weekly Swing Scanner")
st.caption("Weekly swing signals from PSX daily OHLCV data. Signals are evaluated only on completed weekly candles.")

with st.sidebar:
    st.header("Scanner settings")
    universe = st.selectbox("Stock universe", ["All PSX symbols", "KSE-100", "Custom symbols"])
    custom = st.text_area("Custom symbols (comma separated)", "SYS, LUCK, GAL, FFC, OGDC, PPL, MARI, HUBC")
    history_years = st.slider("History to download (years)", 2, 10, 5)
    include_watch = st.checkbox("Show WATCH signals", True)
    include_sell = st.checkbox("Show SELL signals", True)
    run = st.button("🔎 Scan PSX now", type="primary", use_container_width=True)

st.info("Data source: free `psxdata` Python library (public PSX website data; no API key). Historical intraday candles are not used.")

def get_symbols(mode, custom_text):
    import psxdata
    if mode == "Custom symbols":
        return sorted(set(x.strip().upper() for x in custom_text.split(",") if x.strip()))
    if mode == "KSE-100":
        raw = psxdata.indices("KSE100")
        if isinstance(raw, pd.DataFrame):
            col = next((c for c in raw.columns if str(c).lower() in ("symbol","ticker","scrip")), raw.columns[0])
            vals = raw[col].astype(str).tolist()
        else:
            vals = list(raw)
    else:
        raw = psxdata.tickers()
        if isinstance(raw, pd.DataFrame):
            col = next((c for c in raw.columns if str(c).lower() in ("symbol","ticker","scrip")), raw.columns[0])
            vals = raw[col].astype(str).tolist()
        else:
            vals = list(raw)
    cleaned = []
    for x in vals:
        s = str(x).strip().upper()
        if s and s not in ("NAN","NONE") and len(s) <= 20:
            cleaned.append(s)
    return sorted(set(cleaned))

def normalize(df):
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d.columns = [str(c).lower().strip() for c in d.columns]
    if "date" not in d.columns:
        for c in ("trading_date","datetime"):
            if c in d.columns:
                d = d.rename(columns={c:"date"})
                break
    required = ["date","open","high","low","close","volume"]
    if not all(c in d.columns for c in required):
        return pd.DataFrame()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    for c in required[1:]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=required).sort_values("date").drop_duplicates("date")
    return d.set_index("date")

def indicators(d):
    d = d.copy()
    d["ema20"] = d.close.ewm(span=20, adjust=False).mean()
    d["ema50"] = d.close.ewm(span=50, adjust=False).mean()
    delta = d.close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    d["rsi"] = 100 - (100 / (1 + rs))
    fast = d.close.ewm(span=12, adjust=False).mean()
    slow = d.close.ewm(span=26, adjust=False).mean()
    d["macd"] = fast - slow
    d["macd_signal"] = d.macd.ewm(span=9, adjust=False).mean()
    d["macd_hist"] = d.macd - d.macd_signal
    d["vol_avg20"] = d.volume.rolling(20).mean()
    tr = pd.concat([(d.high-d.low), (d.high-d.close.shift()).abs(), (d.low-d.close.shift()).abs()], axis=1).max(axis=1)
    d["atr14"] = tr.rolling(14).mean()
    d["prior_high5"] = d.high.shift(1).rolling(5).max()
    d["prior_low5"] = d.low.shift(1).rolling(5).min()
    return d

def scan_one(symbol, start):
    import psxdata
    raw = psxdata.stocks(symbol, start=start.isoformat())
    daily = normalize(raw)
    if len(daily) < 80:
        return None
    # Keep daily data for entry confirmation; weekly calculations use completed Friday-ending weeks only.
    daily_ind = indicators(daily)
    weekly = daily.resample("W-FRI").agg({
        "open":"first", "high":"max", "low":"min", "close":"last", "volume":"sum"
    }).dropna()
    # Drop current week if it has not ended yet (Pakistan market time).
    today = pd.Timestamp(date.today())
    if len(weekly) and weekly.index[-1].date() > today.date():
        weekly = weekly.iloc[:-1]
    elif len(weekly) and today.weekday() < 4 and weekly.index[-1].date() >= today.date():
        weekly = weekly.iloc[:-1]
    w = indicators(weekly)
    if len(w) < 55:
        return None
    x, p = w.iloc[-1], w.iloc[-2]
    if pd.isna(x.ema50) or pd.isna(x.rsi) or pd.isna(x.atr14):
        return None
    trend = "Bullish" if x.close > x.ema20 > x.ema50 else ("Bearish" if x.close < x.ema20 < x.ema50 else "Mixed")
    macd_bull = x.macd > x.macd_signal
    macd_cross_up = p.macd <= p.macd_signal and macd_bull
    macd_cross_down = p.macd >= p.macd_signal and x.macd < x.macd_signal
    vol_ok = pd.notna(x.vol_avg20) and x.volume > x.vol_avg20
    breakout = pd.notna(x.prior_high5) and x.close > x.prior_high5
    strong = x.close > x.ema20 > x.ema50 and 50 <= x.rsi <= 70 and macd_bull and vol_ok and breakout
    buy = x.close > x.ema20 and x.ema20 > x.ema50 and x.rsi > 50 and macd_bull
    watch = (x.close >= x.ema20 * 0.98 and x.rsi >= 45 and macd_bull) or macd_cross_up
    sell = x.close < x.ema20 or (macd_cross_down and x.rsi < 50) or x.rsi < 40
    signal = "STRONG BUY" if strong else ("BUY" if buy else ("SELL" if sell else ("WATCH" if watch else "NO SIGNAL")))
    entry = float(x.close)
    # Recent 5 completed weekly lows are used as structural support; ATR is fallback.
    swing_low = float(w.low.tail(5).min())
    stop = swing_low if swing_low < entry else entry - 1.5 * float(x.atr14)
    if entry - stop <= 0:
        stop = entry - 1.5 * float(x.atr14)
    risk = entry - stop
    # Daily confirmation: last completed daily close above its EMA20 and RSI > 50.
    dd = daily_ind.dropna(subset=["ema20","rsi"])
    daily_ok = bool(len(dd) and dd.close.iloc[-1] > dd.ema20.iloc[-1] and dd.rsi.iloc[-1] > 50)
    return {
        "Symbol":symbol, "Signal":signal, "Weekly Date":w.index[-1].date(),
        "Weekly Close":round(entry,2), "Entry":round(entry,2),
        "Stop Loss":round(stop,2), "Target 1 (2R)":round(entry+2*risk,2),
        "Target 2 (3R)":round(entry+3*risk,2), "RSI":round(float(x.rsi),1),
        "MACD": "Bullish" if macd_bull else "Bearish",
        "Volume": "Above avg" if vol_ok else "Below avg",
        "Trend":trend, "Breakout": "Yes" if breakout else "No",
        "Daily Confirm": "Yes" if daily_ok else "No"
    }

if run:
    with st.spinner("Loading PSX symbols and scanning historical prices. The first full-market scan may take several minutes."):
        try:
            symbols = get_symbols(universe, custom)
            start = date.today() - timedelta(days=365*history_years)
            rows, errors = [], []
            progress = st.progress(0)
            status = st.empty()
            for i, sym in enumerate(symbols):
                try:
                    result = scan_one(sym, start)
                    if result:
                        rows.append(result)
                except Exception as e:
                    errors.append(f"{sym}: {str(e)[:120]}")
                if (i+1) % 5 == 0 or i+1 == len(symbols):
                    progress.progress((i+1)/max(len(symbols),1))
                    status.write(f"Scanned {i+1}/{len(symbols)} symbols • signals found: {len(rows)}")
            st.session_state["scan_rows"] = rows
            st.session_state["scan_errors"] = errors
            st.session_state["scan_universe"] = universe
        except Exception as e:
            st.error(f"Could not start scanner: {e}")
            st.stop()

if "scan_rows" in st.session_state:
    df = pd.DataFrame(st.session_state["scan_rows"])
    if df.empty:
        st.warning("No valid symbols returned. Check the data source or try Custom symbols.")
    else:
        order = {"STRONG BUY":0,"BUY":1,"WATCH":2,"SELL":3,"NO SIGNAL":4}
        df["_rank"] = df.Signal.map(order).fillna(5)
        df = df.sort_values(["_rank","RSI"], ascending=[True,False]).drop(columns="_rank")
        choices = ["STRONG BUY","BUY"]
        if include_watch: choices.append("WATCH")
        if include_sell: choices.append("SELL")
        choices.append("NO SIGNAL")
        selected = st.multiselect("Show signals", choices, default=["STRONG BUY","BUY","WATCH"])
        shown = df[df.Signal.isin(selected)]
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Symbols scanned", len(df))
        c2.metric("Strong Buy", int((df.Signal=="STRONG BUY").sum()))
        c3.metric("Buy", int((df.Signal=="BUY").sum()))
        c4.metric("Watch", int((df.Signal=="WATCH").sum()))
        st.subheader("Weekly scan results")
        st.dataframe(shown, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Download results CSV", shown.to_csv(index=False).encode("utf-8"), "psx_weekly_swing_signals.csv", "text/csv")
        st.caption(f"Universe: {st.session_state.get('scan_universe','')} • Last scan: {date.today()}")
    errs = st.session_state.get("scan_errors", [])
    if errs:
        with st.expander(f"Symbols skipped / data errors ({len(errs)})"):
            st.write("\n".join(errs[:100]))

st.warning("Important: this is a screening tool, not a guaranteed trading signal. Weekly signals use completed weekly candles; verify liquidity, corporate actions and the latest price before placing a trade. The data library is independent of PSX and may occasionally fail or change.")
