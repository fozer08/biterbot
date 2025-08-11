#!/usr/bin/env python3
"""
Basit Telegram mesaj gönderme scripti.
- TOKEN ve CHAT_ID'yi aşağıda doldurun ya da ortam değişkenleriyle verin:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
- Kullanım:
    python send_telegram_message.py "Merhaba dünya"
"""
import os
import sys
import asyncio
from dataclasses import dataclass
from typing import Optional

import aiohttp

# ---- AYARLAR ----
TOKEN = "8290926257:AAFv1sdhY9Pbjp90L2TTUXAPsk9E7pigKTE"
CHAT_ID = "-4927151540"


@dataclass
class TelegramSender:
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
        if not self.token or not self.chat_id:
            print("[telegram] token/chat_id eksik. Gönderim atlandı.")
            return

        url = f"{self._base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": self.parse_mode,
            "disable_web_page_preview": self.disable_web_page_preview,
        }

        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                if self.session is None:
                    async with aiohttp.ClientSession() as s:
                        async with s.post(url, json=payload, timeout=10) as resp:
                            if resp.status == 200:
                                print("[telegram] OK")
                                return
                            body = await resp.text()
                            raise RuntimeError(f"sendMessage {resp.status}: {body}")
                else:
                    async with self.session.post(url, json=payload, timeout=10) as resp:
                        if resp.status == 200:
                            print("[telegram] OK")
                            return
                        body = await resp.text()
                        raise RuntimeError(f"sendMessage {resp.status}: {body}")
            except Exception as e:
                last_err = e
                print(f"[telegram] Deneme {attempt+1} hata: {e}")
                await asyncio.sleep(0.5)
        if last_err:
            print(f"[telegram] Hata: {last_err}")


async def main():
    # Komut satırından mesaj al veya varsayılan metni kullan
    default_msg = "Test: Merhaba Telegram 👋"
    message = " ".join(sys.argv[1:]).strip() or default_msg

    sender = TelegramSender(
        token=TOKEN or None,
        chat_id=CHAT_ID or None,
    )
    await sender.send_message(message)


if __name__ == "__main__":
    asyncio.run(main())
