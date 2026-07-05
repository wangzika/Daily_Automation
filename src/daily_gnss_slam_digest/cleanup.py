from __future__ import annotations

import argparse
import os
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


DAILY_FILE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})-(?:gnss-slam-digest|topic-header|methodology|reading-rubric)\.(?:html|json|md|jpg)$"
)
EMAIL_RUN_RE = re.compile(r"^\d{8}-\d{6}$")
WEEKLY_FILE_RE = re.compile(r"^(?P<year>\d{4})-W(?P<week>\d{2})-gnss-slam-weekly\.(?:html|json|md)$")


@dataclass(frozen=True)
class CleanupConfig:
    output_root: Path
    run_date: date
    daily_retention_days: int
    email_retention_days: int
    email_keep_latest: int
    weekly_retention_days: int
    log_retention_days: int
    deepdives_output: Path | None
    dry_run: bool


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = CleanupConfig(
        output_root=args.output_root,
        run_date=args.run_date,
        daily_retention_days=args.daily_retention_days,
        email_retention_days=args.email_retention_days,
        email_keep_latest=args.email_keep_latest,
        weekly_retention_days=args.weekly_retention_days,
        log_retention_days=args.log_retention_days,
        deepdives_output=args.deepdives_output,
        dry_run=args.dry_run,
    )
    cleaner = OutputCleaner(config)
    removed = cleaner.run()
    print(f"Output cleanup finished: {removed} item(s) removed.")
    return 0


class OutputCleaner:
    def __init__(self, config: CleanupConfig) -> None:
        self.config = config
        self.output_root = config.output_root.resolve()

    def run(self) -> int:
        if _is_disabled(os.getenv("OUTPUT_CLEAN_ENABLED", "1")):
            print("Output cleanup skipped: OUTPUT_CLEAN_ENABLED is disabled.")
            return 0

        self.config.output_root.mkdir(parents=True, exist_ok=True)
        removed = 0
        removed += self._remove_transient_dirs()
        removed += self._clean_deepdives_output()
        removed += self._remove_stale_daily_files()
        removed += self._remove_stale_email_runs()
        removed += self._remove_stale_weekly_files()
        removed += self._remove_stale_logs()
        removed += self._remove_path(self.config.output_root / ".DS_Store")
        return removed

    def _remove_transient_dirs(self) -> int:
        removed = 0
        candidates: set[Path] = set()
        patterns = (
            "deepdives-check",
            "deepdives-variant-check",
            "deepdives-draft-test",
            "deepdives-link-check",
            "deepdives-draft-link-check",
            "deepdives-*-check",
            "deepdives-*-test",
        )
        for pattern in patterns:
            for path in self.config.output_root.glob(pattern):
                if path.is_dir():
                    candidates.add(path)
        for path in sorted(candidates):
            removed += self._remove_path(path)
        return removed

    def _clean_deepdives_output(self) -> int:
        target = self.config.deepdives_output
        if target is None or _is_disabled(os.getenv("DEEPDIVE_CLEAN_BEFORE_RUN", "1")):
            return 0
        if not target.exists():
            return 0
        target = target.resolve()
        protected = {
            self.output_root,
            self.output_root / "cache",
            self.output_root / "logs",
            self.output_root / "weekly",
            self.output_root / "email_commands",
        }
        if target in protected:
            print(f"Output cleanup skipped protected deep-dive target: {target}")
            return 0
        return self._remove_path(target)

    def _remove_stale_daily_files(self) -> int:
        cutoff = self.config.run_date - timedelta(days=self.config.daily_retention_days)
        removed = 0
        for path in self.config.output_root.iterdir():
            if not path.is_file():
                continue
            match = DAILY_FILE_RE.match(path.name)
            if not match:
                continue
            item_date = date.fromisoformat(match.group("date"))
            if item_date < cutoff:
                removed += self._remove_path(path)
        return removed

    def _remove_stale_email_runs(self) -> int:
        root = self.config.output_root / "email_commands"
        if not root.exists():
            return 0

        runs = sorted(
            (path for path in root.iterdir() if path.is_dir() and EMAIL_RUN_RE.match(path.name)),
            key=lambda path: path.name,
            reverse=True,
        )
        keep = set(runs[: max(self.config.email_keep_latest, 0)])
        cutoff = datetime.combine(self.config.run_date, datetime.min.time()) - timedelta(days=self.config.email_retention_days)

        removed = 0
        for path in runs:
            if path in keep:
                continue
            run_time = datetime.strptime(path.name, "%Y%m%d-%H%M%S")
            if run_time < cutoff or len(runs) > self.config.email_keep_latest:
                removed += self._remove_path(path)
        return removed

    def _remove_stale_weekly_files(self) -> int:
        root = self.config.output_root / "weekly"
        if not root.exists():
            return 0
        cutoff = self.config.run_date - timedelta(days=self.config.weekly_retention_days)
        removed = 0
        for path in root.iterdir():
            if not path.is_file():
                continue
            match = WEEKLY_FILE_RE.match(path.name)
            if not match:
                continue
            item_date = date.fromisocalendar(int(match.group("year")), int(match.group("week")), 7)
            if item_date < cutoff:
                removed += self._remove_path(path)
        return removed

    def _remove_stale_logs(self) -> int:
        root = self.config.output_root / "logs"
        if not root.exists():
            return 0
        cutoff = datetime.combine(self.config.run_date, datetime.min.time()) - timedelta(days=self.config.log_retention_days)
        removed = 0
        for path in root.iterdir():
            if not path.is_file():
                continue
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                continue
            if modified < cutoff:
                removed += self._remove_path(path)
        return removed

    def _remove_path(self, path: Path) -> int:
        if not path.exists():
            return 0
        resolved = path.resolve()
        if resolved == self.output_root:
            print(f"Output cleanup skipped output root: {resolved}")
            return 0
        if not _is_relative_to(resolved, self.output_root):
            print(f"Output cleanup skipped unsafe path: {resolved}")
            return 0
        if self.config.dry_run:
            print(f"Would remove: {resolved}")
            return 1
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        print(f"Removed: {resolved}")
        return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean generated output folders before automation runs.")
    parser.add_argument("--output-root", type=Path, default=Path(os.getenv("DIGEST_OUTPUT_DIR", "outputs")))
    parser.add_argument("--run-date", type=date.fromisoformat, default=date.fromisoformat(os.getenv("DIGEST_DATE", date.today().isoformat())))
    parser.add_argument("--daily-retention-days", type=int, default=int(os.getenv("OUTPUT_DAILY_RETENTION_DAYS", "8")))
    parser.add_argument("--email-retention-days", type=int, default=int(os.getenv("OUTPUT_EMAIL_RETENTION_DAYS", "3")))
    parser.add_argument("--email-keep-latest", type=int, default=int(os.getenv("OUTPUT_EMAIL_KEEP_LATEST", "3")))
    parser.add_argument("--weekly-retention-days", type=int, default=int(os.getenv("OUTPUT_WEEKLY_RETENTION_DAYS", "70")))
    parser.add_argument("--log-retention-days", type=int, default=int(os.getenv("OUTPUT_LOG_RETENTION_DAYS", "14")))
    parser.add_argument("--deepdives-output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _is_disabled(value: str) -> bool:
    return value.strip().lower() in {"0", "false", "no", "off"}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
