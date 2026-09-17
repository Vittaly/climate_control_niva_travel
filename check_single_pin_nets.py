#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_single_pin_nets.py — сети с одним узлом во всех YAML проекта."""
import os
import sys
import yaml


def collect(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for n in sorted(os.listdir(p)):
                if n.endswith(".yaml"):
                    out.append(os.path.join(p, n))
        elif os.path.isfile(p):
            out.append(p)
    return out


def main():
    paths = sys.argv[1:] or ["main.yaml", "sheets"]
    files = collect(paths)
    if not files:
        print("Не найдено yaml-файлов.")
        return 1
    print(f"Файлов: {len(files)}")
    print("=" * 72)

    total = 0
    for p in files:
        try:
            doc = yaml.safe_load(open(p, encoding="utf-8")) or {}
        except Exception as e:
            print(f"  [ERR] {p}: {e}")
            continue
        nets = doc.get("nets") or {}
        for net_name, info in nets.items():
            if not isinstance(info, dict):
                continue
            nodes = info.get("nodes") or []
            real = [n for n in nodes
                    if isinstance(n, dict) and n.get("component")]
            if len(real) == 1:
                total += 1
                c = real[0].get("component")
                pin = real[0].get("pin")
                hier = info.get("is_hierarchical_port")
                print(f"  [1-pin] {os.path.basename(p):<22} "
                      f"{net_name:<22} узел={c}.{pin}  hier={hier}")
            elif len(real) == 0:
                total += 1
                print(f"  [0-pin] {os.path.basename(p):<22} "
                      f"{net_name:<22} узлов нет")

    print("=" * 72)
    print(f"Всего проблемных сетей: {total}")
    if total == 0:
        print("Однопиновых сетей нет.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
