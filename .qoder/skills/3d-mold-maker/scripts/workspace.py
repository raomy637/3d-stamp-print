#!/usr/bin/env python3
"""Plan and apply work-folder layout for 3d-mold-maker.

Subcommands:
  plan           read an inbox batch and print a source->target plan
  apply          create folders and copy original images from a plan
  collect        copy printable STLs / records from a pipeline output into a plan
  migrate-plan   dry-run report for out/ and print/ history
  migrate-apply  copy a migration plan (never deletes sources)

This script uses the standard library only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
SKIP_PARTS = {"__pycache__", ".cache", ".git"}
ASCII_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
STAMP_MODELS = ("base.stl", "cutter.stl", "plate.stl")
PET_MODELS = ("outline.stl", "lid.stl")
PET_RECORD_MODELS = ("positive_reference.stl", "detail_coupon.stl")

HEADER_ALIASES = {
    "order": {"order", "订单", "订单号"},
    "item": {"item", "款式", "单号", "图案"},
    "input": {"input", "image", "图", "图片", "原图"},
    "size": {"size", "尺寸"},
    "relief": {"relief", "浮雕", "深度"},
    "mode": {"mode", "模式"},
    "text": {"text", "文案", "文字"},
    "press": {"press", "按压", "压法"},
    "quantity": {"quantity", "qty", "数量", "份数"},
}


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(2)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def human_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f}{unit}" if unit != "B" else f"{int(amount)}B"
        amount /= 1024
    return f"{value}B"


def require_ascii(value: str, field: str) -> str:
    if not value or not ASCII_SLUG.match(value) or ".." in value:
        die(f"{field} must be ASCII letters/digits/._- (no spaces, no '..'): {value!r}")
    return value


def safe_project(value: str, field: str) -> str:
    text = value.strip().replace(" ", "_")
    if not text or text in {".", ".."} or any(ch in text for ch in '<>:"/\\|?*'):
        die(f"{field} contains a path separator or is empty: {value!r}")
    return text


def parse_text(value: str | None, field: str, required: bool) -> bool:
    if value is None or str(value).strip() == "":
        if required:
            die(f"{field} is required (yes/no)")
        return False
    lowered = str(value).strip().lower()
    if lowered in {"yes", "y", "true", "1", "有", "是"}:
        return True
    if lowered in {"no", "n", "false", "0", "无", "否"}:
        return False
    die(f"{field} must be yes/no: {value!r}")
    return False


def parse_press(value: str | None, required: bool) -> str | None:
    if value is None or str(value).strip() == "":
        if required:
            die("press is required for stamp route (flip/direct)")
        return None
    lowered = str(value).strip().lower()
    if lowered in {"flip", "翻压", "翻过来压"}:
        return "flip"
    if lowered in {"direct", "正压", "平放正压", "直压"}:
        return "direct"
    die(f"press must be flip/direct: {value!r}")
    return None


def parse_float(value: str | None, default: float, field: str, max_value: float | None = None) -> float:
    if value is None or str(value).strip() == "":
        return default
    try:
        number = float(value)
    except ValueError:
        die(f"{field} must be a number: {value!r}")
    if field == "size" and max_value is not None and not (0 < number <= max_value):
        die(f"size must be > 0 and <= {max_value:g} mm")
    if field == "relief" and number <= 0:
        die("relief must be > 0")
    return number


def parse_int(value: str | None, default: int, field: str) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        number = int(value)
    except ValueError:
        die(f"{field} must be an integer: {value!r}")
    if number < 1:
        die(f"{field} must be >= 1")
    return number


def normalize_headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        return {}
    mapping: dict[str, str] = {}
    for name in fieldnames:
        key = (name or "").strip().lower()
        for canonical, aliases in HEADER_ALIASES.items():
            if key in aliases:
                mapping[canonical] = name
                break
    return mapping


def read_manifest(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = normalize_headers(reader.fieldnames)
        if "input" not in headers:
            die(f"manifest {path} needs an input column")
        rows = []
        for line_no, raw in enumerate(reader, start=2):
            if not any((value or "").strip() for value in raw.values()):
                continue
            rows.append({key: raw.get(column) for key, column in headers.items()} | {"_line": line_no})
        return rows


def scan_images(inbox: Path) -> list[Path]:
    return sorted(
        path for path in inbox.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS and not (set(path.parts) & SKIP_PARTS)
    )


def versioned(base: Path) -> tuple[Path, int]:
    if not base.exists():
        return base, 1
    index = 2
    while True:
        candidate = base.parent / f"{base.name}_v{index}"
        if not candidate.exists():
            return candidate, index
        index += 1


def build_item(raw: dict, args, inbox: Path) -> dict:
    order = (raw.get("order") or args.order or "").strip()
    if args.kind == "order":
        if not order:
            die(f"order is required for every row (line {raw.get('_line')})")
        require_ascii(order, "order")
    item = (raw.get("item") or "").strip()
    if not item:
        die(f"item is required for every row (line {raw.get('_line')})")
    require_ascii(item, "item")

    source_text = (raw.get("input") or "").strip()
    if not source_text:
        die(f"input is required for every row (line {raw.get('_line')})")
    source = Path(source_text)
    if not source.is_absolute():
        source = inbox / source
    source = source.resolve()
    if not source.is_file():
        die(f"input not found: {source}")

    route = args.route
    if route == "pet":
        size = parse_float(raw.get("size"), 95.0, "size", 100.0)
        relief = parse_float(raw.get("relief"), 4.0, "relief")
        mode = "raise"
        text = parse_text(raw.get("text"), "text", required=False)
        press = None
        mirror = True
        reason = "pet lid is mirrored by construction"
    else:
        size = parse_float(raw.get("size"), 85.0, "size", 300.0)
        relief = parse_float(raw.get("relief"), 1.8, "relief")
        mode = (raw.get("mode") or "raise").strip().lower()
        if mode in {"凸", "凸模", "印章"}:
            mode = "raise"
        if mode in {"凹", "凹模"}:
            mode = "sink"
        if mode not in {"raise", "sink"}:
            die(f"mode must be raise/sink: {mode!r}")
        text = parse_text(raw.get("text"), "text", required=True)
        press = parse_press(raw.get("press"), required=True)
        mirror = press == "flip"
        reason = f"press={press} overrides text default"

    quantity = parse_int(raw.get("quantity"), 1, "quantity")
    return {
        "order": order if args.kind == "order" else None,
        "item": item,
        "source": str(source),
        "source_size": source.stat().st_size,
        "source_sha256": sha256_file(source),
        "size_mm": size,
        "relief_mm": relief,
        "mode": mode,
        "text": text,
        "press": press,
        "mirror": mirror,
        "mirror_reason": reason,
        "quantity": quantity,
    }


def command_plan(args) -> None:
    root = Path(args.root).resolve()
    inbox = Path(args.inbox).resolve()
    if not inbox.is_dir():
        die(f"inbox not found: {inbox}")

    if args.kind == "sample":
        if not args.project:
            die("--project is required for sample batches")
        project = safe_project(args.project, "project")
        date = None
    else:
        project = None
        date = args.date or datetime.now().strftime("%Y%m%d")
        if not re.fullmatch(r"\d{8}", date):
            die("--date must be YYYYMMDD")

    if args.manifest:
        rows = read_manifest(Path(args.manifest).resolve())
    else:
        images = scan_images(inbox)
        if not images:
            die(f"no images found in {inbox}")
        rows = []
        for path in images:
            rows.append({
                "input": str(path.relative_to(inbox)),
                "item": path.stem,
                "order": args.order,
                "_line": 0,
            })

    items = [build_item(raw, args, inbox) for raw in rows]
    seen: set[tuple[str | None, str]] = set()
    for item in items:
        key = (item["order"], item["item"])
        if key in seen:
            die(f"duplicate item in batch: {key}")
        seen.add(key)

    counts = Counter(item["order"] for item in items if item["order"])
    date_dir = root / "订单" / date if args.kind == "order" else None
    sample_root = root / "打样" / project if args.kind == "sample" else None
    sample_multi = args.kind == "sample" and len(items) > 1

    image_targets: set[str] = set()
    for item in items:
        if args.kind == "sample":
            base, version = versioned(sample_root)
        else:
            order_root = date_dir / item["order"]
            if counts[item["order"]] == 1:
                base, version = versioned(order_root)
            else:
                base, version = versioned(order_root / item["item"])
        item["version"] = version
        item["target_base"] = str(base)
        item["image_target"] = str(base / "原始图" / Path(item["source"]).name)
        if sample_multi:
            item["model_target"] = str(base / "打印模型" / item["item"])
            item["record_target"] = str(base / "_记录" / item["item"])
        else:
            item["model_target"] = str(base / "打印模型")
            item["record_target"] = str(base / "_记录")
        if item["image_target"] in image_targets:
            die(f"duplicate image target: {item['image_target']}")
        image_targets.add(item["image_target"])

    summary = {
        "items": len(items),
        "orders": len(counts),
        "source_bytes": sum(item["source_size"] for item in items),
        "versioned": sum(1 for item in items if item["version"] > 1),
    }
    plan = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "root": str(root),
        "inbox": str(inbox),
        "kind": args.kind,
        "route": args.route,
        "batch": require_ascii(args.batch, "batch"),
        "project": project,
        "date": date,
        "summary": summary,
        "items": items,
    }

    if args.json_out:
        target = Path(args.json_out).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.format == "json":
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    print(f"# 归类计划：{plan['batch']}（{args.kind} / {args.route}）")
    print()
    print(f"数据根：`{root}`")
    print(f"收件箱：`{inbox}`")
    if project:
        print(f"项目名：{project}")
    if date:
        print(f"处理日期：{date}")
    print()
    print("| 订单 | 款式 | 镜像 | 尺寸/浮雕 | 目标 |")
    print("|---|---|---|---|---|")
    for item in items:
        order = item["order"] or "-"
        print(f"| {order} | {item['item']} | {item['mirror']} | "
              f"{item['size_mm']:g}/{item['relief_mm']:g} | `{item['target_base']}` |")
    print()
    print(f"共 {summary['items']} 项，{summary['orders']} 个订单，"
          f"源图 {human_bytes(summary['source_bytes'])}，版本化 {summary['versioned']} 项。")
    print("此步不写盘；确认后再 apply。")
    if args.json_out:
        print(f"计划文件：`{Path(args.json_out).resolve()}`")


def load_plan(path: str) -> dict:
    plan_path = Path(path).resolve()
    if not plan_path.is_file():
        die(f"plan not found: {plan_path}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema_version") != 1:
        die("unsupported plan schema_version")
    return plan


def command_apply(args) -> None:
    plan = load_plan(args.plan)
    created = 0
    copied = 0
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in plan["items"]:
        grouped[item["target_base"]].append(item)

    for base_text, items in grouped.items():
        base = Path(base_text)
        if base.exists():
            die(f"target already exists; re-plan for a new version: {base}")
        planned_dirs: set[Path] = set()
        for item in items:
            planned_dirs.add(Path(item["image_target"]).parent)
            planned_dirs.add(Path(item["model_target"]))
            planned_dirs.add(Path(item["record_target"]))
        for directory in sorted(planned_dirs, key=lambda value: len(value.parts)):
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
                created += 1

    for item in plan["items"]:
        base = Path(item["target_base"])
        source = Path(item["source"])
        target = Path(item["image_target"])
        if target.exists():
            die(f"image target already exists: {target}")
        shutil.copy2(source, target)
        copied += 1
        if sha256_file(target) != item["source_sha256"]:
            die(f"copy checksum mismatch: {target}")

    for base_text, items in grouped.items():
        base = Path(base_text)
        manifest = {
            "schema_version": 1,
            "kind": plan["kind"],
            "batch": plan["batch"],
            "route": plan["route"],
            "project": plan["project"],
            "order": items[0]["order"] if len({item['order'] for item in items}) == 1 else None,
            "date": plan["date"],
            "created_at": now_iso(),
            "items": [
                {
                    "item": item["item"],
                    "source": Path(item["image_target"]).relative_to(base).as_posix(),
                    "source_sha256": item["source_sha256"],
                    "size_mm": item["size_mm"],
                    "relief_mm": item["relief_mm"],
                    "mode": item["mode"],
                    "text": item["text"],
                    "press": item["press"],
                    "mirror": item["mirror"],
                    "mirror_reason": item["mirror_reason"],
                    "quantity": item["quantity"],
                    "models": [],
                    "records": [],
                }
                for item in items
            ],
        }
        (base / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"APPLIED: {len(plan['items'])} items, {created} directories, {copied} images copied")
    for base in grouped:
        print(f"- {base}")


def update_manifest(base: Path, item_name: str, models: list[str], records: list[str],
                    model_source: Path, record_source: Path) -> None:
    path = base / "manifest.json"
    if not path.is_file():
        die(f"manifest not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data.get("items", []):
        if item.get("item") == item_name:
            item["models"] = models
            item["records"] = records
            item["pipeline_output"] = {"models": str(model_source), "records": str(record_source)}
            item["collected_at"] = now_iso()
            break
    else:
        die(f"item not found in manifest: {item_name}")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def command_collect(args) -> None:
    plan = load_plan(args.plan)
    items = plan["items"]
    if args.item:
        selected = [item for item in items if item["item"] == args.item]
        if not selected:
            die(f"item not in plan: {args.item}")
        item = selected[0]
    elif len(items) == 1:
        item = items[0]
    else:
        die("multiple items in plan; pass --item")

    if args.source_dir:
        model_source = Path(args.source_dir).resolve()
        record_source = model_source
    else:
        if not args.model_dir or not args.record_dir:
            die("provide --source-dir, or both --model-dir and --record-dir")
        model_source = Path(args.model_dir).resolve()
        record_source = Path(args.record_dir).resolve()
    if not model_source.is_dir():
        die(f"model source not found: {model_source}")
    if not record_source.is_dir():
        die(f"record source not found: {record_source}")
    base = Path(item["target_base"])
    model_dir = Path(item["model_target"])
    record_dir = Path(item["record_target"])
    model_dir.mkdir(parents=True, exist_ok=True)
    record_dir.mkdir(parents=True, exist_ok=True)

    if plan["route"] == "pet":
        candidates = PET_MODELS + PET_RECORD_MODELS
    else:
        candidates = STAMP_MODELS

    models: list[str] = []
    records: list[str] = []
    for name in candidates:
        source = model_source / name
        if not source.is_file():
            continue
        target = (record_dir if name in PET_RECORD_MODELS else model_dir) / name
        if target.exists():
            die(f"target already exists: {target}")
        shutil.copy2(source, target)
        relative = target.relative_to(base).as_posix()
        (records if target.parent == record_dir else models).append(relative)

    for source in sorted(record_source.rglob("*")):
        if not source.is_file() or source.name in candidates:
            continue
        if set(source.relative_to(record_source).parts) & SKIP_PARTS:
            continue
        target = record_dir / source.relative_to(record_source)
        if target.exists():
            die(f"target already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        records.append(target.relative_to(base).as_posix())

    if not models:
        die(f"no printable STL found in {model_source} (expected {candidates})")
    update_manifest(base, item["item"], models, records, model_source, record_source)
    print(f"COLLECTED: {item['item']}")
    print(f"- models: {', '.join(models)}")
    print(f"- records: {len(records)} files")
    print(f"- target: {base}")


def tree_stats(path: Path) -> tuple[int, int]:
    if path.is_file():
        return 1, path.stat().st_size
    files = 0
    bytes_total = 0
    for child in path.rglob("*"):
        if child.is_file() and not (set(child.relative_to(path).parts) & SKIP_PARTS):
            files += 1
            bytes_total += child.stat().st_size
    return files, bytes_total


def migration_mappings(repo: Path, root: Path) -> tuple[list[dict], list[str]]:
    mappings: list[dict] = []
    skipped: list[str] = []
    out_dir = repo / "out"
    print_dir = repo / "print"

    def add(source: Path, target_rel: Path) -> None:
        files, bytes_total = tree_stats(source)
        if files == 0:
            skipped.append(f"{source}（空目录）")
            return
        mappings.append({
            "source": str(source),
            "target": str(root / target_rel),
            "type": "dir" if source.is_dir() else "file",
            "files": files,
            "bytes": bytes_total,
        })

    if out_dir.is_dir():
        for child in sorted(out_dir.iterdir()):
            if child.name == "handles":
                skipped.append(f"{child}（标准件记录，留原地）")
            elif child.name == "_archive":
                add(child, Path("_归档/历史件/out/_archive"))
            elif child.name.startswith("_"):
                add(child, Path("_实验/out") / child.name)
            else:
                add(child, Path("_归档/历史件/out") / child.name)

    if print_dir.is_dir():
        for child in sorted(print_dir.iterdir()):
            if child.name == "standard":
                skipped.append(f"{child}（标准件，留原地）")
            elif child.name in {"test", "_tmp"} or child.name.startswith("_"):
                add(child, Path("_实验/print") / child.name)
            elif child.name == "jobs":
                add(child, Path("_归档/历史件/print/jobs"))
            else:
                add(child, Path("_归档/历史件/print") / child.name)

    return mappings, skipped


def command_migrate_plan(args) -> None:
    repo = Path(args.repo).resolve()
    root = Path(args.root).resolve()
    if not (repo / "out").is_dir() and not (repo / "print").is_dir():
        die(f"no out/ or print/ under {repo}")

    mappings, skipped = migration_mappings(repo, root)
    targets = Counter(mapping["target"] for mapping in mappings)
    conflicts = []
    for mapping in mappings:
        mapping["conflict"] = False
        if targets[mapping["target"]] > 1:
            mapping["conflict"] = True
            conflicts.append(f"重复目标：{mapping['target']}")
        elif Path(mapping["target"]).exists():
            mapping["conflict"] = True
            conflicts.append(f"目标已存在：{mapping['target']}")

    total_files = sum(mapping["files"] for mapping in mappings)
    total_bytes = sum(mapping["bytes"] for mapping in mappings)
    plan = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "repo": str(repo),
        "root": str(root),
        "summary": {
            "mappings": len(mappings),
            "files": total_files,
            "bytes": total_bytes,
            "conflicts": len(conflicts),
            "skipped": len(skipped),
        },
        "mappings": mappings,
        "skipped": skipped,
        "conflicts": conflicts,
    }

    out_dir = Path(args.out_dir).resolve() if args.out_dir else root / "_归档" / "_迁移报告"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"migration-plan-{stamp}.json"
    json_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.format == "json":
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    md_path = out_dir / f"migration-plan-{stamp}.md"
    lines = [
        "# 历史件迁移计划（dry-run）",
        "",
        f"- 生成时间：{plan['generated_at']}",
        f"- 源仓库：`{repo}`",
        f"- 目标数据根：`{root}`",
        f"- 计划文件：`{json_path}`",
        "",
        "## 汇总",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| 映射条目 | {len(mappings)} |",
        f"| 文件数 | {total_files} |",
        f"| 总体积 | {human_bytes(total_bytes)} |",
        f"| 冲突 | {len(conflicts)} |",
        f"| 跳过 | {len(skipped)} |",
        "",
        "## 映射",
        "",
        "| 源 | 目标 | 文件 | 体积 | 冲突 |",
        "|---|---|---|---|---|",
    ]
    for mapping in mappings:
        source = Path(mapping["source"]).relative_to(repo).as_posix()
        target = Path(mapping["target"]).relative_to(root).as_posix()
        flag = "是" if mapping["conflict"] else ""
        lines.append(f"| `{source}` | `{target}` | {mapping['files']} | {human_bytes(mapping['bytes'])} | {flag} |")
    if skipped:
        lines += ["", "## 跳过", ""]
        lines += [f"- {item}" for item in skipped]
    if conflicts:
        lines += ["", "## 冲突", ""]
        lines += [f"- {item}" for item in conflicts]
    lines += ["", "> 本计划只读；`migrate-apply` 只复制、不删除源目录。"]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"MIGRATION PLAN: {len(mappings)} mappings, {total_files} files, {human_bytes(total_bytes)}, "
          f"{len(conflicts)} conflicts")
    print(f"- report: {md_path}")
    print(f"- json:   {json_path}")


def command_migrate_apply(args) -> None:
    plan = load_plan(args.plan)
    if "mappings" not in plan:
        die("not a migration plan")
    copied_files = 0
    copied_bytes = 0
    conflicts = 0
    for mapping in plan["mappings"]:
        source = Path(mapping["source"])
        target = Path(mapping["target"])
        if target.exists():
            conflicts += 1
            print(f"SKIP (target exists): {target}")
            continue
        if mapping["type"] == "dir":
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(*SKIP_PARTS))
            files, bytes_total = tree_stats(target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            files, bytes_total = 1, target.stat().st_size
        copied_files += files
        copied_bytes += bytes_total
        print(f"COPIED: {source} -> {target}")
    print(f"MIGRATION APPLIED: {copied_files} files, {human_bytes(copied_bytes)}, {conflicts} conflicts skipped")
    print("旧目录未删除；核对无误后再人工决定是否清理。")


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="3d-mold-maker work-folder planner")
    commands = root.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="read inbox and print a layout plan")
    plan.add_argument("--root", required=True)
    plan.add_argument("--kind", choices=["sample", "order"], required=True)
    plan.add_argument("--batch", required=True)
    plan.add_argument("--inbox", required=True)
    plan.add_argument("--project")
    plan.add_argument("--date")
    plan.add_argument("--order")
    plan.add_argument("--manifest")
    plan.add_argument("--route", choices=["stamp", "pet"], default="stamp")
    plan.add_argument("--json-out")
    plan.add_argument("--format", choices=["md", "json"], default="md")
    plan.set_defaults(func=command_plan)

    apply_cmd = commands.add_parser("apply", help="create folders and copy images from a plan")
    apply_cmd.add_argument("--plan", required=True)
    apply_cmd.set_defaults(func=command_apply)

    collect = commands.add_parser("collect", help="copy printable STLs and records into a plan")
    collect.add_argument("--plan", required=True)
    collect.add_argument("--item")
    collect.add_argument("--source-dir", help="pet-relief: single directory with STLs and records")
    collect.add_argument("--model-dir", help="stamp: print/jobs/<job> with base.stl/cutter.stl/plate.stl")
    collect.add_argument("--record-dir", help="stamp: out/<job> with report/preview")
    collect.set_defaults(func=command_collect)

    migrate_plan = commands.add_parser("migrate-plan", help="dry-run migration report")
    migrate_plan.add_argument("--repo", required=True)
    migrate_plan.add_argument("--root", required=True)
    migrate_plan.add_argument("--out-dir")
    migrate_plan.add_argument("--format", choices=["md", "json"], default="md")
    migrate_plan.set_defaults(func=command_migrate_plan)

    migrate_apply = commands.add_parser("migrate-apply", help="copy a migration plan")
    migrate_apply.add_argument("--plan", required=True)
    migrate_apply.set_defaults(func=command_migrate_apply)
    return root


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
