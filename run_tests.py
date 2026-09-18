#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_tests.py — запуск Ngspice-сценариев и проверка PASS/FAIL по допускам.

Все проверки берутся из YAML:
  * main.yaml → simulation_sheets (перечень листов со сценариями)
  * <sheet>.yaml → scenarios[].checks[] (node, min, max, id, description)

Один .cir может дать несколько проверок — ngspice запускается один раз.
"""
import os
import re
import subprocess
import sys
import yaml

PROJ = os.path.dirname(os.path.abspath(__file__))
MAIN_YAML = os.path.join(PROJ, "main.yaml")


# ─────────────────────────────────────────────────────────────────────
# Загрузка YAML
# ─────────────────────────────────────────────────────────────────────

def load_main():
    return yaml.safe_load(open(MAIN_YAML, encoding="utf-8"))["root_page"]


def load_sheet_yaml(sheet):
    """Найти per-sheet YAML по имени страницы."""
    root = load_main()
    for comp_name, comp in root.get("components", {}).items():
        if comp.get("symbol") != "Core:Hierarchical_Sheet":
            continue
        if comp_name[2:] != sheet and comp_name != "X_" + sheet:
            continue
        yml_path = os.path.splitext(comp["value_sch"])[0] + ".yaml"
        return yaml.safe_load(open(os.path.join(PROJ, yml_path), encoding="utf-8"))
    # fallback: искать в sheets/
    guess = os.path.join(PROJ, "sheets", sheet.lower() + ".yaml")
    if os.path.exists(guess):
        return yaml.safe_load(open(guess, encoding="utf-8"))
    return {}


# ─────────────────────────────────────────────────────────────────────
# Сбор проверок из YAML
# ─────────────────────────────────────────────────────────────────────

def collect_checks():
    """
    Возвращает список словарей:
      { id, cir, node, min, max, description }
    """
    root = load_main()
    sheets = root.get("simulation_sheets", [])
    out = []
    for sheet in sheets:
        sy = load_sheet_yaml(sheet)
        for sc in sy.get("scenarios") or []:
            sc_checks = sc.get("checks") or []
            if not sc_checks:
                continue
            multiple = len(sc_checks) > 1
            for idx, chk in enumerate(sc_checks):
                cid = chk.get("id")
                if cid is None:
                    if multiple:
                        # без id нельзя однозначно назвать проверку
                        cid = f"{sc['name']}#{idx+1}"
                    else:
                        cid = sc["name"]
                out.append({
                    "id": cid,
                    "cir": sc["name"],
                    "node": chk["node"],
                    "min": float(chk["min"]),
                    "max": float(chk["max"]),
                    "description": chk.get("description", ""),
                })
    return out


# ─────────────────────────────────────────────────────────────────────
# Запуск ngspice и парсинг
# ─────────────────────────────────────────────────────────────────────

def run(cir):
    r = subprocess.run(["ngspice", "-b", cir], capture_output=True, text=True)
    return r.stdout


def parse_vals(out):
    """Извлечь `key = value` из stdout ngspice.

    Возвращает { 'v(vbat_prot)': 0.0, 'ifan': 15.2, … }
    Регистр сохраняется как есть — ngspice обычно печатает строчными.
    """
    vals = {}
    for m in re.finditer(
        r'^\s*([a-zA-Z_][\w()]*)\s*=\s*([-+0-9.eE]+)',
        out, re.M):
        try:
            vals[m.group(1)] = float(m.group(2))
        except ValueError:
            continue
    # дополнительно — заголовки транзиентного анализа типа "vbat_prot  1.5"
    return vals


# ─────────────────────────────────────────────────────────────────────
# Основной проход
# ─────────────────────────────────────────────────────────────────────

def main():
    only = set(sys.argv[1:])  # опциональный фильтр по id или по cir

    checks = collect_checks()
    if not checks:
        print("Не найдено ни одной проверки в YAML.")
        return 1

    # Группируем проверки по .cir, чтобы запускать ngspice один раз на файл
    by_cir = {}
    for chk in checks:
        by_cir.setdefault(chk["cir"], []).append(chk)

    results = []
    for cir_name in sorted(by_cir):
        if only and cir_name not in only and not (set(c["id"] for c in by_cir[cir_name]) & only):
            continue

        cir_path = os.path.join(PROJ, "spice", cir_name + ".cir")
        if not os.path.exists(cir_path):
            for chk in by_cir[cir_name]:
                print("%-18s MISSING (%s)" % (chk["id"], os.path.relpath(cir_path, PROJ)))
                results.append(False)
            continue

        out = run(cir_path)
        vals = parse_vals(out)

        for chk in by_cir[cir_name]:
            node = chk["node"]
            lo, hi = chk["min"], chk["max"]
            if node not in vals:
                print("%-18s SKIP (%s не измерен в %s.cir)" % (chk["id"], node, cir_name))
                results.append(False)
                continue
            v = vals[node]
            ok = lo <= v <= hi
            results.append(ok)
            print("%-18s %s  %s=%+.3e  [%g..%g] %s" % (
                chk["id"],
                "PASS" if ok else "FAIL",
                node, v, lo, hi,
                chk["description"]))

    if results:
        print("\nИтого PASS: %d/%d" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())