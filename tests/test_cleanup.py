from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from daily_gnss_slam_digest.cleanup import CleanupConfig, OutputCleaner


class OutputCleanerTest(unittest.TestCase):
    def test_cleanup_removes_transient_and_stale_outputs_but_keeps_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "outputs"
            _write(output_root / "2026-06-20-gnss-slam-digest.json")
            _write(output_root / "2026-07-05-gnss-slam-digest.json")
            _write(output_root / "cache" / "arxiv" / "cached.xml")
            _write(output_root / "deepdives" / "01-old" / "article.html")
            _write(output_root / "deepdives-link-check" / "01-test" / "article.html")
            _write(output_root / "email_commands" / "20260701-090000" / "result.json")
            _write(output_root / "email_commands" / "20260702-090000" / "result.json")
            _write(output_root / "email_commands" / "20260703-090000" / "result.json")
            _write(output_root / "email_commands" / "20260704-090000" / "result.json")

            config = CleanupConfig(
                output_root=output_root,
                run_date=date(2026, 7, 5),
                daily_retention_days=8,
                email_retention_days=3,
                email_keep_latest=2,
                weekly_retention_days=70,
                log_retention_days=14,
                deepdives_output=output_root / "deepdives",
                dry_run=False,
            )

            with patch.dict(os.environ, {"OUTPUT_CLEAN_ENABLED": "1", "DEEPDIVE_CLEAN_BEFORE_RUN": "1"}):
                removed = OutputCleaner(config).run()

            self.assertGreaterEqual(removed, 5)
            self.assertFalse((output_root / "2026-06-20-gnss-slam-digest.json").exists())
            self.assertTrue((output_root / "2026-07-05-gnss-slam-digest.json").exists())
            self.assertFalse((output_root / "deepdives").exists())
            self.assertFalse((output_root / "deepdives-link-check").exists())
            self.assertFalse((output_root / "email_commands" / "20260701-090000").exists())
            self.assertFalse((output_root / "email_commands" / "20260702-090000").exists())
            self.assertTrue((output_root / "email_commands" / "20260703-090000").exists())
            self.assertTrue((output_root / "email_commands" / "20260704-090000").exists())
            self.assertTrue((output_root / "cache" / "arxiv" / "cached.xml").exists())


def _write(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
