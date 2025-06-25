import pandas as pd

from binance import Client


class PublicClient:
    """
    Wrapper around Binance Client for public data endpoints.
    """
    def __init__(self):
        self._client = Client()

    def get_server_time(self) -> int:
        """
        Return Binance server time in milliseconds.
        """
        return int(self._client.get_server_time()["serverTime"])

    def fetch_ohlcv(self, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
        """
        Fetch klines and return DataFrame with OHLCV.
        """
        raw = self._client.get_klines(symbol=symbol, interval=interval, limit=limit)
        rows = []
        for k in raw:
            rows.append({
                'open_time': int(k[0]),
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5]),
                'close_time': int(k[6])
            })
        return pd.DataFrame(rows)

