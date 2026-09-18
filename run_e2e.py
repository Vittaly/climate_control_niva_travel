#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_e2e.py — сквозной тестовый прогон аналоговой части через Ngspice.

Шаги:
  1. Экспорт нетлистов (kicad-cli) для каждого листа из main.yaml.
  2. Генерация .sub/.cir (kicad_to_spice.py) из нетлиста + YAML.
  3. Сверка нетлиста и YAML — ОБЯЗАТЕЛЬНЫЙ БЛОКИРУЮЩИЙ ШАГ.
     Любое расхождение останавливает прогон: тесты будут проверять
     не ту схему, которая попадёт на плату.
  4. Эмулятор Ngspice (run_tests.py) — только если шаг 3 прошёл.

Запуск:
    python3 run_e2e.py                  # полный цикл, сверка обязательна
    python3 run_e2e.py --gen            # только экспорт + генерация
    python3 run_e2e.py --run            # только прогон (сверку пропускает)
    python3 run_e2e.py --check          # валидация .lib
    python3 run_e2e.py --net-check      # только сверка, без прогона
    python3 run_e2e.py --no-net-check   # ОПАСНО: пропустить сверку,
                                        # только для ручной отладки
    python3 run_e2e.py --sheet FAN_KEY

Код возврата: 0 если все PASS. Иначе:
  * 1 — расхождение нетлиста и YAML (независимо от количества);
  * N — число провалов тестов (если сверка прошла, но тесты упали).
"""
import glob
import os
import re
import subprocess
import sys
import yaml

PROJ = os.path.dirname(os.path.abspath(__file__))
MAIN_YAML = os.path.join(PROJ, "main.yaml")
SHEETS_DIR = os.path.join(PROJ, "sheets")
SPICE = os.path.join(PROJ, "spice")
PY = sys.executable


def run(cmd, label=None):
    """Запустить процесс. Каждая строка stdout/stderr — с меткой [label].

    Warning/error выделяются отдельным префиксом, но метка листа
    сохраняется всегда, чтобы не было путаницы при буферизации.
    """
    r = subprocess.run(cmd, cwd=PROJ, capture_output=True, text=True)
    tag = f"[{label}] " if label else ""

    def emit(stream, text):
        for line in text.splitlines():
            low = line.lower()
            if "warning" in low:
                stream.write(f"{tag}WARN: {line}\n")
            elif "error" in low:
                stream.write(f"{tag}ERROR: {line}\n")
            else:
                stream.write(f"{tag}{line}\n")

    if r.stdout:
        emit(sys.stdout, r.stdout)
    if r.stderr:
        emit(sys.stderr, r.stderr)
    return r.returncode


def load_main():
    return yaml.safe_load(open(MAIN_YAML, encoding="utf-8"))["root_page"]


def find_sheet_yaml(sheet):
    root = load_main()
    for comp_name, comp in root.get("components", {}).items():
        if comp.get("symbol") != "Core:Hierarchical_Sheet":
            continue
        if comp_name[2:] == sheet or comp_name == "X_" + sheet:
            yml = os.path.splitext(comp["value_sch"])[0] + ".yaml"
            full = os.path.join(PROJ, yml)
            if os.path.exists(full):
                return full
    for yml in glob.glob(os.path.join(SHEETS_DIR, "*.yaml")):
        try:
            data = yaml.safe_load(open(yml, encoding="utf-8"))
        except Exception:
            continue
        if data and data.get("page_name") == sheet:
            return yml
    return None


def find_sheet_sch(sheet):
    """Найти .kicad_sch листа.

    Ищем ТОЛЬКО в корне проекта. Никаких альтернативных путей:
    если файла тут нет — это ошибка конфигурации, а не повод искать
    где-то ещё (иначе можно случайно подхватить устаревшую копию).
    """
    yml_path = find_sheet_yaml(sheet)
    if not yml_path:
        return None
    data = yaml.safe_load(open(yml_path, encoding="utf-8")) or {}
    sch = data.get("file")
    if not sch:
        return None

    path = sch if os.path.isabs(sch) else os.path.join(PROJ, sch)
    return path if os.path.exists(path) else None


def netlist_ports(netfile):
    """Порты .subckt = именованные цепи нетлиста + GND.

    KiCad-цепочки `unconnected-(...)` и с недопустимыми для SPICE
    именами (скобки/дефисы) отбрасываем.
    """
    text = open(netfile, encoding="utf-8").read()
    ports = set()
    for m in re.finditer(r'\(net\s+\(code "\d+"\)\s+\(name "([^"]+)"\)', text):
        n = m.group(1).lstrip('/')
        if n.startswith("unconnected-"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_]+", n):
            continue
        ports.add(n)
    ports.add("GND")
    return sorted(ports)


def check_libs():
    root = load_main()
    lib_dir = os.path.join(PROJ, root.get("spice", {}).get("lib_dir", "spice/lib"))
    missing = []
    for name, model in root.get("spice", {}).get("component_models", {}).items():
        inc = model.get("include")
        if inc and not os.path.exists(os.path.join(lib_dir, inc)):
            missing.append((name, os.path.join(lib_dir, inc)))
    for yml in glob.glob(os.path.join(SHEETS_DIR, "*.yaml")):
        try:
            data = yaml.safe_load(open(yml, encoding="utf-8"))
        except Exception:
            continue
        for inc in (data or {}).get("spice", {}).get("includes", []):
            if not os.path.exists(os.path.join(lib_dir, inc)):
                missing.append((os.path.basename(yml), os.path.join(lib_dir, inc)))
    if not missing:
        print("  Все .lib на месте в %s" % os.path.relpath(lib_dir, PROJ))
        return True, []
    for owner, path in missing:
        print("  WARN: %s: нет %s" % (owner, os.path.relpath(path, PROJ)))
    return False, missing


# ─────────────────────────────────────────────────────────────────────
# Сверка нетлиста и YAML
# ─────────────────────────────────────────────────────────────────────

def parse_netlist_components(text):
    comps = {}
    for m in re.finditer(
        r'\(comp\s+\(ref "([^"]+)"\).*?'
        r'\(value "([^"]*)"\).*?'
        r'\(libsource\s+\(lib "([^"]+)"\)\s+\(part "([^"]+)"\)',
        text, re.S):
        ref, value, lib, part = m.groups()
        comps[ref] = {"value": value, "lib": lib, "part": part}
    return comps


def parse_netlist_nets(text):
    nets = {}
    for m in re.finditer(
        r'\(net\s+\(code "\d+"\)\s+\(name "([^"]+)"\)(.*?)\n\t\t\)',
        text, re.S):
        name = m.group(1).lstrip('/')
        if name.startswith("unconnected-"):
            continue
        nodes = set()
        for nm in re.finditer(r'\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)', m.group(2)):
            nodes.add((nm.group(1), nm.group(2)))
        nets[name] = nodes
    return nets


def yaml_component_refs(sheet_yaml):
    refs = set()
    for ref, comp in (sheet_yaml.get("components") or {}).items():
        if comp.get("symbol") == "Core:Hierarchical_Sheet":
            continue
        if ref.startswith("X_"):
            continue
        refs.add(ref)
    return refs


def yaml_nets(sheet_yaml):
    out = {}
    for net_name, net in (sheet_yaml.get("nets") or {}).items():
        nodes = set()
        for n in net.get("nodes", []):
            if isinstance(n, dict) and n.get("component") and n.get("pin") is not None:
                nodes.add((n["component"], str(n["pin"])))
        out[net_name] = nodes
    return out


def check_netlist_vs_yaml(sheet, netfile):
    yml_path = find_sheet_yaml(sheet)
    if not yml_path:
        return [f"  нет YAML для листа {sheet} — сверка невозможна"]

    sheet_yaml = yaml.safe_load(open(yml_path, encoding="utf-8")) or {}
    text = open(netfile, encoding="utf-8").read()
    nl_comps = parse_netlist_components(text)
    nl_nets = parse_netlist_nets(text)

    yml_refs = yaml_component_refs(sheet_yaml)
    yml_nets_map = yaml_nets(sheet_yaml)

    diffs = []

    # 1. Компоненты
    nl_refs = {r for r, c in nl_comps.items()
               if not r.startswith("X_")
               and c.get("part") != "Hierarchical_Sheet"}
    if nl_refs - yml_refs:
        diffs.append("  Компоненты только в нетлисте: " +
                     ", ".join(sorted(nl_refs - yml_refs)))
    if yml_refs - nl_refs:
        diffs.append("  Компоненты только в YAML: " +
                     ", ".join(sorted(yml_refs - nl_refs)))

    # 2. Сети
    nl_names = set(nl_nets.keys())
    yml_names = set(yml_nets_map.keys())
    if nl_names - yml_names:
        diffs.append("  Сети только в нетлисте: " +
                     ", ".join(sorted(nl_names - yml_names)))
    if yml_names - nl_names:
        diffs.append("  Сети только в YAML: " +
                     ", ".join(sorted(yml_names - nl_names)))

    # 3. Узлы в общих сетях
    for name in sorted(nl_names & yml_names):
        nl_set = {(r, p) for r, p in nl_nets[name] if not r.startswith("X_")}
        yml_set = {(r, p) for r, p in yml_nets_map[name] if not r.startswith("X_")}
        if nl_set == yml_set:
            continue
        if nl_set - yml_set:
            diffs.append(f"  Сеть {name}: в YAML нет " +
                         ", ".join(f"{r}.{p}" for r, p in sorted(nl_set - yml_set)))
        if yml_set - nl_set:
            diffs.append(f"  Сеть {name}: в нетлисте нет " +
                         ", ".join(f"{r}.{p}" for r, p in sorted(yml_set - nl_set)))

    return diffs


# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    only_gen   = "--gen" in args
    only_run   = "--run" in args
    only_check = "--check" in args
    only_nc    = "--net-check" in args
    no_nc      = "--no-net-check" in args
    sheet_filter = None
    for a in args:
        if a.startswith("--sheet="):
            sheet_filter = a.split("=", 1)[1]

    os.makedirs(SPICE, exist_ok=True)
    os.makedirs(os.path.join(SPICE, "lib"), exist_ok=True)

    root = load_main()
    sheets_all = root.get("simulation_sheets", [])
    if sheet_filter:
        sheets_all = [s for s in sheets_all if s == sheet_filter]

    if only_check:
        print("== Валидация библиотек ==")
        ok, _ = check_libs()
        return 0 if ok else 1

    # ─── Шаги 1-2 ──────────────────────────────────────────────────
    netfiles = {}
    if not only_run:
        print("== 1. Экспорт нетлистов (kicad-cli) ==")
        netfiles = {}
        for name in sheets_all:
            sch = find_sheet_sch(name)
            if not sch:
                print("  %-18s нет .kicad_sch — пропускаю" % name)
                continue
            net = os.path.join(SPICE, name + ".net")
            rc = run(["kicad-cli", "sch", "export", "netlist",
                    "--output", net, sch], label=name)      # ← label здесь
            print("  %-18s rc=%d -> %s" % (name, rc, os.path.relpath(net, PROJ)))
            if rc == 0:
                netfiles[name] = net                        # ← и это вернулось

        print("== 2. Генерация .sub/.cir (kicad_to_spice.py) ==")
        for name, net in netfiles.items():
            ports = netlist_ports(net)
            rc = run([PY, os.path.join(PROJ, "kicad_to_spice.py"),
                      net, name] + ports)
            print("  %-18s rc=%d (портов: %d)" % (name, rc, len(ports)))

        if only_gen:
            print("\nГотово: .sub/.cir сгенерированы (прогон пропущен, используйте --run).")
            return 0

    # ─── Шаг 3: сверка — БЛОКИРУЮЩАЯ ───────────────────────────────
    net_mismatch = False
    if not no_nc:
        if only_run:
            # В режиме --run нет свежих нетлистов, но сверить можем
            # с уже лежащими в spice/. Это страхует от «прогон старых
            # .cir после правки YAML».
            for name in sheets_all:
                net = os.path.join(SPICE, name + ".net")
                if os.path.exists(net):
                    netfiles[name] = net

        print("== 3. Сверка нетлистов и YAML ==")
        any_diff = False
        for name in sorted(netfiles):
            diffs = check_netlist_vs_yaml(name, netfiles[name])
            if not diffs:
                print("  %-18s OK" % name)
                continue
            any_diff = True
            print("  %-18s РАСХОЖДЕНИЯ:" % name)
            for d in diffs:
                print(d)
        if any_diff:
            net_mismatch = True
            print()
            print("!! Схема и YAML разошлись — прогон тестов отменён.")
            print("!! Исправьте схему, либо YAML, либо и то и другое.")
            print("!! Если уверены, что расхождения безобидны:")
            print("!!   python3 run_e2e.py --no-net-check  (для отладки)")
            return 1
        else:
            print("  Все листы согласованы.")

    if only_nc:
        return 0

    # ─── Шаг 4: только если сверка прошла ──────────────────────────
    print("== 4. Эмулятор Ngspice + проверка (run_tests.py) ==")
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