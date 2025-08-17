"""
Telegram Entegrasyonu

- EventBus üzerinde bir veya birden çok pattern'e abone olur (örn. "signal:*", "decision:*").
- Her pattern için ayrı bir formatter kullanılabilir.
- Gönderim async'tir; hafif hız sınırlaması içerir.
- Varsayılan olarak signal dict'lerini (name/symbol/interval/direction/strength/at/price) biçimlendirir.

Kullanım (main.py içinde):
    import os
    from .telegram import TelegramSink, format_signal_message

    tg = TelegramSink(
        bus,
        token=os.getenv("TELEGRAM_BOT_TOKEN"),
        chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        subscriptions={
            "signal:*": format_signal_message,     # gösterge sinyalleri
            # ileride karar/pozisyon katmanı eklendiğinde:
            # "decision:*": format_decision_message,
            # "position:*": format_position_message,
        },
    )
    tg.bind()
"""
import asyncio
import json
import os
import time
from typing import Any, Callable, Dict, Optional

from .eventbus import EventBus
from .signals import Signal


# ----------------------------------------------------------------------------
# Yardımcı biçimlendirme
# ----------------------------------------------------------------------------
def _fmt_ts(ts: Optional[int]) -> str:
    """ms/s farkını otomatik ayıkla ve 'YYYY-mm-dd HH:MM:SS' döndür."""
    if ts is None:
        return "-"
    # saniye mi milisaniye mi?
    if ts > 10_000_000_000:  # ~ 2001-2286 arası ms
        secs = ts / 1000.0
    else:
        secs = float(ts)
    lt = time.localtime(secs)
    return time.strftime("%Y-%m-%d %H:%M:%S", lt)


def _fmt_float(x: Any, precision: int = 4, dash_on_none: bool = True) -> str:
    if x is None:
        return "-" if dash_on_none else ""
    try:
        return f"{float(x):.{precision}f}"
    except Exception:
        return str(x)


# ----------------------------------------------------------------------------
# Formatters
# ----------------------------------------------------------------------------
def format_generic_message(obj: Any) -> str:
    """Herhangi bir dict/objeyi pretty JSON olarak gönderir."""
    try:
        txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), indent=2)
    except Exception:
        txt = str(obj)
    # Telegram code block
    return f"<pre>{txt}</pre>"


def format_signal_message(sig: Signal) -> str:
    """
    Beklenen alanlar:
      name, symbol, interval, direction("UP"|"DOWN"|None), strength, at, price
    """
    name = sig["name"]
    symbol = sig["symbol"]
    interval = sig["interval"]
    direction = sig["direction"]
    strength = sig.get("strength", 0.0)
    ts = sig.get("at")
    price = sig.get("price")

    arrow = "🔼" if direction == "UP" else ("🔽" if direction == "DOWN" else "•")
    st_txt = _fmt_float(strength, 4)
    pr_txt = _fmt_float(price, 8)
    ts_txt = _fmt_ts(ts)

    lines = [
        f"{arrow} <b>{name}</b>",
        f"• {symbol} / {interval}",
        f"• direction: <b>{direction}</b>",
        f"• strength: <code>{st_txt}</code>",
        f"• price: <code>{pr_txt}</code>",
        f"• at: <code>{ts_txt}</code>",
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Telegram gönderici
# ----------------------------------------------------------------------------
class TelegramSender:
    """Telegram Bot API göndereni (async, stdlib tabanlı)."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        parse_mode: str = "HTML",
        min_interval: float = 0.5,   # flood koruması
        timeout: float = 10.0,
    ) -> None:
        if not token or not chat_id:
            raise ValueError("TelegramSender: token/chat_id gerekli.")
        self._token = token
        self._chat_id = chat_id
        self._parse_mode = parse_mode
        self._min_interval = float(min_interval)
        self._timeout = float(timeout)
        self._last_send = 0.0
        self._lock = asyncio.Lock()

    async def send_message(self, text: str, disable_web_page_preview: bool = True) -> None:
        """Mesaj gönderir (stdlib HTTP)."""
        import urllib.request
        import urllib.parse

        async with self._lock:
            # basit hız sınırı
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_send)
            if wait > 0:
                await asyncio.sleep(wait)

            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            data = {
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": self._parse_mode,
                "disable_web_page_preview": "true" if disable_web_page_preview else "false",
            }
            body = urllib.parse.urlencode(data).encode()

            def _post():
                req = urllib.request.Request(url, data=body, method="POST")
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    return resp.read()

            try:
                await asyncio.to_thread(_post)
            finally:
                self._last_send = time.monotonic()


# ----------------------------------------------------------------------------
# EventBus -> Telegram
# ----------------------------------------------------------------------------
class TelegramSink:
    """
    EventBus -> Telegram köprüsü.

    Args:
        bus: EventBus örneği.
        token, chat_id: Opsiyonel; verilmezse ortamdan okunur.
        subscriptions: pattern -> formatter fonksiyonu haritası.
            Formatter imzası: Callable[[Dict[str, Any]], str]

    Notlar:
        - EventBus callback imzası: cb(payload, msg_id)
        - Topic adı callback'e geçmiyor; her pattern için ayrı handler oluşturuluyor.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        subscriptions: Optional[Dict[str, Callable[[Dict[str, Any]], str]]] = None,
        parse_mode: str = "HTML",
        min_interval: float = 0.5,
        timeout: float = 10.0,
    ) -> None:
        self.bus = bus
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        if not self.token or not self.chat_id:
            raise ValueError("TelegramSink: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID eksik.")

        # Varsayılan: sadece signal:* dinle
        self.subscriptions: Dict[str, Callable[[Dict[str, Any]], str]] = subscriptions or {
            "signal:*": format_signal_message
        }

        self.sender = TelegramSender(
            self.token, self.chat_id,
            parse_mode=parse_mode, min_interval=min_interval, timeout=timeout
        )
        self._handlers: Dict[str, Callable[[Dict[str, Any], int], Any]] = {}
        self._bound = False

    def bind(self) -> None:
        if self._bound:
            return

        for pattern, formatter in self.subscriptions.items():
            async def _handler(
                payload: Dict[str, Any], 
                msg_id: int, 
                *args, 
                _fmt=formatter, _pat=pattern, 
                **kwargs
            ) -> None:
                try:
                    try:
                        text = _fmt(payload)
                    except Exception:
                        text = format_generic_message(payload)
                    await self.sender.send_message(text)
                except Exception as e:
                    print(f"[telegram] gönderim hatası ({_pat}): {e}")

            self._handlers[pattern] = _handler
            self.bus.subscribe(pattern, _handler)
        self._bound = True

    def unbind(self) -> None:
        if not self._bound:
            return
        for pattern, handler in list(self._handlers.items()):
            self.bus.unsubscribe(pattern, handler)
        self._handlers.clear()
        self._bound = False
