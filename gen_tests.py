#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_tests.py — сборка тестовых .cir поверх экспорта KiCad.

Для каждой страницы:
  1) kicad-cli sch export netlist --format spice  -> база .cir (пассивы/диоды/транзисторы из KiCad);
  2) к базе добавляем .INCLUDE внешних моделей (DRV8871/MCP2562) и сценарий (источники + print + PASS/FAIL);
  3) пишем spice/<PAGE>_test.cir.
"""
import json
import os
import re
import re
import subprocess
import sys

PROJ = "/home/vitaly-pc/kicad/climate_control_niva_travel"
SPICE = os.path.join(PROJ, "spice")

def export_base(page_file):
    name = os.path.splitext(os.path.basename(page_file))[0]
    out = os.path.join(SPICE, name + "_base.cir")
    r = subprocess.run(
        ["kicad-cli", "sch", "export", "netlist", "--format", "spice",
         "--output", out, page_file],
        capture_output=True, text=True)
    return name, out, r.returncode

def scenario_lines(sheet):
    s = {
        "PWR": [
            "* P1: переполюсовка",
            "VIN VBAT_IN 0 DC -14", ".op",
            "print V(VBAT_PROT)", "quit",
        ],
    }.get(sheet, [
        "* Сценарии для %s - в TODO" % sheet, ".op", "quit",
    ])
    return s

def build_test(name, base, sheet, includes):
    text = open(base, encoding="utf-8").read()
    if text.rstrip().endswith(".end"):
        text = text.rstrip()
        text = text[: text.rfind(".end")].rstrip() + "\n"
    lines = []
    for ln in text.splitlines():
        if ln.strip().startswith('.include "Simulation_SPICE"'):
            ln = '.INCLUDE /usr/share/kicad/symbols/Simulation_SPICE.sp'
        # компоненты без SPICE-модели (J1, U6/U7...) - убираем заглушки __X
        if re.search(r'\s+\w+ __\w+$', ln.strip()):
            continue
        lines.append(ln)
    head = ["* Тест: %s (база - экспорт KiCad)" % sheet]
    head += [".INCLUDE %s" % i for i in includes if i]
    body = lines
    scen = scenario_lines(sheet)
    out = os.path.join(SPICE, sheet + "_test.cir")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(head + [""] + body + [""] + scen + [".end"]) + "\n")
    return out

def main():
    model = json.load(open(os.path.join(PROJ, "circuit_model.json"), encoding="utf-8"))
    os.makedirs(SPICE, exist_ok=True)
    for sh in model["sheets"]:
        page_file = os.path.join(PROJ, sh["file"])
        if not os.path.exists(page_file):
            print("нет файла", page_file)
            continue
        name, base, rc = export_base(page_file)
        print("экспорт %-12s rc=%d" % (sh["name"], rc))
        inc = []
        if sh["name"] in ("ACT", "CONTROLLER"):
            inc.append("DRV8871_ngspice.sp")
        if sh["name"] == "CONTROLLER":
            inc.append("MCP2562_ngspice.sp")
        test = build_test(name, base, sh["name"], inc)
        print("  тест ->", test)

if __name__ == "__main__":
    main()