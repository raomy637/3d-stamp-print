"""位图 / 描边稿 → 矢量 SVG：线宽封顶 + 花瓣等径重建（纯代码，不重生图、不改图案）。

为什么需要它
------------
源稿是位图时，"改线宽"只能靠重画（错）或腐蚀（错）。正确做法是：把位图先变成真矢量，
再在矢量层把线宽封顶，最后再回光栅化出模。这样：
- 图案拓扑、笔画走向、文字字形完全来自原稿（骨架定位，中心线不动）；
- 线宽可精确到 mm（封顶 / 只压不涨）；
- 外框花瓣按检测到的瓣数重建成等径圆弧，瓣径与角间距完全一致。

关键实现
--------
1. 每块取骨架（剪短毛刺）→ 逐点半径 r = min(局部半宽, cap/2) → 按"最近骨架点半径"重建。
   这是"只有上限、只压不涨"：源线比 cap 细的地方保持原样（不会被加粗）。
2. 外框环单独处理：填充成剪影 → 极坐标测瓣数/峰谷 → `build_scallop_polygon` 重建等径花瓣 →
   取"外边界 = 理想剪影、内边界 = 内缩一个环宽"的环，环宽独立控制（默认 1.5mm）。
3. 轮廓追踪（marching squares，0.5 等值线）→ shapely 多边形（按嵌套深度拼孔）→
   SVG（`fill-rule=evenodd`，单位 mm）+ 抗锯齿 PNG（喂 stamp_pipeline）。

用法
----
  python src/tools/raster_to_svg.py --input 原图.png --out-svg 图.svg --out-png 图_1mm.png \
      --size 101.6 --cap-mm 1.0 --frame-mm 1.5 --px 3000

  # 只量不改（诊断源稿线宽区间、瓣数、是否有并块风险）
  python src/tools/raster_to_svg.py --input 原图.png --out-png x.png --cap-mm 9 --dry-run
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from skimage import filters, measure, morphology
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(_HERE))

import stamp_pipeline as sp
from monoline_normalize import prune_spurs


# --------------------------------------------------------------------------- #
# 1. 读图与二值化
# --------------------------------------------------------------------------- #

def load_mask(path: Path, thr: float | None = None, work_scale: float = 1.0):
    g = np.asarray(Image.open(path).convert("L"))
    if work_scale > 1.0:
        im = Image.fromarray(g)
        g = np.asarray(im.resize((int(round(g.shape[1] * work_scale)),
                                  int(round(g.shape[0] * work_scale))), Image.LANCZOS))
    t = float(thr) if thr is not None else float(filters.threshold_otsu(g))
    if t <= 1.0:                      # 纯 0/255 图 Otsu 会退化
        t = 128.0
    mask = g < t
    if mask.mean() > 0.55:
        mask = ~mask
    return g, mask, t


def span_px(mask: np.ndarray) -> int:
    ys, xs = np.where(mask)
    return int(max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1))


# --------------------------------------------------------------------------- #
# 2. 量线宽（骨架中位）
# --------------------------------------------------------------------------- #

def comp_widths(mask: np.ndarray, mmpp: float, min_area: int = 40):
    dt = ndi.distance_transform_edt(mask)
    lab, n = ndi.label(mask, np.ones((3, 3)))
    rows = []
    for i in range(1, n + 1):
        reg = lab == i
        a = int(reg.sum())
        if a < min_area:
            continue
        sk = morphology.skeletonize(reg)
        if not sk.any():
            continue
        rows.append({"idx": i, "area_px": a, "width_mm": round(float(np.median(dt[sk])) * 2 * mmpp, 3)})
    return rows, n


def summarize(rows):
    if not rows:
        return {"parts": 0, "min": 0.0, "median": 0.0, "max": 0.0}
    w = np.array([r["width_mm"] for r in rows])
    return {"parts": len(w), "min": round(float(w.min()), 2), "median": round(float(np.median(w)), 2),
            "max": round(float(w.max()), 2)}


# --------------------------------------------------------------------------- #
# 3. 线宽封顶（只压不涨，中心线不动）
# --------------------------------------------------------------------------- #

def cap_mask(mask: np.ndarray, cap_px: float, min_area: int = 6, smooth_sigma: float = 0.0) -> np.ndarray:
    """每块骨架 → 逐点半宽 min(dt, cap/2) → 按最近骨架点半径重建。

    与"直接腐蚀"的区别：腐蚀在交叉/接头处会留粗块、在窄处削断；
    这里半径由骨架点决定性给出，中心线严格不动。
    `smooth_sigma` 只平滑"半径值"，让沿骨架的宽度不随像素台阶抖（边缘不再呈波浪）。
    """
    dt_full = ndi.distance_transform_edt(mask)
    if smooth_sigma > 0:
        dt_r = ndi.gaussian_filter(dt_full, smooth_sigma)
    else:
        dt_r = dt_full
    lab, n = ndi.label(mask, np.ones((3, 3)))
    out = np.zeros_like(mask)
    half = cap_px / 2.0
    for i in range(1, n + 1):
        reg = lab == i
        if reg.sum() < min_area:
            out |= reg
            continue
        sk = prune_spurs(morphology.skeletonize(reg))
        ys, xs = np.where(sk)
        if len(ys) == 0:
            out |= reg
            continue
        rval = np.zeros(mask.shape, dtype=float)
        rval[ys, xs] = np.minimum(dt_r[ys, xs], half)
        # 每个像素归到最近骨架点，用该点半径判定是否保留
        dist, inds = ndi.distance_transform_edt(~sk, return_indices=True)
        near = rval[inds[0], inds[1]]
        keep = dist <= near
        out |= keep
    return out


# --------------------------------------------------------------------------- #
# 4. 外框：等径花瓣重建
# --------------------------------------------------------------------------- #

def _scallop_ring(ideal: Polygon, cx: float, cy: float, w: float) -> Polygon | None:
    """沿理想等径花瓣的边界径向内缩 w/2 得到中线，再描边 w → 均匀环。

    不要"每瓣画一整段圆弧再取并集"：瓣很浅时圆弧跨过的角远大于 2π/n（实测 37.7° vs 11.25°），
    相邻弧会互相叠出三角形补丁。用多边形边界反算 r(θ) 就不会重叠。
    """
    coords = np.asarray(ideal.exterior.coords[:-1], dtype=float)
    dx, dy = coords[:, 0] - cx, coords[:, 1] - cy
    theta = np.arctan2(dy, dx)
    rad = np.hypot(dx, dy)
    order = np.argsort(theta)
    grid = np.linspace(-math.pi, math.pi, 2160, endpoint=False)
    r_side = np.interp(grid, theta[order], rad[order], period=2 * math.pi)
    rc = r_side - w / 2.0
    if (rc <= 0).any():
        return None
    pts = [(cx + rc[i] * math.cos(g), cy + rc[i] * math.sin(g)) for i, g in enumerate(grid)]
    pts.append(pts[0])
    ring = LineString(pts).buffer(w / 2.0, quad_segs=10)
    return ring if isinstance(ring, Polygon) and not ring.is_empty else None


def _ring_centerline_from_arcs(m, w: float, petals: int | None) -> Polygon | None:
    """备用：按每瓣圆弧公式生成中线（仅当 ideal 多边形不可用时）。"""
    n = int(petals or m["petals"])
    if not 6 <= n <= 24:
        return None
    R, rv = float(m["R"]), float(m["r_in"])
    delta = math.pi / n
    den = 2 * (R - rv * math.cos(delta))
    if den <= 0:
        return None
    c = (R * R - rv * rv) / den
    rho = R - c
    if rho <= 0 or w / 2 >= rho:
        return None
    phi_end = min(abs(math.atan2(rv * math.sin(delta), rv * math.cos(delta) - c)), delta)
    pts = []
    for i in range(n):
        base = m["phase"] + 2 * math.pi * i / n
        for phi in np.linspace(-phi_end, phi_end, 48, endpoint=False):
            rad = c * math.cos(phi) + math.sqrt(max(rho * rho - c * c * math.sin(phi) ** 2, 0.0)) - w / 2
            if rad <= 0:
                continue
            pts.append((m["cx"] + rad * math.cos(base + phi), m["cy"] + rad * math.sin(base + phi)))
    if len(pts) < 3:
        return None
    pts.append(pts[0])
    ring = LineString(pts).buffer(w / 2.0, quad_segs=10)
    return ring if isinstance(ring, Polygon) and not ring.is_empty else None


def rebuild_frame(frame: np.ndarray, frame_mm: float, mmpp: float, petals: int | None):
    """返回 (ring_shapely_or_None, info)。ring = 等径花瓣环。"""
    info = {"detected": False, "reason": "", "petals": None, "peak_cv_before": None,
            "spacing_cv_before": None, "peak_cv_after": None, "width_mm": round(frame_mm, 2)}
    sil = ndi.binary_fill_holes(frame)
    cs = measure.find_contours(np.pad(sil, 1).astype(float), 0.5)
    if not cs:
        info["reason"] = "no_silhouette"
        return None, info
    poly = Polygon([(x - 1, y - 1) for y, x in max(cs, key=len)])
    if not poly.is_valid:
        poly = poly.buffer(0)
    m = sp.analyze_scallop(poly)
    if m is None:
        info["reason"] = "not_scallop"
        return poly, info
    info.update({"detected": True, "petals": int(m["petals"]),
                 "peak_cv_before": round(m["peak_radius_cv"], 4),
                 "spacing_cv_before": round(m["spacing_cv"], 4)})
    ideal = sp.build_scallop_polygon(m, petals)
    if ideal is None:
        info["reason"] = "build_failed"
        return poly, info
    w = max(frame_mm / mmpp, 1.0)
    ring = _scallop_ring(ideal, m["cx"], m["cy"], w) or _ring_centerline_from_arcs(m, w, petals)
    if ring is None:
        info["reason"] = "ring_build_failed"
        return poly, info
    mm_after = sp.analyze_scallop(ideal)
    if mm_after is not None:
        info.update({"peak_cv_after": round(mm_after["peak_radius_cv"], 4),
                     "spacing_cv_after": round(mm_after["spacing_cv"], 4),
                     "petals_after": int(mm_after["petals"])})
    info["petals_used"] = int(petals or m["petals"])
    return ring, info


# --------------------------------------------------------------------------- #
# 5. 掩码 → 多边形（含孔）
# --------------------------------------------------------------------------- #

def mask_to_polys(mask: np.ndarray, min_area: float = 0.5) -> list[Polygon]:
    cs = measure.find_contours(np.pad(mask, 1).astype(float), 0.5)
    rings = []
    for c in cs:
        if len(c) < 4:
            continue
        p = Polygon([(float(x - 1), float(y - 1)) for y, x in c])
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty or p.area < min_area:
            continue
        rings.append(p)
    rings.sort(key=lambda g: g.area, reverse=True)

    nodes = []
    for i, g in enumerate(rings):
        rp = g.representative_point()
        depth, parent = 0, None
        for j in range(i):                       # rings 已按面积降序，前面的只会更大
            if rings[j].contains(rp):
                depth += 1
                parent = j
        nodes.append({"poly": g, "depth": depth, "parent": parent, "holes": []})

    for i, nd in enumerate(nodes):
        if nd["depth"] % 2 == 1 and nd["parent"] is not None:
            nodes[nd["parent"]]["holes"].append(nd["poly"])

    out = []
    for nd in nodes:
        if nd["depth"] % 2 == 1:
            continue
        shell = nd["poly"]
        if nd["holes"]:
            shell = shell.difference(unary_union([h.buffer(0) for h in nd["holes"]]))
        for g in getattr(shell, "geoms", [shell]):
            if isinstance(g, Polygon) and not g.is_empty:
                out.append(g)
    return out


# --------------------------------------------------------------------------- #
# 6. 输出：SVG + 抗锯齿 PNG
# --------------------------------------------------------------------------- #

def _path_d(poly: Polygon) -> str:
    def ring(coords):
        pts = [f"{x:.4f},{y:.4f}" for x, y in coords]
        return "M " + " L ".join(pts) + " Z"
    parts = [ring(poly.exterior.coords)]
    for hole in poly.interiors:
        parts.append(ring(hole.coords))
    return " ".join(parts)


def write_svg(polys: list[Polygon], size_mm: float, out_path: Path):
    body = "\n".join(f'  <path d="{_path_d(p)}" />' for p in polys)
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{size_mm}mm" height="{size_mm}mm"
     viewBox="0 0 {size_mm} {size_mm}">
  <title>线宽封顶 · 花瓣等径</title>
  <rect width="{size_mm}" height="{size_mm}" fill="#ffffff" />
  <g fill="#000000" fill-rule="evenodd" stroke="none">
{body}
  </g>
</svg>
"""
    out_path.write_text(svg, encoding="utf-8")


def rasterize(polys: list[Polygon], px: int, size_mm: float, ss: int = 2) -> Image.Image:
    """按全局嵌套深度绘制：深度偶数=黑（实体），奇数=白（孔）。

    不能"逐多边形先填外框再填孔"——外框是环时，它的孔里还装着别的图案，
    那样会把先画好的文字擦掉（本条是实测踩过的坑）。
    """
    k = (px * ss) / size_mm
    img = Image.new("L", (px * ss, px * ss), 255)
    d = ImageDraw.Draw(img)
    rings = []
    for p in polys:
        rings.append(Polygon(p.exterior))
        for h in p.interiors:
            rings.append(Polygon(h))
    rings.sort(key=lambda g: g.area, reverse=True)
    nodes = []
    for i, g in enumerate(rings):
        rp = g.representative_point()
        depth = sum(1 for j in range(i) if rings[j].contains(rp))
        nodes.append((depth, g))
    for depth, g in sorted(nodes, key=lambda t: t[0]):
        d.polygon([(x * k, y * k) for x, y in g.exterior.coords], fill=0 if depth % 2 == 0 else 255)
    return img.resize((px, px), Image.LANCZOS)


# --------------------------------------------------------------------------- #
# 7. 主流程
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out-svg")
    ap.add_argument("--out-png", required=True)
    ap.add_argument("--report")
    ap.add_argument("--size", type=float, default=101.6, help="成品最大边 mm")
    ap.add_argument("--margin", type=float, default=1.2)
    ap.add_argument("--cap-mm", type=float, default=1.0, help="线宽上限 mm（只压不涨）")
    ap.add_argument("--frame-mm", type=float, default=1.5, help="外框环线宽 mm")
    ap.add_argument("--petals", default="auto", help="auto / off / 具体瓣数")
    ap.add_argument("--px", type=int, default=3000)
    ap.add_argument("--work-scale", type=float, default=3.0,
                    help="工作分辨率放大倍数（先放大再封顶，抑制像素台阶造成的字形抖动；默认 3）")
    ap.add_argument("--smooth", type=float, default=0.8,
                    help="骨架半径平滑 sigma（工作像素；默认 0.8，设 0 关闭）")
    ap.add_argument("--simplify-mm", type=float, default=0.02,
                    help="多边形简化容差 mm（默认 0.02；顶点过多会让 OpenSCAD 并集失败）")
    ap.add_argument("--thr", type=float, default=None)
    ap.add_argument("--dry-run", action="store_true", help="只量不改")
    args = ap.parse_args()

    src_path = Path(args.input)
    if src_path.suffix.lower() == ".svg":
        raise SystemExit("输入是 SVG 时请先用 svg_shrink.py 渲染成 PNG 再跑本工具")

    g, mask, thr = load_mask(src_path, args.thr, args.work_scale)
    mmpp0 = (args.size - 2 * args.margin) / span_px(mask)
    src_rows, src_n = comp_widths(mask, mmpp0)
    src_sum = summarize(src_rows)
    frame, _ = sp.find_frame(mask)
    print(f"源稿：阈值 {thr:.0f}，图案块 {src_n}，线宽 {src_sum['min']}/{src_sum['median']}/{src_sum['max']}mm"
          f"（min/median/max），外框={'有' if frame is not None else '无'}")

    if args.dry_run:
        if frame is not None:
            ring, info = rebuild_frame(frame, args.frame_mm, mmpp0, None)
            print(f"外框：检测瓣数 {info.get('petals')}，峰半径 CV {info.get('peak_cv_before')}，"
                  f"角间距 CV {info.get('spacing_cv_before')}")
        print("（dry-run，未写文件）")
        return

    petals = None
    if args.petals not in ("auto", "off"):
        petals = int(args.petals)

    # 线宽上限：先按源稿 mm/px 换算
    cap_px = args.cap_mm / mmpp0
    pat = mask.copy()
    ring_geom = None
    info = {"detected": False}
    if frame is not None:
        pat[frame] = False
        if args.petals != "off":
            ring_geom, info = rebuild_frame(frame, args.frame_mm, mmpp0, petals)
        if ring_geom is None:                 # 兜底：原框保留
            pat |= frame
    capped = cap_mask(pat, cap_px, smooth_sigma=args.smooth)
    if capped.sum() == 0:
        raise SystemExit("封顶后图案为空：cap 太小或阈值有问题")

    polys = mask_to_polys(capped)
    out_n_before_union = len(polys)
    if ring_geom is not None:
        polys.append(ring_geom)
    merged = unary_union(polys)
    final = [g for g in getattr(merged, "geoms", [merged]) if isinstance(g, Polygon) and not g.is_empty]

    # 统一缩放居中：内容 max 边 = size - 2*margin
    minx = min(p.bounds[0] for p in final)
    miny = min(p.bounds[1] for p in final)
    maxx = max(p.bounds[2] for p in final)
    maxy = max(p.bounds[3] for p in final)
    w_px, h_px = maxx - minx, maxy - miny
    scale = (args.size - 2 * args.margin) / max(w_px, h_px)
    ox = (args.size - w_px * scale) / 2 - minx * scale
    oy = (args.size - h_px * scale) / 2 - miny * scale
    from shapely import affinity
    final = [affinity.translate(affinity.scale(p, xfact=scale, yfact=scale, origin=(0, 0)), ox, oy)
             for p in final]
    if args.simplify_mm and args.simplify_mm > 0:
        simp = []
        for p in final:
            q = p.simplify(args.simplify_mm, preserve_topology=True)
            if not q.is_empty:
                simp.extend(g for g in getattr(q, "geoms", [q]) if isinstance(g, Polygon))
        if simp:
            final = simp

    mmpp_out = args.size / args.px
    img = rasterize(final, args.px, args.size)
    Path(args.out_png).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out_png)
    if args.out_svg:
        Path(args.out_svg).parent.mkdir(parents=True, exist_ok=True)
        write_svg(final, args.size, Path(args.out_svg))

    # 复核实测：用输出图自己的 mm/px 量
    arr = np.asarray(img)
    t_out = float(filters.threshold_otsu(arr))
    out_mask = arr < (t_out if t_out > 1 else 128)
    if out_mask.mean() > 0.55:
        out_mask = ~out_mask
    out_rows, out_n = comp_widths(out_mask, mmpp_out)
    out_sum = summarize(out_rows)

    print(f"封顶 cap={args.cap_mm}mm（{cap_px:.1f}px），图案块 {src_n} → 输出 {out_n}"
          f"（{'+' if out_n >= src_n else ''}{out_n - src_n}）")
    print(f"实测线宽 {out_sum['min']}/{out_sum['median']}/{out_sum['max']}mm（min/median/max）")
    if info.get("detected"):
        print(f"外框：{info['petals']} 瓣 → 等径重建 {info.get('petals_after')} 瓣，"
              f"峰半径 CV {info.get('peak_cv_before')} → {info.get('peak_cv_after')}，"
              f"角间距 CV {info.get('spacing_cv_before')} → {info.get('spacing_cv_after')}，"
              f"环宽 {args.frame_mm}mm")
    if out_sum["max"] > args.cap_mm + 0.15:
        print(f"  [!] 最粗块 {out_sum['max']}mm 超出上限：多为字母交叉/笔画合并处的鼓包，看 max 而非 median")

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps({
            "src": str(src_path), "size_mm": args.size, "cap_mm": args.cap_mm,
            "frame_mm": args.frame_mm, "scale_mm_per_px": round(mmpp_out, 6),
            "src_width": src_sum, "out_width": out_sum,
            "parts_src": src_n, "parts_out": out_n, "polys_out": len(final),
            "frame": info,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", args.out_png, args.out_svg or "")


if __name__ == "__main__":
    main()
