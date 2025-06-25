from abc import ABC, abstractmethod

from .clients import PublicClient


class SignalBase(ABC):
    """
    Base class for strategies. Registers itself with the engine.
    Subclasses must define `interval` and optionally override `buffer_seconds`.
    """
    SIGNAL_LONG = "long"
    SIGNAL_SHORT = "short"
    SIGNAL_EXIT = "exit"
    
    interval: str
    buffer_seconds: int = 3

    def __init__(self, name: str, symbol: str, public_client: PublicClient):
        self.name = name
        self.symbol = symbol
        self.public_client = public_client

    @abstractmethod
    async def check(self) -> tuple:
        """
        Execute strategy logic and return last candle dict.

        Returns:
            (signal, candle) (tuple): 
            - signal (str): Generated trading signal.
            - candle (dict): Last candle data dictionary.
        """
        ...