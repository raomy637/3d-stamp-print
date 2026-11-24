#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
把 STL 打包成一个自包含的 HTML 3D 查看器（离线可用，双击即开）。

几何压缩方式：
    顶点位置按包围盒量化成 uint16（误差 ≈ 尺寸/65535，肉眼不可见）
    三角索引按顶点数自动选 uint16 / uint32
    整体 base64 内嵌，three.js / OrbitControls 直接内联进 HTML

用法：
    python make_viewer.py --stl ..\out\bakers_v2.stl --handle ..\out\bakers_v2_handle.stl \
        --report ..\out\bakers_v2.json --out ..\out\viewer\bakers_v2.html --title "圣诞印章 85mm"
"""

from __future__ import annotations

import argparse
import base64
import json
import struct
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
LIBS = HERE / "libs"


# --------------------------------------------------------------------------- #
# 几何 -> base64
# --------------------------------------------------------------------------- #

def pack_mesh(mesh: trimesh.Trimesh) -> str:
    mesh.merge_vertices()
    v = np.asarray(mesh.vertices, dtype=np.float64)
    f = np.asarray(mesh.faces, dtype=np.int64)

    bb_min = v.min(axis=0)
    bb_max = v.max(axis=0)
    span = bb_max - bb_min
    span[span == 0] = 1.0

    q = np.clip(np.round((v - bb_min) / span * 65535.0), 0, 65535).astype(np.uint16)

    nv, ni = len(v), len(f)
    use16 = nv <= 65535
    idx = f.astype(np.uint16 if use16 else np.uint32).ravel()

    out = struct.pack("<IIB3x", nv, ni, 0 if use16 else 1)
    out += np.asarray(list(bb_min) + list(bb_max), dtype="<f4").tobytes()
    out += q.astype("<u2").tobytes()

    pos_bytes = nv * 6
    pad = (4 - pos_bytes % 4) % 4
    out += b"\x00" * pad
    out += idx.tobytes()
    return base64.b64encode(out).decode("ascii")


def dims_of(mesh):
    b = mesh.bounds
    return [round(float(b[1][i] - b[0][i]), 2) for i in range(3)]


# --------------------------------------------------------------------------- #
# HTML 模板
# --------------------------------------------------------------------------- #

TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · 3D 预览</title>
<style>
  :root{
    --bg0:#0d1014; --bg1:#171c24; --line:#2a3140;
    --ink:#e8e6e1; --dim:#8f98a8; --acc:#7fd1b0; --hot:#e0855a;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;overflow:hidden;background:
    radial-gradient(120% 90% at 50% 0%, var(--bg1) 0%, var(--bg0) 70%);
    color:var(--ink);font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif}
  #c{position:fixed;inset:0;display:block}
  #hud{position:fixed;left:22px;top:20px;max-width:330px;pointer-events:none}
  #hud h1{font-size:17px;margin:0 0 2px;font-weight:650;letter-spacing:.02em}
  #hud .sub{font-size:12px;color:var(--dim);margin-bottom:14px}
  #params{border-top:1px solid var(--line);padding-top:12px}
  .row{display:flex;justify-content:space-between;gap:14px;font-size:12.5px;
       line-height:1.9;border-bottom:1px dashed rgba(42,49,64,.55)}
  .row span:first-child{color:var(--dim)}
  .row span:last-child{color:var(--ink);font-variant-numeric:tabular-nums}
  .row b{color:var(--acc);font-weight:600}
  #bar{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);
       display:flex;gap:8px;padding:8px;border-radius:14px;
       background:rgba(23,28,36,.82);border:1px solid var(--line);
       backdrop-filter:blur(8px);box-shadow:0 10px 30px rgba(0,0,0,.45)}
  button{appearance:none;border:1px solid transparent;background:rgba(255,255,255,.05);
         color:var(--ink);font:inherit;font-size:13px;padding:8px 14px;border-radius:9px;
         cursor:pointer;transition:.15s}
  button:hover{background:rgba(255,255,255,.12)}
  button.on{background:rgba(127,209,176,.16);border-color:rgba(127,209,176,.5);color:#bff0dd}
  #hint{position:fixed;right:22px;bottom:26px;font-size:12px;color:var(--dim);text-align:right;line-height:1.8}
  #badge{position:fixed;right:22px;top:22px;font-size:11.5px;color:var(--dim);
         border:1px solid var(--line);border-radius:8px;padding:6px 10px;background:rgba(23,28,36,.7)}
  @media (max-width:820px){ #hud{max-width:210px} #params{font-size:11px} }
</style>
</head>
<body>
<canvas id="c"></canvas>

<div id="hud">
  <h1>__TITLE__</h1>
  <div class="sub">__SUBTITLE__</div>
  <div id="params">__PARAMS__</div>
</div>

<div id="badge">__BADGE__</div>

<div id="bar">
  <button id="bMode" class="on">分离视图</button>
  <button id="bSpin">自动旋转</button>
  <button id="bTop">俯视</button>
  <button id="bSide">侧视</button>
  <button id="bBack">背面</button>
</div>

<div id="hint">左键拖拽旋转<br>滚轮缩放 · 右键平移</div>

<script>__THREE__</script>
<script>__ORBIT__</script>
<script>
__GEO__
</script>
<script>
(function(){
  const cv = document.getElementById('c');
  const renderer = new THREE.WebGLRenderer({canvas: cv, antialias: true, alpha: false});
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.setSize(innerWidth, innerHeight, false);
  renderer.outputEncoding = THREE.sRGBEncoding;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.92;
  renderer.physicallyCorrectLights = false;

  const scene = new THREE.Scene();
  scene.background = null;

  const camera = new THREE.PerspectiveCamera(35, innerWidth/innerHeight, 0.5, 4000);

  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.075;
  controls.rotateSpeed = 0.85;
  controls.zoomSpeed = 0.9;
  controls.minDistance = 30;
  controls.maxDistance = 1200;

  scene.add(new THREE.HemisphereLight(0xdfe9ff, 0x20232b, 0.22));

  const key = new THREE.DirectionalLight(0xfff3e2, 0.62);
  key.position.set(-1.05, 1.35, 1.05);
  scene.add(key);

  const fill = new THREE.DirectionalLight(0xa9c4ff, 0.14);
  fill.position.set(1.15, 0.35, -0.85);
  scene.add(fill);

  const rimL = new THREE.DirectionalLight(0xffffff, 0.08);
  rimL.position.set(0.2, -0.9, -0.4);
  scene.add(rimL);

  // 掠射光：几乎平行于印面，专打浮雕侧壁，让 1.8mm 的高度差看得出来
  const graze = new THREE.DirectionalLight(0xffffff, 0.55);
  graze.position.set(0.9, 0.14, -1.0);
  scene.add(graze);

  // ---- 几何
  function build(geo){
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(geo.pos, 3));
    g.setIndex(new THREE.BufferAttribute(geo.idx, 1));
    g.computeVertexNormals();
    g.computeBoundingBox();
    return g;
  }

  const matStamp = new THREE.MeshStandardMaterial({
    color: 0xc2a884, roughness: 0.46, metalness: 0.02, flatShading: true
  });
  const matKnob = new THREE.MeshStandardMaterial({
    color: 0x8e9bb0, roughness: 0.55, metalness: 0.04, flatShading: true
  });
  const matRing = new THREE.MeshStandardMaterial({
    color: 0x7f8fa6, roughness: 0.62, metalness: 0.03, flatShading: true
  });

  const stampMesh = new THREE.Mesh(build(STAMP), matStamp);
  const knobMesh  = new THREE.Mesh(build(KNOB),  matKnob);
  const ringMesh  = new THREE.Mesh(build(RING),  matRing);

  const group = new THREE.Group();
  group.add(stampMesh);
  group.add(knobMesh);
  group.add(ringMesh);
  scene.add(group);

  // 手柄高（用于装配位）
  const knobH = KNOB.bb[4] - KNOB.bb[1];

  let mode = 'split';
  let hideKnob = false;   // 侧视时把手柄藏掉，否则正好挡住章体盘沿

  function applyMode(){
    const sw = STAMP.bb[3] - STAMP.bb[0];
    const kw = KNOB.bb[3] - KNOB.bb[0];
    const rw = RING.bb[3] - RING.bb[0];
    if(mode === 'split'){
      // 章体正面朝向观察者平放，手柄竖立在右上，边框放在左边（同一“桌面”）
      knobMesh.rotation.set(-Math.PI/2, 0, 0);   // 轴向 +z -> +y，底盘落到 y=0
      knobMesh.position.set(sw/2 + kw/2 + 16, -STAMP.bb[4], 0);
      ringMesh.rotation.set(0, 0, 0);
      ringMesh.position.set(-(sw/2 + rw/2 + 20), 0, 0);
    }else{
      // 装配：边框原位居中，章体落进内腔；手柄贴在章体背面
      knobMesh.rotation.set(Math.PI, 0, 0);
      knobMesh.position.set(0, 0, -0.04);   // 微退 0.04mm，避免与底板共面闪烁
      ringMesh.rotation.set(0, 0, 0);
      ringMesh.position.set(0, 0, 0);
    }
    knobMesh.visible = !(hideKnob && mode === 'split');
  }

  // ---- 相机
  const box = new THREE.Box3();
  let sphere = new THREE.Sphere(new THREE.Vector3(), 1);
  let view = {az: 1.28, el: 0.34, dist: 200};

  function updateBounds(){
    group.updateMatrixWorld(true);
    box.makeEmpty();
    group.children.forEach(function(o){
      if(!o.visible || !o.geometry) return;          // 隐藏的手柄不该拉远镜头
      o.geometry.computeBoundingBox();
      box.union(o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld));
    });
    box.getBoundingSphere(sphere);
    view.dist = sphere.radius * 2.75;
  }

  function placeCamera(instant){
    const az = view.az, el = view.el, d = view.dist;
    const t = sphere.center;
    const p = new THREE.Vector3(
      t.x + d * Math.cos(el) * Math.cos(az),
      t.y + d * Math.sin(el),
      t.z + d * Math.cos(el) * Math.sin(az)
    );
    camera.position.copy(p);
    controls.target.copy(t);
    controls.update();
  }

  function refresh(){ updateBounds(); placeCamera(true); }

  applyMode();
  refresh();
  window.__V = {camera, scene, controls, sphere, group, view, renderer};


  // ---- UI
  const bMode = document.getElementById('bMode');
  const bSpin = document.getElementById('bSpin');

  bMode.onclick = function(){
    mode = (mode === 'split' ? 'assembled' : 'split');
    bMode.textContent = (mode === 'split' ? '分离视图' : '装配视图');
    hideKnob = false;
    applyMode();
    // 装配后手柄在章体背面，从侧后方看才看得见
    view.el = (mode === 'split' ? 0.34 : 0.42);
    view.az = (mode === 'split' ? 1.28 : -1.05);
    refresh();
  };

  let spin = false;
  bSpin.onclick = function(){
    spin = !spin;
    bSpin.classList.toggle('on', spin);
  };

  // 模型是 Z 轴朝上（印面法线 = +z），所以“俯视”= 沿 +z 看，不是世界坐标的正上方
  function goTo(el, az, hide){
    view.el = el; view.az = az; hideKnob = hide;
    applyMode();
    refresh();
  }
  document.getElementById('bTop').onclick  = function(){ goTo(0.08, Math.PI/2, false); };
  // 低角度平视：看的不是盘面而是厚度——边框 12 高、底板 4.8、手柄 48 的对比
  document.getElementById('bSide').onclick = function(){ goTo(0.05, 0.35, false); };
  // 背面 = 装配态从后方看：底板背面 + 粘上去的手柄 + 边框外壁
  document.getElementById('bBack').onclick = function(){
    mode = 'asm'; applyMode();
    goTo(0.30, -1.75, false);
  };

  addEventListener('resize', function(){
    camera.aspect = innerWidth/innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight, false);
  });

  // ---- 循环
  let last = performance.now();
  function tick(now){
    const dt = Math.min((now - last)/1000, 0.06);
    last = now;
    if(spin){
      const r = 1.1 * dt;
      const t = sphere.center;
      const off = camera.position.clone().sub(t);
      const c = Math.cos(r), s = Math.sin(r);
      const x = off.x * c - off.z * s;
      const z = off.x * s + off.z * c;
      camera.position.set(t.x + x, camera.position.y, t.z + z);
      controls.target.copy(t);
    }
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();
</script>
</body>
</html>
"""

APP_GEO = """
// ---- 内嵌几何解码
function decode(b64){
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for(let i=0;i<bin.length;i++) u8[i] = bin.charCodeAt(i);
  const dv = new DataView(u8.buffer);
  const nv = dv.getUint32(0, true);
  const ni = dv.getUint32(4, true);
  const fmt = dv.getUint8(8);
  const bb = [];
  for(let i=0;i<6;i++) bb.push(dv.getFloat32(12 + i*4, true));

  const off = 36;
  const q = new Uint16Array(u8.buffer, u8.byteOffset + off, nv*3);
  const sx = bb[3]-bb[0], sy = bb[4]-bb[1], sz = bb[5]-bb[2];
  const pos = new Float32Array(nv*3);
  for(let i=0;i<nv;i++){
    pos[i*3]   = bb[0] + q[i*3]   / 65535 * sx;
    pos[i*3+1] = bb[1] + q[i*3+1] / 65535 * sy;
    pos[i*3+2] = bb[2] + q[i*3+2] / 65535 * sz;
  }
  let io = off + nv*6;
  while(io % 4) io++;
  const idx = (fmt === 0)
    ? new Uint16Array(u8.buffer, u8.byteOffset + io, ni*3)
    : new Uint32Array(u8.buffer, u8.byteOffset + io, ni*3);
  return {pos: pos, idx: idx, bb: bb, nv: nv, ni: ni};
}

const STAMP = decode("__B64_STAMP__");
const KNOB  = decode("__B64_KNOB__");
const RING  = decode("__B64_RING__");
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stl", required=True)
    ap.add_argument("--handle", default=None)
    ap.add_argument("--cutter", default=None, help="边框（切模）STL，可选")
    ap.add_argument("--report", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="3D 印章")
    args = ap.parse_args()

    stamp = trimesh.load(args.stl)
    sd = dims_of(stamp)

    if args.handle:
        knob = trimesh.load(args.handle)
        kd = dims_of(knob)
        b64k = pack_mesh(knob)
    else:
        knob = trimesh.creation.box(extents=[0.1, 0.1, 0.1])
        kd = [0, 0, 0]
        b64k = pack_mesh(knob)

    if args.cutter:
        ring = trimesh.load(args.cutter)
        rd = dims_of(ring)
        b64r = pack_mesh(ring)
    else:
        ring = trimesh.creation.box(extents=[0.1, 0.1, 0.1])
        rd = [0, 0, 0]
        b64r = pack_mesh(ring)

    b64s = pack_mesh(stamp)

    rep = {}
    if args.report and Path(args.report).exists():
        rep = json.loads(Path(args.report).read_text(encoding="utf-8"))

    def row(k, v, hot=False):
        vs = f"<b>{v}</b>" if hot else v
        return f'<div class="row"><span>{k}</span><span>{vs}</span></div>'

    pr = []
    pr.append(row("外形 (mm)", f"{sd[0]:.0f} × {sd[1]:.0f} × {sd[2]:.1f}"))
    pr.append(row("底板 / 浮雕", f"{rep.get('base_thickness', '?')} / {rep.get('relief', '?')} mm"))
    if rep.get("rim_w_mm"):
        pr.append(row("凸边框", f"宽 {rep['rim_w_mm']} · 顶高 {rep.get('total_height_mm')} mm", True))
    if args.cutter:
        cu = rep.get("cutter") or {}
        pr.append(row("边框（切模）", f"内腔 {rd[0]:.0f} · 高 {rd[2]:.1f} · 壁 {cu.get('wall_mm','?')} mm", True))
    if args.handle:
        pr.append(row("手柄", f"φ{kd[0]:.0f} × {kd[2]:.1f} mm"))
        pr.append(row("装配总高", f"{(rep.get('total_height_mm') or sd[2]) + kd[2]:.2f} mm"))
    pr.append(row("网格", f"{rep.get('triangles', len(stamp.faces)):,} 面 · 水密 {'✓' if rep.get('watertight', stamp.is_watertight) else '×'}"))
    if rep.get("stroke_stats_mm"):
        s = rep["stroke_stats_mm"]
        pr.append(row("线宽 min/中位", f"{s['min']} / {s['median']} mm"))
    pr.append(row("镜像", "已镜像（凸版）" if rep.get("mirrored", True) else "未镜像"))

    params_html = "\n  ".join(pr)

    three_src = (LIBS / "three.min.js").read_text(encoding="utf-8")
    orbit_src = (LIBS / "OrbitControls.js").read_text(encoding="utf-8")

    html = (TEMPLATE
            .replace("__TITLE__", args.title)
            .replace("__SUBTITLE__", Path(args.stl).name)
            .replace("__PARAMS__", params_html)
            .replace("__BADGE__", Path(args.stl).name)
            .replace("__THREE__", three_src)
            .replace("__ORBIT__", orbit_src)
            .replace("__GEO__", (APP_GEO
                                 .replace("__B64_STAMP__", b64s)
                                 .replace("__B64_KNOB__", b64k)
                                 .replace("__B64_RING__", b64r))))

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(html, encoding="utf-8")
    print(f"HTML 输出: {outp}  ({outp.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
