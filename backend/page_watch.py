"""Notices when the last browser page is closed while the program keeps running in the background.

The packaged app has no console window, so closing the tab looks like closing the program but
the server (and the unlocked archive) stays alive. Each page tells the server when it opens and
when it is closed; after a short grace period without any page (a reload closes and reopens one)
the server shows a native message box saying how to get back in and how to switch it off.
"""
import threading
from typing import Callable, Optional, Set


class PageWatcher:
    def __init__(self, on_all_closed: Callable[[], None], grace_seconds: float = 6.0):
        self._on_all_closed = on_all_closed
        self._grace = grace_seconds
        self._pages: Set[str] = set()
        self._timer: Optional[threading.Timer] = None
        self._stopping = False
        self._lock = threading.Lock()

    def opened(self, page_id: str) -> None:
        with self._lock:
            self._pages.add(page_id)
            self._cancel_timer()

    def closed(self, page_id: str) -> None:
        with self._lock:
            # only a page we have seen opening counts: a stray "closed" must not trigger a warning
            if page_id not in self._pages:
                return
            self._pages.discard(page_id)
            if self._pages or self._stopping:
                return
            self._cancel_timer()
            self._timer = threading.Timer(self._grace, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def stopping(self) -> None:
        """The user asked to quit: no warning needed."""
        with self._lock:
            self._stopping = True
            self._cancel_timer()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _fire(self) -> None:
        with self._lock:
            if self._pages or self._stopping:
                return
            self._timer = None
        self._on_all_closed()


def windows_message_box(text: str, title: str) -> bool:
    """Native Yes/No box (works without a console window). True if the user pressed Yes."""
    import ctypes
    MB_YESNO, MB_ICONINFORMATION, MB_DEFBUTTON2, MB_SETFOREGROUND, MB_TOPMOST = 0x4, 0x40, 0x100, 0x10000, 0x40000
    IDYES = 6
    flags = MB_YESNO | MB_ICONINFORMATION | MB_DEFBUTTON2 | MB_SETFOREGROUND | MB_TOPMOST
    return ctypes.windll.user32.MessageBoxW(0, text, title, flags) == IDYES
