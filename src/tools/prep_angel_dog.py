#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""angel_dog_detail_v4.svg -> 流水线可吃的位图（v6：忠于原图 + 挂孔自动量）

v6 相对 v5：
- **不再封湾口、不再造挖空区**。原图两腿之间本来就是一道约 3.5mm 的通开缺口，
  v3 用形态学闭合把口封死、再在内部掏一个"挖空区"，是凭空加的结构，去掉。
- 因此边框与底模都直接跟着原轮廓走：缺口是外轮廓的一部分，
  不需要内岛刃、不需要顶桥、底模天然是通开的（--void-mask 不再传）。
- **挂孔不再手写**：从矢量图里量出那个小圆的直径，取 min(图纸, 吸管直径)，
  图和孔位（像素坐标）一起打印出来，直接喂 --hole。
- 其余处理与 v3 一致：外框环带 RING_PX、细节线只贴剪影内部、光环那圈细节线抹掉
  （沉台那圈已停用 --pocket）。

输出：inputs/angel_dog_100_open.png（图案层，已含外轮廓环带 + 细节线）
用法：python src\\tools\\prep_angel_dog.py
"""
import re, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from skimage.morphology import disk, closing

SRC = Path(r"C:\Users\bydh6\Downloads\61\angel_dog_detail_v4.svg")
ROOT = Path(r"D:\opencode\3D-stamp-print")
WORK = Path(__file__).resolve().parent.parent.parent / "out" / "_prep"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
N = 2496                # 1248 的 2 倍
SC = N / 1248.0
RING_PX = 20            # 外框环带厚（@2496 -> 0.8mm@100mm）
DETACH_PX = 24          # 细节线相对剪影边缘的收进量

HALO_C = (620.0, 269.0)         # 光环圆心（SVG 坐标）
HALO_R = 60.0                   # 光环外半径（SVG 坐标）
STRAW_D_MM = 6.0                # 打孔孔径上限 = 常规吸管外径（用户口径）
STROKE_MM = 0.30                # 线稿 stroke-width 3/1248，换算到 100mm 约 0.3mm

WORK.mkdir(parents=True, exist_ok=True)
svg = SRC.read_text(encoding="utf-8")
g_out = re.search(r'<g id="outline".*?</g>', svg, re.S).group(0)
g_det = re.search(r'<g id="relief_details".*?</g>', svg, re.S).group(0)


def wrap(g: str, path: Path):
    s = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{N}" height="{N}" '
         f'viewBox="0 0 1248 1248"><rect width="1248" height="1248" fill="#ffffff"/>'
         f'{g}</svg>')
    path.write_text(s, encoding="utf-8")


def shot(svg_path: Path, png_path: Path):
    cmd = [EDGE, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=1", f"--window-size={N},{N}",
           f"--user-data-dir={WORK / '_edge_profile'}",
           f"--screenshot={png_path}", svg_path.as_uri()]
    subprocess.run(cmd, check=True, timeout=180, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    if not png_path.exists():
        sys.exit(f"[x] 截图失败：{png_path}")


def load(p: Path) -> np.ndarray:
    return np.array(Image.open(p).convert("L")) < 128


def disc(h, w, cx, cy, r):
    yy, xx = np.ogrid[:h, :w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r


wrap(g_out, WORK / "outline.svg")
wrap(g_det, WORK / "details.svg")
shot(WORK / "outline.svg", WORK / "outline.png")
shot(WORK / "details.svg", WORK / "details.png")

o = load(WORK / "outline.png")
d = load(WORK / "details.png")

# 只填「被线稿包住」的内洞；两腿之间的缺口通向图外，填洞不会碰它
S = ndi.binary_fill_holes(o)
S = ndi.binary_closing(S, iterations=2)

# ---- 挂孔：从矢量图里自己量那个小圆，不手写 --hole
# 口径：孔的直径最多 = 吸管外径（照片里是素孔）；图上画得更大就按吸管收小。
ys, xs = np.where(S)
y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
mm_per_px = 97.6 / max(x1 - x0 + 1, y1 - y0 + 1)
holes = S & ~o                      # fill_holes 补出来的封闭内洞
lab_h, n_h = ndi.label(holes)
hole_drawn, hole_cxy = None, None
for i in range(1, n_h + 1):
    c = lab_h == i
    a = int(c.sum())
    if a < 300:
        continue
    dia = 2 * ndi.distance_transform_edt(c).max() * mm_per_px
    if 0.8 <= dia <= 8.0:           # 小圆孔才认，身体内腔那种几十毫米的排除
        hole_drawn, hole_cxy = dia, ndi.center_of_mass(c)
        break
if hole_drawn is None:
    sys.exit("[x] 没在轮廓里找到挂孔，检查 outline.png")
hole_mm = min(hole_drawn, STRAW_D_MM)
print(f"[i] 挂孔：图上画的 φ{hole_drawn:.1f}mm"
      f"（含线宽；矢量原圆 φ{hole_drawn + STROKE_MM:.1f}）→ 取 φ{hole_mm:.1f}mm"
      f"（上限 = 吸管 {STRAW_D_MM:.1f}mm）")

hc = (HALO_C[0] * SC, HALO_C[1] * SC)
S = S | disc(*S.shape, hc[0], hc[1], HALO_R * SC)   # 光环圆内填实

if S.mean() < 0.2:
    sys.exit(f"[x] 剪影只占 {S.mean():.1%}，填洞失败")
ys, xs = np.where(S)
y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
mm_per_px = 97.6 / max(x1 - x0 + 1, y1 - y0 + 1)
print(f"[i] 剪影 bbox {x1-x0+1}x{y1-y0+1}px，填充率 {S.mean():.1%}，"
      f"折合面积 {S.sum()*mm_per_px**2:.0f}mm²")

# ---- 两腿之间缺口：原样保留，只报一下开口宽度（4 倍降采样二分，够用）
small = S[::4, ::4]
w_mm = None
for r in range(1, 26):
    sealed = closing(small, disk(r))
    if (ndi.binary_fill_holes(sealed) & ~sealed).sum() > 200:   # 口被封住、里面留出内腔
        w_mm = 2 * (r - 0.5) * 4 * mm_per_px
        break
print(f"[i] 湾口开口宽 ≈ {w_mm:.1f}mm（原样保留，不封口）" if w_mm else "[i] 湾口没有开口")

ring = S & ~ndi.binary_erosion(S, iterations=RING_PX)
det = d & ndi.binary_erosion(S, iterations=DETACH_PX)
# 光环那圈线属于细节组，压在 r≈120px 处，正好贴着 --pocket 沉台外沿 → 压出来就是
# 用户说的「圆圈外侧又出现一个圆环」。只抹细节里的这一圈，不动外轮廓环带。
_rr = np.sqrt((np.arange(S.shape[1])[None, :] - hc[0]) ** 2
              + (np.arange(S.shape[0])[:, None] - hc[1]) ** 2)
det = det & ~((_rr >= 105) & (_rr <= 140))

M = ring | det          # 光环不再画凸环：改由 --pocket 在底模上铣沉台

pad = 24
sx0, sx1 = max(x0 - pad, 0), min(x1 + pad, N - 1)
sy0, sy1 = max(y0 - pad, 0), min(y1 + pad, N - 1)
M = M[sy0:sy1 + 1, sx0:sx1 + 1]
H, W = M.shape

lab2, n2 = ndi.label(M)
sizes2 = ndi.sum(M, lab2, range(1, n2 + 1))
print(f"[i] 合成图 {W}x{H}，连通块 {n2} 个，最大块 {int(sizes2.max()):,}px")

soft = ndi.gaussian_filter(M.astype(np.float32), 1.0)
img = np.clip(255.0 * (1.0 - soft), 0, 255).astype(np.uint8)
out_png = ROOT / "inputs" / "angel_dog_100_open.png"
Image.fromarray(img).save(out_png)

hole_px = (hc[0] - sx0, hc[1] - sy0)
print(f"[o] {out_png}  {W}x{H}  前景 {M.mean():.1%}")
print(f"[i] --hole {hole_px[0]:.1f},{hole_px[1]:.1f},{hole_mm:.1f}")
print("[i] 不传 --void-mask（缺口来自原图外轮廓，不需要内岛刃/顶桥）")
