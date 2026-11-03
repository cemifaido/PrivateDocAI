import threading
import unittest

from backend.page_watch import PageWatcher


class PageWatcherTests(unittest.TestCase):
    def make(self, grace=0.15):
        fired = threading.Event()
        return PageWatcher(fired.set, grace_seconds=grace), fired

    def test_warns_when_last_page_closes(self):
        watcher, fired = self.make()
        watcher.opened("a")
        watcher.closed("a")
        self.assertTrue(fired.wait(1.0))

    def test_no_warning_while_another_page_is_open(self):
        watcher, fired = self.make()
        watcher.opened("a")
        watcher.opened("b")
        watcher.closed("a")
        self.assertFalse(fired.wait(0.5))

    def test_reload_does_not_warn(self):
        watcher, fired = self.make()
        watcher.opened("a")
        watcher.closed("a")      # the old page goes away...
        watcher.opened("b")      # ...and the reloaded one arrives within the grace period
        self.assertFalse(fired.wait(0.5))

    def test_no_warning_after_quit_was_requested(self):
        watcher, fired = self.make()
        watcher.opened("a")
        watcher.stopping()
        watcher.closed("a")
        self.assertFalse(fired.wait(0.5))

    def test_quit_during_grace_period_cancels_the_warning(self):
        watcher, fired = self.make(grace=0.3)
        watcher.opened("a")
        watcher.closed("a")
        watcher.stopping()
        self.assertFalse(fired.wait(0.6))

    def test_unknown_page_closing_is_ignored(self):
        watcher, fired = self.make()
        watcher.closed("never-opened")
        self.assertFalse(fired.wait(0.5))


if __name__ == "__main__":
    unittest.main()
