#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_CANDIDATES = (
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a WeChat article cover image.")
    parser.add_argument("--input", required=True, type=Path, help="Generated background image.")
    parser.add_argument("--output", default=Path("outputs/wechat-cover-gnss-slam.jpg"), type=Path)
    args = parser.parse_args()

    cover = build_cover(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cover.save(args.output, format="JPEG", quality=92, optimize=True, progressive=True)
    print(args.output)
    return 0


def build_cover(input_path: Path) -> Image.Image:
    target_w, target_h = 900, 383
    image = Image.open(input_path).convert("RGB")
    image = _cover_resize(image, target_w, target_h)

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((0, 0, 500, target_h), fill=(0, 8, 16, 150))
    draw.rectangle((0, 0, target_w, target_h), fill=(0, 0, 0, 22))
    image = Image.alpha_composite(image.convert("RGBA"), overlay)

    draw = ImageDraw.Draw(image)
    title_font = _font(42)
    subtitle_font = _font(24)
    meta_font = _font(18)

    x = 54
    y = 78
    accent = (49, 224, 186, 255)
    white = (245, 250, 255, 255)
    muted = (168, 204, 214, 255)

    draw.rounded_rectangle((x, y - 22, x + 116, y - 6), radius=8, fill=accent)
    draw.text((x, y), "每日论文推荐", font=subtitle_font, fill=muted)
    draw.text((x, y + 42), "GNSS 欺骗检测", font=title_font, fill=white)
    draw.text((x, y + 92), "多模态融合 · SLAM", font=title_font, fill=white)
    draw.text((x, y + 160), "Paper Digest for Robust Navigation", font=meta_font, fill=muted)
    draw.text((x, y + 194), "arXiv · Robotics · PNT Integrity", font=meta_font, fill=(116, 180, 190, 255))

    return image.convert("RGB")


def _cover_resize(image: Image.Image, width: int, height: int) -> Image.Image:
    src_w, src_h = image.size
    scale = max(width / src_w, height / src_h)
    resized = image.resize((round(src_w * scale), round(src_h * scale)), Image.Resampling.LANCZOS)
    left = max((resized.width - width) // 2, 0)
    top = max((resized.height - height) // 2, 0)
    return resized.crop((left, top, left + width, top + height))


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


if __name__ == "__main__":
    raise SystemExit(main())
