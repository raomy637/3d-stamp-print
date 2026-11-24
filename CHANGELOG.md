# 变更记录

> 只记「改了什么 + 为什么」。现状看 `README.md`，历史细节留在这里，避免 README 膨胀。

## v8 · 2026-11-24 · 纳入 Git，备份到 GitHub 私有仓库

- 本项目此前没有版本管理（`git status` 报 not a repository），改文档只能整份重写来兜底。现在 `git init -b main`，首个提交 53 个文件 / 12.5 MiB，远端为私有仓库 `raomy637/3d-stamp-print`（SSH，`origin/main` 已跟踪）。
- 新增 `.gitignore`：排除 `__pycache__`、`*.pyc`、`_p_*.html` / `probe_*.html` 探针副本、`.vscode`、`*.gcode` / `*.3mf`。STL 与 `model.html` 故意入库——克隆即得完整可打状态。
- 之前踩的"无 git 可回滚"的坑自此关闭：Markdown 改坏了可以直接 `git checkout`。

## v7 · 2026-11-24 · 打包成 Skill（clay-stamp-mold）

- 流程不再只活在这个仓库里：新建 Skill `clay-stamp-mold`（路径 `workspace/.user_skills/clay-stamp-mold`），描述里写死了触发语（粘土印章/饼干模具/曲奇切模/线稿转 STL/底模边框手柄/尺寸与打印参数），下次说"做张模具"就会自动路由过来。
- SKILL.md 只留"怎么跑 + 输出约定 + 汇报三件事 + 默认参数 + 踩过的坑"，细节靠按需读本仓库的 `guides/*.md` 与 `CHANGELOG.md`（不复制，避免双份维护）。
- 新增 `scripts/run_job.py`：一条命令串起 出件 → 3D 预览 → 手柄补料（缺才补）→ PRINT.md 刷新与体检 → 摘要，已在本机跑通（bakers_v3 全绿）。
- `quick_validate.py` 校验通过。

## v6 · 2026-11-24 · 输出目录规范化（print/ + out/&lt;图案&gt;/）

- 以前所有产物平铺在 `out/`，靠 `bakers_v2`、`bakers_v3` 后缀区分几代，肉眼分不清哪个能打。现在**按"能不能打印"分家**：
  - `print/`：只放可打印 `.stl`，命名 `<图案>_base.stl` / `<图案>_cutter.stl` / `handle_*.stl`；
  - `out/<图案>/`：只放给人看的（`MANIFEST.md` 清单、`report.json`、`preview.png`、`lines.svg`、`model.html`、`shot_*.png`）。
- `--out` 语义改为**图案目录名**（`out\bakers_v3` → 目录 `out/bakers_v3`；传 `out\x.stl` 也认并按 `x` 处理）。新增 `--print-dir`（默认 `print`）。
- 新增 `make_print_index.py`：扫 `print/` 生成根目录 **`PRINT.md`** 打印总表（件名/外形/面数/水密/体积/打印要点），两个脚本收尾自动刷新；`--check` 退出码 0=全部可打，能抓命名不合规、非水密、只有底模没边框三类问题（已造违规验证会真报错）。
- 每次运行多写一份 `out/<图案>/MANIFEST.md`：这批出了什么、哪个能打、打什么设置。
- 迁移：现有件搬进新布局；v2 那批、85mm 早期件、旧截图全部归档到 `out/_archive/`（**留档不删**），`handles/`、`out/viewer/` 两个旧目录撤掉，手柄排布脚本移到 `tools/`。
- 文档：新增 `guides/output-layout.md`；README 压到 181 行（索引层），旧的平铺路径全部改掉。

## v5 · 2026-11-24 · 手柄改成小把手（φ14 × 25）

- 按用户要求缩到手部实际需要：**总高 25mm、底盘 φ14**，握柄 φ9.8–11 腰形（原来 φ20–21.2 / 48 高不合理地大）。
- 粘接面从 804mm² 降到 154mm²；单个体积 17.2 → 2.03 cm³，6 联排从 232×32 缩到 124×14mm（一盘能排十几二十个）。
- `HANDLE_PROFILE` 是唯一的数据源，`make_handle.py` 与预览图重跑即可，底模/边框一行不动。
- 预览器 HUD 改为自动读 STL 尺寸 → 手柄行显示 φ14 × 25.0，装配总高 29.8mm。

## v4 · 2026-11-24 · 边框从底模里拆成独立件（三件套）

- **结构性改动**：以前"外沿凸起一道边框"（`--rim-w`）是错的——那道墙跟着底模走，每换一张图就要重打一圈墙，刃口也做不薄。改为**边框独立成件**：只有一圈 1.2mm 墙 + 0.4mm 刃口，专门切粘土外形。
- 新增 `build_cutter()` 与 `--cutter-wall/height/edge/edge-h/flange-w/flange-t/clearance`、`--no-cutter`；`--rim-w` 默认改 0 并标注为淘汰写法。
- **`--size` 语义变更**：以前=底模外形，现在=**边框内腔（切出来的粘土尺寸）**；底模自动内缩 2×0.4mm 环隙（MakerWorld 生成器的 standard clearance）。
- 取值依据（12mm 高 / 1.2 墙 / 0.4 刃口 / 4.0×1.6 翼缘 / 0.4 环隙）连同出处落到 `guides/parts.md`；刃口锥段从 4 段改 8 段，避免明显台阶。
- `make_viewer.py` 支持第三个网格（`--cutter`）：分离视图三件并排、装配视图落进内腔；侧视改低角度平视（看 12/4.8/25 的厚度对比）、背面改从后方看粘接面。
- 实测：底模 84.2×84.2×4.8、56,194 面、水密、18.6cm³；边框 95.4×95.4×12、58,930 面、水密、5.62cm³。
- 文档拆分：README 压回 184 行（索引层），细节进 `guides/parts.md`（尺寸链/参数出处）与 `guides/printing.md`（切片/后处理）。

## v3 · 2026-11-24 · 手柄独立成件

- 新增 `make_handle.py`：手柄从章体流水线剥离，尺寸定死后**一次打一批**（`--count 6` → 124×14mm 联排），换图案不用重打手柄。
- 手柄改瘦长款：底盘 φ32×2.4、握柄 φ20–21.2、总高 48mm（旧款 φ44×33.2 偏矮胖）。**v5 又改成小把手 φ14×25，见下。**
- `stamp_pipeline.py` 移除 `--handle / --handle-height / --handle-flange-r` 与 `*_handle.stl` 输出；json 不再含 handle 字段。旧件 `out/bakers_v2_handle.stl` 已删。
- 预览第三栏改为**半剖（2x，带中心线）**：手柄不再画进章体剖面，底部注明另件路径。

## v2 · 2026-11-24 · 加边框 + 3D 预览

- 新增 `--rim-w / --rim-h`：外沿凸边框限深 0.4mm（我这张 85 盘取宽 4mm）。
- 新增 `viewer/make_viewer.py`：单文件离线 HTML 查看器（three.js 内联、网格 uint16 量化），五视角 + 分离/装配。
- 尺寸精度修正：底板轮廓按 `size - 2*margin` 反算，输出严格等于 `--size`。
- 取舍记录：纹理 PEI 会把纹路翻印到印面 → 追求平整须用光面/玻璃板；但 rim 比浮雕高 0.4mm，与「图案朝下」互斥，二选一。

## v1 · 2026-11-24 · 首发

- 线稿 → 凸印章：`find_contours` 取轮廓 + even-odd 判孔洞 → 2D 布尔 → 分层拉伸 → manifold 并集出单一水密网格。
- 外框识别：铺满整图的闭合连通块转为底面轮廓（扇贝边自动继承），框体丢弃。
- 线宽体检：0.44mm 腐蚀校验部件存亡；`--min-stroke` 只加粗「本来印不出来」的部件。
- 默认 X 镜像（凸印章压出来才正读）。
- 实测：85×85×4.8mm、58,086 面、水密 18.9cm³；线宽 min 0.59 / 中位 1.54mm → 0.2 喷嘴可行。
