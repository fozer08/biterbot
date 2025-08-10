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
    feed.start("BTCUSDT", "1m")
    feed.start("SOLUSDT", "1m")

    # Stratejiler
    trend_eth_1h = TrendSignalGen(client, "trend_eth_1h", "ETHUSDT", "1h")
    trend_xrp_1h = TrendSignalGen(client, "trend_xrp_1h", "XRPUSDT", "1h")
    trend_eth_1d = TrendSignalGen(client, "trend_eth_1d", "ETHUSDT", "1d")
    trend_xrp_1d = TrendSignalGen(client, "trend_xrp_1d", "XRPUSDT", "1d")
    # Test için
    trend_eth_1m = TrendSignalGen(client, "trend_eth_1d", "ETHUSDT", "1m", hysteresis_threshold=0.001)

    # Adaptörler
    SignalAdaptor(bus, trend_eth_1h).bind()
    SignalAdaptor(bus, trend_xrp_1h).bind()
    SignalAdaptor(bus, trend_eth_1d).bind()
    SignalAdaptor(bus, trend_xrp_1d).bind()
    SignalAdaptor(bus, trend_eth_1m).bind()

    # Telegram entegrasyonu
    tg_sender = TelegramSender(
        token="8290926257:AAFv1sdhY9Pbjp90L2TTUXAPsk9E7pigKTE",
        chat_id="-4927151540"
    )
    tg = TelegramSink(bus, sender=tg_sender)
    tg.bind()

    # Konsola da yazmaya devam edebilir
    async def on_any_signal(payload, msg_id):
        print("[SIGNAL]", msg_id, payload)

    bus.subscribe("signal:*", on_any_signal)

    await feed.wait_forever()

if __name__ == "__main__":
    asyncio.run(main())
