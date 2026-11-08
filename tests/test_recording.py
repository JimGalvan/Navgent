import tempfile
import unittest
from pathlib import Path

import cv2

from navgent.browser.browser_manager import BrowserManager
from navgent.browser.browser_session import BrowserSession

SITE = Path(__file__).resolve().parent / "e2e" / "nav"


class RecordingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.manager = BrowserManager(headless=True)
        self.addAsyncCleanup(self.manager.stop)

    async def test_each_tab_is_recorded_after_close(self) -> None:
        browser = BrowserSession(self.manager, recording_dir=self.folder)
        await browser.attempt_navigate_and_observe((SITE / "home.html").as_uri())
        await browser.page.click("#home-catalog-new-tab")
        await browser.page.wait_for_timeout(500)
        self.assertEqual(browser.recording_paths, [])
        await browser.close()
        self.assertEqual(len(browser.recording_paths), 2)
        for path in browser.recording_paths:
            self.assertEqual(path.parent, self.folder)
            self.assertEqual(path.suffix, ".webm")
            video = cv2.VideoCapture(str(path))
            readable, _ = video.read()
            video.release()
            self.assertTrue(readable)

    async def test_nothing_is_recorded_without_a_folder(self) -> None:
        browser = BrowserSession(self.manager)
        await browser.attempt_navigate_and_observe((SITE / "home.html").as_uri())
        await browser.close()
        self.assertEqual(browser.recording_paths, [])
        self.assertEqual(list(self.folder.iterdir()), [])
