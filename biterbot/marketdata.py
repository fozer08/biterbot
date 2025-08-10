import asyncio
from typing import Dict, Tuple
import pandas as pd

from .clients import PublicClient
from .helpers import Interval, Topics
from .eventbus import EventBus

class OhlcvFeed:
    """
    OHLCV verisini periyodik olarak çekip EventBus'a yayınlar.

    Args:
        client: Veri kaynağı.
        bus: EventBus örneği.
        limit: En fazla kaç mum çekilecek.
        buffer_seconds: Kapanıştan sonra bekleme tamponu.
    """

    def __init__(
        self,
        client: PublicClient,
        bus: EventBus,
        *,
        limit: int = 200,
        buffer_seconds: int = 2,
    ):
        self.client = client
        self.bus = bus
        self.limit = limit
        self.buffer_seconds = buffer_seconds
        self._tasks: Dict[Tuple[str, str], asyncio.Task] = {}
        self._stopping = asyncio.Event()

    def start(self, symbol: str, interval: str) -> None:
        """
        Belirli (symbol, interval) için yayın yapan görev başlat.

        Args:
            symbol: Enstrüman sembolü.
            interval: Periyot.
        """
        key = (symbol, interval)
        if key in self._tasks:
            return
        self._tasks[key] = asyncio.create_task(self._run(symbol, interval))

    async def _run(self, symbol: str, interval: str):
        """
        İç döngü: bar kapanışlarına hizalan, veri çek ve yayınla.

        Args:
            symbol: Enstrüman.
            interval: Periyot.
        """
        sec = Interval(interval).seconds
        topic = Topics.ohlcv(symbol, interval)

        while not self._stopping.is_set():
            try:
                now = self.client.get_server_time() / 1000
                next_run = (now // sec + 1) * sec + self.buffer_seconds
                wait = max(0, next_run - now)
                await asyncio.wait_for(self._stopping.wait(), timeout=wait)
                if self._stopping.is_set():
                    break
            except asyncio.TimeoutError:
                pass

            try:
                df: pd.DataFrame = await asyncio.to_thread(
                    self.client.fetch_ohlcv,
                    symbol,
                    interval,
                    self.limit,
                    True,
                )
            except Exception as e:
                print(f"[OhlcvFeed] fetch error {symbol}-{interval}: {e}")
                continue

            try:
                close_time = int(df.iloc[-1]['close_time'])
            except Exception:
                close_time = None

            try:
                if close_time is not None:
                    await self.bus.publish(topic, df, msg_id=close_time, dedupe=True)
                else:
                    await self.bus.publish(topic, df, dedupe=True)
            except Exception as e:
                print(f"[OhlcvFeed] publish error {symbol}-{interval}: {e}")

    async def stop(self):
        """
        Tüm görevleri zarifçe durdur.
        """
        self._stopping.set()
        tasks = list(self._tasks.values())
        if tasks:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def wait_forever(self):
        """
        Başlatılmış görevler varsa onları bekle; yoksa hemen dön.
        """
        tasks = list(self._tasks.values())
        if tasks:
            await asyncio.gather(*tasks)
