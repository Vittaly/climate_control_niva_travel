#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_nets.py — сверка сетей YAML с фактическим нетлистом KiCad.

Для каждой страницы:
  1. Из YAML: net_name -> {(ref_kicad, pin)}
  2. Через kicad-cli sch export netlist --format kicadxml: реальный нетлист
  3. Сравнение: missing / extra / mismatch.

Запуск:
  python3 validate_nets.py
Отчёт:
  netlist_report.txt  (в текущей директории)
"""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
import yaml

_REF_RE = re.compile(r"^[A-Z]+[0-9]+$")


def sanitize_ref(ref):
    """Совпадает с одноимённой функцией в generate_kicad_project.py."""
    s = str(ref)
    if _REF_RE.match(s):
        return s
    s = re.sub(r"[^A-Za-z0-9]", "", s.upper())
    if not s:
        s = "X1"
    if not s[-1].isdigit():
        s += "1"
    return s


def expected_from_yaml(page_info):
    """net -> {(ref_kicad, pin_str)}"""
    out = defaultdict(set)
    for net_name, info in (page_info.get("nets") or {}).items():
        for node in info.get("nodes", []) or []:
            ref = node.get("component")
            if not ref or str(ref).startswith("X_"):
                continue
            pin = str(node.get("pin", "1"))
            out[net_name].add((sanitize_ref(ref), pin))
    return out


def export_netlist(sch_path, xml_out):
    """kicad-cli 10.0.4: sch export netlist --format kicadxml INPUT -o OUTPUT"""
    cmd = [
        "kicad-cli", "sch", "export", "netlist",
        "--format", "kicadxml",
        sch_path, "-o", xml_out,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
    except FileNotFoundError:
        print("[ERROR] kicad-cli не найден. Установите KiCad 7+.")
        sys.exit(2)
    except subprocess.TimeoutExpired:
        print(f"[ERROR] kicad-cli таймаут на {sch_path}")
        return False
    if r.returncode != 0:
        print(f"[ERROR] kicad-cli упал на {sch_path}:")
        print(r.stderr.decode("utf-8", errors="replace")[:500])
        return False
    return True


def parse_netlist(xml_path):
    """net -> {(ref, pin)}"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    out = defaultdict(set)
    for net in root.iter("net"):
        name = net.get("name")
        if not name:
            continue
        for node in net.findall("node"):
            ref = node.get("ref")
            pin = node.get("pin")
            if ref and pin:
                out[name].add((ref, pin))
    return out


def compare(expected, actual, page_name, report):
    def out(s=""):
        print(s)
        report.append(s)

    out(f"\n=== {page_name} ===")
    exp_names = set(expected.keys())
    act_names = set(actual.keys())
    only_yaml = exp_names - act_names
    only_kicad = act_names - exp_names
    common = exp_names & act_names
    issues = 0

    if only_yaml:
        out(f"  В YAML есть, в схеме нет ({len(only_yaml)}):")
        for n in sorted(only_yaml):
            out(f"    - {n}: {sorted(expected[n])}")
        issues += len(only_yaml)

    if only_kicad:
        clean = [n for n in only_kicad if not n.startswith("Net-(")]
        if clean:
            out(f"  В схеме есть, в YAML нет ({len(clean)}):")
            for n in sorted(clean):
                out(f"    - {n}: {sorted(actual[n])}")
            issues += len(clean)

    mismatches = 0
    for n in sorted(common):
        e = expected[n]
        a = actual[n]
        if e != a:
            mismatches += 1
            out(f"  Сеть {n}: состав отличается")
            miss = e - a
            extra = a - e
            if miss:
                out(f"    нет в схеме: {sorted(miss)}")
            if extra:
                out(f"    лишние в схеме: {sorted(extra)}")
    issues += mismatches

    if issues == 0:
        out(f"  ✓ все сети совпадают ({len(common)} шт.)")
    return issues


def main():
    if not os.path.exists("main.yaml"):
        print("[ERROR] нет main.yaml в текущей директории.")
        sys.exit(1)

    with open("main.yaml", encoding="utf-8") as f:
        main = yaml.safe_load(f) or {}
    root = main.get("root_page", {})

    pages = []
    if root:
        pages.append((
            "MAIN_ROOT",
            root,
            root.get("file", "climate_control_niva_travel.kicad_sch"),
        ))

    sdir = "sheets"
    if os.path.isdir(sdir):
        for name in sorted(os.listdir(sdir)):
            if not name.endswith(".yaml"):
                continue
            with open(os.path.join(sdir, name), encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not data:
                continue
            pages.append((
                data.get("page_name", name),
                data,
                os.path.join("schematics", data.get("file", "")),
            ))

    tmp = ".netlist_tmp"
    os.makedirs(tmp, exist_ok=True)
    report = []
    total = 0

    for page_name, page_info, sch_path in pages:
        if not os.path.exists(sch_path):
            line = f"\n=== {page_name} ===\n  [WARN] файл {sch_path} не найден"
            print(line); report.append(line)
            continue
        xml_out = os.path.join(tmp, f"{page_name}.xml")
        if not export_netlist(sch_path, xml_out):
            continue
        try:
            actual = parse_netlist(xml_out)
        except Exception as e:
            print(f"[ERROR] парсинг {xml_out}: {e}")
            continue
        expected = expected_from_yaml(page_info)
        total += compare(expected, actual, page_name, report)

    summary = [
        "",
        "=" * 70,
        ("✓ ВАЛИДАЦИЯ ПРОЙДЕНА: все сети совпадают"
         if total == 0
         else f"✗ НАЙДЕНО РАСХОЖДЕНИЙ: {total}"),
    ]
    for s in summary:
        print(s)
    report.extend(summary)

    with open("netlist_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print("\nОтчёт сохранён: netlist_report.txt")
    sys.exit(0 if total == 0 else 1)


if __name__ == "__main__":
    main()