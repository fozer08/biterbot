import sys
import os
from datetime import datetime, timezone

import pandas as pd

# Repo kökünü PYTHONPATH'e ekle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from biterbot.clients import BinancePublicClient


def ms_to_dt(ms: int):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)

if __name__ == '__main__':
    client = BinancePublicClient()

    # --- server time ---
    server_ms = client.get_server_time()
    assert isinstance(server_ms, int)
    # UTC now'dan çok ileri-geri olmasın (+-60sn)
    system_ms = datetime.now(timezone.utc).timestamp() * 1000
    assert abs(system_ms - server_ms) < 60 * 1000
    print("Sunucu saati OK.")

    # --- fetch completed candles ---
    df_completed = client.fetch_ohlcv("BTCUSDT", "1m", limit=120, last_candle_completed=True)
    assert isinstance(df_completed, pd.DataFrame) and not df_completed.empty
    required_cols = {"open_time","open","high","low","close","volume","close_time"}
    assert required_cols.issubset(df_completed.columns)

    # zaman monoton artmalı
    assert (df_completed["open_time"].values < df_completed["close_time"].values).all()
    assert (df_completed["open_time"].values[1:] >= df_completed["open_time"].values[:-1]).all()
    assert (df_completed["close_time"].values[1:] >= df_completed["close_time"].values[:-1]).all()

    # her satır ~1 dakikalık olmalı (esnek tolerans)
    durations = df_completed["close_time"] - df_completed["open_time"]
    assert (durations >= 59_000).all() and (durations <= 60_000).all()

    assert (df_completed["high"] >= df_completed["low"]).all()
    assert (df_completed["high"] >= df_completed["open"]).all()
    assert (df_completed["high"] >= df_completed["close"]).all()
    assert (df_completed["low"] <= df_completed["open"]).all()
    assert (df_completed["low"] <= df_completed["close"]).all()

    print("OHLCV OK.")

    # son kapanış makul şekilde "geçmişte" olmalı (server'a göre)
    last_close_ms = int(df_completed.iloc[-1]["close_time"])
    # Binance close_time genelde periyod sonunu (çoğunlukla -1ms) gösterir.
    # Burada 1dk tolerans bırakıyoruz.
    assert 0 <= server_ms - last_close_ms <= 60_000

    last_close = ms_to_dt(last_close_ms)
    last_open = ms_to_dt(int(df_completed.iloc[-1]["open_time"]))
    print(f"Last open: {last_open}, last close: {last_close}") 
    print("Kapanış mumu OK.")

    