"""SVG 线宽收缩 → 位图源稿（供 stamp_pipeline 出模）。纯代码路线，不调用生图模型。

两种 SVG 处理方式（自动判别）：
1. 描边式（元素/组带 stroke-width + fill="none"）：直接精确改 stroke-width 到目标线宽，几何中心线完全不变。
   外框组（id/类名含 frame/outline/边框）默认保持原线宽或按 --frame-ratio 放大。
2. 填充式（fill 为实体，线条是 filled path）：用距离变换做形态学腐蚀，每条线减 2d、中心线不变；
   线宽估计 w ≈ 2*area/perimeter（连通块面积除周长），再取 d=(w-target)/2。
   腐蚀不会产生毛刺、不会拆笔画，是标准的"字重减轻"算子。

渲染通道：本机 msedge/chrome headless 截图（无 cairo/cairosvg 依赖）。

用法：
  python src/tools/svg_shrink.py --input 设计.svg --out 细线.png --size 101.6 --target-mm 0.6 --px 3000
"""
import argparse
import html
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from skimage import measure, morphology

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
FRAME_HINTS = ("frame", "outline", "border", "cutter", "外框", "边框")


def _num(v, default=0.0):
    if v is None:
        return default
    m = re.match(r"[-+]?\d*\.?\d+(?:e[-+]?\d+)?", str(v).strip())
    return float(m.group()) if m else default


def svg_geometry(root):
    """返回 (宽度mm, 高度mm, viewBox宽, viewBox高) —— 用于 mm↔user unit 换算。"""
    w_mm = _num(root.get("width"), 0.0)
    h_mm = _num(root.get("height"), 0.0)
    vb = root.get("viewBox")
    if vb:
        vbw, vbh = [float(x) for x in re.split(r"[ ,]+", vb.strip())[:4]][2:4]
    else:
        vbw, vbh = w_mm, h_mm
    if not w_mm:
        w_mm, h_mm = vbw, vbh
    return w_mm, h_mm, vbw, vbh


def is_stroke_based(root):
    """判别造型方式：有实体 fill（非 none/transparent）即视为填充式造型；
    纯 stroke（fill 全为 none）才算描边式。stroke-width 只是装饰描边时不能判成描边式。"""
    filled = False
    stroked = False
    for el in root.iter():
        fill = (el.get("fill") or "").strip().lower()
        if fill and fill not in ("none", "transparent"):
            filled = True
        elif el.get("stroke-width") is not None:
            stroked = True
        st = (el.get("style") or "").lower()
        if "fill:" in st and "fill:none" not in st:
            filled = True
        if "stroke-width" in st:
            stroked = True
    if filled:
        return False
    return stroked


def _is_frame(el):
    tag = " ".join([el.get("id") or "", el.get("class") or ""]).lower()
    return any(h in tag for h in FRAME_HINTS)


def shrink_strokes(root, mapper, units_per_mm, frame_mm=None):
    """描边式：每个 stroke-width 按 mapper(旧mm)->新mm 换算（统一收细或范围压缩）；外框用 frame_mm。"""
    changed = 0
    for el in root.iter():
        is_frame = _is_frame(el)
        new_units = None
        if is_frame and frame_mm:
            new_units = frame_mm * units_per_mm
        sw = el.get("stroke-width")
        if sw is not None:
            old = _num(sw, 0.0)
            if old > 0:
                if new_units is None:
                    new_units = mapper(old / units_per_mm) * units_per_mm
                if abs(new_units - old) > 1e-6:
                    el.set("stroke-width", str(round(new_units, 4)))
                    changed += 1
        style = el.get("style") or ""
        if style and "stroke-width" in style:
            def _rep(m, el=el, is_frame=is_frame, new_units=new_units):
                old = float(m.group(1))
                if old <= 0:
                    return m.group(0)
                nu = new_units if (is_frame and frame_mm) else mapper(old / units_per_mm) * units_per_mm
                return f"stroke-width:{round(nu, 4)}"
            new_style = re.sub(r"stroke-width\s*:\s*([-+]?\d*\.?\d+)", _rep, style)
            if new_style != style:
                el.set("style", new_style)
                changed += 1
    return changed


def render_svg(svg_path, png_path, px):
    """Edge/Chrome headless 截图。返回实际像素尺寸。"""
    browser = next((b for b in BROWSERS if os.path.exists(b)), None)
    if browser is None:
        raise RuntimeError("未找到 msedge/chrome，无法渲染 SVG")
    tmp = Path(tempfile.mkdtemp(prefix="svgrender_"))
    root = ET.parse(str(svg_path)).getroot()
    w_mm, h_mm, _, _ = svg_geometry(root)
    py = max(1, int(round(px * (h_mm / w_mm)))) if w_mm else px
    page = tmp / "page.html"
    page.write_text(
        '<html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;background:#fff}'
        'img{display:block}</style></head><body>'
        f'<img src="file:///{str(Path(svg_path).resolve()).replace(chr(92), "/")}" '
        f'width="{px}" height="{py}"></body></html>',
        encoding="utf-8",
    )
    out = Path(png_path).resolve()
    cmd = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=1", "--default-background-color=FFFFFFFF",
           f"--user-data-dir={tmp / 'prof'}",
           f"--window-size={px},{py}", f"--screenshot={out}", page.as_uri()]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    if not out.exists():
        raise RuntimeError("浏览器渲染未产出截图")
    im = Image.open(out)
    return im.size


def find_frame_comp(mask):
    """外框环：铺满画幅的闭合环。不设 2% 面积门槛（细装饰框常只有 0.2mm，正是要加粗的对象）。"""
    lab, n = ndi.label(mask, structure=np.ones((3, 3)))
    h, w = mask.shape
    best, comp_id = 0.0, 0
    for i in range(1, n + 1):
        reg = lab == i
        area = float(reg.sum())
        if area < 0.002 * h * w:
            continue
        ys, xs = np.where(reg)
        wr, hr = (xs.max() - xs.min() + 1) / w, (ys.max() - ys.min() + 1) / h
        fr = ndi.binary_fill_holes(reg).sum() / area
        if wr > 0.80 and hr > 0.80 and fr > 2.0 and area > best:
            best, comp_id = area, i
    return (lab == comp_id) if comp_id else None


def measure_halfwidth(reg, edt):
    """用骨架上的 EDT 中位数估计半宽（只测宽，不用骨架重建，故不会拆字/长毛刺）。
    比 2A/P 稳：短弧/字母笔画上 2A/P 会严重低估。"""
    from skimage import morphology
    sk = morphology.skeletonize(reg)
    if not sk.any():
        return float(edt.max()) / 2.0
    vals = edt[sk]
    return float(np.median(vals))


def remap_fills(png_path, out_png, min_px, max_px, frame_px=None):
    """范围压缩：最细的线 → min_px，其余按同一斜率收窄（w' = min + (w-wmin)*slope）。
    粗的走腐蚀（中心线不变），比下限还细的走骨架加粗（只影响本来就细的笔画）。"""
    g = np.asarray(Image.open(png_path).convert("L"))
    mask = g < 128
    lab, n = ndi.label(mask, structure=np.ones((3, 3)))
    frame = find_frame_comp(mask)

    widths, edts = {}, {}
    for i in range(1, n + 1):
        reg = lab == i
        if reg.sum() < 12:
            widths[i] = None
            continue
        edt = ndi.distance_transform_edt(reg)
        edts[i] = edt
        widths[i] = 2.0 * measure_halfwidth(reg, edt)

    vals = [w for i, w in widths.items() if w and not (frame is not None and (lab == i)[frame].any())]
    if not vals:
        raise RuntimeError("没有可测量的线条")
    wmin, wmax = min(vals), max(vals)
    slope = (max_px - min_px) / (wmax - wmin) if wmax > wmin else 0.0

    out = np.zeros_like(mask)
    rows = []
    for i in range(1, n + 1):
        reg = lab == i
        if widths[i] is None:
            out |= reg
            continue
        if frame is not None and frame[reg].any():
            w_now = widths[i]
            reg2 = reg
            if frame_px and w_now > 0:
                d = (frame_px - w_now) / 2.0
                if d > 0.5:
                    reg2 = ndi.binary_dilation(reg, morphology.disk(int(round(d))))
                elif d < -0.5:
                    reg2 = edts[i] > (-d)
            out |= reg2
            rows.append((round(w_now, 2), round(frame_px or w_now, 2)))
            continue
        w = widths[i]
        w_t = min(max(min_px + (w - wmin) * slope, min_px), max_px)
        if w_t >= w - 0.5:  # 加粗：骨架重建到目标宽度
            sk = morphology.skeletonize(reg)
            r = max(1, int(round(w_t / 2.0)))
            kept = morphology.binary_dilation(sk, morphology.disk(r))
        else:  # 收窄：距离变换腐蚀，中心线严格不变
            kept = edts[i] > ((w - w_t) / 2.0)
        if not kept.any():
            kept = morphology.binary_dilation(morphology.skeletonize(reg), morphology.disk(1))
        out |= kept
        rows.append((round(w, 2), round(w_t, 2)))

    _, n_after = ndi.label(out, structure=np.ones((3, 3)))
    img = ndi.gaussian_filter(out.astype(float) * 255.0, sigma=0.6)
    Image.fromarray(np.clip(255 - img, 0, 255).astype(np.uint8)).save(out_png)
    return rows, (n, n_after), (wmin, wmax)


def erode_fills(png_path, out_png, target_px, frame_px=None):
    """填充式：按骨架中位半宽实测线宽，腐蚀到 target。
    外框环（若存在）不腐蚀；给了 frame_px 则按该宽度加粗（只取剪影，需 ≥2% 图幅才被 find_frame 认）。"""
    g = np.asarray(Image.open(png_path).convert("L"))
    mask = g < 128
    lab, n = ndi.label(mask, structure=np.ones((3, 3)))
    frame = find_frame_comp(mask)
    out = np.zeros_like(mask)
    rows = []
    for i in range(1, n + 1):
        reg = lab == i
        area = float(reg.sum())
        if area < 12:
            out |= reg
            continue
        if frame is not None and frame[reg].any():
            edt = ndi.distance_transform_edt(reg)
            w_now = 2.0 * measure_halfwidth(reg, edt)
            if frame_px and w_now > 0:
                d = (frame_px - w_now) / 2.0
                if d > 0.5:
                    reg = ndi.binary_dilation(reg, morphology.disk(int(round(d))))
                elif d < -0.5:
                    reg = edt > (-d)
            out |= reg
            rows.append((round(w_now, 2), round(frame_px or w_now, 2), 0.0))
            continue
        edt = ndi.distance_transform_edt(reg)
        hw = measure_halfwidth(reg, edt)
        w_est = 2.0 * hw
        d = max(0.0, (w_est - target_px) / 2.0)
        kept = edt > d
        if not kept.any():
            kept = morphology.binary_dilation(morphology.skeletonize(reg), morphology.disk(1))
        out |= kept
        rows.append((round(w_est, 2), round(target_px, 2), round(d, 2)))
    img = ndi.gaussian_filter(out.astype(float) * 255.0, sigma=0.6)
    Image.fromarray(np.clip(255 - img, 0, 255).astype(np.uint8)).save(out_png)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=float, default=101.6, help="成品外接尺寸 mm（决定 mm↔unit 比）")
    ap.add_argument("--target-mm", type=float, default=0.6, help="统一目标线宽（成品 mm）；给了 --min-mm 则改用范围压缩")
    ap.add_argument("--min-mm", type=float, default=None,
                    help="范围压缩：最细那条线设为此宽（如 1.0），其余按同一斜率收窄")
    ap.add_argument("--max-mm", type=float, default=None, help="范围压缩：最粗那条线的目标宽度（默认 min-mm×1.4）")
    ap.add_argument("--frame-mm", type=float, default=1.5,
                    help="外框环线宽 mm（只取剪影、需 ≥2%% 图幅才能被 find_frame 认；0=保持原样）")
    ap.add_argument("--frame-ratio", type=float, default=1.0, help="（兼容旧参数，已不使用）")
    ap.add_argument("--px", type=int, default=3000, help="渲染像素宽度")
    ap.add_argument("--mode", choices=["auto", "stroke", "fill"], default="auto")
    args = ap.parse_args()

    svg = Path(args.input).resolve()
    root = ET.parse(str(svg)).getroot()
    w_mm, h_mm, vbw, vbh = svg_geometry(root)
    units_per_mm = vbw / args.size if args.size else 1.0
    target_units = args.target_mm * units_per_mm

    mode = args.mode
    if mode == "auto":
        mode = "stroke" if is_stroke_based(root) else "fill"

    tmp = Path(tempfile.mkdtemp(prefix="svgshrink_"))
    work_svg = tmp / "work.svg"
    if mode == "stroke":
        if args.min_mm:
            ws_mm = []
            for el in root.iter():
                if _is_frame(el):
                    continue
                sw = el.get("stroke-width")
                if sw is not None and _num(sw, 0) > 0:
                    ws_mm.append(_num(sw, 0) / units_per_mm)
            wmin = min(ws_mm) if ws_mm else 0.0
            wmax = max(ws_mm) if ws_mm else 0.0
            mmax = args.max_mm or args.min_mm * 1.4
            slope = (mmax - args.min_mm) / (wmax - wmin) if wmax > wmin else 0.0

            def mapper(w, wmin=wmin, slope=slope, a=args.min_mm, b=mmax):
                return min(max(a + (w - wmin) * slope, a), b)

            changed = shrink_strokes(root, mapper, units_per_mm, args.frame_mm)
            print(f"[stroke] 范围压缩：源 {wmin:.2f}–{wmax:.2f}mm → {args.min_mm:.2f}–{mmax:.2f}mm，改动 {changed} 处")
        else:
            changed = shrink_strokes(root, lambda w: args.target_mm, units_per_mm, args.frame_mm)
            print(f"[stroke] stroke-width -> {args.target_mm:.2f}mm，改动 {changed} 处")
        root.set("width", f"{args.size}mm")
        root.set("height", f"{args.size * h_mm / w_mm:.3f}mm" if h_mm else f"{args.size}mm")
        root.set("viewBox", f"0 0 {vbw} {vbh}")
        ET.ElementTree(root).write(str(work_svg), encoding="utf-8", xml_declaration=True)
    else:
        shutil.copy(svg, work_svg)
        if args.min_mm:
            print(f"[fill] 保留原 SVG，渲染后按范围压缩（最细 {args.min_mm:.2f}mm）")
        else:
            print(f"[fill] 保留原 SVG，渲染后按线宽腐蚀到 {args.target_mm:.2f}mm")

    px = args.px
    print(f"几何：{w_mm:.2f}x{h_mm:.2f}mm, viewBox {vbw:g}x{vbh:g}, {units_per_mm:.3f} unit/mm")
    size_px = render_svg(work_svg, tmp / "raw.png", px)
    print(f"渲染：{size_px[0]}x{size_px[1]}px")

    target_px = args.target_mm * (px / args.size)
    frame_px = (args.frame_mm * (px / args.size)) if args.frame_mm else None
    ppm = px / args.size
    if mode == "fill" and args.min_mm:
        min_px = args.min_mm * ppm
        max_px = (args.max_mm or args.min_mm * 1.4) * ppm
        rows, (n0, n1), (wmin, wmax) = remap_fills(tmp / "raw.png", args.out, min_px, max_px, frame_px)
        print(f"范围压缩：源线宽 {wmin / ppm:.2f}–{wmax / ppm:.2f}mm → "
              f"{args.min_mm:.2f}–{(args.max_mm or args.min_mm * 1.4):.2f}mm（同斜率）")
        if n1 < n0:
            print(f"  [!] 注意：连通块 {n0} → {n1}，有 {n0 - n1} 处线条因加粗并块")
        uniq = sorted({(r[0], r[1]) for r in rows}, key=lambda r: -r[0])
        for w_src, w_t in uniq[:6]:
            print(f"   源 {w_src / ppm:5.2f}mm -> 目标 {w_t / ppm:5.2f}mm")
    elif mode == "fill":
        rows = erode_fills(tmp / "raw.png", args.out, target_px, frame_px)
        rows.sort(key=lambda r: -r[0])
        print(f"腐蚀：{len(rows)} 个连通块，最大线宽 {rows[0][0]:.2f}px -> 目标 {target_px:.2f}px"
              f"（外框目标 {frame_px:.2f}px）" if frame_px else
              f"腐蚀：{len(rows)} 个连通块，最大线宽 {rows[0][0]:.2f}px -> 目标 {target_px:.2f}px")
        for r in rows[:5]:
            print(f"   宽 {r[0]:6.2f}px 目标 {r[1]:5.2f}px 腐蚀 {r[2]:5.2f}px")
    else:
        Image.open(tmp / "raw.png").save(args.out)
        g = np.asarray(Image.open(args.out).convert("L"))
        mask = g < 128
        lab, n = ndi.label(mask, structure=np.ones((3, 3)))
        ws = []
        for i in range(1, n + 1):
            reg = lab == i
            if reg.sum() < 12:
                continue
            edt = ndi.distance_transform_edt(reg)
            ws.append(2.0 * measure_halfwidth(reg, edt))
        if ws:
            ws = np.array(ws) / (px / args.size)
            print(f"实测线宽 mm：min {ws.min():.2f} / 中位 {np.median(ws):.2f} / max {ws.max():.2f}")
    print("saved", args.out)


if __name__ == "__main__":
    main()