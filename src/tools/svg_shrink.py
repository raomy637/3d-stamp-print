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


def shrink_strokes(root, target_units, frame_units=None):
    """描边式：把 stroke-width 设为 target_units；外框组设为 frame_units（None=保持原样）。"""
    changed = 0
    for el in root.iter():
        is_frame = _is_frame(el)
        sw = el.get("stroke-width")
        style = el.get("style") or ""
        new = (frame_units if (is_frame and frame_units) else target_units)
        if sw is not None:
            old = _num(sw, 0.0)
            if old > 0 and abs(new - old) > 1e-6:
                el.set("stroke-width", str(round(new, 4)))
                changed += 1
        if style and "stroke-width" in style:
            def _rep(m):
                old = float(m.group(1))
                return f"stroke-width:{round(new, 4)}" if old > 0 else m.group(0)
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
    img = ndi.gaussian_filter(out.astype(float) * 255.0, sigma=0.6)
    Image.fromarray(np.clip(255 - img, 0, 255).astype(np.uint8)).save(out_png)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=float, default=101.6, help="成品外接尺寸 mm（决定 mm↔unit 比）")
    ap.add_argument("--target-mm", type=float, default=0.6, help="目标线宽（成品 mm）")
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
        frame_units = (args.frame_mm * units_per_mm) if args.frame_mm else None
        changed = shrink_strokes(root, target_units, frame_units)
        root.set("width", f"{args.size}mm")
        root.set("height", f"{args.size * h_mm / w_mm:.3f}mm" if h_mm else f"{args.size}mm")
        root.set("viewBox", f"0 0 {vbw} {vbh}")
        ET.ElementTree(root).write(str(work_svg), encoding="utf-8", xml_declaration=True)
        print(f"[stroke] stroke-width -> {target_units:.3f} unit = {args.target_mm:.2f}mm，改动 {changed} 处")
    else:
        shutil.copy(svg, work_svg)
        print(f"[fill] 保留原 SVG，渲染后按线宽腐蚀到 {args.target_mm:.2f}mm")

    px = args.px
    print(f"几何：{w_mm:.2f}x{h_mm:.2f}mm, viewBox {vbw:g}x{vbh:g}, {units_per_mm:.3f} unit/mm")
    size_px = render_svg(work_svg, tmp / "raw.png", px)
    print(f"渲染：{size_px[0]}x{size_px[1]}px")

    target_px = args.target_mm * (px / args.size)
    frame_px = (args.frame_mm * (px / args.size)) if args.frame_mm else None
    if mode == "fill":
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
            ws.append(2.0 * reg.sum() / max(1.0, measure.perimeter(reg)))
        if ws:
            ws = np.array(ws) / (px / args.size)
            print(f"实测线宽 mm：min {ws.min():.2f} / 中位 {np.median(ws):.2f} / max {ws.max():.2f}")
    print("saved", args.out)


if __name__ == "__main__":
    main()