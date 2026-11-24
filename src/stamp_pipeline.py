#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
线稿 -> 3D 印章（凸版）流水线
================================

适用：线稿 PNG/JPG（黑线白底，或白线透明底）-> 可打印的印章 STL。
特征：
  - 自动二值化 + 去碎点 + 连通域分析
  - 自动识别"外框"，外框 -> 印章底面轮廓（扇贝边等形状自动继承），框体本身丢弃
  - 细线自动归一化到最小可打印线宽（只加粗本来就太细的部件，不动粗笔画）
  - 凸版印章默认 X 轴镜像（压印后图案方向正确）
  - 底板 + 浮雕 用 2D 布尔 + manifold 3D 并集，输出水密单体网格
  - 同时导出分层 SVG（底面 / 图案 分开，方便进 Inkscape 手改）

用法：
  python stamp_pipeline.py --input 图.png --out 前缀 --size 85
  python stamp_pipeline.py --input a.png --out b --size 85 --relief 1.8 --min-stroke 0.6
  python stamp_pipeline.py --help

注意：参数里的长度单位一律 mm。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
from PIL import Image
from scipy import ndimage as ndi
from skimage import filters, measure, morphology
import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely import affinity
import trimesh

try:                       # 同目录模块（脚本直接运行时可用）
    import scad_engine
except ImportError:        # 作为包导入时
    from . import scad_engine

# --------------------------------------------------------------------------- #
# 1. 读图 -> 二值掩码
# --------------------------------------------------------------------------- #

def log(msg=""):
    print(msg, flush=True)


def load_mask(path: Path, thr_value=None, invert=False):
    im = Image.open(path)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    g = np.asarray(im.convert("L"), dtype=np.uint8)

    if invert:
        g = 255 - g

    thr = float(thr_value) if thr_value is not None else float(filters.threshold_otsu(g))
    mask = g < thr

    # 自动判断"图案应该是少数派"（黑线白底）。若黑占了多数，说明是反相稿。
    frac = mask.mean()
    if frac > 0.55:
        log(f"  [i] 前景占比 {frac:.2f}，判定为反相稿，自动取反")
        mask = ~mask

    log(f"  [i] 阈值 {thr:.0f}，前景像素占比 {mask.mean():.1%}，尺寸 {g.shape[1]}x{g.shape[0]}")
    return mask, thr


def _label(mask):
    """兼容不同 skimage 版本的连通域标记。"""
    res = measure.label(mask, connectivity=2)
    if isinstance(res, tuple):
        return res[0], res[1]
    return res, int(res.max())


def denoise_mask(mask: np.ndarray, min_area_px: float, min_hole_px: float):
    m = mask.copy()
    if min_area_px > 1:
        try:
            m = morphology.remove_small_objects(m, min_size=int(min_area_px), connectivity=2)
        except TypeError:
            m = morphology.remove_small_objects(m, max_size=int(min_area_px), connectivity=2)
    if min_hole_px > 1:
        try:
            m = morphology.remove_small_holes(m, area_threshold=int(min_hole_px), connectivity=2)
        except TypeError:
            m = morphology.remove_small_holes(m, max_size=int(min_hole_px), connectivity=2)
    removed = int(mask.sum() - m.sum())
    log(f"  [i] 去噪：像素变化 {removed:+d}")
    return m


# --------------------------------------------------------------------------- #
# 2. 外框识别
# --------------------------------------------------------------------------- #

def find_frame(mask: np.ndarray):
    """返回 (frame_mask 或 None, base_silhouette_mask 或 None)。

    判定条件：连通块 bbox 几乎铺满整图 + 填充后面积远大于自身面积（说明是个闭合环）。
    """
    h, w = mask.shape
    lab, n = _label(mask)
    best = None
        # 注意：下面用 best_area 记录，避免重新计算
    best_area = 0.0

    for i in range(1, n + 1):
        region = lab == i
        area = float(region.sum())
        if area < 0.02 * h * w:
            continue
        ys, xs = np.where(region)
        bw = xs.max() - xs.min() + 1
        bh = ys.max() - ys.min() + 1
        wr, hr = bw / w, bh / h
        filled = ndi.binary_fill_holes(region)
        fill_ratio = float(filled.sum()) / max(area, 1.0)

        if wr > 0.80 and hr > 0.80 and fill_ratio > 2.0 and area > best_area:
            best_area = area
            best = (region, filled)

    if best is None:
        return None, None
    frame, filled = best
    log(f"  [i] 识别到外框：面积 {best_area:.0f}px，"
        f"填充比 {float(filled.sum())/best_area:.1f}x（已转为底面轮廓）")
    return frame, filled


# --------------------------------------------------------------------------- #
# 3. 细线归一化
# --------------------------------------------------------------------------- #

def stroke_stats(mask: np.ndarray, mm_per_px: float):
    """统计各连通块的"局部最大线宽"，换算成 mm，用于决定喷嘴线宽。"""
    if mask.sum() == 0:
        return {}
    dt = ndi.distance_transform_edt(mask)
    lab, n = _label(mask)
    widths = []
    for i in range(1, n + 1):
        region = lab == i
        if region.sum() < 1:
            continue
        widths.append(float(dt[region].max()) * 2.0 * mm_per_px)
    if not widths:
        return {}
    w = np.array(sorted(widths))
    return {
        "parts": len(w),
        "min": round(float(w[0]), 2),
        "p10": round(float(np.percentile(w, 10)), 2),
        "median": round(float(np.median(w)), 2),
        "max": round(float(w[-1]), 2),
        "lt_0.5": int((w < 0.5).sum()),
        "lt_0.6": int((w < 0.6).sum()),
        "lt_0.8": int((w < 0.8).sum()),
        "lt_1.0": int((w < 1.0).sum()),
    }


def normalize_thin(mask: np.ndarray, min_w_px: float, protect_px: float = 0.0):
    """只把"本身就比 min_w_px 窄"的连通块，按骨架加粗到 min_w_px。

    粗笔画/大色块完全不动，因此不会把字糊掉。
    """
    if min_w_px <= 0:
        return mask, []

    dt = ndi.distance_transform_edt(mask)
    lab, n = _label(mask)
    out = mask.copy()
    fixed = []

    for i in range(1, n + 1):
        region = lab == i
        area = region.sum()
        if area < 1:
            continue
        local_w = float(dt[region].max()) * 2.0
        if local_w >= min_w_px - 0.3:
            continue
        if protect_px > 0 and area > protect_px:
            log(f"  [!] 部件 {i} 面积较大({area:.0f}px)但线宽仅 {local_w:.1f}px，"
                f"按保护规则跳过，请人工确认")
            continue

        sk = morphology.skeletonize(region)
        r = max(1, int(round(min_w_px / 2.0)))
        thick = morphology.binary_dilation(sk, morphology.disk(r))
        out[region] = False
        out |= thick
        fixed.append({"label": int(i), "from_px": round(local_w, 2), "to_px": int(min_w_px)})

    # 收敛一次，处理加粗后与邻居重叠
    out = morphology.remove_small_objects(out, min_size=2, connectivity=2)
    if fixed:
        log(f"  [i] 加粗过细部件 {len(fixed)} 个 -> {min_w_px}px")
    return out, fixed


# --------------------------------------------------------------------------- #
# 4. 矢量化（含孔洞层级）
# --------------------------------------------------------------------------- #

def mask_to_geometry(mask: np.ndarray) -> MultiPolygon:
    padded = np.pad(mask.astype(np.uint8), 1, mode="constant", constant_values=0)
    contours = measure.find_contours(padded, 0.5)
    if not contours:
        return MultiPolygon()

    rings = []
    for c in contours:
        if len(c) < 4:
            continue
        x = c[:, 1] - 1.0
        y = -(c[:, 0] - 1.0)          # 图像 y 向下 -> 模型 y 向上
        poly = Polygon(np.column_stack([x, y]))
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.area < 0.5:
            continue
        rings.append(poly)

    if not rings:
        return MultiPolygon()

    rings.sort(key=lambda p: p.area, reverse=True)
    n = len(rings)
    depth = [0] * n
    parent = [-1] * n
    rep_points = [r.representative_point() for r in rings]

    for j in range(n):
        pj = rep_points[j]
        for i in range(j):
            if rings[i].contains(pj):
                depth[j] = depth[i] + 1
                parent[j] = i

    solids = []
    for j in range(n):
        if depth[j] % 2 != 0:
            continue
        holes = []
        for k in range(n):
            if depth[k] % 2 == 1 and parent[k] == j:
                # 只取直接子级；孙级（岛中岛）由外层 solid 自己处理
                holes.append(np.asarray(rings[k].exterior.coords))
        try:
            poly = Polygon(np.asarray(rings[j].exterior.coords), holes)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if not poly.is_empty and poly.area > 0.5:
                solids.append(poly)
        except Exception as e:  # noqa: BLE001
            log(f"  [!] 轮廓构造失败，跳过：{e}")

    geom = unary_union(solids) if solids else MultiPolygon()
    if isinstance(geom, Polygon):
        geom = MultiPolygon([geom])
    return geom


# --------------------------------------------------------------------------- #
# 5. 变换
# --------------------------------------------------------------------------- #

def scale_and_center(geom, factor_x, factor_y, offset_x, offset_y):
    if geom.is_empty:
        return geom
    g = affinity.scale(geom, xfact=factor_x, yfact=factor_y, origin=(0, 0))
    return affinity.translate(g, xoff=offset_x, yoff=offset_y)


def geom_bounds(geom):
    b = geom.bounds  # minx,miny,maxx,maxy
    return b, b[2] - b[0], b[3] - b[1]


# --------------------------------------------------------------------------- #
# 6. 建 3D
# --------------------------------------------------------------------------- #

def extrude(geom, z0, z1, name=""):
    if geom.is_empty:
        return None
    if isinstance(geom, Polygon):
        geom = MultiPolygon([geom])
    parts = []
    for poly in geom.geoms:
        if poly.is_empty or poly.area <= 0:
            continue
        try:
            m = trimesh.creation.extrude_polygon(poly, height=float(z1 - z0))
        except Exception as e:  # noqa: BLE001
            log(f"  [!] 拉伸失败（{name}）：{e}")
            continue
        m.apply_translation([0, 0, z0])
        parts.append(m)
    if not parts:
        return None
    return trimesh.util.concatenate(parts)


def safe_union(meshes):
    meshes = [m for m in meshes if m is not None and len(m.faces) > 0]
    if not meshes:
        return None
    if len(meshes) == 1:
        return meshes[0]
    try:
        out = trimesh.boolean.union(meshes, engine="manifold")
        return out
    except Exception as e:  # noqa: BLE001
        log(f"  [!] manifold 并集失败（{e}），退化为拼接（切片器可自行合并）")
        return trimesh.util.concatenate(meshes)


# --------------------------------------------------------------------------- #
# 7. 预览渲染（2.5D 高度场 + 斜射光）
# --------------------------------------------------------------------------- #

def _font(size=20):
    from PIL import ImageFont
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
              "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _labelize(img, text, pad=8):
    from PIL import ImageDraw
    out = Image.new("RGB", (img.width, img.height + 36), (18, 20, 24))
    out.paste(img, (0, 36))
    ImageDraw.Draw(out).text((pad, 10), text, font=_font(19), fill=(226, 226, 226))
    return out


def render_top(base, pattern, base_t, relief, ppm, rim_w, rim_h, sink=False):
    """俯视高度场渲染，返回 PIL.Image（未镜像）。"""
    bounds = unary_union([g for g in (base, pattern) if g is not None and not g.is_empty]).bounds
    w_mm = bounds[2] - bounds[0]
    h_mm = bounds[3] - bounds[1]
    pad = 2.0
    W = int((w_mm + 2 * pad) * ppm)
    H = int((h_mm + 2 * pad) * ppm)

    def to_px(g):
        return [(int((x - bounds[0] + pad) * ppm), int(H - (y - bounds[1] + pad) * ppm))
                for x, y in g.coords]

    hfield = np.zeros((H, W), dtype=np.float32)

    def fill(g, value):
        from skimage.draw import polygon as sk_poly
        pts = np.array(to_px(g), dtype=float)
        r, c = sk_poly(pts[:, 1], pts[:, 0], shape=hfield.shape)
        hfield[r, c] = value

    rim_z = base_t + relief + rim_h if rim_w > 0 else 0.0
    if sink:
        rim_z = base_t + rim_h
    inner = base.buffer(-rim_w) if rim_w > 0 else None

    for poly in (base.geoms if isinstance(base, MultiPolygon) else [base]):
        if sink:
            fill(poly.exterior, (base_t + rim_h) if rim_w > 0 else base_t)
        else:
            fill(poly.exterior, rim_z if rim_w > 0 else base_t)
        for ring in poly.interiors:
            fill(ring, 0.0)
    if inner is not None and not inner.is_empty:
        for poly in (inner.geoms if isinstance(inner, MultiPolygon) else [inner]):
            fill(poly.exterior, base_t)
    for poly in (pattern.geoms if isinstance(pattern, MultiPolygon) else [pattern]):
        fill(poly.exterior, base_t - relief if sink else base_t + relief)
        for ring in poly.interiors:
            fill(ring, base_t)

    hfield = ndi.gaussian_filter(hfield, 0.3)

    gy, gx = np.gradient(hfield, 1.0 / ppm, 1.0 / ppm)
    nz = np.ones_like(hfield)
    norm = np.sqrt(gx ** 2 + gy ** 2 + nz ** 2)
    nx, ny = -gx / norm, -gy / norm

    light = np.array([-0.45, 0.5, 0.74])
    light = light / np.linalg.norm(light)
    shade = nx * light[0] + ny * light[1] + (nz / norm) * light[2]
    shade = np.clip(0.45 + 0.62 * shade, 0, 1.1)

    inside = hfield > 0.01
    edge = inside & ~ndi.binary_erosion(inside, morphology.disk(1))
    shade = np.where(edge, shade * 0.45, shade)

    base_rgb = np.array([228, 221, 206], dtype=np.float32)
    rim_rgb = np.array([176, 163, 142], dtype=np.float32)
    relief_rgb = np.array([186, 142, 104], dtype=np.float32)
    cavity_rgb = np.array([132, 104, 78], dtype=np.float32)
    outside = hfield <= 0.005

    if sink:
        rgb = np.where((hfield < base_t - 1e-6)[..., None], cavity_rgb, base_rgb)
        if rim_w > 0:
            rgb = np.where((hfield > base_t + rim_h - 0.05)[..., None], rim_rgb, rgb)
        rgb = np.where(outside[..., None], np.array([28, 30, 34], dtype=np.float32), rgb)
        rgb = np.clip(rgb * shade[..., None], 0, 255).astype(np.uint8)
        return Image.fromarray(rgb)

    rgb = np.where((hfield > base_t + 1e-6)[..., None], relief_rgb, base_rgb)
    if rim_w > 0:
        rgb = np.where((hfield > rim_z - 0.05)[..., None], rim_rgb, rgb)

    t = np.clip((hfield - base_t) / max(relief, 1e-6), 0, 1)[..., None]
    rgb = rgb * (1 - 0.10 * t) + np.array([205, 170, 136], dtype=np.float32) * (0.10 * t)
    rgb = np.where(outside[..., None], np.array([28, 30, 34], dtype=np.float32), rgb)
    rgb = np.clip(rgb * shade[..., None], 0, 255).astype(np.uint8)
    return Image.fromarray(rgb)


def render_side(base, base_t, relief, ppm, rim_w, rim_h, note="", sink=False):
    """半剖示意（画到中心线为止，2 倍放大），带尺寸标注。

    手柄是独立件（make_handle.py），这里不画，只在底部注明。
    """
    from PIL import ImageDraw
    R = max(abs(base.bounds[0]), abs(base.bounds[2]))
    rim_z = base_t + relief + rim_h
    if sink:
        rim_z = base_t + rim_h

    pad_x, sc = 6.0, 2.0                 # sc=2：半剖后放大一倍，薄板细节看得清
    W = int((R + pad_x) * sc * ppm)
    H = int((2 * R + 2 * pad_x) * ppm)   # 和左右两块一样高

    def px(x, z):
        return (int((x + R) * sc * ppm + pad_x * ppm),
                int(H / 2 + (rim_z / 2 - z) * sc * ppm))

    img = Image.new("RGB", (W, H), (24, 26, 30))
    dr = ImageDraw.Draw(img)

    def slab(x0, x1, z0, z1, fill):
        dr.polygon([px(x0, z0), px(x1, z0), px(x1, z1), px(x0, z1)],
                   fill=fill, outline=(30, 30, 30))

    inner_r = R - rim_w if rim_w > 0 else R
    # 底板 + 中间浮雕（画成梳齿，示意线稿断面）
    if sink:
        slab(-inner_r, 0.0, 0, base_t, (232, 225, 210))
        step = 3.0
        x = -inner_r + 0.6
        while x < -0.6:
            # 凹槽：从顶面往下挖，开口略宽（画成梯形示意锥度）
            x1 = min(x + 1.2, -0.6)
            top = 0.05
            dr.polygon([px(x, base_t - relief), px(x1, base_t - relief),
                        px(x1 + top, base_t), px(x - top, base_t)],
                       fill=(24, 26, 30), outline=(90, 82, 70))
            x += step
    else:
        slab(-inner_r, 0.0, 0, base_t, (232, 225, 210))
        step = 3.0
        x = -inner_r + 0.6
        while x < -0.6:
            slab(x, min(x + 1.2, -0.6), base_t, base_t + relief, (238, 232, 218))
            x += step
    # 边框
    if rim_w > 0:
        slab(-R, -inner_r, 0, rim_z, (206, 194, 174))
    else:
        slab(-R, -inner_r, 0, base_t, (232, 225, 210))

    # 中心线（点划线，标准制图记号）
    cx = px(0.0, 0.0)[0]
    y = 8
    while y < H - 8:
        dr.line([(cx, y), (cx, y + 14)], fill=(90, 140, 200), width=2)
        y += 26

    # 尺寸标注（放在剖面下方，不压线）
    dims = [f"底板 {base_t:.1f}",
            (f"槽深 {relief:.1f}" if sink else f"浮雕 {relief:.1f}")]
    if rim_w > 0:
        dims += [f"边框宽 {rim_w:.1f}", f"边框顶 {rim_z:.1f}"]
    dims += [f"总高 {rim_z:.1f}", "半剖 · 2x"]
    y = int(H / 2 + (rim_z / 2 + 2.0) * sc * ppm)
    for d in dims:
        dr.text((10, y), d, font=_font(17), fill=(120, 210, 180))
        y += 24

    dr.text((10, H - 34), note or "手柄另件：print/standard/handle_slim.stl（φ14 × 25）",
            font=_font(15), fill=(130, 140, 155))

    return img


def render_preview(base, pattern, base_t, relief, out_png, ppm=12,
                   rim_w=0.0, rim_h=0.0, note="", sink=False):
    top = render_top(base, pattern, base_t, relief, ppm, rim_w, rim_h, sink=sink)
    press = top.transpose(Image.FLIP_LEFT_RIGHT)
    side = render_side(base, base_t, relief, ppm, rim_w, rim_h, note, sink=sink)

    panels = [_labelize(top, "① 凹模实物（镜像）" if sink else "① 印章实物（镜像）"),
              _labelize(press, "② 压到粘土上的效果（正读）"),
              _labelize(side, "③ 剖面示意（尺寸 mm）")]

    gap = 16
    W = sum(p.width for p in panels) + gap * (len(panels) - 1)
    H = max(p.height for p in panels)
    canvas = Image.new("RGB", (W, H), (14, 16, 20))
    x = 0
    for p in panels:
        canvas.paste(p, (x, 0))
        x += p.width + gap

    if canvas.width > 1780:
        canvas = canvas.resize((1780, int(canvas.height * 1780 / canvas.width)), Image.LANCZOS)
    canvas.save(out_png)
    return out_png


# --------------------------------------------------------------------------- #
# 8. SVG 导出（分层，方便手改）
# --------------------------------------------------------------------------- #

def geom_to_path_d(geom):
    d = []
    for poly in (geom.geoms if isinstance(geom, MultiPolygon) else [geom]):
        for ring in [poly.exterior] + list(poly.interiors):
            pts = list(ring.coords)
            d.append("M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in pts) + " Z")
    return " ".join(d)


def write_svg(base, pattern, bounds, out_svg: Path):
    minx, miny, maxx, maxy = bounds
    w, h = maxx - minx, maxy - miny
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.2f}mm" height="{h:.2f}mm" '
        f'viewBox="{minx:.3f} {miny:.3f} {w:.3f} {h:.3f}">',
        '<g id="base" fill="#cfd8e0" stroke="#5b7fa6" stroke-width="0.2" fill-rule="evenodd">',
        f'<path d="{geom_to_path_d(base)}"/>', "</g>",
        '<g id="pattern" fill="#111" stroke="none" fill-rule="evenodd">',
        f'<path d="{geom_to_path_d(pattern)}"/>', "</g>",
        "</svg>",
    ]
    out_svg.write_text("\n".join(parts), encoding="utf-8")
    return out_svg


def build_cutter(inner, wall=1.2, height=12.0, edge=0.4, edge_h=3.0,
                 flange_w=4.0, flange_t=1.6, edge_mode="vertical"):
    """边框（切模）：内腔固定不动，外表面向上收成刃口。

    打印朝向 = 翼缘贴床（z=0）、刃口在顶；打完翻过来就是
    刃口朝下切粘土、翼缘朝上可以手掌压。
    内腔全程不缩，所以切出来的尺寸恒等于 inner。

    edge_mode:
      vertical —— 刃口段外壁一次性收薄到 edge 后垂直到底（零斜面，推荐）
      taper    —— 旧做法，8 段阶梯近似锥面，侧面看得出台阶
    """
    top = max(height - edge_h, flange_t + 0.4)
    parts = []

    flange = inner.buffer(wall + flange_w, join_style="round").difference(inner)
    parts.append(extrude(flange, 0, flange_t, "cutter-flange"))

    if top > flange_t:
        body = inner.buffer(wall, join_style="round").difference(inner)
        parts.append(extrude(body, flange_t, top, "cutter-wall"))

    if height > top and edge_mode == "vertical":
        ring = inner.buffer(edge, join_style="round").difference(inner)
        parts.append(extrude(ring, top, height, "cutter-edge"))
    else:
        n = 8                              # 旧：刃口锥度分 8 段近似
        for k in range(n):
            z0 = top + edge_h * k / n
            z1 = top + edge_h * (k + 1) / n
            w = wall + (edge - wall) * (k + 1) / n
            ring = inner.buffer(w, join_style="round").difference(inner)
            parts.append(extrude(ring, z0, z1, f"cutter-edge{k}"))

    m = safe_union(parts)
    if m is None:
        return None
    m.merge_vertices()
    m.fix_normals()
    return m


def _probe(path):
    """读 STL 拿 外形/面数/水密/体积，用于写清单。"""
    import trimesh as _tm
    m = _tm.load(str(path), force="mesh")
    b = m.bounds
    return ([round(float(b[1][i] - b[0][i]), 1) for i in range(3)],
            int(len(m.faces)), bool(m.is_watertight), round(float(m.volume) / 1000.0, 2))


def write_manifest(job_dir: Path, job: str, report: dict, args,
                   base_stl: Path, cutter_stl, watertight: bool):
    """写 out/<job>/MANIFEST.md：这批出了哪些文件、哪些能直接打印。"""
    import datetime as _dt
    t = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    sink = getattr(args, "relief_mode", "raise") == "sink"
    mode_txt = (f"凹模（图案下沉 {args.relief}mm，成品图案凸起，槽壁外张 {args.cavity_draft}°）"
                if sink else f"凸模（浮雕 {args.relief}mm，成品图案凹陷）")
    L = [f"# {job} · 输出清单", "",
         f"> 由 `stamp_pipeline.py` 自动生成（{t}），别手改。",
         f"> 输入 `{Path(args.input).name}` · 成品 {args.size}mm · {mode_txt} · "
         f"底板 {args.base_thickness}mm · 最小线宽 {args.min_stroke or '不改'}", "",
         "## 可以直接打印（都在 `print/jobs/<job>/`）", "",
         "| 件 | 文件 | 外形 mm | 面数 | 水密 | 体积 cm³ |", "|---|---|---|---|---|---|"]
    for label, p in (("底模" if not sink else "凹模", base_stl), ("边框", cutter_stl)):
        if not p:
            continue
        size, faces, wt, vol = _probe(p)
        L.append(f"| {label} | `print/jobs/{Path(p).parent.name}/{Path(p).name}` | "
                 f"{size[0]} × {size[1]} × {size[2]} | "
                 f"{faces:,} | {'✓' if wt else '×'} | {vol} |")
    if not cutter_stl:
        L.append("| 边框 | _本次没出（`--no-cutter` 或 `--rim-w>0`）_ | | | | |")
    L += ["", "## 只给人看", "", "| 文件 | 内容 |", "|---|---|",
          "| `preview.png` | 三栏预览：镜像实物 / 压印效果 / 半剖带尺寸 |",
          "| `report.json` | 几何体检：尺寸 / 面数 / 水密 / 线宽 / 边框参数 |"]
    if (job_dir / "lines.svg").exists():
        L.append("| `lines.svg` | 分层 SVG（底面 / 图案分开，可进 Inkscape 手改） |")
    if (job_dir / "model.html").exists():
        L.append("| `model.html` | 单文件 3D 预览，双击即开 |")
    L += ["", "## 打印设置", "",
          "- 底模：平板贴床、**图案朝上**，0.2 喷嘴 0.10 层高 / 4 墙 / 25% 填充 / 顶面熨烫 / 无支撑；"
          "只有 0.4 喷嘴时先加 `--min-stroke 0.9`。",
          "- 边框：**翼缘贴床、刃口朝上**，4 墙 + 4mm brim，打完翻过来用。",
          "- 手柄：`print/standard/handle_x12.stl`（标准件，粘在底模背面中心）。", "",
          "> 总表（跨所有图案）看根目录 `PRINT.md`；切片细节看 `guides/printing.md`。"]
    (job_dir / "MANIFEST.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def refresh_print_index():
    """刷新根目录 PRINT.md（失败不影响出件）。"""
    try:
        from make_print_index import rebuild
        rebuild()
    except Exception as exc:            # noqa: BLE001
        log(f"  [i] PRINT.md 未刷新：{exc}")


# --------------------------------------------------------------------------- #
# 9. 主流程
# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="线稿 -> 3D 凸印章 STL（拓竹 P1S 可直接切片）",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ap.add_argument("--input", required=True, help="输入线稿 PNG/JPG")
    ap.add_argument("--out", required=True, help="输出前缀（不含扩展名）")
    ap.add_argument("--size", type=float, default=85.0, help="成品最大外形尺寸 mm（默认 85）")
    ap.add_argument("--base-thickness", type=float, default=3.0, help="底板厚度 mm（默认 3）")
    ap.add_argument("--relief", type=float, default=1.8, help="图案凸起高度 mm（默认 1.8）")
    ap.add_argument("--relief-mode", choices=["raise", "sink"], default="raise",
                    help="raise=图案凸起成印章，压出来是凹线（默认）\n"
                         "sink=图案下沉成凹槽（凹模），压出来是凸线；凹槽自动带脱模锥度")
    ap.add_argument("--engine", choices=["scad", "mesh"], default="scad",
                    help="scad=2D 轮廓交给 OpenSCAD（CGAL）挤出+布尔，参数化、可预览（默认）\n"
                         "mesh=旧的 shapely+trimesh/manifold 路径，作回退")
    ap.add_argument("--cutter-engine", choices=["mesh", "scad"], default="mesh",
                    help="边框用哪个引擎。默认 mesh：边框全是 offset，\n"
                         "OpenSCAD 逐段 offset 实测 115s，trimesh 只要 0.5s")
    ap.add_argument("--cavity-draft", type=float, default=5.0,
                    help="凹模槽壁外张锥度 °（仅 --relief-mode sink；默认 5，0=垂直墙）")
    ap.add_argument("--cavity-segments", type=int, default=4,
                    help="凹模锥面的阶梯段数（默认 4；8 更平滑但面数翻倍）")
    ap.add_argument("--grow", type=float, default=0.0, help="图案整体外扩 mm（默认 0，慎用会糊字）")
    ap.add_argument("--min-stroke", type=float, default=0.0,
                    help="最小线宽 mm（0=不改）。0.4喷嘴建议 0.9，0.2喷嘴建议 0.55")
    ap.add_argument("--margin", type=float, default=1.2, help="底面轮廓相对图案外扩的边距 mm")
    ap.add_argument("--rim-w", type=float, default=0.0,
                    help="一体式外沿凸边框宽度 mm（0=不做，分体模式默认 0）。\n"
                         "分体模式请用 --cutter 单独出边框，别用这个")
    ap.add_argument("--rim-h", type=float, default=0.4,
                    help="边框比浮雕顶面再高出的量 mm（仅 --rim-w>0 有效）")
    # ---- 边框（独立切模）
    ap.add_argument("--no-cutter", action="store_true",
                    help="不出边框 STL（默认出，随便框跟底模分离）")
    ap.add_argument("--cutter-wall", type=float, default=1.2,
                    help="边框壁厚 mm（刃口上方主体，0.4 喷嘴 1.2 刚好 3 圈实心）")
    ap.add_argument("--cutter-height", type=float, default=12.0,
                    help="边框总高 mm（含底部翼缘）")
    ap.add_argument("--cutter-edge", type=float, default=0.4,
                    help="刃口厚度 mm（翻转后朝下切粘土那面）")
    ap.add_argument("--cutter-edge-h", type=float, default=3.0,
                    help="刃口薄壁段高度 mm（该段整段都是 --cutter-edge 这么厚）")
    ap.add_argument("--cutter-edge-mode", choices=["vertical", "taper"], default="vertical",
                    help="刃口形态：vertical=外壁一次性收薄后垂直到底（默认，零斜面、侧面对比干净）；"
                         "taper=旧 8 段阶梯锥面（侧面有台阶，不推荐）")
    ap.add_argument("--cutter-flange-w", type=float, default=4.0,
                    help="底部翼缘外扩宽 mm（贴床防翘、翻过来当握边）")
    ap.add_argument("--cutter-flange-t", type=float, default=1.6,
                    help="翼缘厚度 mm")
    ap.add_argument("--cutter-clearance", type=float, default=0.4,
                    help="底模相对边框内腔的内缩 mm（防粘壁/防卡，单边）")
    ap.add_argument("--scale", type=float, default=1.0, help="线稿放大倍数（补救低分辨率细线）")
    ap.add_argument("--frame-mode", choices=["silhouette", "keep", "ignore"], default="silhouette",
                    help="silhouette=外框转底面并丢弃框体(默认)\nkeep=框也当图案\nignore=丢框用圆底")
    ap.add_argument("--no-mirror", action="store_true", help="不镜像（仅当你要直接看图案本身）")
    ap.add_argument("--thr", type=float, default=None, help="手动二值阈值 0-255")
    ap.add_argument("--invert", action="store_true", help="反相（白线黑底）")
    ap.add_argument("--simplify", type=float, default=0.02, help="曲线简化容差 mm（默认 0.02）")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--svg", action="store_true", help="同时导出分层 SVG")
    ap.add_argument("--print-dir", default="print",
                    help="可打印 STL 的根目录（默认 print/；每单落到 print/jobs/<job>/）")
    args = ap.parse_args(argv)

    # ---- 输出布局（约定见 guides/output-layout.md）
    #   print/jobs/<job>/base.stl      可打印：底模 / 凹模
    #   print/jobs/<job>/cutter.stl    可打印：边框
    #   out/<job>/                     其余全部（report / preview / svg / model / MANIFEST）
    out = Path(args.out)
    job_dir = out.with_suffix("") if out.suffix else out      # 兼容老写法 --out out\x.stl
    job = job_dir.name
    pdir = Path(args.print_dir)
    job_print = pdir / "jobs" / job
    job_print.mkdir(parents=True, exist_ok=True)
    job_dir.mkdir(parents=True, exist_ok=True)
    base_stl = job_print / "base.stl"
    cutter_stl_path = job_print / "cutter.stl"
    src = Path(args.input)
    log(f"=== {src.name} -> {args.size}mm 凸印章（job: {job}）===")

    # ---- 1. 掩码
    if args.scale != 1.0:
        im = Image.open(src)
        im = im.resize((int(im.width * args.scale), int(im.height * args.scale)), Image.LANCZOS)
        tmp = job_dir / f".{job}_scaled.png"
        im.save(tmp)
        src = tmp
        log(f"  [i] 预放大 x{args.scale} -> {im.width}x{im.height}")

    mask, _ = load_mask(src, args.thr, args.invert)

    rough_mm_per_px = args.size / mask.shape[1]
    min_area_px = 0.6 / (rough_mm_per_px ** 2)     # 0.6 mm² 以下视为噪点
    min_hole_px = 0.3 / (rough_mm_per_px ** 2)
    mask = denoise_mask(mask, min_area_px, min_hole_px)

    # ---- 2. 外框
    frame, silhouette = find_frame(mask)
    if frame is None:
        log("  [i] 未识别到外框，底面用圆/方包络")
        pattern_mask = mask
        base_mask = None
    else:
        if args.frame_mode == "silhouette":
            pattern_mask = mask & ~frame
            base_mask = silhouette
        elif args.frame_mode == "keep":
            pattern_mask = mask
            base_mask = silhouette
        else:
            pattern_mask = mask & ~frame
            base_mask = None

    pattern_mask = morphology.remove_small_objects(pattern_mask, min_size=2, connectivity=2)

    # ---- 3. 线宽体检 + 细线归一化
    stats = stroke_stats(pattern_mask, rough_mm_per_px)
    if stats:
        log(f"  [i] 线宽分布(mm)：min {stats['min']} | p10 {stats['p10']} | 中位 {stats['median']} | max {stats['max']}")
        log(f"      <0.5mm {stats['lt_0.5']} 处 | <0.6 {stats['lt_0.6']} | <0.8 {stats['lt_0.8']} | <1.0 {stats['lt_1.0']}")
    pattern_mask, fixed = normalize_thin(pattern_mask, args.min_stroke * 1.0 / rough_mm_per_px)

    # ---- 4. 矢量化
    pat = mask_to_geometry(pattern_mask)
    base_raw = mask_to_geometry(base_mask) if base_mask is not None else None
    if pat.is_empty:
        log("[x] 图案矢量化后为空，检查阈值/反相设置")
        return 2
    log(f"  [i] 图案：{len(pat.geoms)} 个多边形")

    # ---- 5. 缩放 / 镜像 / 居中
    ref = base_raw if (base_raw is not None and not base_raw.is_empty) else pat
    _, ref_w, ref_h = geom_bounds(ref)
    has_silhouette = base_raw is not None and not base_raw.is_empty and args.frame_mode != "ignore"
    # --size 指「成品尺寸」= 边框内腔 = 切出来的粘土外形。
    # 分体模式下底模要再内缩 cutter_clearance（单边），所以要减掉 2 倍。
    clr = 0.0 if (args.no_cutter or args.rim_w > 0) else args.cutter_clearance
    if clr > 0:
        log(f"  [i] 分体模式：成品 {args.size}mm = 边框内腔，底模内缩 {clr}mm/边")
    target = args.size - 2 * args.margin - 2 * clr   # 底面还要外扩 margin / 内缩 clearance
    s = max(target, 1.0) / max(ref_w, ref_h)
    log(f"  [i] 参考轮廓 {ref_w:.1f}x{ref_h:.1f}px -> 比例 {s:.5f} mm/px")

    fx = -s if not args.no_mirror else s
    if fx < 0:
        log("  [i] 已 X 轴镜像（凸印章默认）")

    def place(g):
        if g is None or g.is_empty:
            return g
        b, w, h = geom_bounds(g)
        g2 = affinity.scale(g, xfact=fx, yfact=s, origin=(0, 0))
        b2 = g2.bounds
        return affinity.translate(g2, xoff=-(b2[0] + b2[2]) / 2, yoff=-(b2[1] + b2[3]) / 2)

    pat_mm = place(pat)
    base_ref_mm = place(ref)

    # 底面
    if base_raw is not None and not base_raw.is_empty and args.frame_mode != "ignore":
        base_mm = base_ref_mm.buffer(args.margin, join_style="round")
    else:
        _, w, h = geom_bounds(base_ref_mm)
        r = max(w, h) / 2 + args.margin
        base_mm = shapely.Point(0, 0).buffer(r, resolution=96)

    # 简化
    if args.simplify > 0:
        pat_mm = pat_mm.simplify(args.simplify, preserve_topology=True)
        base_mm = base_mm.simplify(args.simplify, preserve_topology=True)

    # ---- 外轮廓凸边框（rim）
    rim_w, rim_h = args.rim_w, args.rim_h
    inner = None
    if rim_w > 0:
        inner = base_mm.buffer(-rim_w, join_style="round")
        if inner.is_empty or inner.area < base_mm.area * 0.35:
            log(f"  [!] 边框宽 {rim_w}mm 相对成品过大，已关闭边框")
            rim_w, inner = 0.0, None

    clip_limit = (inner.buffer(-0.3) if inner is not None else base_mm.buffer(-0.25))

    # 图案收进底面内，避免悬空
    pat_mm = pat_mm.intersection(clip_limit)
    if args.grow > 0:
        pat_mm = pat_mm.buffer(args.grow, join_style="round").intersection(clip_limit)
    if isinstance(pat_mm, Polygon):
        pat_mm = MultiPolygon([pat_mm])
    if pat_mm.is_empty:
        log("[x] 图案与底面求交后为空")
        return 2

    # 线宽体检
    thin_probe = pat_mm.buffer(-0.22)  # 0.2mm 喷嘴 ≈ 单线 0.42
    lost = sum(1 for p in (thin_probe.geoms if hasattr(thin_probe, "geoms") else [thin_probe])
               if p.is_empty) if not thin_probe.is_empty else len(pat_mm.geoms)
    log(f"  [i] 线宽体检：以 0.44mm 线宽做腐蚀，{len(pat_mm.geoms)} 个部件中 "
        f"{lost} 个会消失（{lost/max(len(pat_mm.geoms),1):.0%}）")

    # ---- 6. 3D
    B, D = args.base_thickness, args.relief
    sink = args.relief_mode == "sink"
    draft = max(0.0, float(args.cavity_draft))
    if os.environ.get("SP_DUMP_GEOM"):
        import pickle
        with open(job_dir / "geom.pkl", "wb") as fh:
            pickle.dump({"base_mm": base_mm, "pat_mm": pat_mm, "inner": inner,
                         "B": B, "D": D, "draft": draft}, fh)
    if sink:
        D = min(D, B - 1.0)
        log(f"  [i] 建体：凹模 · 底板 {B}mm、图案下沉 {D}mm、槽壁外张 {draft}°"
            + (f"、边框 {rim_w}mm宽/{B + rim_h}mm高" if rim_w > 0 else ""))
    else:
        log(f"  [i] 建体：底板 {B}mm + 浮雕 {D}mm"
            + (f" + 边框 {rim_w}mm宽/{B + D + rim_h}mm高" if rim_w > 0 else ""))

    parts = []
    scad_seconds = None
    use_scad = (args.engine == "scad" and rim_w == 0)
    if args.engine == "scad" and rim_w > 0:
        log("  [!] 一体式 --rim-w 目前只在 mesh 引擎里实现，本次改用 mesh")
    if use_scad:
        mods = {
            "outline_2d": scad_engine.geom_to_scad_module(base_mm, "outline_2d"),
            "pattern_2d": scad_engine.geom_to_scad_module(pat_mm, "pattern_2d"),
        }
        scad_file = scad_engine.write_job_scad(
            mods, scad_engine.SCAD_DIR / "base.scad",
            job_dir / "scad" / "base_job.scad")
        d_ratio = scad_engine.draft_ratio(D, draft, pat_mm) if sink else 1.0
        ok, scad_seconds, tail = scad_engine.render(
            scad_file, base_stl,
            defs=dict(mode=("sink" if sink else "raise"), base_t=B, relief=D,
                      draft_ratio=round(d_ratio, 6)))
        if ok:
            mesh = trimesh.load(str(base_stl))
            total_h = B if sink else B + D
            log(f"  [i] 建体引擎：OpenSCAD（polygon 内联，渲染 {scad_seconds:.1f}s）")
        else:
            log(f"  [!] OpenSCAD 渲染失败，回退 mesh 引擎：{tail}")
            use_scad = False
    if not use_scad:
        parts = []
        if sink:
            # 凹模：整块底板到 B，图案区域从顶面往下挖 D 深。
            # 槽底窄、开口宽（外张锥度），粘土才拔得出来；锥面按 cavity_segments 段阶梯近似。
            # 坑：图案把顶面切碎成多个互不相连的小岛，union 前的 volume 预检会直接报错，
            #     所以这里走 check_volume=False，交给 manifold 自己合并多体。
            body = inner if rim_w > 0 else base_mm
            slab = extrude(body, 0, B, "base")
            n = max(1, int(args.cavity_segments))
            tan_a = math.tan(math.radians(draft))
            cav_parts = []
            pieces = pat_mm.geoms if hasattr(pat_mm, "geoms") else [pat_mm]
            for k in range(n):
                z0 = (B - D) + D * k / n
                z1 = (B - D) + D * (k + 1) / n
                off = D * tan_a * (k + 0.5) / n
                for piece in pieces:
                    p = piece.buffer(off, join_style="mitre") if off > 1e-9 else piece
                    if p.is_empty:
                        continue
                    c = extrude(p, z0, z1, f"cavity{k}")
                    if c is not None:
                        cav_parts.append(c)
            cav = (cav_parts[0] if len(cav_parts) == 1
                   else trimesh.boolean.union(cav_parts, engine="manifold", check_volume=False))
            mesh = None
            if slab is not None and cav is not None:
                try:
                    mesh = trimesh.boolean.difference([slab, cav], engine="manifold",
                                                      check_volume=False)
                except Exception as e:  # noqa: BLE001
                    log(f"  [!] 差集失败：{e}")
            if rim_w > 0 and mesh is not None:
                ring = base_mm.difference(inner)
                rim_m = extrude(ring, 0, B + rim_h, "rim")
                mesh = (rim_m if mesh is None else
                        trimesh.boolean.union([mesh, rim_m], engine="manifold", check_volume=False))
            total_h = B + (rim_h if rim_w > 0 else 0.0)
        elif rim_w > 0:
            ring = base_mm.difference(inner)
            parts.append(extrude(inner.difference(pat_mm), 0, B, "base"))
            parts.append(extrude(pat_mm, 0, B + D, "relief"))
            parts.append(extrude(ring, 0, B + D + rim_h, "rim"))
            total_h = B + D + rim_h
            mesh = safe_union(parts)
        else:
            parts.append(extrude(base_mm.difference(pat_mm), 0, B, "base"))
            parts.append(extrude(pat_mm, 0, B + D, "relief"))
            total_h = B + D
            mesh = safe_union(parts)


    if mesh is None:
        log("[x] 网格生成失败")
        return 3

    mesh.merge_vertices()
    mesh.fix_normals()
    watertight = mesh.is_watertight
    vol = mesh.volume / 1000.0
    bb = mesh.bounds

    stl = base_stl
    mesh.export(str(stl))

    # ---- 手柄
    # 不在这里出：手柄是「一套配所有图案」的标准件，用 make_handle.py 单独定尺寸、
    # 一次打一批。章体背面留平整粘接面即可。

    # ---- 边框（独立切模）
    cutter_stl, cutter_info = None, {}
    if args.no_cutter:
        pass
    elif rim_w > 0:
        log("  [!] 已启用一体式 --rim-w，跳过独立边框（两者只能选一个）")
    else:
        inner_geom = base_mm.buffer(clr, join_style="round")
        cm = None
        if args.cutter_engine == "scad":
            mods = {"inner_2d": scad_engine.geom_to_scad_module(inner_geom, "inner_2d")}
            scad_file = scad_engine.write_job_scad(
                mods, scad_engine.SCAD_DIR / "cutter.scad",
                job_dir / "scad" / "cutter_job.scad")
            ok, cut_secs, tail = scad_engine.render(
                scad_file, cutter_stl_path,
                defs=dict(wall=args.cutter_wall, height=args.cutter_height,
                          edge=args.cutter_edge, edge_h=args.cutter_edge_h,
                          flange_w=args.cutter_flange_w, flange_t=args.cutter_flange_t,
                          edge_mode=args.cutter_edge_mode))
            if ok:
                cm = trimesh.load(str(cutter_stl_path))
                log(f"  [i] 边框引擎：OpenSCAD（渲染 {cut_secs:.1f}s）")
            else:
                log(f"  [!] 边框 OpenSCAD 渲染失败，回退 mesh：{tail}")
        if cm is None:
            cm = build_cutter(inner_geom,
                              wall=args.cutter_wall, height=args.cutter_height,
                              edge=args.cutter_edge, edge_h=args.cutter_edge_h,
                              flange_w=args.cutter_flange_w, flange_t=args.cutter_flange_t,
                              edge_mode=args.cutter_edge_mode)
        if cm is not None and len(cm.faces) > 0:
            cutter_stl = cutter_stl_path
            cm.export(str(cutter_stl))
            cb = cm.bounds
            cutter_info = {
                "file": str(cutter_stl),
                "inner_size_mm": [round(float(inner_geom.bounds[2] - inner_geom.bounds[0]), 2),
                                  round(float(inner_geom.bounds[3] - inner_geom.bounds[1]), 2)],
                "wall_mm": args.cutter_wall, "height_mm": args.cutter_height,
                "edge_mm": args.cutter_edge, "edge_h_mm": args.cutter_edge_h,
                "edge_mode": args.cutter_edge_mode,
                "flange_mm": [args.cutter_flange_w, args.cutter_flange_t],
                "clearance_mm": clr,
                "triangles": int(len(cm.faces)),
                "watertight": bool(cm.is_watertight),
            }
            log(f"  边框 STL   : {cutter_stl}  (内腔 "
                f"{cutter_info['inner_size_mm'][0]:.1f}x{cutter_info['inner_size_mm'][1]:.1f}mm, "
                f"壁 {args.cutter_wall} / 高 {args.cutter_height} / 刃 {args.cutter_edge}mm,"
                f" 水密 {cm.is_watertight})")
        else:
            log("  [!] 边框生成失败（内腔几何可能自交），跳过")

    log("")
    log(f"  输出 STL   : {stl}")
    log(f"  尺寸       : {bb[1][0]-bb[0][0]:.2f} x {bb[1][1]-bb[0][1]:.2f} x {bb[1][2]-bb[0][2]:.2f} mm")
    log(f"  三角面      : {len(mesh.faces)}   水密: {watertight}   体积: {vol:.1f} cm3")

    report = {
        "input": str(src),
        "engine": args.engine,
        "engine_note": ("2D 轮廓交给 OpenSCAD/CGAL 挤出与布尔" if args.engine == "scad"
                        else "旧路径：shapely 2D 布尔 + trimesh/manifold 3D"),
        "scad_render_s": round(scad_seconds, 1) if scad_seconds else None,
        "size_mm": args.size,
        "size_semantics": "成品尺寸（分体模式下 = 边框内腔；底模再内缩 cutter_clearance）",
        "stamp_size_mm": [round(float(bb[1][i] - bb[0][i]), 2) for i in range(2)],
        "base_thickness": B,
        "relief": D,
        "relief_mode": args.relief_mode,
        "relief_mode_note": ("凹模：图案下沉成槽，成品图案凸起" if sink
                            else "印章：图案凸起，成品图案凹陷"),
        "cavity_draft_deg": draft if sink else 0.0,
        "rim_w_mm": rim_w,
        "rim_h_above_relief_mm": rim_h if rim_w > 0 else 0.0,
        "total_height_mm": round(float(total_h), 2),
        "mirrored": not args.no_mirror,
        "min_stroke_mm": args.min_stroke,
        "bbox_mm": [round(float(bb[1][i] - bb[0][i]), 3) for i in range(3)],
        "triangles": int(len(mesh.faces)),
        "watertight": bool(watertight),
        "volume_cm3": round(float(vol), 2),
        "pattern_parts": len(pat_mm.geoms),
        "thin_parts_fixed": len(fixed),
        "thin_parts_at_risk": int(lost),
        "stroke_stats_mm": stats,
        "cutter": cutter_info,
        "handle": {"note": "独立标准件，见 print/standard/handle_slim.stl（src/make_handle.py）"},
    }
    out_marker = job_dir / "report.json"
    out_marker.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.svg:
        pos_bounds = [min(bb[0][0], base_mm.bounds[0]), min(bb[0][1], base_mm.bounds[1]),
                      max(bb[1][0], base_mm.bounds[2]), max(bb[1][1], base_mm.bounds[3])]
        svg = write_svg(base_mm, pat_mm, pos_bounds, job_dir / "lines.svg")
        log(f"  分层 SVG   : {svg}")

    if not args.no_preview:
        if cutter_info:
            note = (f"手柄另件 φ14x25 · 边框另件 内腔 "
                    f"{cutter_info['inner_size_mm'][0]:.0f} 壁 {args.cutter_wall} "
                    f"高 {args.cutter_height} 刃 {args.cutter_edge}mm")
        else:
            note = "手柄另件：print/standard/handle_slim.stl（φ14 × 25）"
        if sink:
            note = f"凹模 · 图案下沉 {D}mm · 槽壁外张 {draft}° · " + note
        p1 = render_preview(base_mm, pat_mm, B, D, job_dir / "preview.png",
                            rim_w=rim_w, rim_h=rim_h, note=note, sink=sink)
        log(f"  预览       : {p1}")

    write_manifest(job_dir, job, report, args, base_stl, cutter_stl, watertight)

    if not watertight:
        log("  [!] 网格非水密，切片前请在 Bambu Studio 里做一次修复")

    refresh_print_index()
    return 0


if __name__ == "__main__":
    sys.exit(main())

