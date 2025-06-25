# main.py
import asyncio
from services.trade_manager import TradeManager
from services.signal_engine import SignalEngine
from users import user_configs

async def main():
    signal_engine = SignalEngine()
    asyncio.create_task(signal_engine.run())

    tasks = []
    for user in user_configs:
        manager = TradeManager(user)
        for strat_name in user['strategies']:
            signal_engine.subscribe(strat_name, manager.handle_signal)
        tasks.append(asyncio.create_task(manager.run()))

    await asyncio.gather(*tasks)

if __name__ == '__main__':
    asyncio.run(main())


# users/user_configs.py
user_configs = [
    {
        "api_key": "YOUR_API_KEY",
        "api_secret": "YOUR_API_SECRET",
        "leverage": 5,
        # Only list strategy names
        "strategies": ["ema_btcusdt", "rsi_ethusdt"],
        # Capital allocation per strategy
        "capital_allocations": {
            "ema_btcusdt": 0.6,
            "rsi_ethusdt": 0.4
        }
    }
]

# services/strategies_config.py
# Centralized strategy metadata
strategies_config = {
    "ema_btcusdt": {
        "symbol": "BTCUSDT",
        "entry_strategy": {
            "name": "StaggeredEntryStrategy",
            "levels": [
                {"delay": 0, "portion": 0.5},
                {"delay": 1, "portion": 0.3},
                {"delay": 2, "portion": 0.2}
            ]
        },
                "take_profit_strategy": {
            "name": "TakeProfitStrategy",
            "levels": [
                {"pct": 1.0, "portion": 0.5},
                {"pct": 2.0, "portion": 0.3},
                {"pct": 3.0, "portion": 0.2}
            ]
        },
        "stop_loss_strategy": {"name": "StopLossStrategy", "pct": 1.5}
    },
    "rsi_ethusdt": {
        "symbol": "ETHUSDT",
        "entry_strategy": None,
                "take_profit_strategy": {
            "name": "TakeProfitStrategy",
            "levels": [
                {"pct": 1.0, "portion": 0.5},
                {"pct": 2.0, "portion": 0.5}
            ]
        },
        "stop_loss_strategy": None
    }
}


# services/signal_engine.py


# services/entry_strategies.py
from abc import ABC, abstractmethod

class BaseEntryStrategy(ABC):
    @abstractmethod
    def generate_levels(self, base_qty):
        pass

class StaggeredEntryStrategy(BaseEntryStrategy):
    def __init__(self, levels):
        self.levels = sorted(levels, key=lambda x: x['delay'])

    def generate_levels(self, base_qty):
        return [{'delay': lvl['delay'], 'qty': base_qty * lvl['portion']} for lvl in self.levels]


# services/exit_strategies.py
from abc import ABC, abstractmethod

class BaseExitStrategy(ABC):
    @abstractmethod
    def apply(self, price, entry_price, quantity, **kwargs):
        pass

class TakeProfitStrategy(BaseExitStrategy):
    def __init__(self, levels=None):
        self.levels = sorted(levels or [], key=lambda x: x['pct'])

    def apply(self, price, entry_price, quantity, tp_hits=None, side='BUY', **kwargs):
        pnl = ((price-entry_price)/entry_price)*100 if side=='BUY' else ((entry_price-price)/entry_price)*100
        exited, hits = 0.0, list(tp_hits or [])
        for lvl in self.levels:
            if lvl['pct'] not in hits and pnl >= lvl['pct']:
                exited += quantity * lvl['portion']
                hits.append(lvl['pct'])
        return exited, hits

class StopLossStrategy(BaseExitStrategy):
    def __init__(self, pct=None): self.pct = pct
    def apply(self, price, entry_price, quantity, side='BUY', **kwargs):
        if self.pct is None: return 0.0, None
        pnl = ((price-entry_price)/entry_price)*100 if side=='BUY' else ((entry_price-price)/entry_price)*100
        return (quantity, None) if pnl <= -self.pct else (0.0, None)


# services/binance_client.py
from binance.client import Client
from binance.enums import *

class BinanceClient:
    def __init__(self, api_key, api_secret): self.client = Client(api_key, api_secret)
    def set_leverage(self, symbol, leverage): self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
    def get_balance(self, asset="USDT"): return float([b for b in self.client.futures_account_balance() if b['asset']==asset][0]['balance'])
    def open_position(self, symbol, side, quantity): self.client.futures_create_order(symbol=symbol,side=SIDE_BUY if side=='BUY' else SIDE_SELL,type=ORDER_TYPE_MARKET,quantity=quantity)
    def close_position(self, symbol, side, quantity): self.client.futures_create_order(symbol=symbol,side=SIDE_SELL if side=='BUY' else SIDE_BUY,type=ORDER_TYPE_MARKET,quantity=quantity)


# services/trade_manager.py
import asyncio
from services.binance_client import BinanceClient
from services.entry_strategies import StaggeredEntryStrategy
from services.exit_strategies import TakeProfitStrategy, StopLossStrategy
from services.strategies_config import strategies_config

class TradeManager:
    def __init__(self, user_config):
        self.client = BinanceClient(user_config['api_key'], user_config['api_secret'])
        self.leverage = user_config['leverage']
        self.capital_allocations = user_config.get('capital_allocations', {})
        # Only strategy names from user config
        self.strategy_names = user_config['strategies']
        # Load metadata for only these strategies
        self.strategy_configs = {name: strategies_config[name] for name in self.strategy_names}
        # State
        self.pending_entries = {name: [] for name in self.strategy_names}
        self.positions = {name: None for name in self.strategy_names}
        self.used_alloc = {name: 0.0 for name in self.strategy_names}

    async def run(self):
        while True:
            for name in self.strategy_names:
                cfg = self.strategy_configs[name]
                sym = cfg['symbol']
                queue = self.pending_entries[name]
                new_q = []
                for item in queue:
                    if item['delay'] <= 0:
                        side = self.positions[name]['side']
                        self.client.open_position(sym, side, item['qty'])
                        if not self.positions[name]:
                            self.positions[name] = {'side': side, 'entry': None, 'quantity': item['qty'], 'tp_hits': []}
                        else:
                            self.positions[name]['quantity'] += item['qty']
                    else:
                        item['delay'] -= 1
                        new_q.append(item)
                self.pending_entries[name] = new_q
            # process exits omitted for brevity
            await asyncio.sleep(30)

    async def handle_signal(self, strategy_name, signal, df):
        cfg = self.strategy_configs[strategy_name]
        sym = cfg['symbol']
        price = df['close'].iloc[-1]
        balance = self.client.get_balance()
        quote = cfg['symbol'][-4:]
        base = cfg['symbol'][:-4]
        alloc_map = self.capital_allocations.get(quote, {})
        alloc_frac = alloc_map.get(base, 0.0)
        target = balance * alloc_frac
        used_other = sum(self.used_alloc[n] for n in self.strategy_names if n != strategy_name)
        avail = max(target - used_other, 0.0)
        if avail <= 0:
            return
        base_qty = (avail * self.leverage) / price
        self.used_alloc[strategy_name] = avail
        # initialize position state
        self.positions[strategy_name] = {'side': 'BUY' if signal=='buy' else 'SELL', 'entry': None, 'quantity': 0.0, 'tp_hits': []}
        ent_cfg = cfg.get('entry_strategy')
        if ent_cfg:
            strat = StaggeredEntryStrategy(ent_cfg['levels'])
            self.pending_entries[strategy_name] = strat.generate_levels(base_qty)
        else:
            self.pending_entries[strategy_name] = [{'delay': 0, 'qty': base_qty}]
