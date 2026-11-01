"""把用户提供的走路 GIF 转成项目可用的像素矩阵 JSON。

来源素材的背景是烘焙进去的棋盘格，且经过 JPEG 压缩（同一个色块会有几十种
近似色），不能直接当像素画用。处理流程：

1. 从四边泛洪，把"高亮度 + 近乎无彩色"的像素判为背景并剔除；
2. 按 20px 网格采样，每格取不透明像素的中位色（抑制压缩噪点）；
3. 把每格颜色映射到坐姿猫素材的调色板（同色系，保证两只猫配得上）；
4. 8 帧取并集的包围盒，统一裁切，保证动画不抖；
5. 输出 ``assets/cat/cat_walk.json``，并顺手生成一张预览图。

用法::

    python tools/extract_walk_frames.py <gif 路径>
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageSequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SIT_ASSET = PROJECT_ROOT / "assets" / "cat" / "cat_sit.json"
OUTPUT = PROJECT_ROOT / "assets" / "cat" / "cat_walk.json"
PREVIEW = PROJECT_ROOT / "assets" / "cat" / "cat_walk_preview.png"

# 源 GIF 的像素块边长。实测 20px 会把腿和耳朵吞掉（整只猫只有 18x18 格），
# 10px 才能还原成 35x35 的可辨认像素画，与坐姿猫的像素密度也更接近。
CELL = 10
OPAQUE_RATIO = 0.2   # 一格中至少这么多像素不透明，才算"有内容"（腿很细，不能太高）


def is_background(color: tuple[int, int, int, int]) -> bool:
    """棋盘格背景：高亮度、几乎无彩色。"""
    red, green, blue, alpha = color
    if alpha < 40:
        return True
    high = max(red, green, blue)
    low = min(red, green, blue)
    return high >= 225 and (high - low) <= 14


def background_mask(image: Image.Image) -> list[list[bool]]:
    """从四边泛洪，返回 mask[x][y] = True 表示"属于猫"。"""
    width, height = image.size
    pixels = image.load()
    visited = [[False] * height for _ in range(width)]
    queue: deque[tuple[int, int]] = deque()

    def push(x: int, y: int) -> None:
        if 0 <= x < width and 0 <= y < height and not visited[x][y]:
            if is_background(pixels[x, y]):
                visited[x][y] = True
                queue.append((x, y))

    for x in range(width):
        push(x, 0)
        push(x, height - 1)
    for y in range(height):
        push(0, y)
        push(width - 1, y)
    while queue:
        x, y = queue.popleft()
        push(x + 1, y)
        push(x - 1, y)
        push(x, y + 1)
        push(x, y - 1)

    return [[not visited[x][y] for y in range(height)] for x in range(width)]


def cell_color(image: Image.Image, mask, cx: int, cy: int) -> tuple[int, int, int] | None:
    """取一格的中位色；不透明像素太少则返回 None。"""
    pixels = image.load()
    samples = []
    for y in range(cy * CELL, (cy + 1) * CELL):
        for x in range(cx * CELL, (cx + 1) * CELL):
            if y < image.height and x < image.width and mask[x][y]:
                samples.append(pixels[x, y][:3])
    if len(samples) < CELL * CELL * OPAQUE_RATIO:
        return None
    return tuple(int(statistics.median([s[i] for s in samples])) for i in range(3))


def nearest_symbol(color: tuple[int, int, int], palette: dict[str, str]) -> str:
    """把颜色映射到最近的调色板符号（加权 RGB 距离，更贴近人眼）。"""
    best, best_distance = "#", float("inf")
    for symbol, hex_value in palette.items():
        target = tuple(int(hex_value[i : i + 2], 16) for i in (1, 3, 5))
        distance = (
            2 * (color[0] - target[0]) ** 2
            + 4 * (color[1] - target[1]) ** 2
            + 3 * (color[2] - target[2]) ** 2
        )
        if distance < best_distance:
            best, best_distance = symbol, distance
    return best


def frame_grid(image: Image.Image, palette: dict[str, str]) -> list[list[str]]:
    mask = background_mask(image)
    cols = image.width // CELL
    rows = image.height // CELL
    grid = []
    for cy in range(rows):
        row = []
        for cx in range(cols):
            color = cell_color(image, mask, cx, cy)
            row.append(" " if color is None else nearest_symbol(color, palette))
        grid.append(row)
    return grid


def denoise(grid: list[list[str]]) -> list[list[str]]:
    """去掉孤立噪点。

    源图经过 JPEG 压缩，边缘会渗出零星的粉色/深棕像素，单看是一格，放大就
    成了猫背上的杂点。规则：某格的四邻没有同色格时，用它邻居里最多的颜色替换。
    只处理"孤立"格，轮廓和细节（相邻的深棕边线）不会被误伤。
    """
    rows, cols = len(grid), len(grid[0])
    result = [row[:] for row in grid]
    for y in range(rows):
        for x in range(cols):
            symbol = grid[y][x]
            if symbol == " ":
                continue
            neighbours = []
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < rows and 0 <= nx < cols:
                    neighbours.append(grid[ny][nx])
            if symbol in neighbours:
                continue
            filled = [n for n in neighbours if n != " "]
            if filled:
                result[y][x] = max(set(filled), key=filled.count)
    return result


def trim(grids: list[list[list[str]]]) -> tuple[list[list[list[str]]], int, int]:
    """按所有帧的并集包围盒裁切，保证 8 帧对得齐。"""
    top, bottom, left, right = 10**9, -1, 10**9, -1
    for grid in grids:
        for y, row in enumerate(grid):
            for x, cell in enumerate(row):
                if cell != " ":
                    top, bottom = min(top, y), max(bottom, y)
                    left, right = min(left, x), max(right, x)
    return [row[left : right + 1] for grid in grids for row in grid[top : bottom + 1]], top, left


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("用法: python tools/extract_walk_frames.py <gif>")

    palette = json.loads(SIT_ASSET.read_text(encoding="utf-8"))["palette"]
    source = Image.open(sys.argv[1])

    raw_grids = [
        frame_grid(frame.convert("RGBA"), palette)
        for frame in ImageSequence.Iterator(source)
    ]
    height = len(raw_grids[0])
    width = len(raw_grids[0][0])

    trimmed = []
    top = left = 10**9
    bottom = right = -1
    for grid in raw_grids:
        for y, row in enumerate(grid):
            for x, cell in enumerate(row):
                if cell != " ":
                    top, bottom = min(top, y), max(bottom, y)
                    left, right = min(left, x), max(right, x)
    for grid in raw_grids:
        trimmed.append([row[left : right + 1] for row in grid[top : bottom + 1]])

    frames = {}
    for index, grid in enumerate(trimmed):
        grid = denoise(grid)
        frames[f"walk_{index}"] = ["".join(row) for row in grid]

    data = {
        "name": "cat_walk",
        "version": 1,
        "state": "walk",
        "grid": [right - left + 1, bottom - top + 1],
        "cell_pixels": 4,
        "scale": "nearest",
        "palette": palette,
        "roles": {"base": "walk_0", "walk": [f"walk_{i}" for i in range(len(trimmed))]},
        "frames": frames,
    }
    OUTPUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"写出 {OUTPUT}：{data['grid'][0]}x{data['grid'][1]}，{len(frames)} 帧")

    # 预览：逐帧拼成一排，方便肉眼检查有没有残影/噪点
    cell_px = 8
    gw, gh = data["grid"]
    sheet = Image.new("RGBA", (gw * cell_px * len(frames) + 8 * (len(frames) + 1),
                               gh * cell_px + 16), (250, 240, 225, 255))
    for index, (name, rows) in enumerate(frames.items()):
        for y, row in enumerate(rows):
            for x, symbol in enumerate(row):
                if symbol == " ":
                    continue
                hex_value = palette[symbol]
                color = tuple(int(hex_value[i : i + 2], 16) for i in (1, 3, 5)) + (255,)
                box = (8 + index * (gw * cell_px + 8) + x * cell_px,
                       8 + y * cell_px,
                       8 + index * (gw * cell_px + 8) + (x + 1) * cell_px,
                       8 + (y + 1) * cell_px)
                sheet.paste(color, box)
    sheet.save(PREVIEW)
    print(f"预览图 {PREVIEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
