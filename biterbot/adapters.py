from typing import Any

import pandas as pd

from .helpers import Topics
from .eventbus import EventBus
from .signals import SignalGenerator


class SignalAdaptor:
    """
    EventBus <-> SignalGenerator köprüsü.

    Args:
        bus: EventBus örneği.
        signalgen: Strateji örneği.
    """

    def __init__(self, bus: EventBus, signalgen: SignalGenerator):
        self.bus = bus
        self.signalgen = signalgen

    def bind(self):
        """
        Stratejinin OHLCV topic'ine abone ol.
        """
        topic = Topics.ohlcv(self.signalgen.symbol, self.signalgen.interval)
        self.bus.subscribe(topic, self._handle_df)

    def unbind(self):
        """
        Aboneliği kaldır.
        """
        self.bus.unsubscribe(
            Topics.ohlcv(self.signalgen.symbol, self.signalgen.interval),
            self._handle_df,
        )

    async def _handle_df(self, df: pd.DataFrame, msg_id: int):
        """
        OHLCV geldiğinde stratejiyi çalıştır ve sinyali yayınla.

        Args:
            df: OHLCV DataFrame.
            msg_id: Bu OHLCV yayınının kimliği (çoğunlukla close_time).
        """
        try:
            trade_signal = await self.signalgen.check(df)
        except Exception as e:
            print(f"[SignalAdaptor] check error {self.signalgen.name}: {e}")
            return
        
        if trade_signal:
            payload: dict[str, Any] = {
                "name": self.signalgen.name,
                "symbol": self.signalgen.symbol,
                "interval": self.signalgen.interval,
                "trade_signal": trade_signal,
                "close_time": int(df.iloc[-1].get("close_time", 0)),
            }
            try:
                await self.bus.publish(
                    Topics.signal(self.signalgen.symbol, self.signalgen.interval),
                    payload,
                    msg_id=msg_id,
                    dedupe=True,
                )
            except Exception as e:
                print(f"[SignalAdaptor] publish error {self.signalgen.name}: {e}")
