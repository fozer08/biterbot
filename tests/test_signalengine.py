import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio

from biterbot.clients import BinancePublicClient
from biterbot.signals import EMACrossSignalGen, TrendSignalGen
from biterbot.adapters import SignalEngine


async def trader(name, trade_signal):
    print(name, trade_signal)


if __name__ == '__main__':
    client = BinancePublicClient()

    signal_engine = SignalEngine(client)
    signal_engine.register_signal_gen(
        EMACrossSignalGen(
            client, 
            name="emacross_ethusdt", 
            symbol="ETHUSDT",
            interval="1m"
        )
    )
    signal_engine.register_signal_gen(
        TrendSignalGen(
            client, 
            name="trend_ethusdt", 
            symbol="ETHUSDT", 
            interval="1m",
            hysteresis_threshold=0.001
        )
    )
    
    signal_engine.subscribe("emacross_ethusdt", trader)
    signal_engine.subscribe("trend_ethusdt", trader)
    
    asyncio.run(signal_engine.run())