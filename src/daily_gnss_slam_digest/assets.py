from __future__ import annotations

from datetime import date
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_CANDIDATES = (
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
)


def ensure_article_assets(output_dir: Path, issue_date: date, focus_topic: str = "") -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "header": output_dir / f"{issue_date.isoformat()}-topic-header.jpg",
    }
    _make_topic_header(paths["header"], issue_date, focus_topic)
    return paths


def _make_topic_header(path: Path, issue_date: date, focus_topic: str) -> None:
    topic = _topic_theme(focus_topic)
    image = _canvas(900, 430)
    draw = ImageDraw.Draw(image)
    accent = topic["accent"]
    soft = topic["soft"]

    for radius, alpha in ((250, 35), (180, 48), (110, 64)):
        color = tuple(int(c * alpha / 255 + b * (255 - alpha) / 255) for c, b in zip(accent, (4, 13, 22)))
        draw.ellipse((560 - radius, 210 - radius, 560 + radius, 210 + radius), outline=color, width=2)

    draw.rounded_rectangle((52, 46, 178, 60), radius=7, fill=accent)
    draw.text((52, 80), "今日导航定位论文", font=_font(24), fill=(204, 230, 235))
    _draw_wrapped(draw, topic["title"], (52, 116), _font(44), (246, 252, 255), 500, line_gap=8, max_lines=2)
    _draw_wrapped(draw, topic["subtitle"], (54, 236), _font(22), (171, 204, 211), 474, line_gap=8, max_lines=2)

    x = 54
    y = 316
    for label in topic["chips"]:
        width = int(draw.textlength(label, font=_font(18))) + 28
        draw.rounded_rectangle((x, y, x + width, y + 34), radius=17, fill=(12, 38, 48), outline=soft, width=1)
        draw.text((x + 14, y + 7), label, font=_font(18), fill=(227, 246, 247))
        x += width + 10

    draw.text((54, 374), issue_date.isoformat(), font=_font(20), fill=(137, 174, 183))
    _draw_topic_visual(draw, topic["kind"], accent, soft)
    _save_jpeg(image, path)


def _topic_theme(focus_topic: str) -> dict[str, object]:
    topic = focus_topic or "导航定位热点论文"
    if "具身导航" in topic:
        return {
            "kind": "embodied",
            "title": topic,
            "subtitle": "从语言指令、视觉理解到移动机器人决策，关注模型怎样真正落到可执行导航。",
            "chips": ("VLM", "ObjectNav", "Policy"),
            "accent": (44, 218, 185),
            "soft": (52, 135, 145),
        }
    if "3DGS" in topic or "NeRF" in topic:
        return {
            "kind": "neural",
            "title": topic,
            "subtitle": "把稠密地图、相机位姿和实时重建放在一起看，重点关注表达能力和运行代价。",
            "chips": ("3DGS", "NeRF", "Dense SLAM"),
            "accent": (73, 195, 255),
            "soft": (58, 119, 164),
        }
    if "开放词汇" in topic:
        return {
            "kind": "semantic",
            "title": topic,
            "subtitle": "让地图不只记几何结构，也能记物体、语义和自然语言目标。",
            "chips": ("Open Vocabulary", "Scene Graph", "VLN"),
            "accent": (255, 196, 87),
            "soft": (144, 115, 55),
        }
    if "地点识别" in topic:
        return {
            "kind": "place",
            "title": topic,
            "subtitle": "跨季节、跨视角、跨传感器回到同一个地方，是长期自主系统的基本功。",
            "chips": ("Place Recognition", "Loop Closure", "Retrieval"),
            "accent": (151, 219, 85),
            "soft": (84, 133, 75),
        }
    if "多机器人" in topic:
        return {
            "kind": "multi_robot",
            "title": topic,
            "subtitle": "多台机器人共享约束、地图和相对位姿，关键在通信、鲁棒关联和一致性。",
            "chips": ("Multi-Agent", "Distributed Map", "Relative Pose"),
            "accent": (181, 145, 255),
            "soft": (104, 86, 160),
        }
    if "PNT" in topic or "GNSS" in topic:
        return {
            "kind": "pnt",
            "title": topic,
            "subtitle": "从卫星信号异常到完整性监测，重点看系统怎样识别干扰、欺骗和失锁。",
            "chips": ("Spoofing", "Jamming", "Integrity"),
            "accent": (255, 111, 92),
            "soft": (158, 78, 78),
        }
    if "退化场景" in topic or "里程计" in topic:
        return {
            "kind": "odometry",
            "title": topic,
            "subtitle": "当光照、纹理、结构或 GNSS 都不可靠时，看融合系统怎样稳住状态估计。",
            "chips": ("LIO/VIO", "Factor Graph", "Degeneracy"),
            "accent": (45, 219, 188),
            "soft": (52, 135, 145),
        }
    return {
        "kind": "generic",
        "title": topic,
        "subtitle": "把近期论文放到工程系统里读，关注问题定义、实验可信度和可迁移价值。",
        "chips": ("Navigation", "Localization", "Robotics"),
        "accent": (45, 219, 188),
        "soft": (52, 135, 145),
    }


def _draw_topic_visual(draw: ImageDraw.ImageDraw, kind: object, accent: tuple[int, int, int], soft: tuple[int, int, int]) -> None:
    if kind == "embodied":
        _draw_grid(draw, 570, 86, 250, 250, soft)
        points = [(598, 300), (650, 262), (700, 232), (750, 176), (802, 132)]
        draw.line(points, fill=accent, width=5, joint="curve")
        for x, y in points:
            draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=accent)
        draw.rounded_rectangle((600, 100, 735, 148), radius=18, fill=(14, 42, 54), outline=soft, width=2)
        draw.text((618, 114), "go to door", font=_font(20), fill=(236, 250, 251))
        _robot(draw, 610, 304, accent)
    elif kind == "neural":
        center = (692, 216)
        for i in range(90):
            angle = i * 0.52
            radius = 28 + (i % 18) * 5
            x = center[0] + math.cos(angle) * radius
            y = center[1] + math.sin(angle * 0.8) * radius * 0.55
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(accent[0], min(accent[1] + 20, 255), accent[2]))
        draw.polygon([(560, 300), (618, 264), (618, 336)], outline=soft, fill=None)
        draw.rectangle((538, 278, 560, 322), outline=accent, width=3)
        draw.line((618, 264, 760, 176), fill=soft, width=2)
        draw.line((618, 336, 760, 256), fill=soft, width=2)
    elif kind == "semantic":
        rooms = [(575, 120, 680, 222, "desk"), (690, 120, 810, 222, "chair"), (575, 236, 810, 318, "door")]
        for x1, y1, x2, y2, label in rooms:
            draw.rounded_rectangle((x1, y1, x2, y2), radius=14, outline=soft, width=3, fill=(11, 36, 46))
            draw.text((x1 + 18, y1 + 18), label, font=_font(20), fill=(246, 250, 255))
        draw.line((680, 171, 690, 171), fill=accent, width=4)
        draw.line((692, 236, 692, 222), fill=accent, width=4)
        draw.rounded_rectangle((614, 324, 760, 360), radius=18, fill=accent)
        draw.text((637, 331), "find a mug", font=_font(20), fill=(6, 22, 28))
    elif kind == "place":
        path = [(580, 260), (632, 154), (742, 136), (812, 224), (756, 312), (642, 318), (580, 260)]
        draw.line(path, fill=soft, width=4)
        for i, (x, y) in enumerate(path[:-1], start=1):
            draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=accent)
            draw.text((x - 5, y - 34), str(i), font=_font(18), fill=(235, 250, 251))
        for x, y in ((602, 108), (688, 254), (766, 92)):
            draw.rounded_rectangle((x, y, x + 68, y + 42), radius=8, outline=soft, width=2, fill=(13, 38, 48))
            draw.line((x + 12, y + 14, x + 56, y + 14), fill=accent, width=3)
            draw.line((x + 12, y + 28, x + 44, y + 28), fill=accent, width=3)
    elif kind == "multi_robot":
        nodes = [(598, 128), (750, 112), (820, 246), (690, 326), (570, 244)]
        for a, b in zip(nodes, nodes[1:] + nodes[:1]):
            draw.line((a, b), fill=soft, width=3)
        draw.line((598, 128, 820, 246), fill=soft, width=2)
        draw.line((750, 112, 690, 326), fill=soft, width=2)
        for i, (x, y) in enumerate(nodes, start=1):
            draw.ellipse((x - 24, y - 24, x + 24, y + 24), fill=(12, 40, 52), outline=accent, width=4)
            draw.text((x - 6, y - 12), str(i), font=_font(22), fill=(240, 251, 252))
    elif kind == "pnt":
        receiver = (704, 286)
        for x, y in ((590, 96), (705, 78), (818, 116)):
            draw.ellipse((x - 16, y - 16, x + 16, y + 16), fill=accent)
            draw.line((x, y, receiver[0], receiver[1]), fill=soft, width=2)
        for radius in (45, 78, 112):
            draw.arc((receiver[0] - radius, receiver[1] - radius, receiver[0] + radius, receiver[1] + radius), 205, 335, fill=accent, width=3)
        draw.polygon([(704, 232), (754, 254), (744, 324), (704, 352), (664, 324), (654, 254)], outline=accent, fill=(14, 39, 50))
        draw.text((686, 276), "PNT", font=_font(22), fill=(245, 250, 255))
        draw.line((810, 210, 846, 246), fill=(255, 230, 120), width=5)
        draw.line((846, 210, 810, 246), fill=(255, 230, 120), width=5)
    elif kind == "odometry":
        _draw_grid(draw, 572, 106, 260, 220, soft)
        robot = (694, 254)
        draw.rounded_rectangle((robot[0] - 42, robot[1] - 24, robot[0] + 42, robot[1] + 24), radius=12, fill=(13, 42, 52), outline=accent, width=3)
        for angle in range(-55, 56, 22):
            end = (
                robot[0] + math.cos(math.radians(angle - 90)) * 128,
                robot[1] + math.sin(math.radians(angle - 90)) * 128,
            )
            draw.line((robot, end), fill=soft, width=2)
        draw.line((620, 310, 772, 150), fill=accent, width=5)
        draw.line((620, 150, 772, 310), fill=(255, 230, 120), width=3)
    else:
        _draw_grid(draw, 572, 106, 260, 220, soft)
        draw.line((598, 286, 648, 224, 720, 242, 796, 148), fill=accent, width=5)
        for x, y in ((598, 286), (648, 224), (720, 242), (796, 148)):
            draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=accent)


def _draw_grid(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int, color: tuple[int, int, int]) -> None:
    for offset in range(0, width + 1, 40):
        draw.line((x + offset, y, x + offset, y + height), fill=color, width=1)
    for offset in range(0, height + 1, 40):
        draw.line((x, y + offset, x + width, y + offset), fill=color, width=1)


def _robot(draw: ImageDraw.ImageDraw, x: int, y: int, accent: tuple[int, int, int]) -> None:
    draw.rounded_rectangle((x, y, x + 58, y + 38), radius=12, fill=(11, 37, 48), outline=accent, width=3)
    draw.ellipse((x + 10, y + 26, x + 26, y + 42), fill=accent)
    draw.ellipse((x + 34, y + 26, x + 50, y + 42), fill=accent)
    draw.line((x + 44, y + 8, x + 70, y - 10), fill=accent, width=4)


def _draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    max_width: int,
    line_gap: int = 6,
    max_lines: int = 2,
) -> None:
    units = _text_units(text)
    lines: list[str] = []
    current = ""
    for unit in units:
        trial = current + unit
        if not current or draw.textlength(trial, font=font) <= max_width:
            current = trial
            continue
        lines.append(current.rstrip())
        current = unit.lstrip()
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current.rstrip())
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if len(lines) == max_lines and len("".join(lines)) < len(text):
        lines[-1] = _truncate_to_width(draw, lines[-1] + "...", font, max_width)

    x, y = xy
    line_height = font.size + line_gap
    for i, line in enumerate(lines):
        draw.text((x, y + i * line_height), line, font=font, fill=fill)


def _text_units(text: str) -> list[str]:
    units: list[str] = []
    buffer = ""
    for char in text:
        if char.isascii() and (char.isalnum() or char in "-+/_."):
            buffer += char
            continue
        if buffer:
            units.append(buffer)
            buffer = ""
        units.append(char)
    if buffer:
        units.append(buffer)
    return units


def _truncate_to_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    while text and draw.textlength(text, font=font) > max_width:
        text = text[:-4].rstrip() + "..."
    return text


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
