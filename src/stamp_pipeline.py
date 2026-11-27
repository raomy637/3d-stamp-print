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
  python stamp_pipeline.py --input a.png --out b --size 85 --relief 2.5 --min-stroke 0.6
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
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from scipy.signal import find_peaks
from skimage import filters, measure, morphology
import shapely
from shapely.geometry import MultiPolygon, Polygon, Point
from shapely.ops import unary_union, nearest_points
from shapely.geometry import LineString
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
# 2b. 花瓣外轮廓：检测与规整
# --------------------------------------------------------------------------- #

def _largest_polygon(poly):
    if poly is None or poly.is_empty:
        return None
    if isinstance(poly, Polygon):
        return poly
    geoms = [g for g in getattr(poly, "geoms", []) if isinstance(g, Polygon) and not g.is_empty]
    return max(geoms, key=lambda g: g.area) if geoms else None


def analyze_scallop(poly):
    """极坐标测外轮廓的瓣数、峰/谷半径、角间距变异。"""
    p = _largest_polygon(poly)
    if p is None or len(p.exterior.coords) < 20:
        return None
    coords = np.asarray(p.exterior.coords[:-1])
    c = p.centroid
    dx, dy = coords[:, 0] - c.x, coords[:, 1] - c.y
    theta = np.arctan2(dy, dx)
    radius = np.hypot(dx, dy)
    order = np.argsort(theta)
    bins = 1440
    grid = np.linspace(-np.pi, np.pi, bins, endpoint=False)
    r = np.interp(grid, theta[order], radius[order], period=2 * np.pi)
    r = ndi.gaussian_filter1d(r, sigma=8, mode="wrap")
    mean = float(r.mean())
    peaks, _ = find_peaks(r, distance=bins // 72, prominence=mean * 0.004)
    valleys, _ = find_peaks(-r, distance=bins // 72, prominence=mean * 0.004)
    if len(peaks) < 5 or len(valleys) < 5:
        return None
    n = len(peaks) if abs(len(peaks) - len(valleys)) <= 1 else int(round((len(peaks) + len(valleys)) / 2))
    if not 6 <= n <= 24:
        return None
    R = float(np.median(r[peaks]))
    r_in = float(np.median(r[valleys]))
    if r_in <= 0 or R <= r_in:
        return None
    peak_r = r[peaks]
    peak_r_cv = float(peak_r.std() / peak_r.mean()) if len(peak_r) > 2 else 0.0
    spacing = np.diff(peaks)
    spacing_cv = float(spacing.std() / spacing.mean()) if len(spacing) > 2 else 0.0
    perimeter = float(p.length)
    circularity = 4 * math.pi * p.area / (perimeter * perimeter) if perimeter > 0 else 0.0
    solidity = float(p.area / p.convex_hull.area) if p.convex_hull.area > 0 else 0.0
    phase = float(np.angle(np.mean(np.exp(1j * n * grid[peaks]))) / n)
    amp = (R - r_in) / R
    scallop_like = (solidity >= 0.92 and circularity >= 0.60 and 8 <= n <= 24
                    and 0.02 <= amp <= 0.12)
    suggest = scallop_like and (spacing_cv >= 0.10 or peak_r_cv >= 0.015)
    return {
        "poly": p, "cx": c.x, "cy": c.y, "grid": grid, "r": r,
        "peaks": peaks, "valleys": valleys, "petals": n, "phase": phase,
        "R": R, "r_in": r_in, "amplitude": amp,
        "spacing_cv": spacing_cv, "peak_radius_cv": peak_r_cv,
        "circularity": circularity, "solidity": solidity,
        "scallop_like": bool(scallop_like), "suggest": bool(suggest),
    }


def build_scallop_polygon(m, petals=None):
    n = int(petals or m["petals"])
    if not 6 <= n <= 24:
        return None
    R, r = float(m["R"]), float(m["r_in"])
    delta = math.pi / n
    den = 2 * (R - r * math.cos(delta))
    if den <= 0:
        return None
    c = (R * R - r * r) / den
    rho = R - c
    if rho <= 0:
        return None
    phi_end = math.atan2(r * math.sin(delta), r * math.cos(delta) - c)
    if abs(phi_end) < 1e-4:
        return None
    pts = []
    for i in range(n):
        center = m["phase"] + 2 * math.pi * i / n
        for phi in np.linspace(-abs(phi_end), abs(phi_end), 80):
            pts.append((m["cx"] + c * math.cos(center) + rho * math.cos(center + phi),
                        m["cy"] + c * math.sin(center) + rho * math.sin(center + phi)))
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly if not poly.is_empty else None


def regularize_frame(poly, mode, petals=None):
    info = {"mode": mode, "applied": False, "reason": "", "detected": None,
            "petals_used": None, "area_change_pct": None}
    m = analyze_scallop(poly)
    if m is None:
        info["reason"] = "not_scallop"
        return poly, info, None
    info["detected"] = {
        "petals": m["petals"],
        "spacing_cv": round(m["spacing_cv"], 4),
        "peak_radius_cv": round(m["peak_radius_cv"], 4),
        "amplitude": round(m["amplitude"], 4),
        "circularity": round(m["circularity"], 4),
        "solidity": round(m["solidity"], 4),
        "scallop_like": m["scallop_like"],
        "suggest": m["suggest"],
    }
    if mode == "auto" and not m["suggest"] and petals is None:
        info["reason"] = "already_regular" if m["scallop_like"] else "not_scallop"
        return poly, info, m
    new = build_scallop_polygon(m, petals)
    if new is None:
        info["reason"] = "build_failed"
        return poly, info, m
    ratio = new.area / max(float(poly.area), 1.0)
    if not 0.80 <= ratio <= 1.20:
        info["reason"] = "area_drift"
        return poly, info, m
    info.update({
        "applied": True,
        "petals_used": int(petals or m["petals"]),
        "area_change_pct": round((ratio - 1.0) * 100.0, 2),
    })
    return new, info, m


def render_frame_check(src, mask, m, new_poly, out_png):
    """外轮廓检测叠加图：原始轮廓 / 峰谷 / 规整后轮廓。"""
    img = Image.open(src).convert("RGB")
    draw = ImageDraw.Draw(img)
    contours = measure.find_contours(mask.astype(np.uint8), 0.5)
    if contours:
        c = max(contours, key=len)
        draw.line([(float(x), float(y)) for y, x in c], fill=(0, 150, 0), width=4)
    if m:
        for idx, color in ((m["peaks"], (220, 30, 30)), (m["valleys"], (30, 60, 220))):
            for i in idx:
                x = m["cx"] + m["r"][i] * math.cos(m["grid"][i]) + 1
                y = 1 - m["cy"] - m["r"][i] * math.sin(m["grid"][i])
                draw.ellipse([x - 7, y - 7, x + 7, y + 7], fill=color)
    if new_poly is not None and not new_poly.is_empty:
        p = _largest_polygon(new_poly)
        if p is not None:
            pts = [(x + 1, 1 - y) for x, y in p.exterior.coords]
            draw.line(pts, fill=(255, 140, 0), width=4)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)


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


def cap_stroke_width(mask: np.ndarray, cap_mm: float, mm_per_px: float):
    """把宽于 cap_mm 的笔画收细到 cap_mm（骨架 + 圆盘重建），窄笔画不动。

    目的：线宽超过约 4 道墙（0.4 喷嘴约 1.7mm）时，切片器会在笔画中间生成
    稀疏填充区，顶壳不足就露出蜂窝。收到 cap_mm 以内可让整条线只由墙填满。
    """
    if cap_mm <= 0 or mask.sum() == 0:
        return mask, []
    dt = ndi.distance_transform_edt(mask)
    lab, n = _label(mask)
    out = mask.copy()
    r = max(1, int(round(cap_mm / 2.0 / mm_per_px)))
    changed = []
    for i in range(1, n + 1):
        region = lab == i
        local_w = float(dt[region].max()) * 2.0 * mm_per_px
        if local_w <= cap_mm * 1.02:
            continue
        if local_w > max(5.0, cap_mm * 4):
            log(f"  [!] 部件 {i} 最大宽度 {local_w:.1f}mm，疑似实心块，跳过收细")
            continue
        sk = morphology.skeletonize(region)
        thin = morphology.binary_dilation(sk, morphology.disk(r)) & region
        if thin.sum() == 0:
            continue
        out[region] = False
        out |= thin
        changed.append({"label": int(i), "from_mm": round(local_w, 2)})
    out = morphology.remove_small_objects(out, min_size=2, connectivity=2)
    if changed:
        kept = float(out.sum()) / max(float(mask.sum()), 1.0)
        log(f"  [i] 收细宽笔画 {len(changed)} 个 -> ≤{cap_mm:g}mm（面积 {kept-1:+.0%}）")
    return out, changed


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


def render_top(base, pattern, base_t, relief, ppm, rim_w, rim_h, sink=False,
               pockets=None):
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
    # 环形沉台（--pocket）：俯视画成一圈浅槽，深度按 dep 扣
    for cx, cy, rin, rout, dep in (pockets or []):
        c = Point(cx, cy)
        ring = c.buffer(rout, resolution=72).difference(c.buffer(rin, resolution=72))
        for poly in (ring.geoms if isinstance(ring, MultiPolygon) else [ring]):
            fill(poly.exterior, base_t - dep)
    # 图案/沉台的内环填色会盖掉底模上的通孔（打孔定位孔），最后统一把它们挖回来
    for poly in (base.geoms if isinstance(base, MultiPolygon) else [base]):
        for ring in poly.interiors:
            fill(ring, 0.0)

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
    rgb = np.where((hfield < base_t - 0.2)[..., None],
                   np.array([196, 184, 166], dtype=np.float32), rgb)
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
    rim_z = base_t + relief + rim_h if rim_w > 0 else base_t + relief
    if sink:
        rim_z = base_t + rim_h if rim_w > 0 else base_t

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
                   rim_w=0.0, rim_h=0.0, note="", sink=False, pockets=None):
    top = render_top(base, pattern, base_t, relief, ppm, rim_w, rim_h, sink=sink,
                     pockets=pockets)
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
                 flange_w=4.0, flange_t=1.6, edge_mode="vertical",
                 void=None, bridge=3.0):
    """边框（切模）：内腔固定不动，外表面向上收成刃口。

    打印朝向 = 翼缘贴床（z=0）、刃口在顶；打完翻过来就是
    刃口朝下切粘土、翼缘朝上可以手掌压。
    内腔全程不缩，所以切出来的尺寸恒等于 inner。

    void  —— 内腔里要挖掉的洞（挖空区）。给了就在内腔里长出**内岛刃**（一圈闭合刃），
             并且翼缘/主体/刃口都不跨过这个洞（翼缘不会在洞口上补一块板）。
    bridge—— 内岛刃与外圈之间的顶桥宽度 mm；桥只在最上面 2mm，压在 z≈height，
             比底模高得多，碰不到泥。0 = 不搭桥（内岛会变成孤立件，打不出来）。

    edge_mode:
      vertical —— 刃口段外壁一次性收薄到 edge 后垂直到底（零斜面，推荐）
      taper    —— 旧做法，8 段阶梯近似锥面，侧面看得出台阶
    """
    top = max(height - edge_h, flange_t + 0.4)
    has_void = void is not None and not getattr(void, "is_empty", True)

    def band(off, drop_void=False):
        b = inner.buffer(off, join_style="round").difference(inner)
        if drop_void and has_void:        # 翼缘不许在洞口上补一块板
            b = b.difference(void)
        return b

    parts = []

    flange = band(wall + flange_w, drop_void=True)
    parts.append(extrude(flange, 0, flange_t, "cutter-flange"))

    if top > flange_t:
        parts.append(extrude(band(wall), flange_t, top, "cutter-wall"))

    if height > top and edge_mode == "vertical":
        parts.append(extrude(band(edge), top, height, "cutter-edge"))
    else:
        n = 8                              # 旧：刃口锥度分 8 段近似
        for k in range(n):
            z0 = top + edge_h * k / n
            z1 = top + edge_h * (k + 1) / n
            w = wall + (edge - wall) * (k + 1) / n
            parts.append(extrude(band(w), z0, z1, f"cutter-edge{k}"))

    # 顶桥：把内岛刃拉回外圈，否则内岛是悬空孤件
    if has_void and bridge > 0:
        zone = band(max(wall, edge))
        polys = list(zone.geoms) if hasattr(zone, "geoms") else [zone]
        if len(polys) >= 2:
            outer = max(polys, key=lambda p: p.area)
            for isl in [p for p in polys if p is not outer]:
                try:
                    p1, p2 = nearest_points(outer.boundary, isl.boundary)
                    bar = LineString([p1, p2]).buffer(bridge / 2.0, cap_style="round",
                                                      join_style="round")
                    parts.append(extrude(bar, max(height - 2.0, top), height, "cutter-bridge"))
                    log(f"  [i] 内岛刃顶桥 {bridge:.1f}mm：({p1.x:.1f},{p1.y:.1f}) -> "
                        f"({p2.x:.1f},{p2.y:.1f})")
                except Exception as e:  # noqa: BLE001
                    log(f"  [!] 顶桥生成失败：{e}")

    m = safe_union(parts)
    if m is None:
        return None
    m.merge_vertices()
    m.fix_normals()
    return m


def apply_pockets(mesh, specs, base_t):
    """底模板顶面铣环形沉台（--pocket）：粘土压进去就凸起一圈立体环（挂环效果）。

    沉台外侧带一点拔模（分两段，下窄上宽 0.15mm），泥才好拔出来。
    """
    solids = []
    for spec in specs:
        try:
            cx, cy, rin, rout, dep = [float(v) for v in spec.split(",")]
        except Exception:  # noqa: BLE001
            log(f"  [!] --pocket 格式应为 CX,CY,RIN,ROUT,DEPTH：{spec}")
            continue
        if dep <= 0 or rout <= rin:
            log(f"  [!] --pocket 参数不合理（DEPTH>0 且 ROUT>RIN）：{spec}")
            continue
        z0 = max(base_t - dep, 0.2)
        steps = [(z0, base_t - dep * 0.5, rout), (base_t - dep * 0.5, base_t + 0.45, rout + 0.15)]
        for za, zb, ro in steps:
            ann = (shapely.Point(cx, cy).buffer(ro, resolution=96)
                   .difference(shapely.Point(cx, cy).buffer(rin, resolution=96)))
            m = extrude(ann, za, zb, "pocket")
            if m is not None:
                solids.append(m)
        log(f"  [i] 环形沉台 φ{2 * rin:.1f}/φ{2 * rout:.1f} 深 {dep:.1f}mm @ ({cx:.1f},{cy:.1f})")
    if not solids:
        return mesh
    try:
        out = trimesh.boolean.difference([mesh] + solids, engine="manifold", check_volume=False)
    except Exception as e:  # noqa: BLE001
        log(f"  [!] 沉台差集失败：{e}")
        return mesh
    out.merge_vertices()
    out.fix_normals()
    return out


def _probe(path):
    """读 STL 拿 外形/面数/水密/体积，用于写清单。"""
    import trimesh as _tm
    m = _tm.load(str(path), force="mesh")
    b = m.bounds
    return ([round(float(b[1][i] - b[0][i]), 1) for i in range(3)],
            int(len(m.faces)), bool(m.is_watertight), round(float(m.volume) / 1000.0, 2))


def write_manifest(job_dir: Path, job: str, report: dict, args,
                   base_stl: Path, cutter_stl, watertight: bool, plate_stl=None):
    """写 out/<job>/MANIFEST.md：这批出了哪些文件、哪些能直接打印。"""
    import datetime as _dt
    t = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    sink = getattr(args, "relief_mode", "raise") == "sink"
    mode_txt = (f"凹模（图案下沉 {args.relief}mm，成品图案凸起，槽壁外张 {args.cavity_draft}°）"
                if sink else f"凸模（浮雕 {args.relief}mm，成品图案凹陷）")
    head = (f"> 输入 `{Path(args.input).name}` · 成品 {args.size}mm · {mode_txt} · "
            f"底板 {args.base_thickness}mm · 最小线宽 {args.min_stroke or '不改'}")
    if getattr(args, "close_gap", 0) > 0:
        head += f" · 窄缝闭合 {args.close_gap}mm（填实）"
    if getattr(args, "stroke_cap", 0) > 0:
        head += f" · 线宽上限 {args.stroke_cap:g}mm"
    frame = (report or {}).get("frame") or {}
    if frame.get("applied"):
        head += f" · 外轮廓规整 {frame.get('petals_used')} 瓣"
    if getattr(args, "hole", None):
        ds = [f"φ{d.split(',')[2].strip()}mm" for d in args.hole if len(d.split(",")) >= 3]
        if ds:
            head += " · 打孔定位孔 " + "/".join(ds)
    if getattr(args, "pocket", None):
        head += f" · 环形沉台 {len(args.pocket)} 个"
    if getattr(args, "void_mask", None):
        base_txt = ("，底模整片闭合" if getattr(args, "void_base", "both") == "cutter"
                    else "，底模同位置留空")
        head += (f" · 挖空区（边框内岛刃 + 顶桥 {getattr(args, 'island_bridge', 3.0)}mm{base_txt}）")
    def _rel(p):
        try:
            return Path(p).resolve().relative_to(Path.cwd().resolve()).as_posix()
        except Exception:
            return Path(p).as_posix()

    L = [f"# {job} · 输出清单", "",
         f"> 由 `stamp_pipeline.py` 自动生成（{t}），别手改。",
         head, "",
         f"## 可以直接打印（`{_rel(base_stl.parent)}/`）", "",
         "| 件 | 文件 | 外形 mm | 面数 | 水密 | 体积 cm³ |", "|---|---|---|---|---|---|"]
    for label, p in (("底模" if not sink else "凹模", base_stl), ("边框", cutter_stl)):
        if not p:
            continue
        size, faces, wt, vol = _probe(p)
        L.append(f"| {label} | `{_rel(p)}` | "
                 f"{size[0]} × {size[1]} × {size[2]} | "
                 f"{faces:,} | {'✓' if wt else '×'} | {vol} |")
    if not cutter_stl:
        L.append("| 边框 | _本次没出（`--no-cutter` 或 `--rim-w>0`）_ | | | | |")
    if plate_stl:
        clr = (report.get("plate") or {}).get("clearance_mm", 0.8)
        size, faces, wt, vol = _probe(plate_stl)
        L.append(f"| 合盘 | `{_rel(plate_stl)}` | "
                 f"{size[0]} × {size[1]} × {size[2]} | "
                 f"{faces:,} | {'✓' if wt else '×'} | {vol} |")
        L += ["", f"> `plate.stl` = 底模套在边框内腔同盘打印（装配间隙 {clr:g}mm）；仍是两件，打完取出底模用。"]
    L += ["", "## 只给人看", "", "| 文件 | 内容 |", "|---|---|",
          "| `preview.png` | 三栏预览：镜像实物 / 压印效果 / 半剖带尺寸 |",
          "| `report.json` | 几何体检：尺寸 / 面数 / 水密 / 线宽 / 边框参数 |"]
    if (job_dir / "lines.svg").exists():
        L.append("| `lines.svg` | 分层 SVG（底面 / 图案分开，可进 Inkscape 手改） |")
    if (job_dir / "model.html").exists():
        L.append("| `model.html` | 单文件 3D 预览，双击即开 |")
    if (job_dir / "frame_check.png").exists():
        L.append("| `frame_check.png` | 外轮廓检测：原始轮廓 / 峰谷 / 规整后轮廓 |")
    L += ["", "## 打印设置", "",
          "- 底模：平板贴床、**图案朝上**，0.2 喷嘴 0.10 层高 / **100% 填充（底线）+ 8 墙（0.4 喷嘴；0.2 喷嘴线宽细，以填充为准）** / **Arachne** / 顶壳 6 / **顶面不熨烫** / 无支撑；"
          "只有 0.4 喷嘴时先加 `--min-stroke 0.9`。",
          "  墙数 × 线宽 ≥ 最大笔画（本单见 report.json 的 `wall_hint`）时，笔画内部没有可放填充的缝，即使填充被改回 15–25% 也不会蜂窝；"
          "100% 填充本身也能兜底，两者一起用。熨烫会把窄浮雕顶端熨平，实物上表现为「线条断开」，务必关掉。",
          "- 边框：**翼缘贴床、刃口朝上**，4 墙 + 4mm brim，打完翻过来用（单壁 1.0 到底，不再是薄刃）。",
          "- 手柄：`print/standard/handle_straight.stl`（标准件，粘在底模背面中心；批量打 `handle_straight_x12.stl`）。", "",
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
    ap.add_argument("--relief", type=float, default=2.5, help="图案凸起高度 mm（默认 2.5）")
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
    ap.add_argument("--stroke-cap", type=float, default=0.0,
                    help="实验项，默认 0=关闭。按骨架把宽笔画收细到该值；"
                         "转角多的字母（A/M 等）可能形变，量产件不要用")
    ap.add_argument("--margin", type=float, default=1.2, help="底面轮廓相对图案外扩的边距 mm")
    ap.add_argument("--close-gap", type=float, default=0.0,
                    help="窄缝闭合 mm：把轮廓上窄于 2×该值的凹口/窄缝填实（默认 0=不处理）")
    ap.add_argument("--hole", action="append", default=[], metavar="COL,ROW,D",
                    help="底模板开打孔定位通孔：输入图像素坐标 COL,ROW + 孔径 mm；可重复")
    ap.add_argument("--void-mask", default=None,
                    help="挖空区掩码 PNG（黑=挖掉；与 --input 同尺寸同原点）。给了就在边框里长出"
                         "内岛刃、底模同位置开洞，粘土成品是一个闭合的洞")
    ap.add_argument("--island-bridge", type=float, default=3.0,
                    help="内岛刃与外圈的顶桥宽度 mm（0=不搭桥，内岛会成孤立件）")
    ap.add_argument("--void-base", choices=["both", "cutter"], default="both",
                    help="挖空区作用到哪：both=底模也开洞（粘土通透空）；"
                         "cutter=只边框长内岛刃、底模保持整片（粘土上只是一个闭合的三角线/可挑出来）")
    ap.add_argument("--pocket", action="append", default=[], metavar="CX,CY,RIN,ROUT,DEPTH",
                    help="底模板上铣环形沉台（模型 mm 坐标），粘土上压出一圈立体凸环；可重复")
    ap.add_argument("--rim-w", type=float, default=0.0,
                    help="一体式外沿凸边框宽度 mm（0=不做，分体模式默认 0）。\n"
                         "分体模式请用 --cutter 单独出边框，别用这个")
    ap.add_argument("--rim-h", type=float, default=0.4,
                    help="边框比浮雕顶面再高出的量 mm（仅 --rim-w>0 有效）")
    # ---- 边框（独立切模）
    ap.add_argument("--no-cutter", action="store_true",
                    help="不出边框 STL（默认出，随便框跟底模分离）")
    ap.add_argument("--cutter-wall", type=float, default=1.0,
                    help="边框壁厚 mm（定稿单壁：主体与刃口同厚，默认 1.0）")
    ap.add_argument("--cutter-height", type=float, default=15.0,
                    help="边框总高 mm（含底部翼缘，默认 15 = 切割高度 1.5cm）")
    ap.add_argument("--cutter-edge", type=float, default=1.0,
                    help="刃口厚度 mm（翻转后朝下切粘土那面）；定稿与 --cutter-wall 同值 = 单壁，不外分薄刃")
    ap.add_argument("--cutter-edge-h", type=float, default=3.0,
                    help="刃口薄壁段高度 mm（该段整段都是 --cutter-edge 这么厚）")
    ap.add_argument("--cutter-edge-mode", choices=["vertical", "taper"], default="vertical",
                    help="刃口形态：vertical=外壁一次性收薄后垂直到底（默认，零斜面、侧面对比干净）；"
                         "taper=旧 8 段阶梯锥面（侧面有台阶，不推荐）")
    ap.add_argument("--cutter-flange-w", type=float, default=4.0,
                    help="底部翼缘外扩宽 mm（贴床防翘、翻过来当握边）")
    ap.add_argument("--cutter-flange-t", type=float, default=1.6,
                    help="翼缘厚度 mm")
    ap.add_argument("--cutter-clearance", type=float, default=0.8,
                    help="底模相对边框内腔的内缩 mm（防粘壁/防卡，单边；FDM 实测 0.4 会卡，默认 0.8）")
    ap.add_argument("--scale", type=float, default=1.0, help="线稿放大倍数（补救低分辨率细线）")
    ap.add_argument("--frame-mode", choices=["silhouette", "keep", "ignore"], default="silhouette",
                    help="silhouette=外框转底面并丢弃框体(默认)\nkeep=框也当图案\nignore=丢框用圆底")
    ap.add_argument("--frame-regularize", choices=["off", "auto", "force"], default="auto",
                    help="外轮廓花瓣规整：auto=只在检测到明显大小/间距不均时规整（默认）；\n"
                         "force=按检测到的瓣数强制规整；off=保留原轮廓")
    ap.add_argument("--frame-petals", type=int, default=None,
                    help="强制指定花瓣数（6-24）；不填则用检测值")
    ap.add_argument("--no-mirror", action="store_true", help="不镜像（仅当你要直接看图案本身）")
    ap.add_argument("--thr", type=float, default=None, help="手动二值阈值 0-255")
    ap.add_argument("--invert", action="store_true", help="反相（白线黑底）")
    ap.add_argument("--simplify", type=float, default=0.02, help="曲线简化容差 mm（默认 0.02）")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--svg", action="store_true", help="同时导出分层 SVG")
    ap.add_argument("--print-dir", default="print",
                    help="可打印 STL 的根目录（默认 print/；每单落到 print/jobs/<job>/）")
    ap.add_argument("--job", default=None,
                    help="打印目录里的单号，可带批次子目录（如 xmas40/snowman_A）；"
                         "默认取 --out 的最后一段目录名")
    ap.add_argument("--no-index", action="store_true",
                    help="不刷新根目录 PRINT.md（批量出件时用，批次结束统一刷一次）")
    args = ap.parse_args(argv)

    # ---- 输出布局（约定见 guides/output-layout.md）
    #   print/jobs/<job>/base.stl      可打印：底模 / 凹模
    #   print/jobs/<job>/cutter.stl    可打印：边框
    #   out/<job>/                     其余全部（report / preview / svg / model / MANIFEST）
    out = Path(args.out)
    job_dir = out.with_suffix("") if out.suffix else out      # 兼容老写法 --out out\x.stl
    job = args.job.strip("/") if args.job else job_dir.name
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
    capped = []
    if args.stroke_cap > 0:
        pattern_mask, capped = cap_stroke_width(pattern_mask, args.stroke_cap, rough_mm_per_px)
        stats = stroke_stats(pattern_mask, rough_mm_per_px) or stats
    wall_hint = None
    if stats and stats.get("max", 0) > 0:
        wall_hint = max(2, int(math.ceil(stats["max"] / 0.42)))
        log(f"  [i] 建议切片墙数 ≥ {wall_hint}（0.42mm ×{wall_hint} = {wall_hint * 0.42:.2f}mm "
            f"≥ 最大笔画 {stats['max']}mm）：笔画内部不留填充，蜂窝从切片层面消失")

    # ---- 4. 矢量化
    pat = mask_to_geometry(pattern_mask)
    base_raw = mask_to_geometry(base_mask) if base_mask is not None else None
    frame_info = {"mode": args.frame_regularize, "applied": False, "reason": "",
                  "detected": None, "petals_used": None, "area_change_pct": None}
    frame_m = None
    if base_raw is not None and not base_raw.is_empty and args.frame_mode == "silhouette":
        if args.frame_regularize == "off":
            frame_info["reason"] = "off"
        else:
            base_raw_orig = base_raw
            base_raw, frame_info, frame_m = regularize_frame(
                base_raw, args.frame_regularize, args.frame_petals)
            if frame_info["applied"]:
                outside = pat.difference(base_raw.buffer(0.5)).area
                if outside > max(1.0, pat.area * 0.002):
                    log("  [!] 规整轮廓会切到图案，回退原轮廓")
                    base_raw = base_raw_orig
                    frame_info["applied"] = False
                    frame_info["reason"] = "pattern_conflict"
            detected = frame_info.get("detected")
            if detected:
                if frame_info["applied"]:
                    status = "规整"
                elif frame_info["reason"] == "already_regular":
                    status = "已较规整，保留"
                elif frame_info["reason"] == "not_scallop":
                    status = "非花瓣框，保留原轮廓"
                elif frame_info["reason"] == "pattern_conflict":
                    status = "规整被回退（切到图案）"
                else:
                    status = f"未规整（{frame_info['reason']}）"
                log(f"  [i] 外轮廓：{detected['petals']} 瓣，间距CV "
                    f"{detected['spacing_cv'] * 100:.1f}%，峰半径CV "
                    f"{detected['peak_radius_cv'] * 100:.1f}%，圆度 "
                    f"{detected['circularity']:.3f}/实心度 {detected['solidity']:.3f} -> {status}")
                if frame_info["applied"]:
                    log(f"  [i] 花瓣规整：{frame_info['petals_used']} 瓣等距，"
                        f"面积变化 {frame_info['area_change_pct']:+.1f}%")
    elif base_mask is None:
        frame_info["reason"] = "no_frame"
    elif args.frame_regularize != "off":
        frame_info["reason"] = "frame_mode"
    if pat.is_empty:
        log("[x] 图案矢量化后为空，检查阈值/反相设置")
        return 2
    log(f"  [i] 图案：{len(pat.geoms)} 个多边形")

    # ---- 5. 缩放 / 镜像 / 居中
    ref = base_raw if (base_raw is not None and not base_raw.is_empty) else pat
    _, ref_w, ref_h = geom_bounds(ref)
    has_silhouette = base_raw is not None and not base_raw.is_empty and args.frame_mode != "ignore"
    # --size 指「成品尺寸」= 边框内腔 = 切出来的粘土外形（不再为 clearance 打折）。
    clr = 0.0 if (args.no_cutter or args.rim_w > 0) else args.cutter_clearance
    if clr > 0:
        log(f"  [i] 分体模式：成品 {args.size}mm = 边框内腔，底模按 {clr}mm/边 内缩")
    target = args.size - 2 * args.margin      # 底面再外扩 margin 就是内腔
    s = max(target, 1.0) / max(ref_w, ref_h)
    log(f"  [i] 参考轮廓 {ref_w:.1f}x{ref_h:.1f}px -> 比例 {s:.5f} mm/px")

    fx = -s if not args.no_mirror else s
    if fx < 0:
        log("  [i] 已 X 轴镜像（凸印章默认）")

    # 轮廓/图案/孔统一以「参考轮廓」包围盒中心为原点：旧版逐件各自居中，
    # 图案与轮廓包围盒不一致时会被各推一下，属于隐藏错位。
    ref_scaled = affinity.scale(ref, xfact=fx, yfact=s, origin=(0, 0))
    rbb = ref_scaled.bounds
    off = (-(rbb[0] + rbb[2]) / 2.0, -(rbb[1] + rbb[3]) / 2.0)

    def place(g):
        if g is None or g.is_empty:
            return g
        g2 = affinity.scale(g, xfact=fx, yfact=s, origin=(0, 0))
        return affinity.translate(g2, xoff=off[0], yoff=off[1])

    def place_pt(col, row):
        """输入图像素 (col,row) -> 模型 mm（与 mask_to_geometry 的 y 翻转一致）。"""
        return (fx * col + off[0], s * (-row) + off[1])

    pat_mm = place(pat)
    base_ref_mm = place(ref)

    # 外轮廓 = 边框内腔 = 成品轮廓（唯一基准，底模由它缩出来）
    if has_silhouette:
        cavity_mm = base_ref_mm.buffer(args.margin, join_style="round")
    else:
        _, w, h = geom_bounds(base_ref_mm)
        r = max(w, h) / 2 + args.margin
        cavity_mm = shapely.Point(0, 0).buffer(r, resolution=96)

    # 「实心」：把轮廓上窄于 2×close_gap 的凹口/窄缝填掉（形态学闭合）。
    # 两腿之间那种 1~2mm 的缝，切割时会把泥挤进去形成飞边，闭合后切口才是整块料。
    # 缝口被合上后里面可能留出一个内腔，一律填实（轮廓本来就不该有洞）；
    # 真要开孔请用 --hole，它在这之后减，不会被吃掉。
    if args.close_gap > 0:
        rr = float(args.close_gap)
        cavity_mm = cavity_mm.buffer(rr, join_style="round").buffer(-rr, join_style="round")
        polys = list(cavity_mm.geoms) if hasattr(cavity_mm, "geoms") else [cavity_mm]
        n_holes = sum(len(p.interiors) for p in polys)
        if n_holes:
            cavity_mm = MultiPolygon([Polygon(p.exterior) for p in polys if not p.is_empty])
            log(f"  [i] 窄缝闭合 {rr}mm：填实窄于 {2 * rr:.1f}mm 的凹口，"
                f"并填掉闭合后留下的 {n_holes} 个内腔")
        else:
            log(f"  [i] 窄缝闭合 {rr}mm：填实窄于 {2 * rr:.1f}mm 的凹口")
    if cavity_mm.is_empty:
        log("[x] 轮廓闭合后为空，close-gap 给太大")
        return 2

    # ---- 挖空区（边框内岛刃切出来的那个洞）
    void_mm = None
    if args.void_mask:
        vpath = Path(args.void_mask)
        if not vpath.exists():
            log(f"[x] 找不到 --void-mask：{vpath}")
            return 2
        vmask, vthr = load_mask(vpath)
        if vmask.shape != mask.shape:
            log(f"[x] --void-mask 尺寸 {vmask.shape} 与 --input {mask.shape} 不一致")
            return 2
        vraw = mask_to_geometry(vmask)
        if not vraw.is_empty:
            void_mm = place(vraw)
            if not cavity_mm.contains(void_mm):
                log("  [!] 挖空区没完全落在外轮廓内，超出的部分会被截掉")
            cavity_solid_mm = cavity_mm            # 底模用（不扣挖空区，保持整片料）
            cavity_mm = cavity_mm.difference(void_mm)
            _, wv, hv = geom_bounds(void_mm)
            if getattr(args, "void_base", "both") == "cutter":
                log(f"  [i] 挖空区 {wv:.1f}x{hv:.1f}mm：边框长出内岛刃，底模保持整片（三角形闭合）")
            else:
                log(f"  [i] 挖空区 {wv:.1f}x{hv:.1f}mm：边框长出内岛刃，底模同位置开洞")

    # 底模 = 内腔沿法向内缩 clr。不能用「底模再外扩」求内腔：外扩会把窄缝跨接，
    # 出现「边框一段圆弧、底模一个尖」的环隙跳变（本单实测局部 3.5mm）。
    base_cavity = (cavity_solid_mm if (void_mm is not None
                  and getattr(args, "void_base", "both") == "cutter") else cavity_mm)
    base_mm = (base_cavity.buffer(-clr, join_style="round") if clr > 0 else base_cavity)

    # ---- 打孔定位通孔（底模板上开孔，压完用同径冲子从孔里穿下去打穿粘土）
    hole_geoms, hole_info = [], []
    for spec in (args.hole or []):
        try:
            col, row, dia = [float(v) for v in spec.split(",")]
        except Exception:  # noqa: BLE001
            log(f"  [!] --hole 格式应为 COL,ROW,D：{spec}")
            return 2
        cxy = place_pt(col, row)
        hole_geoms.append(shapely.Point(*cxy).buffer(max(dia, 0.5) / 2.0, resolution=48))
        hole_info.append((cxy[0], cxy[1], dia))
    if hole_geoms:
        ok_all = True
        for g in hole_geoms:
            if not base_mm.buffer(-0.2).contains(g):
                ok_all = False
        if not ok_all:
            log("  [!] 有孔不在底模实心区（贴边或落在缝里），这几个会被削掉一部分")
        holes_union = unary_union(hole_geoms)
        base_mm = base_mm.difference(holes_union)
        pat_mm = pat_mm.difference(holes_union.buffer(0.25, join_style="round"))
        log("  [i] 底模打孔定位孔：" + " | ".join(
            f"φ{dia:.1f}mm @ ({x:.1f}, {y:.1f})" for x, y, dia in hole_info))

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
        if D > B - 1.0:
            log(f"  [!] 槽深 {D}mm 超过底板 {B}mm 的安全上限（底留 1mm），已压到 {B - 1.0:.1f}mm"
                f"；要 2.5mm 槽深请加 --base-thickness 4.0")
            D = B - 1.0
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
    pocket_list = []
    if args.pocket:
        mesh = apply_pockets(mesh, args.pocket, B)
        if mesh is None:
            log("[x] 环形沉台处理失败")
            return 3
        mesh.merge_vertices()
        mesh.fix_normals()
        for spec in args.pocket:
            try:
                pocket_list.append(tuple(float(v) for v in spec.split(",")))
            except Exception:
                pass
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
        inner_geom = cavity_mm      # 内腔就是成品轮廓本身，底模由它内缩而来
        cm = None
        if args.cutter_engine == "scad" and void_mm is None:
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
                              edge_mode=args.cutter_edge_mode,
                              void=void_mm, bridge=args.island_bridge)
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

    # ---- 合盘：底模套进边框内腔，同盘一个 STL（两件仍独立）
    plate_stl, plate_info = None, {}
    if cutter_stl is not None:
        try:
            bm = trimesh.load(str(base_stl))
            cm2 = trimesh.load(str(cutter_stl))
            # 同心嵌套：底模居中放进边框内腔，底面同贴床（实际批量就是这么打的）
            cc = (cm2.bounds[0][:2] + cm2.bounds[1][:2]) / 2
            bc = (bm.bounds[0][:2] + bm.bounds[1][:2]) / 2
            bm.apply_translation([float(cc[0] - bc[0]), float(cc[1] - bc[1]), 0.0])
            plate = trimesh.util.concatenate([bm, cm2])
            # 先按切片器口径重焊一遍点，再剔掉个别边框带出的零体积膜片
            tmp_stl = job_print / ".plate_merge.stl"
            plate.export(str(tmp_stl))
            plate = trimesh.load(str(tmp_stl))
            parts = plate.split(only_watertight=False)
            good = [p for p in parts if abs(p.volume) >= 0.05]
            if len(good) != len(parts):
                plate = trimesh.util.concatenate(good)
            plate_stl = job_print / "plate.stl"
            plate.export(str(plate_stl))
            tmp_stl.unlink()
            plate = trimesh.load(str(plate_stl))
            pb = plate.bounds
            plate_info = {
                "file": str(plate_stl),
                "parts": ["base", "cutter"],
                "layout": "nested",
                "clearance_mm": round(float(clr), 2),
                "size_mm": [round(float(pb[1][i] - pb[0][i]), 2) for i in range(3)],
                "triangles": int(len(plate.faces)),
                "watertight": bool(plate.is_watertight),
            }
            log(f"  合盘 STL   : {plate_stl}  (底模套边框, 间隙 {clr:.1f}mm, "
                f"{plate_info['size_mm'][0]:.0f}x{plate_info['size_mm'][1]:.0f}mm, "
                f"水密 {plate.is_watertight})")
            if clr < 0.2:
                log("  [!] 底模与边框内壁间隙 <0.2mm，合盘会粘连，建议加 --cutter-clearance")
            if plate_info["size_mm"][0] > 256 or plate_info["size_mm"][1] > 256:
                log("  [!] 合盘超过 256mm 热床，切片时需分开打或换大床机型")
        except Exception as e:
            log(f"  [!] 合盘导出失败：{e}")

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
        "close_gap_mm": args.close_gap,
        "holes": [{"x": round(x, 2), "y": round(y, 2), "d_mm": d} for x, y, d in hole_info],
        "min_stroke_mm": args.min_stroke,
        "stroke_cap_mm": args.stroke_cap or None,
        "stroke_capped_parts": len(capped),
        "bbox_mm": [round(float(bb[1][i] - bb[0][i]), 3) for i in range(3)],
        "triangles": int(len(mesh.faces)),
        "watertight": bool(watertight),
        "volume_cm3": round(float(vol), 2),
        "pattern_parts": len(pat_mm.geoms),
        "thin_parts_fixed": len(fixed),
        "thin_parts_at_risk": int(lost),
        "stroke_stats_mm": stats,
        "wall_hint": wall_hint,
        "frame": frame_info,
        "cutter": cutter_info,
        "plate": plate_info,
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
                            rim_w=rim_w, rim_h=rim_h, note=note, sink=sink,
                            pockets=pocket_list)
        log(f"  预览       : {p1}")

    if (not args.no_preview and frame_info.get("detected")
            and (frame_info["applied"] or frame_info["detected"]["suggest"])):
        render_frame_check(src, base_mask, frame_m,
                           base_raw if frame_info["applied"] else None,
                           job_dir / "frame_check.png")
        log(f"  外轮廓检查 : {job_dir / 'frame_check.png'}")

    write_manifest(job_dir, job, report, args, base_stl, cutter_stl, watertight, plate_stl)

    if not watertight:
        log("  [!] 网格非水密，切片前请在 Bambu Studio 里做一次修复")

    if getattr(args, "no_index", False):
        log("  清单       : 跳过 PRINT.md（--no-index）")
    else:
        refresh_print_index()
    return 0


if __name__ == "__main__":
    sys.exit(main())

