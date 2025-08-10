from dataclasses import dataclass


def interval_seconds(interval: str) -> int:
    """
    '1m', '15m', '1h', '1d' gibi stringleri saniyeye çevir.
    """
    s = (interval or "").strip().lower()
    if len(s) < 2 or not s[:-1].isdigit():
        raise ValueError(f"Invalid interval: {interval!r}")
    unit = s[-1]
    val = int(s[:-1])
    sec = {'s':1, 'm':60, 'h':3600, 'd':86400}.get(unit)
    if sec is None or val <= 0:
        raise ValueError(f"Invalid interval: {interval!r}")
    return sec * val


@dataclass
class Interval:
    """
    Zaman aralığı; saniye ve milisaniye kolay erişim sağlar.

    Args:
        s: interval string. Örn: '1m', '1h', '4h', ...
    """
    s: str

    @property
    def seconds(self) -> int:
        """Return: int — saniye."""
        return interval_seconds(self.s)

    @property
    def milliseconds(self) -> int:
        """Return: int — milisaniye."""
        return self.seconds * 1000


class Topics:
    """
    Topic yardımcıları

    Biçimler:
      - OHLCV : ohlcv:{symbol}_{interval}
      - Signal: signal:{symbol}_{interval}
    """

    @staticmethod
    def ohlcv(symbol: str, interval: str) -> str:
        """
        OHLCV topic'i üretir.

        Args:
            symbol: Enstrüman sembolü.
            interval: Periyot.

        Return:
            str: Topic adı.
        """
        return f"ohlcv:{symbol}_{interval}"

    @staticmethod
    def signal(symbol: str, interval: str) -> str:
        """
        Signal topic'i üretir.

        Args:
            symbol: Enstrüman sembolü.
            interval: Periyot.

        Return:
            str: Topic adı.
        """
        return f"signal:{symbol}_{interval}"
