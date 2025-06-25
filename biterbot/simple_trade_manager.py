import asyncio
from binance import Client

from .signal_engine import PublicClient, SignalEngine, StrategyBase, TrendStrategy


class SimpleTradeManager:

    def __init__(
        self,
        engine: SignalEngine,
        accounts: list[dict],  # account configs with credentials and strategy definitions
        fee_rate: float = 0.001
    ):
        self.engine = engine
        self.fee_rate = fee_rate

        acct = accounts[0]
        # Initialize Binance margin client
        self.client = Client(
            api_key=acct["credentials"]["api_key"],
            api_secret=acct["credentials"]["api_secret"]
        )

        # Build state per strategy: max_notional, leverage, and current position
        strategies_cfg = acct.get("strategies", [])
        self.states = {}
        for cfg in strategies_cfg:
            name = cfg["name"]
            self.states[name] = {
                "max_notional": cfg["max_notional"],
                "leverage": cfg.get("leverage", 1),
                "position": None
            }

        # Sync existing margin positions (locked -> LONG, borrowed -> SHORT)
        margin_info = self.client.get_margin_account()
        for name, state in self.states.items():
            strat = engine.strategies.get(name)
            if not strat:
                continue
            symbol = strat.symbol
            base = symbol[:-4] if symbol.endswith("USDT") else symbol[:-3]
            for asset in margin_info.get("userAssets", []):
                if asset.get("asset") != base:
                    continue
                locked = float(asset.get("locked", 0))
                borrowed = float(asset.get("borrowed", 0))
                if locked > 0:
                    state["position"] = {"side": "LONG", "quantity": locked, "entry": None}
                elif borrowed > 0:
                    state["position"] = {"side": "SHORT", "quantity": borrowed, "entry": None}
                break

        # Subscribe to engine signals
        for name in self.states:
            if name in engine.strategies:
                engine.subscribe(name, self.on_signal)
            else:
                print(f"[WARN] Strategy '{name}' not found, skipped.")

    async def on_signal(self, name: str, signal: str, candle: dict):
        strat = self.engine.strategies[name]
        symbol = strat.symbol
        state = self.states[name]
        pos = state["position"]
        price = candle["close"]
        loop = asyncio.get_running_loop()

        # Get up-to-date margin balances
        margin_info = await loop.run_in_executor(None, self.client.get_margin_account)
        quote = "USDT" if symbol.endswith("USDT") else "USD"
        free_bal = next(
            (float(a.get("free", 0)) for a in margin_info.get("userAssets", []) if a.get("asset") == quote),
            0.0
        )

        # Determine notional and quantity
        lev = state["leverage"]
        max_not = state["max_notional"]
        allowed_notional = min(free_bal * lev, max_not)
        usable = allowed_notional * (1 - self.fee_rate)
        qty = usable / price

        # LONG signal handling
        if signal == StrategyBase.SIGNAL_LONG:
            if pos is None:
                # Open LONG
                order = await loop.run_in_executor(
                    None,
                    self.client.create_margin_order,
                    symbol,
                    Client.SIDE_BUY,
                    Client.ORDER_TYPE_MARKET,
                    qty
                )
                state["position"] = {"side": "LONG", "entry": price, "quantity": qty}
                print(f"[TRADE] Open LONG {symbol} @ {price:.4f}, qty={qty:.6f} (Lev: {lev}x)")
            elif pos["side"] == "SHORT":
                # Close SHORT
                locked_qty = pos["quantity"]
                await loop.run_in_executor(
                    None,
                    self.client.create_margin_order,
                    symbol,
                    Client.SIDE_BUY,
                    Client.ORDER_TYPE_MARKET,
                    locked_qty
                )
                print(f"[TRADE] Close SHORT {symbol} @ {price:.4f}")
                # Open LONG
                order = await loop.run_in_executor(
                    None,
                    self.client.create_margin_order,
                    symbol,
                    Client.SIDE_BUY,
                    Client.ORDER_TYPE_MARKET,
                    qty
                )
                state["position"] = {"side": "LONG", "entry": price, "quantity": qty}
                print(f"[TRADE] Open LONG {symbol} @ {price:.4f}, qty={qty:.6f} (Lev: {lev}x)")

        # SHORT signal handling
        elif signal == StrategyBase.SIGNAL_SHORT:
            if pos is None:
                # Open SHORT
                order = await loop.run_in_executor(
                    None,
                    self.client.create_margin_order,
                    symbol,
                    Client.SIDE_SELL,
                    Client.ORDER_TYPE_MARKET,
                    qty
                )
                state["position"] = {"side": "SHORT", "entry": price, "quantity": qty}
                print(f"[TRADE] Open SHORT {symbol} @ {price:.4f}, qty={qty:.6f} (Lev: {lev}x)")
            elif pos["side"] == "LONG":
                # Close LONG
                locked_qty = pos["quantity"]
                await loop.run_in_executor(
                    None,
                    self.client.create_margin_order,
                    symbol,
                    Client.SIDE_SELL,
                    Client.ORDER_TYPE_MARKET,
                    locked_qty
                )
                print(f"[TRADE] Close LONG {symbol} @ {price:.4f}")
                # Open SHORT
                order = await loop.run_in_executor(
                    None,
                    self.client.create_margin_order,
                    symbol,
                    Client.SIDE_SELL,
                    Client.ORDER_TYPE_MARKET,
                    qty
                )
                state["position"] = {"side": "SHORT", "entry": price, "quantity": qty}
                print(f"[TRADE] Open SHORT {symbol} @ {price:.4f}, qty={qty:.6f} (Lev: {lev}x)")


# ---- TEST MAIN ----
if __name__ == "__main__":
    accounts = [
        {
            "user": "xxx",
            "credentials": {"api_key": "YOUR_API_KEY", "api_secret": "YOUR_SECRET_KEY"},
            "strategies": [
                {"name": "trend_solusdt", "max_notional": 100, "leverage": 2}
            ]
        }
    ]

    public_client = PublicClient()
    engine = SignalEngine(public_client)
    engine.add_strategy(TrendStrategy("trend_solusdt", "SOLUSDT"))

    manager = SimpleTradeManager(
        engine=engine,
        accounts=accounts,
        fee_rate=0.001
    )

    asyncio.run(engine.run())
