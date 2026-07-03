#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from daily_gnss_slam_digest.wechat import WeChatConfig, WeChatPublisher


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload a cover image to WeChat and save media_id.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--env-file", default=Path(".env"), type=Path)
    args = parser.parse_args()

    load_env(args.env_file)
    publisher = WeChatPublisher(WeChatConfig.from_env(require_thumb_media_id=False))
    token = publisher.get_access_token()
    result = publisher.upload_permanent_image(token, args.image)
    media_id = result.get("media_id")
    if not media_id:
        raise RuntimeError(f"WeChat upload response missing media_id: {result}")
    update_env(args.env_file, "WECHAT_THUMB_MEDIA_ID", str(media_id))
    print(f"uploaded_media_id={media_id}")
    return 0


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def update_env(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            new_lines.append(f'{key}="{value}"')
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f'{key}="{value}"')
    path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
