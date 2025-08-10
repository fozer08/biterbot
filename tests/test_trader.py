import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio

from biterbot.clients import BinancePublicClient, BinanceAuthenticatedClient
from biterbot.signals import TrendSignalGen
from biterbot.adapters import Engine
from biterbot.trader import SimpleTrader


accounts = [
    {
        "user": "fozer",
        "credentials": {
            "api_key": "fUeJGT3wAIteZaGW2YMLtzBnNPIXqoaw6eY6CMIFbsvzGiRtrX8CGHjsmuphf1Hp", 
            "api_secret": "U6njDqGUXt15FzVpAZLeAi9Gt1AtP6YEF20xxrPcWFfCAgl4TjxrnCaeB3w1LRCo"
        },
        "strategies": [
            {"signal_name": "trend_solusdt", "max_notional": 10, "leverage": 1}
        ]
    }
]


async def main():

    public_client = BinancePublicClient()
    trend_solusdt = TrendSignalGen(
        public_client, 
        "trend_solusdt", 
        "SOLUSDT", 
        "15m",
        hysteresis_threshold=0.002
    )

    user_client = BinanceAuthenticatedClient(
        api_key=accounts[0]["credentials"]["api_key"],
        api_secret=accounts[0]["credentials"]["api_secret"],
    )
    user_trader = SimpleTrader(
        user_client,
        strategies=accounts[0]["strategies"],
        fee_rate=0.001
    )

    engine = Engine(public_client)
    engine.add_signal_gen(trend_solusdt)
    engine.add_trader(user_trader)

    await engine.run()


if __name__ == '__main__':
    asyncio.run(main())