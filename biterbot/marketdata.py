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
        Aynı key zaten çalışıyorsa no-op (idempotent).
        """
        key = (str(symbol), str(interval))
        if key in self._tasks:
            return
        self._tasks[key] = asyncio.create_task(self._run(symbol, interval))

    def start_many(self, *items) -> None:
        """
        Birden fazla feed'i tek seferde başlatır.

        Kullanım örnekleri:
            feed.start_many(("ETHUSDT","15m"), ("ETHUSDT","1h"))
            feed.start_many({"ETHUSDT": ["15m","1h","4h"], "XRPUSDT": ["15m"]})

        Notlar:
            - Aynı (symbol, interval) çifti bu çağrı içinde birden fazla verilse bile
              yalnızca bir kez işlenir.
            - Zaten aktif olanlar (daha önce start edilmiş olanlar) tekrar başlatılmaz.
        """
        pairs = []

        # Tek argüman dict ise {symbol: [intervals]} formatını aç
        if len(items) == 1 and isinstance(items[0], dict):
            mapping = items[0]
            for sym, ivs in mapping.items():
                for iv in ivs:
                    pairs.append((str(sym), str(iv)))
        else:
            # Varargs: ("SYM","INT") ikilileri
            for it in items:
                if isinstance(it, (tuple, list)) and len(it) == 2:
                    pairs.append((str(it[0]), str(it[1])))
                else:
                    raise ValueError(f"Geçersiz pair: {it!r} — ('SYMBOL','INTERVAL') veya dict beklenir")

        # Aynı çağrı içindeki tekrarları eliyoruz
        seen = set()
        for sym, iv in pairs:
            key = (sym, iv)
            if key in seen:
                continue
            seen.add(key)
            # Zaten aktifse start() içi no-op
            self.start(sym, iv)

    async def _run(self, symbol: str, interval: str):
        """
        İç döngü: bar kapanışlarına hizalan, veri çek ve yayınla.
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
