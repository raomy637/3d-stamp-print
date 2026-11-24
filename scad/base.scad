// =============================================================
// base.scad — 底模（印章 / 凹模）参数化模板
//
// 由 src/scad_engine.py 生成的 job.scad 拼接本文件后运行；
// 2D 轮廓由 Python 直接写成 polygon() 模块（outline_2d / pattern_2d），
// 不走 SVG import —— OpenSCAD 2021.01 对多个 SVG 的 y 轴映射不一致，
// 两件 union 时会整体错位（实测 bbox 里图案跑到 base 上方）。
//
// 参数一律用 -D 传入（job.scad 里不重复赋值，避免 is_undef 三方式失效）。
// =============================================================

$fa = is_undef(curve_fa) ? 4   : curve_fa;
$fs = is_undef(curve_fs) ? 0.4 : curve_fs;

mode         = is_undef(mode)         ? "raise" : mode;
base_t       = is_undef(base_t)       ? 3.0     : base_t;
relief       = is_undef(relief)       ? 1.8     : relief;
overlap      = is_undef(overlap)      ? 0.05    : overlap;
draft_ratio  = is_undef(draft_ratio)  ? 1.0     : draft_ratio;   // 槽顶 / 槽底

module base_body() {
    if (mode == "sink") {
        // 凹模：图案从顶面向下挖 relief 深；槽底窄、开口宽（外张锥度）
        difference() {
            linear_extrude(height = base_t, convexity = 10) outline_2d();
            translate([0, 0, base_t - relief])
                linear_extrude(height = relief + overlap,
                               scale = draft_ratio, convexity = 10)
                    pattern_2d();
        }
    } else {
        // 印章：图案从底板顶面向上挤 relief 高（整体沉入 overlap 防共面）
        union() {
            linear_extrude(height = base_t, convexity = 10) outline_2d();
            translate([0, 0, base_t - overlap])
                linear_extrude(height = relief + overlap, convexity = 10)
                    pattern_2d();
        }
    }
}

base_body();
