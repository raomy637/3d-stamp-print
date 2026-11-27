R = is_undef(edge_r) ? 0.5 : edge_r;
base_t = is_undef(base_t) ? 3.0 : base_t;
echo(R=R, base_t=base_t);
translate([0,0,0]) linear_extrude(height=base_t - R + 1e-4) offset(delta=-R) circle(r=10);
