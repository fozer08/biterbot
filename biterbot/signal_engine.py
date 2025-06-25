import asyncio

from .clients import PublicClient
from .signal_base import SignalBase


class SignalEngine:

    def __init__(self, client: PublicClient):
        self.client = client
        self.signals: dict[str, SignalBase] = {}
        self.subscribers: dict[str, list] = {}

    def add_strategy(self, strategy: SignalBase) -> None:
        """
        Register a SignalBase instance.
        """
        self.signals[strategy.name] = strategy

    def subscribe(self, name: str, callback: callable) -> None:
        if name not in self.signals:
            raise ValueError(f"Signal {name} not found.")
        self.subscribers.setdefault(name, []).append(callback)

    async def notify(self, name: str, signal: str, candle: dict) -> None:
        tasks = [asyncio.create_task(cb(name, signal, candle)) for cb in self.subscribers.get(name, [])]
        if tasks:
            await asyncio.gather(*tasks)

    def _interval_seconds(self, interval: str) -> int:
        unit = interval[-1]
        val = int(interval[:-1])
        return {'s':1,'m':60,'h':3600,'d':86400}.get(unit,0)*val

    async def _execute_signal(self, strat: SignalBase) -> None:
        interval_sec = self._interval_seconds(strat.interval)
        last_close = None

        while True:
            # For first iteration
            if last_close is not None:
                now = self.client.get_server_time() / 1000
                next_run = last_close / 1000 + interval_sec + strat.buffer_seconds
                if next_run > now:
                    await asyncio.sleep(next_run - now)

            # Run strategy then notify
            signal, candle = await strat.check()
            if signal:
                await self.notify(strat.name, signal, candle)

            # Update last close time
            last_close = candle["close_time"]

    async def run(self) -> None:
        tasks = [self._execute_signal(s) for s in self.signals.values()]
        if tasks:
            await asyncio.gather(*tasks)


# ---- TEST ----
if __name__ == '__main__':
    client = PublicClient()
    engine = SignalEngine(client)

    from signals import EMACrossSignal, TrendSignal
    engine.add_strategy(EMACrossSignal("emacross_solusdt", "SOLUSDT", client))
    engine.add_strategy(TrendSignal("trend_solusdt", "SOLUSDT", client))

    async def trader(name, sig, candle):
        print(name, sig, candle)

    engine.subscribe('emacross_solusdt', trader)
    engine.subscribe('trend_solusdt', trader)

    asyncio.run(engine.run())
