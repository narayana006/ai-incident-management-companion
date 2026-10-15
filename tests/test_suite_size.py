"""Guard against silent test-collection loss.

A setUpClass failure removes a whole class from the run without failing it, so
the suite can shrink while still reporting OK. This pins the collected count.
Update EXPECTED when tests are deliberately added or removed.
"""

from __future__ import annotations

import pathlib
import unittest

EXPECTED = 228
TESTS_DIR = pathlib.Path(__file__).resolve().parent


class SuiteSizeTest(unittest.TestCase):
    def test_collected_test_count_is_pinned(self) -> None:
        suite = unittest.defaultTestLoader.discover(str(TESTS_DIR), pattern="test_*.py")
        self.assertEqual(suite.countTestCases(), EXPECTED)


if __name__ == "__main__":
    unittest.main()
