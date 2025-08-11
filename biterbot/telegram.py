"""Telegram entegrasyonu

Bu modül, EventBus üzerindeki sinyal yayınlarını yakalayıp Telegram'a
otomatik iletmek için basit bir yardımcı sağlar.

Kullanım (main.py içinde):
    from .telegram import TelegramSink

    bus = EventBus()
    # ... feed, strateji/adaptör kurulumları ...
    tg = TelegramSink(bus)  # TOKEN/CHAT_ID ortam değişkenlerinden okunur
    tg.bind()               # varsayılan olarak "signal:*" pattern'ine abone olur

Gerekli ortam değişkenleri:
    TELEGRAM_BOT_TOKEN = "123456:ABCDEF..."
    TELEGRAM_CHAT_ID   = "123456789"  # kullanıcı ya da grup/chat id

Bağımlılıklar:
    aiohttp

Notlar:
- Mesaj biçimi HTML'dir. İsterseniz parse_mode parametresi ile MarkdownV2'a
  da çevirebilirsiniz.
- Bu modül yalnızca mesaj göndermek içindir; polling/webhook kurulumu yoktur.
"""
from __future__ import annotations

import os
import json
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aiohttp

from .eventbus import EventBus

__all__ = [
    "TelegramSender",
    "TelegramSink",
    "format_signal_message",
]


@dataclass
class TelegramSender:
    """Basit Telegram Bot API istemcisi.

    Args:
        token: Bot token. None ise TELEGRAM_BOT_TOKEN ortamından okunur.
        chat_id: Mesajın gönderileceği chat. None ise TELEGRAM_CHAT_ID ortamından okunur.
        session: Dışarıdan verilen aiohttp.ClientSession (opsiyonel).
        parse_mode: "HTML" veya "MarkdownV2". Varsayılan: "HTML".
        disable_web_page_preview: Link önizlemelerini kapat.

    Return:
        None
    """

    token: Optional[str] = None
    chat_id: Optional[str] = None
    session: Optional[aiohttp.ClientSession] = None
    parse_mode: str = "HTML"
    disable_web_page_preview: bool = True

    def __post_init__(self) -> None:
        if self.token is None:
            self.token = os.getenv("TELEGRAM_BOT_TOKEN") or None
        if self.chat_id is None:
            self.chat_id = os.getenv("TELEGRAM_CHAT_ID") or None
        if not self.token:
            print("[telegram] Uyarı: TELEGRAM_BOT_TOKEN tanımlı değil.")
        if not self.chat_id:
            print("[telegram] Uyarı: TELEGRAM_CHAT_ID tanımlı değil.")

    @property
    def _base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}" if self.token else ""

    async def send_message(self, text: str) -> None:
        """Telegram'a mesaj gönder.

        Args:
            text: Gönderilecek metin.
        Return:
            None
        """
        if not self.token or not self.chat_id:
            return

        url = f"{self._base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": self.parse_mode,
            "disable_web_page_preview": self.disable_web_page_preview,
        }

        # Basit retry: geçici ağ hataları için 3 deneme
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                if self.session is None:
                    async with aiohttp.ClientSession() as s:
                        async with s.post(url, json=payload, timeout=10) as resp:
                            if resp.status == 200:
                                return
                            body = await resp.text()
                            raise RuntimeError(f"sendMessage {resp.status}: {body}")
                else:
                    async with self.session.post(url, json=payload, timeout=10) as resp:
                        if resp.status == 200:
                            return
                        body = await resp.text()
                        raise RuntimeError(f"sendMessage {resp.status}: {body}")
            except Exception as e:
                last_err = e
                await asyncio.sleep(0.5)
        if last_err:
            print(f"[telegram] Hata: {last_err}")


def _ms_to_iso(ms: Optional[int]) -> str:
    """ms epoch'u ISO8601 UTC'ye çevirir."""
    if not ms:
        return "-"
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def format_signal_message(payload: Dict[str, Any]) -> str:
    """Sinyal payload'unu Telegram için biçimlendirir.

    Beklenen payload (adapters.SignalAdaptor ile uyumlu):
        {
          "name": str,
          "symbol": str,
          "interval": str,
          "trade_signal": "LONG"|"SHORT"|"EXIT",
          "close_time": int  # ms
        }

    Args:
        payload: EventBus ile gelen sinyal sözlüğü.
    Return:
        str: HTML biçiminde mesaj.
    """
    name = str(payload.get("name", "-"))
    symbol = str(payload.get("symbol", "-"))
    interval = str(payload.get("interval", "-"))
    signal = str(payload.get("trade_signal", "-"))
    close_time = int(payload.get("close_time", 0) or 0)

    emoji = {
        "LONG": "🟢",
        "SHORT": "🔴",
        "EXIT": "⚪",
    }.get(signal, "🔔")

    fields = [
        f"<b>{emoji} Sinyal</b>",
        f"• Strateji: <b>{name}</b>",
        f"• Enstrüman: <b>{symbol}</b>",
        f"• Periyot: <b>{interval}</b>",
        f"• Yön: <b>{signal}</b>",
    ]

    if close_time:
        fields.append(f"• Kapanış: <code>{_ms_to_iso(close_time)}</code>")

    # Opsiyonel: kalan alanları bir önizleme olarak ekle (çok uzunsa kısalt)
    extras = {k: v for k, v in payload.items() if k not in {
        "name", "symbol", "interval", "trade_signal", "close_time"}}
    if extras:
        preview = json.dumps(extras, ensure_ascii=False)
        if len(preview) > 400:
            preview = preview[:400] + "…"
        fields.append(f"• Detay: <code>{preview}</code>")

    return "\n".join(fields)


class TelegramSink:
    """
    EventBus sinyallerini Telegram'a ileten yardımcı.

    Varsayılan olarak "signal:*" desenine abone olur ve her sinyalde
    biçimlendirilmiş bir mesaj gönderir.

    Args:
        bus: EventBus örneği.
        sender: Özelleştirilebilir TelegramSender. None ise varsayılan oluşturulur.
        topic_pattern: Abone olunacak topic ya da pattern. Varsayılan: "signal:*".

    Return:
        None
    """

    def __init__(
        self,
        bus: EventBus,
        sender: Optional[TelegramSender] = None,
        *,
        topic_pattern: str = "signal:*",
    ) -> None:
        self.bus = bus
        self.sender = sender or TelegramSender()
        self.topic_pattern = topic_pattern
        self._bound = False

    def bind(self) -> None:
        """
        EventBus aboneliğini aktif eder.
        """
        if self._bound:
            return
        self.bus.subscribe(self.topic_pattern, self._on_signal)
        self._bound = True

    def unbind(self) -> None:
        """
        EventBus aboneliğini kaldırır.
        """
        if not self._bound:
            return
        self.bus.unsubscribe(self.topic_pattern, self._on_signal)
        self._bound = False

    async def _on_signal(self, payload: Dict[str, Any], msg_id: int) -> None:
        """EventBus callback'i: sinyali biçimlendirip gönderir.

        Args:
            payload: Sinyal verisi.
            msg_id: EventBus mesaj kimliği (genellikle close_time).
        """
        try:
            text = format_signal_message(payload)
            await self.sender.send_message(text)
        except Exception as e:
            print(f"[telegram] gönderim hatası: {e}")
