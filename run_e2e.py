#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_e2e.py — сквозной тестовый прогон аналоговой части через эмулятор Ngspice.

Оркестратор: сам ничего не дублирует, а по шагам вызывает уже имеющиеся
скрипты/утилиты с нужными параметрами:

  1. ЭКСПОРТ НЕТЛИСТОВ  — для каждого листа схемы (из circuit_model.json)
         kicad-cli sch export netlist  ->  spice/<SHEET>.net
  2. ГЕНЕРАЦИЯ .CIR     — из нетлиста листа
         python3 kicad_to_spice.py <net> <SHEET> <порты...>
         ->  spice/<SHEET>.sub   (субсхема, порты = цепи листа + GND)
             spice/<SCEN>.cir    (по одному файлу на сценарий)
  3. ЭМУЛЯТОР И ОТЧЁТ    —
         python3 run_tests.py
         -> прогон каждого .cir через `ngspice -b`, печать PASS/FAIL,
            итог "PASS: X/Y" (допуски — в CHECKS внутри run_tests.py).

Порты субсхемы для kicad_to_spice.py берутся прямо из экспортированного
нетлиста (все цепи листа + GND) — чтобы любой узел сценария был доступен
как внешний вывод тестовой обвязки.

Запуск (из корня проекта):
    python3 run_e2e.py              # полный цикл: экспорт+генерация+прогон
    python3 run_e2e.py --gen        # только шаги 1-2 (без прогона)
    python3 run_e2e.py --run        # только шаг 3 (прогнать уже готовые .cir)
    python3 run_e2e.py --sheet PWR  # только лист PWR

Код возврата: 0, если все сценарии PASS, иначе число провалов.
"""
import json
import os
import re
import subprocess
import sys

PROJ = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(PROJ, "circuit_model.json")
SPICE = os.path.join(PROJ, "spice")
PY = sys.executable

# Листы, для которых есть аналоговые сценарии (остальные пропускаем)
SCENARIO_SHEETS = ("PWR", "UI", "SEN_HEAT", "SEN_SOLAR", "SEN_COND",
                   "ACT", "OUT", "CAN", "SEN_CABIN")


def run(cmd):
    """Запустить внешний скрипт/утилиту, пробросив вывод, вернуть код."""
    r = subprocess.run(cmd, cwd=PROJ, capture_output=True, text=True)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def netlist_ports(netfile):
    """Порты субсхемы = цепи листа из нетлиста + GND.

    Отбрасываем внутренние no-connect цепи KiCad (`unconnected-(...)`),
    у них невалидные для SPICE имена (скобки/дефисы) — как порты они не нужны.
    """
    text = open(netfile, encoding="utf-8").read()
    ports = set()
    for m in re.findall(r'\(net\s+\(code "\d+"\)\s+\(name "([^"]+)"\)', text):
        n = m.lstrip('/')
        if n.startswith("unconnected-"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_]+", n):
            continue
        ports.add(n)
    ports.add("GND")
    return sorted(ports)


def sheet_files(model):
    return {sh["name"]: os.path.join(PROJ, sh["file"]) for sh in model["sheets"]}


def main():
    args = sys.argv[1:]
    only_gen = "--gen" in args
    only_run = "--run" in args
    sheet_filter = None
    for a in args:
        if a.startswith("--sheet="):
            sheet_filter = a.split("=", 1)[1]
    os.makedirs(SPICE, exist_ok=True)

    model = json.load(open(MODEL_PATH, encoding="utf-8"))
    files = sheet_files(model)

    if not only_run:
        print("== 1. Экспорт нетлистов (kicad-cli) ==")
        netfiles = {}
        for name in SCENARIO_SHEETS:
            if sheet_filter and name != sheet_filter:
                continue
            if name not in files:
                print("  %-12s нет файла листа" % name)
                continue
            net = os.path.join(SPICE, name + ".net")
            rc = run(["kicad-cli", "sch", "export", "netlist",
                      "--output", net, files[name]])
            print("  %-12s rc=%d -> %s" % (name, rc, os.path.relpath(net, PROJ)))
            netfiles[name] = net

        print("== 2. Генерация .sub/.cir (kicad_to_spice.py) ==")
        for name, net in netfiles.items():
            ports = netlist_ports(net)
            rc = run([PY, os.path.join(PROJ, "kicad_to_spice.py"),
                      net, name] + ports)
            print("  %-12s rc=%d (портов: %d)" % (name, rc, len(ports)))
        if only_gen:
            print("\nГотово: .cir сгенерированы (прогон пропущен, используйте --run).")
            return 0

    print("== 3. Эмулятор Ngspice + проверка (run_tests.py) ==")
    r = subprocess.run([PY, os.path.join(PROJ, "run_tests.py")],
                       cwd=PROJ, capture_output=True, text=True)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    m = re.search(r"Итого PASS:\s*(\d+)/(\d+)", r.stdout)
    if not m:
        print("Не удалось получить сводку run_tests.py (код %d)." % r.returncode)
        return 1
    passed, total = int(m.group(1)), int(m.group(2))
    return total - passed


if __name__ == "__main__":
    sys.exit(main())