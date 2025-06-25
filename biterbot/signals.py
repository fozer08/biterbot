import ta

from .signal_base import SignalBase


class EMACrossSignal(SignalBase):
    interval = "15m"
    # buffer_seconds uses default

    async def check(self) -> tuple:
        df = self.public_client.fetch_ohlcv(self.symbol, self.interval, limit=200)
        df['ema_short'] = ta.trend.ema_indicator(df['close'], window=9)
        df['ema_long'] = ta.trend.ema_indicator(df['close'], window=21)
        last = df.iloc[-1]
        prev = df.iloc[-2]
        candle = last[['open_time','open','high','low','close','volume','close_time']].to_dict()

        signal = None
        if prev['ema_short'] < prev['ema_long'] and last['ema_short'] > last['ema_long']:
            signal = self.SIGNAL_LONG
        elif prev['ema_short'] > prev['ema_long'] and last['ema_short'] < last['ema_long']:
            signal = self.SIGNAL_SHORT
        
        return signal, candle


class TrendSignal(SignalBase):
    interval = "15m"
    # Hysteresis threshold for EMA difference (% of long EMA)
    hysteresis_threshold: float = 0.002  # 0.2%
    # ATR period
    atr_window: int = 14
    # EMA windows
    ema_short_window: int = 9
    ema_long_window: int = 21

    async def check(self) -> tuple:
        # Fetch recent OHLCV data
        df = self.public_client.fetch_ohlcv(self.symbol, self.interval, limit=200)

        # EMA indicators
        df['ema_short'] = ta.trend.ema_indicator(df['close'], window=self.ema_short_window)
        df['ema_long'] = ta.trend.ema_indicator(df['close'], window=self.ema_long_window)

        # ATR indicator
        df['atr'] = ta.volatility.average_true_range(
            high=df['high'], low=df['low'], close=df['close'], window=self.atr_window
        )
        # Compute average ATR as threshold
        atr_threshold = df['atr'].rolling(window=self.atr_window).mean().iloc[-1]

        # Get last and previous rows
        last = df.iloc[-1]
        prev = df.iloc[-2]
        candle = last[['open_time','open','high','low','close','volume','close_time']].to_dict()

        # Cross conditions
        long_cross = prev['ema_short'] < prev['ema_long'] and last['ema_short'] > last['ema_long']
        short_cross = prev['ema_short'] > prev['ema_long'] and last['ema_short'] < last['ema_long']
        
        # Hysteresis: EMA difference relative to long EMA
        diff = (last['ema_short'] - last['ema_long']) / last['ema_long']
        hysteresis_ok = abs(diff) >= self.hysteresis_threshold

        # ATR filter: require sufficient volatility
        atr_ok = last['atr'] > atr_threshold

        # Generate signals with all filters
        signal = None
        if long_cross and hysteresis_ok and atr_ok:
            signal = self.SIGNAL_LONG
        elif short_cross and hysteresis_ok and atr_ok:
            signal = self.SIGNAL_SHORT

        return signal, candle
