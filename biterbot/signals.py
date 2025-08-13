from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd
import numpy as np
import ta

from .clients import PublicClient


class SignalGenerator(ABC):
    """
    Strateji temel sınıfı; `check(df)` sinyal üretir veya None döner.

    Args:
        client: Veri kaynağı.
        name: Strateji adı.
        symbol: Enstrüman sembolü.
        interval: Periyot.
    """
    
    LONG = "LONG"
    SHORT = "SHORT"
    EXIT = "EXIT"

    def __init__(self, client: PublicClient, name: str, symbol: str, interval: str):
        self.client = client
        self.name = name
        self.symbol = symbol
        self.interval = interval

    @abstractmethod
    async def check(self, df: pd.DataFrame) -> Optional[str]:
        """
        Verilen df üzerinde sinyal hesapla.

        Args:
            df: OHLCV DataFrame.
        Return:
            Optional[str]: Sinyal (LONG/SHORT/EXIT) veya None.
        """
        ...


class TestSignalGen(SignalGenerator):

    def __init__(
        self,
        client,
        name, symbol, interval,
    ):
        super().__init__(client, name, symbol, interval)

    async def check(self, df: pd.DataFrame) -> Optional[str]:
        """
        Args:
            df: OHLCV DataFrame.
        Return:
            Optional[str]: LONG/SHORT veya None.
        """
        if df.empty:
            return None
        
        print("1")
        return self.LONG


class EMACrossSignalGen(SignalGenerator):
    """Kısa/uzun EMA kesişimine dayalı sinyal üretimi."""

    def __init__(
        self,
        client,
        name, symbol, interval,
        *,
        ema_short_window=7, ema_long_window=25,
    ):
        super().__init__(client, name, symbol, interval)
        self.ema_short_window = ema_short_window
        self.ema_long_window = ema_long_window

    async def check(self, df: pd.DataFrame) -> Optional[str]:
        """
        Args:
            df: OHLCV DataFrame.
        Return:
            Optional[str]: LONG/SHORT veya None.
        """
        if df.empty:
            return None
        
        need = max(self.ema_short_window, self.ema_long_window) + 2
        if len(df) < need:
            return None
        
        df['ema_short'] = ta.trend.ema_indicator(df['close'], window=self.ema_short_window)
        df['ema_long'] = ta.trend.ema_indicator(df['close'], window=self.ema_long_window)
        last, prev = df.iloc[-1], df.iloc[-2]
        
        if pd.isna(last['ema_long']) or pd.isna(prev['ema_long']):
            return None
        
        crossed_up = prev['ema_short'] < prev['ema_long'] and last['ema_short'] > last['ema_long']
        crossed_dn = prev['ema_short'] > prev['ema_long'] and last['ema_short'] < last['ema_long']
        
        if crossed_up:
            return self.LONG
        if crossed_dn:
            return self.SHORT
        
        return None


class TrendSignalGen(SignalGenerator):
    """EMA + (TR fast EWM / ATR slow) oranı ile teyit edilen trend sinyali."""

    def __init__(
        self,
        client,
        name, symbol, interval,
        *,
        ema_short_window=7, ema_long_window=25,
        atr_window=14, tr_fast_window=3, ratio_th=1.2,
        hysteresis_threshold=0.002,
        confirmation_bars=5
    ):
        super().__init__(client, name, symbol, interval)
        self.ema_short_window = ema_short_window
        self.ema_long_window = ema_long_window
        self.atr_window = atr_window
        self.tr_fast_window = tr_fast_window
        self.ratio_th = ratio_th
        self.hysteresis_threshold = hysteresis_threshold
        self.confirmation_bars = confirmation_bars

    async def check(self, df: pd.DataFrame) -> Optional[str]:
        """
        Args:
            df: OHLCV DataFrame.
        Return:
            Optional[str]: LONG/SHORT veya None.
        """
        if df.empty:
            return None

        # Yeterli veri kontrolü
        need = max(self.ema_short_window, self.ema_long_window, self.atr_window, self.tr_fast_window)
        if len(df) < need + self.confirmation_bars + 2:
            return None

        df = df.copy()

        # EMA'lar
        df['ema_short'] = ta.trend.ema_indicator(df['close'], window=self.ema_short_window)
        df['ema_long']  = ta.trend.ema_indicator(df['close'], window=self.ema_long_window)

        # Slow volatilite seviyesi: ATR (Wilder/RMA tabanlı; ta kütüphanesi uygular)
        df['atr_slow'] = ta.volatility.average_true_range(
            high=df['high'], low=df['low'], close=df['close'], window=self.atr_window
        )

        # True Range (TR)
        prev_close = df['close'].shift(1)
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low']  - prev_close).abs()
        df['tr'] = np.maximum.reduce([tr1, tr2, tr3])

        # Hızlı volatilite: TR üzerinde EWM (son mumlara ağırlık verir; lag düşük)
        df['tr_fast'] = df['tr'].ewm(span=self.tr_fast_window, adjust=False, min_periods=self.tr_fast_window).mean()

        # Oran: son mum etkisi / normal volatilite seviyesi
        ratio = (df['tr_fast'] / (df['atr_slow'] + 1e-12)).replace([np.inf, -np.inf], np.nan)

        # Sinyal arama: EMA kesişimi + volatilite breakout + hysteresis
        trade_signal = None
        cross = None
        atr_ok = False

        for i in range(-self.confirmation_bars - 1, 0):
            curr = df.iloc[i]
            prev = df.iloc[i - 1]

            # EMA kesişimleri
            up = prev['ema_short'] < prev['ema_long'] and curr['ema_short'] > curr['ema_long']
            dn = prev['ema_short'] > prev['ema_long'] and curr['ema_short'] < curr['ema_long']
            if up:
                cross = "UP"
                atr_ok = False
            elif dn:
                cross = "DN"
                atr_ok = False

            # Volatilite breakout: son mum odaklı TR hızlısı, ATR'e göre anlamlı yüksek mi?
            r = ratio.iloc[i]
            if pd.notna(r) and r > self.ratio_th:
                atr_ok = True

            # Hysteresis ile teyit (EMA farkı yeterince açılmış mı?)
            if cross and atr_ok:
                base = max(abs(curr['ema_long']), 1e-12)
                diff = (curr['ema_short'] - curr['ema_long']) / base
                if abs(diff) >= self.hysteresis_threshold:
                    if i == -1:
                        trade_signal = self.LONG if cross == "UP" else self.SHORT
                    break

        return trade_signal

