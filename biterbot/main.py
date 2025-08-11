import asyncio

from .eventbus import EventBus
from .clients import BinancePublicClient
from .marketdata import OhlcvFeed
from .signals import EMACrossSignalGen, TrendSignalGen
from .adapters import SignalAdaptor
from .telegram import TelegramSink, TelegramSender

async def main():
    bus = EventBus()
    client = BinancePublicClient()

    # Feed'i başlat
    feed = OhlcvFeed(client, bus, limit=200, buffer_seconds=2)
    feed.start("ETHUSDT", "1h")
    feed.start("XRPUSDT", "1h")
    feed.start("XRPUSDT", "15m")

    # Stratejiler
    trend_eth_1h = TrendSignalGen(client, "trend_eth_1h", "ETHUSDT", "1h")
    trend_xrp_1h = TrendSignalGen(client, "trend_xrp_1h", "XRPUSDT", "1h")
    trend_xrp_15m = TrendSignalGen(client, "trend_xrp_15m", "XRPUSDT", "15m")

    # Adaptörler
    SignalAdaptor(bus, trend_eth_1h).bind()
    SignalAdaptor(bus, trend_xrp_1h).bind()
    SignalAdaptor(bus, trend_xrp_15m).bind()


    # Telegram entegrasyonu
    tg = TelegramSink(bus)
    tg.bind()

    # Konsola da yazmaya devam edebilir
    async def on_any_signal(payload, msg_id):
        print("[SIGNAL]", msg_id, payload)
    
    bus.subscribe("signal:*", on_any_signal)

    await feed.wait_forever()

if __name__ == "__main__":
    asyncio.run(main())
