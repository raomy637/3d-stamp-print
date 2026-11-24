// =============================================================
// cutter.scad — 独立边框（切模）参数化模板
//
// 结构（与旧 build_cutter 一致）：
//   内腔 = 成品轮廓（不缩，--size 就是它）
//   外壁 = 内腔向外 offset(wall)
//   底部翼缘：再向外 offset(flange_w)，厚 flange_t，贴床防翘
//   顶部刃口：最上 edge_h 内，外壁从 wall 收薄到 edge
//
// 内腔轮廓由 job.scad 以 polygon 提供（inner_2d），参数用 -D 传入。
// offset 只处理一条闭合轮廓，8 段阶梯很快；带大量孔洞的图案不要这样搞。
// =============================================================

$fa = is_undef(curve_fa) ? 4   : curve_fa;
$fs = is_undef(curve_fs) ? 0.4 : curve_fs;

wall     = is_undef(wall)     ? 1.2  : wall;
height   = is_undef(height)   ? 12.0 : height;
edge     = is_undef(edge)     ? 0.4  : edge;
edge_h   = is_undef(edge_h)   ? 3.0  : edge_h;
flange_w = is_undef(flange_w) ? 4.0  : flange_w;
flange_t = is_undef(flange_t) ? 1.6  : flange_t;
edge_seg = is_undef(edge_seg) ? 8    : edge_seg;

module __ring(h, outer) {
    linear_extrude(height = h, convexity = 10)
        difference() {
            offset(delta = outer) inner_2d();
            inner_2d();
        }
}

module cutter_body() {
    union() {
        __ring(height - edge_h, wall);
        for (i = [0 : edge_seg - 1]) {
            outer = wall + (edge - wall) * (i + 1) / edge_seg;
            translate([0, 0, height - edge_h + i * edge_h / edge_seg])
                __ring(edge_h / edge_seg + (i == edge_seg - 1 ? 0.001 : 0), outer);
        }
        __ring(flange_t, wall + flange_w);
    }
}

cutter_body();
