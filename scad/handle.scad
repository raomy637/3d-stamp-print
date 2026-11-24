// =============================================================
// handle.scad — 标准手柄参数化模板
//
// 剖面 profile = [[r, z], ...]，从底面中心出发、沿外轮廓到顶部、
// 最后回到中心轴，围成一个闭合多边形，rotate_extrude 旋转成实体。
// profile 由 src/make_handle.py 按 style 生成：
//   dome  = 现在的圆顶 + 收颈（φ14 × 25）
//   slim  = 直筒 + 顶端 R3 圆角（斜面占比 62% -> <10%）
// =============================================================

$fa = is_undef(curve_fa) ? 4 : curve_fa;
$fs = is_undef(curve_fs) ? 0.4 : curve_fs;
seg  = is_undef(seg) ? 96 : seg;

profile = is_undef(profile) ? [[0, 0], [7, 0], [7, 1.4], [6, 3], [4.9, 12],
                               [4.9, 18], [5.5, 22], [4.2, 24.4], [0, 25]]
                            : profile;

rotate_extrude(angle = 360, $fn = seg)
    polygon(points = profile);
