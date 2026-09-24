#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
strip_primitive_nodes.py — удаляет spice.nodes у типов с primitive M/Q/D.

Зачем:
    Для примитивов SPICE-порты совпадают с pinfunction KiCad-символа
    (D/G/S, C/B/E, A/K). Распиновку генератор выводит сам из нетлиста,
    и spice.nodes становится дублированием.

    Для subckt (BTS141, NTC_10K_3435, моторы) spice.nodes ОСТАЁТСЯ —
    там порядок портов subckt не выводится из конвенций.

Использование:
    python3 strip_primitive_nodes.py                # dry-run, все sheets/*.yaml
    python3 strip_primitive_nodes.py --apply        # применить
    python3 strip_primitive_nodes.py --yaml sheets/cabin_sensor.yaml --apply
    python3 strip_primitive_nodes.py --no-backup    # без .bak

Комментарии:
    Если установлен ruamel.yaml — комментарии сохраняются.
    Иначе используется PyYAML, и комментарии в изменённых файлах
    будут потеряны (для изменённых файлов создаётся .bak).
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent
SHEETS_DIR = PROJ / "sheets"

PRIMITIVES = {"M","Q","D","R","C","L"}


# ─────────────────────────────────────────────────────────────────────
# Загрузка / сохранение YAML
# ─────────────────────────────────────────────────────────────────────

def load_yaml(path: Path):
    """Загружает YAML. Пробует ruamel.yaml (сохраняет комментарии),
    иначе PyYAML. Возвращает (data, kind), kind ∈ {"ruamel", "pyyaml"}.
    """
    try:
        from ruamel.yaml import YAML
        yml = YAML()
        yml.preserve_quotes = True
        with open(path, encoding="utf-8") as f:
            data = yml.load(f)
        return data, "ruamel"
    except ImportError:
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data, "pyyaml"


def save_yaml(path: Path, data, kind: str) -> None:
    if kind == "ruamel":
        from ruamel.yaml import YAML
        yml = YAML()
        yml.preserve_quotes = True
        yml.indent(mapping=2, sequence=4, offset=2)
        with open(path, "w", encoding="utf-8") as f:
            yml.dump(data, f)
    else:
        import yaml
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data, f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )


# ─────────────────────────────────────────────────────────────────────
# Обработка одного файла
# ─────────────────────────────────────────────────────────────────────

def process_file(path: Path, apply: bool, backup: bool) -> tuple[int, int]:
    """Возвращает (найдено, удалено). apply=False — только dry-run."""
    data, kind = load_yaml(path)

    ctypes = (data or {}).get("component_types") or {}
    if not ctypes:
        return 0, 0

    found = 0
    removed = 0

    for tname, tdef in ctypes.items():
        if not isinstance(tdef, dict):
            continue
        sp = tdef.get("spice")
        if not isinstance(sp, dict):
            continue
        prim = sp.get("primitive")
        if prim not in PRIMITIVES:
            continue
        if "nodes" not in sp:
            continue
        found += 1
        print(f"  {path.name}: {tname}: primitive={prim}, "
              f"nodes={list((sp.get('nodes') or {}).keys())}")

        if apply:
            del sp["nodes"]
            removed += 1

    if apply and removed:
        if backup:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        save_yaml(path, data, kind)

    return found, removed


# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Удалить spice.nodes у типов с primitive M/Q/D"
    )
    ap.add_argument("--apply", action="store_true",
                    help="записать изменения (по умолчанию dry-run)")
    ap.add_argument("--no-backup", action="store_true",
                    help="не создавать .bak перед изменением")
    ap.add_argument("--yaml", action="append", default=[],
                    help="конкретный файл (можно несколько). "
                         "По умолчанию — все sheets/*.yaml кроме main.yaml")
    args = ap.parse_args()

    if args.yaml:
        paths = [Path(p).resolve() for p in args.yaml]
    else:
        paths = [
            Path(p).resolve()
            for p in sorted(glob.glob(str(SHEETS_DIR / "*.yaml")))
            if os.path.basename(p) != "main.yaml"
        ]

    if not paths:
        print("Не найдено ни одного YAML для обработки.", file=sys.stderr)
        return 1

    total_found = 0
    total_removed = 0

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"Режим: {mode}")
    print(f"Файлов: {len(paths)}")
    print()

    for path in paths:
        if not path.exists():
            print(f"  {path}: НЕ НАЙДЕН", file=sys.stderr)
            continue

        print(f"[{path.name}]")
        try:
            found, removed = process_file(
                path, apply=args.apply, backup=not args.no_backup,
            )
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            continue
        if found == 0:
            print("  (нет типов с primitive M/Q/D и nodes)")
        total_found += found
        total_removed += removed
        print()

    print(f"Итого: найдено {total_found} типов, "
          f"удалено {total_removed} nodes.")
    if not args.apply and total_found:
        print()
        print("Чтобы применить изменения, повторите с --apply:")
        print(f"  python3 {Path(__file__).name} --apply")

    return 0


if __name__ == "__main__":
    sys.exit(main())
