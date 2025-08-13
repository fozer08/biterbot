from typing import Any, Dict, List, Iterable, Callable
import pandas as pd

from .helpers import Topics
from .eventbus import EventBus
from .signals import SignalGenerator


class SignalAdaptor:
    """
    EventBus <-> SignalGenerator köprüsü.

    - Birden fazla SignalGenerator kabul eder.
    - Her (symbol, interval) için OHLCV topic'ine abone olur.
    - O topic geldiğinde, o topic'e bağlı TÜM generator'ları çalıştırır.
    - Generator'dan dönen signal dict'lerini `signal:{symbol}_{interval}` kanalına publish eder.
    """

    def __init__(self, bus: EventBus, *signalgens: SignalGenerator):
        self.bus = bus
        # Varargs veya tek bir iterable desteği
        if len(signalgens) == 1 and isinstance(signalgens[0], (list, tuple, set)):
            gens = list(signalgens[0])
        else:
            gens = list(signalgens)

        # topic -> [SignalGenerator,...]
        self._by_topic: Dict[str, List[SignalGenerator]] = {}
        for gen in gens:
            topic = Topics.ohlcv(gen.symbol, gen.interval)
            self._by_topic.setdefault(topic, []).append(gen)

        # topic -> handler
        self._handlers: Dict[str, Callable[[pd.DataFrame, int], Any]] = {}
        self._bound = False

    def add(self, *signalgens: SignalGenerator) -> None:
        """
        Sonradan generator ekleme. Eğer adaptor zaten bound ise:
        - Yeni topic ise subscribe edilir
        - Mevcut topic ise listeye eklenir (tek handler tümünü çalıştırır)
        """
        for gen in signalgens:
            topic = Topics.ohlcv(gen.symbol, gen.interval)
            existed = topic in self._by_topic
            self._by_topic.setdefault(topic, []).append(gen)

            if self._bound and not existed:
                # Yeni topic için handler yarat ve subscribe et
                async def _on_ohlcv(df: pd.DataFrame, msg_id: int, t=topic) -> None:
                    await self._dispatch_for_topic(t, df, msg_id)

                self._handlers[topic] = _on_ohlcv
                self.bus.subscribe(topic, _on_ohlcv)

    def bind(self) -> None:
        """Tüm (symbol, interval) topic'lerine abone olur."""
        if self._bound:
            return

        for topic in self._by_topic.keys():
            async def _on_ohlcv(df: pd.DataFrame, msg_id: int, t=topic) -> None:
                await self._dispatch_for_topic(t, df, msg_id)

            self._handlers[topic] = _on_ohlcv
            self.bus.subscribe(topic, _on_ohlcv)

        self._bound = True

    def unbind(self) -> None:
        """Abonelikleri kaldırır."""
        if not self._bound:
            return
        for topic, handler in list(self._handlers.items()):
            self.bus.unsubscribe(topic, handler)
        self._handlers.clear()
        self._bound = False

    async def _dispatch_for_topic(self, topic: str, df: pd.DataFrame, msg_id: int) -> None:
        """Belirli topic için bağlı tüm generator'ları çalıştır, çıkan sinyalleri publish et."""
        gens = self._by_topic.get(topic, [])
        for gen in gens:
            try:
                signal = await gen.check(df=df)
            except Exception as e:
                print(f"[SignalAdaptor] check error {gen.name}: {e}")
                continue

            if signal:
                try:
                    await self.bus.publish(
                        Topics.signal(gen.symbol, gen.interval),
                        signal,
                        msg_id=msg_id,     # genelde close_time
                        dedupe=True,
                    )
                except Exception as e:
                    print(f"[SignalAdaptor] publish error {gen.name}: {e}")
