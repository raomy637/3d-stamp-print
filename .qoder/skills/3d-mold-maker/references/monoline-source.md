# monoline 细线源稿口径（2026-11-27 增补）

竞品参考件实测线宽 0.3–1.4mm ≈ 2 条挤出线：Arachne 沿笔画铺 2 条变宽墙即填实，内部没有放填充的缝 ⇒ 无蜂窝、表面是顺笔画的直线走线。我们存量件线宽 1.3–3.0mm，只能靠切片实心（100% 填充 + 8 墙），表面是实心斜纹。**两条路线并存，按件选，不混用。**

## 路线选择

| 路线 | 适用 | 源稿 | 切片 |
|---|---|---|---|
| 粗线存量 | 已有订单、粗字重源稿 | 不动 | 100% 填充 + 8 墙（0.4 喷嘴）+ Arachne + 顶壳 6，熨烫关 |
| monoline 细线 | 新开发款、客户确认改细线风格 | 按目标线宽**重画** | 默认 2–3 墙 + Arachne，填充比例随意 |

- 目标线宽 = 2×喷嘴线宽是**上限愿望**，实际受源稿最密特征间距限制：中心线归一后相邻平行笔画间距 < 目标线宽就会并块。santa 原图实测上限 ≈0.6mm（雪花分叉/胡子短弧间距 ≈0.67mm）；要 0.9mm 必须源稿本身留更大间距（重画），否则接受合并。0.6mm 仍在竞品实测 0.3–1.4mm 区间内，0.4 喷嘴 Arachne 1–2 条变宽墙填实、无填充缝。
- **首选代码中心线归一**：`src/tools/monoline_normalize.py`（骨架 → 剪毛刺 → 定半径重建，**不做 ∩原区域**）。验收测试 `tests/test_monoline_normalize.py`：线宽均匀、不拆字、中心线覆盖、不长毛刺；RED 基线 = `cap_stroke_width`（∩原区域留粗块，线宽 0.88–1.81 不均匀）。
- **禁止生图模型重新创作订单图案**（文生图会漂移构图/字形/细节）；AI 编辑只作最后备选且必须与原图逐项对比。`--stroke-cap` 维持量产禁用。
- 细线风格改变字重观感（粗字变中心线细字），订单件交付前先给客户确认。

## 源稿三条要求

1. **内部线条细且均匀**（monoline），无填充色块、无灰度阴影。
2. **外框单闭合环、与内部图案分离**（不接触），bbox 铺满 >80%，且**环自身面积 ≥2% 图幅**——`find_frame` 的噪声门槛，细线外框最容易栽在这（house 细线稿外框 1.8% → `no_frame` → 退化圆底）。外框只取剪影、不成浮雕线，所以**外框可单独加粗**（建议线宽 ≈2–2.5% 图幅），不影响内部细线观感。花瓣/异形都走这条，外框形状即成品形状。
3. **无多余内环**：AI 细线稿常多画一圈内圆。prep 按「环状连通块：填充比 >3 且 span 0.5–0.88」删除；**只把删除区涂白、保留其余灰度抗锯齿**——纯 0/255 二值图会让 Otsu 阈值退化为 0，整图判空。

## 核验落点（读 report.json，fail-closed）

- 源稿有外框但 `frame.reason == "no_frame"` ⇒ **停**，修源稿（外框加粗/与图案分离），不得交圆底件。
- monoline 路线 `stroke_stats_mm.max > 1.3` ⇒ 源稿混入粗笔画，停，重画。注意 report 的 min 是加粗前统计，垫细线看日志「线宽体检…0 个会消失」。
- `preview.png` 缺部件 ≠ STL 缺部件：双环源稿会触发预览把内部图案当洞填掉的渲染 bug。**事实来源是 STL 剖切**（trimesh `section` 取 z = 底板 + 浮雕/2，栅格化看闭合环嵌套）。

## 命令与实测

```text
.venv\Scripts\python.exe src\tools\monoline_normalize.py --input 原图.png --out 细线.png --size 101.6 --target-mm 0.6
.venv\Scripts\python.exe src\stamp_pipeline.py --input 细线.png --out out\<job> --size 101.6 --relief 2.5 ^
  --print-dir print --no-index
.venv\Scripts\python.exe tests\test_monoline_normalize.py new 0.6   # 验收判据回归
```

| 件 | 线宽 min/中位/max mm | 外框 | 墙数提示 |
|---|---|---|---|
| house 细线（生图重画，外框未加粗，反例） | 0.48 / 0.80 / 1.18 | `no_frame` → 圆底，**拒收** | 3 |
| santa 代码归一 0.6mm（忠实原图） | 0.58 / 0.71 / 1.02 | 18 瓣继承 | 3 |

证据留档：`work/_实验/monoline_code/`（代码归一源稿、忠实度对比、剖切）、`monoline_house/`、`monoline_santa/`（生图路线留档对照）；cap 收细反证见 `work/_实验/width_diag_demo.png`。