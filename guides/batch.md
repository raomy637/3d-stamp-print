# 批量出模（10 / 20 / 40 套）

一次要做几十套完全不同的模具时，怕的不是生成慢，是**配对错**、**找不到哪个文件是哪套**。所以这里只有两条规矩：目录就是配对关系，清单就是唯一入口。

## 目录：两级，配对靠路径保证

```
print/jobs/<批次>/<单号>/base.stl      底模（或凹模）
print/jobs/<批次>/<单号>/cutter.stl    这一套的边框
out/<批次>/<单号>/                     report.json / preview.png / MANIFEST.md / model.html
out/<批次>/INDEX.md                    批次总表
out/<批次>/batch.json                  机器读：参数 + 耗时 + 体检
```

底模和边框**永远同目录同单号**，不存在"A 的底模配 B 的边框"这种可能——配对不靠文件名前缀，靠路径唯一性。拷到 U 盘也只拷一个文件夹。

单层旧结构（`print/jobs/<单号>/`）继续有效：`make_print_index.py` 会先看目录里有没有 `base.stl` / `cutter.stl`，有就当单套，没有就往下遍历一层当批次。两种可以混放，`PRINT.md` 里分别显示 `bakers_v5` 和 `xmas40/snowman_A`。

## 命名

| 对象 | 规则 | 例子 |
|---|---|---|
| 批次 | `日期_主题_数量`，纯 ASCII | `2026-11-24_xmas_40`、`2026-12-01_pets_20` |
| 单号 | 图案 slug，批量时前面加 `A_` / `B_` 便于口头对号 | `A_snowman`、`B_star`、`01_santa` |

批次名会进路径，**别用空格与中文**（Windows 下 PowerShell 与切片器都容易踩引号坑）；中文只放在 `INDEX.md` 的说明列里。单号取文件名 stem 即可，脚本缺省就这么干。

## 清单

一个 CSV（也吃 JSON 数组），五列，后三列可省略：

```
item,input,size,relief,mode
A_snowman,inputs/snowman.png,85,1.8,raise
B_star,inputs/star.png,70,2.0,raise
C_tree,inputs/tree.png,85,1.8,sink
```

- `item` 空则用 `input` 的文件名 stem
- `size` 缺省 85、`relief` 缺省 1.8、`mode` 缺省 `raise`（`sink` = 凹模）
- 以 `#` 开头的行是注释，可以拿来分组
- 同一批次里尺寸可以各不相同（每套独立算），互不影响

## 跑

```
python src\batch_molds.py --batch 2026-11-24_xmas_40 --list inputs\batch_xmas40.csv --jobs 8
python src\batch_molds.py --batch ... --list ... --limit 2      # 先试跑两套，看图对不对
python src\batch_molds.py --batch ... --list ... --no-html      # 连 model.html 也不要（最快）
python src\batch_molds.py --batch ... --list ... --preview      # 额外出三栏预览图（慢 ~20%）
python src\batch_molds.py --batch ... --list ... --serial       # 每套独立进程（排错用）
```

`--jobs` 默认 `min(8, CPU线程/2)`。默认走**常驻 worker**：任务按 round-robin 分给 N 个 `batch_worker.py` 进程，每个进程只导入一次 numpy/scipy/skimage/trimesh，之后顺序跑自己那一份。`--serial` 退回"每套一个独立进程"，只在单套排错时用。

单套失败不阻塞其他套：失败的那行在 `INDEX.md` 里标「失败」并把最后 800 字错误留在 `batch.json`，其余照跑，退出码 1。

跑完自动刷新 `PRINT.md`（一次，不是每套一次）；单套用 `--no-index` 跳过，避免 40 个进程抢着写同一个文件。**多栏预览图默认不出**（`preview.png` 每套 ~1.9s，40 套白花 76s CPU），要看就加 `--preview`；每套的 `model.html` 照旧生成。

## 性能：40 套 61 秒（8 路）/ 47 秒（16 路）

i5-13400（10 核 16 线程）/ 图案 2048×2048 / `--no-html` / 不出 preview：

| 并行数 | 旧法（每套独立进程） | 现在（常驻 worker） | 提速 |
|---|---|---|---|
| 8 | 96 s（含 preview）→ 75 s（无 preview） | **60.6 s** | −37% |
| 10 | — | 54.8 s | |
| 12 | — | 51.0 s | |
| 16 | — | **46.7 s** | −51% |

10 套规模：51 s（每套带 html + preview）→ 现在 8 路约 22 s。

提速来源（按贡献排）：

1. **常驻 worker**（本次，最大一块）：旧法每套重启解释器，numpy/scipy/skimage/trimesh 重新导入 **4.7 s**，40 套 = 188 s 纯 CPU 白烧。改成一个进程连跑多套后，导入只付 N 次。
2. **OpenSCAD nightly + Manifold 后端**：底模渲染 21.9 s → **1.0 s**（旧 2021.01 / CGAL）。2025-08-18 起 Manifold 是默认后端，官方只发 nightly（`tools/openscad_nightly/`，224MB，gitignore）。同类实测：ModelRift CGAL 540s → Manifold 27s；Brennen Johnston 盲文生成器 45 分钟 → 1.8s。
3. **批量关 preview**：三栏 matplotlib 图 1.9 s/套，40 套 76 s CPU，默认不出。
4. **别每套刷索引**：`PRINT.md` 重建要读全部 STL 网格（40 件 4.1 s/次），批量 `--no-index`，批次结束刷一次。
5. **STL 体检缓存**：`.cache/probe.json` 按 `mtime+size` 记尺寸/面数/水密/体积，索引刷新 4 s → 0.4 s。

单套剩下的 5 s 几何（已不含导入、不含 preview）：轮廓提取 0.4s、外框识别 0.5s、线宽统计 0.8s（距离变换）、shapely 布尔 0.2s、OpenSCAD 进程 + 渲染 1.0–1.3s、trimesh 体检 0.3s。都是 2048px 全图操作或一次性进程启动，**没有单点值得再拆**；降采样能省 0.9s 但会改动轮廓精度，不做。

`--jobs` 怎么选：**8 是"机器还能用"的上限**，12/16 更快但会把 16 线程打满、桌面明显卡；要极限吞吐再往上加。

## 边界件

| 情况 | 处理 |
|---|---|
| 一套失败 | 该行标失败、留错误尾巴；其余照跑；`batch.json` 里可查 `rc` |
| 想重跑某一套 | 清单里只留那一行，`--limit` 或单独跑 `stamp_pipeline.py --job <批次>/<单号>`（同路径会覆盖） |
| 批次改名 | 直接改清单里的 `item` 重跑；旧目录自己删（脚本不删用户文件） |
| 中途取件打印 | 每套独立落盘，跑完一套就能打；不必等整批（`INDEX.md` 是最后才写，中途看 `print/jobs/<批次>/` 目录即可） |
| 手柄 | **不进批次**：`print/standard/handle_straight.stl` 单独打，一套模具配一个 |
| 多套尺寸外框全同 | 边框 STL 字节完全一致（`2026-11-24_xmas_pair` 实测），`INDEX.md` 会标「同 `A_xmas`，不必重复打」；文件保留，索引仍认配对 |

## 坑

- 批次名里带空格 → 路径要引号，切片器与 PowerShell 都可能截断，别用。
- 同一批次里 `item` 重名 → 后跑的覆盖前面的（`setdefault` 只会留下第一个的 report，STL 被后一个覆盖），清单里保证唯一。
- 一次开 16 路不会更快：单套内部 OpenSCAD Manifold 也吃多核，超过物理核数就是互相抢；8 路在这台机上是最优点附近。
- `--no-html` 只是省掉每套的 3D 预览；**正式批次别关**（Skill 的硬规则是每次出件都要留预览 html）。
