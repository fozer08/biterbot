from abc import ABC, abstractmethod

import pandas as pd


class PublicClient(ABC):
    """
    Borsa verilerine salt-okunur erişim için arayüz.
    """

    @abstractmethod
    def get_server_time(self) -> int:
        """
        Sunucu zamanını ms cinsinden döndür.

        Return:
            int: Sunucu zamanı (ms).
        """
        ...

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        interval: str,
        limit: int = 100,
        last_candle_completed: bool = True,
    ) -> pd.DataFrame:
        """
        OHLCV verisini DataFrame olarak getir.

        Args:
            symbol: Enstrüman sembolü.
            interval: Periyot.
            limit: Satır sayısı.
            last_candle_completed: Son mum kapanmış mı kontrolü.

        Return:
            pd.DataFrame: OHLCV verisi.
        """
        ...

class BinancePublicClient(PublicClient):
    """Binance public uçlarına basit sarmalayıcı."""

    def __init__(self):
        import binance
        self._client = binance.Client()

    def get_server_time(self) -> int:
        """Return: int — sunucu zamanı (ms)."""
        return int(self._client.get_server_time()["serverTime"])

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: str,
        limit: int = 100,
        last_candle_completed: bool = True,
    ) -> pd.DataFrame:
        """
        Args:
            symbol: Enstrüman.
            interval: Periyot.
            limit: Kayıt sayısı.
            last_candle_completed: Son mum tamamsa bırak, değilse sil.
        Return:
            pd.DataFrame: OHLCV tablosu.
        """
        raw = self._client.get_klines(symbol=symbol, interval=interval, limit=limit)
        rows = [
            {
                'open_time': int(k[0]),
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5]),
                'close_time': int(k[6]),
            }
            for k in raw
        ]
        df = pd.DataFrame(rows)
        if last_candle_completed and not df.empty:
            server_ms = self.get_server_time()
            last_close_time = int(df.iloc[-1]['close_time'])
            if server_ms < last_close_time:
                df = df.iloc[:-1]
        return df

class AuthenticatedClient(PublicClient):
    """
    Trade gibi özel uçlar için arayüz.
    """
    SIDE_BUY = "BUY"
    SIDE_SELL = "SELL"
    ORDER_TYPE_MARKET = "MARKET"

    def __init__(self, api_key: str, api_secret: str):
        """
        Args:
            api_key: API anahtarı.
            api_secret: API sırrı.
        Return:
            None
        """
        self.api_key = api_key
        self.api_secret = api_secret

    @abstractmethod
    def get_margin_account(self) -> dict:
        """Return: dict — margin hesap bilgileri."""
        ...

    @abstractmethod
    def create_margin_order(self, symbol: str, side: str, order_type: str, quantity: float) -> dict:
        """
        Args:
            symbol: Enstrüman.
            side: BUY/SELL.
            order_type: MARKET vb.
            quantity: Miktar.
        Return:
            dict: Sipariş cevabı.
        """
        ...

class BinanceAuthenticatedClient(AuthenticatedClient, BinancePublicClient):
    """Binance özel uçlarına erişim sağlayan istemci."""

    def __init__(self, api_key: str, api_secret: str):
        """
        Args:
            api_key: API anahtarı.
            api_secret: API sırrı.
        Return:
            None
        """
        import binance
        super().__init__(api_key, api_secret)
        self._client = binance.Client(api_key=api_key, api_secret=api_secret)

    def get_margin_account(self) -> dict:
        """Return: dict — margin hesap."""
        return self._client.get_margin_account()

    def create_margin_order(self, symbol: str, side: str, order_type: str, quantity: float) -> dict:
        """Return: dict — sipariş cevabı."""
        return self._client.create_margin_order(
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
        )
