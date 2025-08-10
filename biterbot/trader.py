from typing import Callable
import asyncio

from .clients import AuthenticatedClient
from .adapters import SignalEngine


class Trader:

    def __init__(
        self,
        client: AuthenticatedClient,
        strategies: list[dict],
        fee_rate: float = 0.001
    ):
        self.client = client
        self.fee_rate = fee_rate

        # Build state per strategy: max_notional, leverage, and current position
        self.states = {}
        for strategy in strategies:
            signal_name = strategy["signal_name"]
            self.states[signal_name] = {
                "signal_name": signal_name,
                "max_notional": strategy["max_notional"],
                "leverage": strategy.get("leverage", 1),
                "position": None
            }
        
        # Sync existing margin positions (locked -> LONG, borrowed -> SHORT)
        margin_info = self.client.get_margin_account()
        for signal_name, state in self.states.items():
            signal_generator = engine.signal_generators.get(signal_name)
            if not signal_generator:
                continue
            symbol = signal_generator.symbol
            base = symbol[:-4] if symbol.endswith("USDT") else symbol[:-3]
            for asset in margin_info.get("userAssets", []):
                if asset.get("asset") != base:
                    continue
                print(asset.get("asset"))
                locked = float(asset.get("locked", 0))
                borrowed = float(asset.get("borrowed", 0))
                if locked > 0:
                    state["position"] = {"side": "long", "quantity": locked, "entry": None}
                elif borrowed > 0:
                    state["position"] = {"side": "short", "quantity": borrowed, "entry": None}
                break

        # Subscribe to engine signals
        for signal_name in self.states:
            if signal_name in engine.signal_generators:
                engine.subscribe(signal_name, self._on_signal)
            else:
                print(f"[WARN] Strategy '{signal_name}' not found, skipped.")

    async def _on_signal(self, signal_name: str, signal: str):
        signal_generator = self.engine.signal_generators[signal_name]
        symbol = signal_generator.symbol
        state = self.states[signal_name]
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
        if signal == "long":
            if pos is None:
                # Open LONG
                order = await loop.run_in_executor(
                    None,
                    self.client.create_margin_order,
                    symbol,
                    AuthenticatedClient.SIDE_BUY,
                    AuthenticatedClient.ORDER_TYPE_MARKET,
                    qty
                )
                state["position"] = {"side": "long", "entry": price, "quantity": qty}
                print(f"[TRADE] Open LONG {symbol} @ {price:.4f}, qty={qty:.6f} (Lev: {lev}x)")
            elif pos["side"] == "short":
                # Close SHORT
                locked_qty = pos["quantity"]
                await loop.run_in_executor(
                    None,
                    self.client.create_margin_order,
                    symbol,
                    AuthenticatedClient.SIDE_BUY,
                    AuthenticatedClient.ORDER_TYPE_MARKET,
                    locked_qty
                )
                print(f"[TRADE] Close SHORT {symbol} @ {price:.4f}")
                # Open LONG
                order = await loop.run_in_executor(
                    None,
                    self.client.create_margin_order,
                    symbol,
                    AuthenticatedClient.SIDE_BUY,
                    AuthenticatedClient.ORDER_TYPE_MARKET,
                    qty
                )
                state["position"] = {"side": "long", "entry": price, "quantity": qty}
                print(f"[TRADE] Open LONG {symbol} @ {price:.4f}, qty={qty:.6f} (Lev: {lev}x)")

        # SHORT signal handling
        elif signal == "short":
            if pos is None:
                # Open SHORT
                order = await loop.run_in_executor(
                    None,
                    self.client.create_margin_order,
                    symbol,
                    AuthenticatedClient.SIDE_SELL,
                    AuthenticatedClient.ORDER_TYPE_MARKET,
                    qty
                )
                state["position"] = {"side": "short", "entry": price, "quantity": qty}
                print(f"[TRADE] Open SHORT {symbol} @ {price:.4f}, qty={qty:.6f} (Lev: {lev}x)")
            elif pos["side"] == "long":
                # Close LONG
                locked_qty = pos["quantity"]
                await loop.run_in_executor(
                    None,
                    self.client.create_margin_order,
                    symbol,
                    AuthenticatedClient.SIDE_SELL,
                    AuthenticatedClient.ORDER_TYPE_MARKET,
                    locked_qty
                )
                print(f"[TRADE] Close LONG {symbol} @ {price:.4f}")
                # Open SHORT
                order = await loop.run_in_executor(
                    None,
                    self.client.create_margin_order,
                    symbol,
                    AuthenticatedClient.SIDE_SELL,
                    AuthenticatedClient.ORDER_TYPE_MARKET,
                    qty
                )
                state["position"] = {"side": "short", "entry": price, "quantity": qty}
                print(f"[TRADE] Open SHORT {symbol} @ {price:.4f}, qty={qty:.6f} (Lev: {lev}x)")

