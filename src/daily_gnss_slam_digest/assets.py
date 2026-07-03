from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_CANDIDATES = (
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
)


def ensure_article_assets(output_dir: Path, issue_date: date) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "methodology": output_dir / f"{issue_date.isoformat()}-methodology.jpg",
        "rubric": output_dir / f"{issue_date.isoformat()}-reading-rubric.jpg",
    }
    _make_methodology(paths["methodology"])
    _make_rubric(paths["rubric"])
    return paths


def _make_methodology(path: Path) -> None:
    image = _canvas(900, 500)
    draw = ImageDraw.Draw(image)
    _header(draw, "方法论：从论文流到工程判断", "不只按热度推荐，而是按主题贴合度、系统价值和新鲜度做每日筛选")

    steps = [
        ("01", "主题检索", "GNSS 欺骗/干扰\n多模态融合\nSLAM/里程计", (52, 158)),
        ("02", "信号打分", "关键词命中\n主题覆盖\n发布时间衰减", (330, 158)),
        ("03", "读法解读", "问题定义\n观测量/约束\n工程迁移价值", (608, 158)),
    ]
    for number, title, body, (x, y) in steps:
        _card(draw, x, y, 238, 220)
        draw.text((x + 24, y + 24), number, font=_font(34), fill=(45, 219, 188))
        draw.text((x + 24, y + 74), title, font=_font(30), fill=(245, 250, 255))
        draw.multiline_text((x + 24, y + 122), body, font=_font(22), fill=(177, 207, 215), spacing=10)

    _arrow(draw, (290, 268), (320, 268))
    _arrow(draw, (568, 268), (598, 268))
    draw.text((52, 422), "输出：今日速览 + 重点推荐 + 系统启发 + 明日检索关键词", font=_font(22), fill=(205, 229, 233))
    _save_jpeg(image, path)


def _make_rubric(path: Path) -> None:
    image = _canvas(900, 470)
    draw = ImageDraw.Draw(image)
    _header(draw, "推荐阅读框架", "按四个问题快速扫读，先抓系统价值，再决定是否阅读全文")

    rows = [
        ("问题", "它解决的是欺骗检测、融合退化，还是地图/里程计鲁棒性？"),
        ("观测", "用了哪些可观测量：C/N0、AGC、GNSS、IMU、LiDAR、视觉、热成像？"),
        ("约束", "融合在前端、滤波器、因子图，还是后端地图优化里发生？"),
        ("迁移", "数据集、实时性、误报率和失败案例是否足够支撑工程复用？"),
    ]
    y = 154
    for label, body in rows:
        draw.rounded_rectangle((52, y, 848, y + 54), radius=14, fill=(12, 34, 45), outline=(40, 111, 124), width=1)
        draw.rounded_rectangle((72, y + 11, 142, y + 43), radius=10, fill=(39, 216, 185))
        draw.text((91, y + 14), label, font=_font(20), fill=(1, 23, 28))
        draw.text((166, y + 13), body, font=_font(22), fill=(226, 244, 246))
        y += 66

    _save_jpeg(image, path)


def _canvas(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height), (4, 13, 22))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = (
            int(4 + 8 * ratio),
            int(13 + 20 * ratio),
            int(22 + 25 * ratio),
        )
        draw.line((0, y, width, y), fill=color)
    for x in range(0, width, 60):
        draw.line((x, 0, x - 240, height), fill=(7, 39, 54), width=1)
    for y in range(48, height, 56):
        draw.line((0, y, width, y), fill=(7, 39, 54), width=1)
    return image


def _header(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    draw.rounded_rectangle((52, 44, 174, 60), radius=8, fill=(45, 219, 188))
    draw.text((52, 78), title, font=_font(38), fill=(245, 250, 255))
    draw.text((54, 122), subtitle, font=_font(21), fill=(158, 195, 204))


def _card(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int) -> None:
    draw.rounded_rectangle((x, y, x + width, y + height), radius=20, fill=(10, 29, 40), outline=(39, 118, 132), width=2)
    draw.rounded_rectangle((x + 14, y + 14, x + width - 14, y + 18), radius=2, fill=(45, 219, 188))


def _arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int]) -> None:
    draw.line((start, end), fill=(45, 219, 188), width=4)
    x, y = end
    draw.polygon([(x, y), (x - 12, y - 8), (x - 12, y + 8)], fill=(45, 219, 188))


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


def _save_jpeg(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=92, optimize=True, progressive=True)
