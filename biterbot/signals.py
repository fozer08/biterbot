from abc import ABC, abstractmethod
from typing import Optional, TypedDict, Literal
import pandas as pd
import numpy as np
import ta

from .clients import PublicClient


SignalDirection = Optional[Literal["UP", "DOWN"]]

class Signal(TypedDict, total=False):
    # Zorunlu alanlar
    name: str
    symbol: str
    interval: str
    direction: SignalDirection      # "UP" | "DOWN" | None
    strength: float                 # anlamlılık metriği (örn. ratio - threshold)
    at: int                         # close_time
    price: float                    # close_price


class SignalGenerator(ABC):
    """
    Gösterge katmanı: check(df) bir 'signal' (dict) döndürür ya da None.
    """

    def __init__(self, name: str, symbol: str, interval: str):
        self.name = name
        self.symbol = symbol
        self.interval = interval

    @abstractmethod
    async def check(
        self,
        df: pd.DataFrame = None,
        client: PublicClient = None
    ) -> Optional[Signal]:
        """
        Args:
            df: OHLCV DataFrame; verilmezse client ile çekilebilir.
            client: df yoksa kullanılacak erişimci.
        Return:
            Optional[Signal]: Gösterge sinyali veya None.
        """
        ...


class EMACrossSignalGen(SignalGenerator):
    """Kısa/uzun EMA kesişimini 'direction' ve 'strength' ile bildirir."""

    def __init__(
        self,
        name: str, symbol: str, interval: str,
        *,
        ema_short_window: int = 7,
        ema_long_window: int = 25,
    ):
        super().__init__(name, symbol, interval)
        self.ema_short_window = ema_short_window
        self.ema_long_window = ema_long_window

    async def check(self, df: pd.DataFrame = None, client: PublicClient = None) -> Optional[Signal]:
        need = max(self.ema_short_window, self.ema_long_window) + 2

        # df yoksa client'tan çek
        if df is None:
            if client is None:
                return None
            try:
                df = client.fetch_ohlcv(
                    symbol=self.symbol,
                    interval=self.interval,
                    limit=need,
                    last_candle_completed=True,
                )
            except Exception:
                return None

        if df is None or df.empty or len(df) < need:
            return None

        df = df.copy()
        df["ema_short"] = ta.trend.ema_indicator(df["close"], window=self.ema_short_window)
        df["ema_long"]  = ta.trend.ema_indicator(df["close"], window=self.ema_long_window)

        last, prev = df.iloc[-1], df.iloc[-2]
        if pd.isna(last["ema_long"]) or pd.isna(prev["ema_long"]):
            return None

        crossed_up = prev["ema_short"] < prev["ema_long"] and last["ema_short"] > last["ema_long"]
        crossed_dn = prev["ema_short"] > prev["ema_long"] and last["ema_short"] < last["ema_long"]
        if not (crossed_up or crossed_dn):
            return None

        direction: SignalDirection = "UP" if crossed_up else "DOWN"
        base = max(abs(last["ema_long"]), 1e-12)
        strength = (last["ema_short"] - last["ema_long"]) / base  # normalize fark
        close_time = int(last.get("close_time", 0))
        price = float(last.get("close", np.nan))

        return {
            "name": self.name,
            "symbol": self.symbol,
            "interval": self.interval,
            "direction": direction,
            "strength": float(strength),
            "at": close_time,
            "price": price,
        }


class TrendSignalGen(SignalGenerator):
    """
    EMA kesişimi + volatilite breakout + hysteresis ile teyit.
    - Kesişim (UP/DOWN) son 'confirm_bars' içinde en az bir kez oluşmuş olmalı
    - Aynı pencerede (TR_fast_EWM / ATR_slow) > ratio_th görülmeli
    - Son bar'da normalize EMA farkı >= hysteresis_th olmalı
    Çıktı: direction="UP"/"DOWN", strength=(ratio - ratio_th) [son bar]
    """

    def __init__(
        self,
        name: str, symbol: str, interval: str,
        *,
        ema_short_window: int = 7,
        ema_long_window: int = 25,
        atr_window: int = 14,
        tr_fast_window: int = 3,
        ratio_th: float = 1.0,
        hysteresis_th: float = 0.002,
        confirm_bars: int = 3,
    ):
        super().__init__(name, symbol, interval)
        self.ema_short_window = ema_short_window
        self.ema_long_window = ema_long_window
        self.atr_window = atr_window
        self.tr_fast_window = tr_fast_window
        self.ratio_th = ratio_th
        self.hysteresis_th = hysteresis_th
        self.confirm_bars = confirm_bars
    
    async def check(
        self, 
        df: pd.DataFrame = None, 
        client: PublicClient = None
    ) -> Optional[Signal]:
        base_need = max(
            self.ema_short_window,
            self.ema_long_window,
            self.atr_window,
            self.tr_fast_window,
        )
        need = base_need + self.confirm_bars + 2

        # df yoksa client'tan çek
        if df is None:
            if client is None:
                return None
            try:
                df = client.fetch_ohlcv(
                    symbol=self.symbol,
                    interval=self.interval,
                    limit=need,
                    last_candle_completed=True,
                )
            except Exception:
                return None

        if df is None or df.empty or len(df) < need:
            return None

        df = df.copy()

        # EMA'lar
        df["ema_short"] = ta.trend.ema_indicator(df["close"], window=self.ema_short_window)
        df["ema_long"]  = ta.trend.ema_indicator(df["close"], window=self.ema_long_window)

        # Slow volatilite seviyesi: ATR
        df["atr_slow"] = ta.volatility.average_true_range(
            high=df["high"], low=df["low"], close=df["close"], window=self.atr_window
        )

        # True Range (TR) — gap'ler dahil
        prev_close = df["close"].shift(1)
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - prev_close).abs()
        tr3 = (df["low"]  - prev_close).abs()
        df["tr"] = np.maximum.reduce([tr1, tr2, tr3])

        # Hızlı volatilite: TR üzerinde EWM (son barlara ağırlık verir)
        df["tr_fast"] = df["tr"].ewm(
            span=self.tr_fast_window, adjust=False, min_periods=self.tr_fast_window
        ).mean()

        # Pencere içinde "kesişim oldu mu?" ve "ratio eşiği aşıldı mı?" durumunu izleyelim
        cross: Optional[str] = None   # "UP" | "DOWN"
        vola_ok = False

        for i in range(-self.confirm_bars - 1, 0):
            curr = df.iloc[i]
            prev = df.iloc[i - 1]

            up = prev["ema_short"] < prev["ema_long"] and curr["ema_short"] > curr["ema_long"]
            dn = prev["ema_short"] > prev["ema_long"] and curr["ema_short"] < curr["ema_long"]
            if up:
                cross = "UP"
                vola_ok = False  # kesişim sonrası volatilite şartını yeniden ara
            elif dn:
                cross = "DOWN"
                vola_ok = False

            r = curr["tr_fast"] / curr["atr_slow"]
            if r > self.ratio_th:
                vola_ok = True

            if cross and vola_ok:
                hysteresis = (curr["ema_short"] - curr["ema_long"]) / curr["ema_long"]
                if abs(hysteresis) >= self.hysteresis_th:
                    if i == -1:
                        close_time = int(curr.get("close_time", 0))
                        price = float(curr.get("close", np.nan))
                        strength = float(r - self.ratio_th)
                        return {
                            "name": self.name,
                            "symbol": self.symbol,
                            "interval": self.interval,
                            "direction": "UP" if cross == "UP" else "DOWN",
                            "strength": strength,
                            "at": close_time,
                            "price": price,
                        }
                    else:
                        break
    
        return None
