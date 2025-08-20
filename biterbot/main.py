import asyncio

from .eventbus import EventBus
from .clients import BinancePublicClient
from .marketdata import OhlcvFeed
from .signals import EMACrossSignalGen, TrendSignalGen
from .adapters import SignalAdaptor
from .telegram import TelegramSink, TelegramSender, format_signal_message

async def main():
    bus = EventBus()
    client = BinancePublicClient()

    # Feed'i başlat
    feed = OhlcvFeed(client, bus, limit=200, buffer_seconds=3)
    feed.start_many(
        {
            "BTCUSDT": ["15m", "1h", "4h"],
            "ETHUSDT": ["15m", "1h", "4h"],
            "SOLUSDT": ["15m", "1h", "4h"],
            "XRPUSDT": ["15m", "1h", "4h"]
        }
    )

    # Sinyaller
    tsa = SignalAdaptor(
        bus,
        TrendSignalGen("BTCUSDT", "15m", hysteresis_th=0.003, confirm_bars=5),
        TrendSignalGen("BTCUSDT", "1h",  hysteresis_th=0.005, confirm_bars=5),
        TrendSignalGen("BTCUSDT", "4h",  hysteresis_th=0.010),
        TrendSignalGen("ETHUSDT", "15m", hysteresis_th=0.003, confirm_bars=5),
        TrendSignalGen("ETHUSDT", "1h",  hysteresis_th=0.005, confirm_bars=5),
        TrendSignalGen("ETHUSDT", "4h",  hysteresis_th=0.010),
        TrendSignalGen("XRPUSDT", "15m", hysteresis_th=0.003, confirm_bars=5),
        TrendSignalGen("XRPUSDT", "1h",  hysteresis_th=0.005, confirm_bars=5),
        TrendSignalGen("XRPUSDT", "4h",  hysteresis_th=0.010),
        TrendSignalGen("SOLUSDT", "15m", hysteresis_th=0.003, confirm_bars=5),
        TrendSignalGen("SOLUSDT", "1h",  hysteresis_th=0.005, confirm_bars=5),
        TrendSignalGen("SOLUSDT", "4h",  hysteresis_th=0.010),
    )
    tsa.bind()

    # Telegram entegrasyonu
    tg = TelegramSink(
        bus,
        subscriptions={
            "signal:*":  format_signal_message,
        }
    )
    tg.bind()

    # Konsola da yazmaya devam edebilir
    async def on_any_signal(payload, msg_id):
        print("[SIGNAL]", msg_id, payload)
    
    bus.subscribe("signal:*", on_any_signal)

    await feed.wait_forever()

if __name__ == "__main__":
    asyncio.run(main())
