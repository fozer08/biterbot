from __future__ import annotations
import asyncio
import inspect
import re
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, Dict, Set, Deque, Optional, List, Tuple


CbType = Callable[[Any, int], Awaitable[None]]  # cb(payload, msg_id)

class EventBus:
    """
    Wildcard destekli asenkron EventBus. `msg_id` tabanlı dedupe içerir.

    Args:
        dedupe_window: Dedupe için tutulacak (topic, msg_id) halka tampon boyutu.

    Return:
        None
    """

    def __init__(self, *, dedupe_window: int = 8192) -> None:
        self._subs: Dict[str, Set[CbType]] = defaultdict(set)
        self._glob_cache: Dict[str, re.Pattern] = {}
        self._lock = asyncio.Lock()
        self._next_id: int = 1

        # _seen: Son dedupe_window içindeki (topic, msg_id) çiftlerini
        # O(1) ortalama hızda var mı diye kontrol etmek için tutar (hash set).
        # _seen_order: FIFO sırasını tutar; maxlen dolunca en eski öğe çıkarılır
        # ve _seen'den silinir (bellek yönetimi + pencere kaydırma).
        self._seen: Set[Tuple[str, int]] = set()
        self._seen_order: Deque[Tuple[str, int]] = deque(maxlen=dedupe_window)

    def _is_pattern(self, key: str) -> bool:
        """
        Basit yardımcı: key içinde '*' var mı?

        Args:
            key: Topic ya da desen.

        Return:
            bool: Desen olup olmadığı.
        """
        return '*' in key

    def _compile(self, pattern: str) -> re.Pattern:
        """
        Glob benzeri pattern'i regex'e çevir.

        Args:
            pattern: '*' içerebilen desen.

        Return:
            re.Pattern: Derlenmiş regex.
        """
        if (rex := self._glob_cache.get(pattern)) is not None:
            return rex
        parts: List[str] = []
        for ch in pattern:
            parts.append('.*' if ch == '*' else re.escape(ch))
        rex = re.compile('^' + ''.join(parts) + '$')
        self._glob_cache[pattern] = rex
        return rex

    def subscribe(self, topic_or_pattern: str, cb: CbType) -> None:
        """
        Bir topic ya da desene callback ekler.

        Args:
            topic_or_pattern: Tam topic veya '*' içeren desen.
            cb: 'async def cb(payload, msg_id)' imzalı fonksiyon.
        """
        self._subs[topic_or_pattern].add(cb)

    def unsubscribe(self, topic_or_pattern: str, cb: CbType) -> None:
        """
        Aboneliği kaldırır.

        Args:
            topic_or_pattern: Tam topic veya desen.
            cb: Kaldırılacak callback.
        """
        lst = self._subs.get(topic_or_pattern)
        if lst and cb in lst:
            lst.remove(cb)
            if not lst:
                self._subs.pop(topic_or_pattern, None)
        self._glob_cache.pop(topic_or_pattern, None)

    async def _next_msg_id(self) -> int:
        """
        Monoton artan bir msg_id üretir.
        """
        async with self._lock:
            mid = self._next_id
            self._next_id += 1
            return mid

    def _mark_seen(self, topic: str, msg_id: int) -> None:
        """
        (topic, msg_id) kombinasyonunu görülmüş olarak işaretler.

        Args:
            topic: Yayın yapılan topic.
            msg_id: Mesaj kimliği.
        """
        key = (topic, msg_id)
        self._seen.add(key)
        self._seen_order.append(key)
        while len(self._seen_order) > self._seen_order.maxlen:
            old = self._seen_order.popleft()
            self._seen.discard(old)

    async def publish(
        self,
        topic: str,
        payload: Any,
        *,
        msg_id: Optional[int] = None,
        dedupe: bool = False,
    ) -> int:
        """
        Eşleşen aboneleri çağır ve kullanılan msg_id'yi döndür.

        Args:
            topic: Yayın topic'i.
            payload: Taşınan veri.
            msg_id: Dışarıdan gelen bir id; yoksa üretilecek.
            dedupe: True ise (topic, msg_id) tekrarları düşer.

        Return:
            int: Kullanılan msg_id.
        """
        if msg_id is None:
            msg_id = await self._next_msg_id()

        if dedupe and (topic, msg_id) in self._seen:
            return msg_id

        callbacks: Set[CbType] = set()
        for key, cbs in list(self._subs.items()):
            try:
                if self._is_pattern(key):
                    if self._compile(key).match(topic):
                        callbacks.update(cbs)
                elif key == topic:
                    callbacks.update(cbs)
            except Exception:
                continue

        if callbacks:
            coros: List[Awaitable[None]] = []
            for cb in list(callbacks):
                if inspect.iscoroutinefunction(cb):
                    coros.append(cb(payload, msg_id))
                else:
                    coros.append(asyncio.to_thread(cb, payload, msg_id))
            results = await asyncio.gather(*coros, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    print(f"[EventBus] callback error on '{topic}': {r}")

        if dedupe:
            self._mark_seen(topic, msg_id)

        return msg_id
