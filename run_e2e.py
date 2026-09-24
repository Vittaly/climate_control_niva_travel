#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_e2e.py — сквозной тестовый прогон аналоговой части через Ngspice.

Модель идентификации листов:
  * Первоисточник — sheets/<stem>.yaml. Stem = имя файла без .yaml.
  * Схема листа   — <stem>.kicad_sch (в корне проекта).
  * Компонент в main.yaml — X_<STEM_UPPER> (одиночный лист)
                            X_<STEM_UPPER>_<INST> (мульти-инстанс).
  * value_sch у X_* — единственная связь компонента со схемой.
  * Список листов к прогону НЕ хранится отдельно: он выводится как
    {X_*, встречающиеся в nets} ∪ standalone_sheets.

Реестр моделей:
  * main.yaml:spice.models — модели компонентов корневой страницы
    (сейчас — STM32F103RCT6) и общие для всего проекта, если такие
    появятся.
  * sheets/<stem>.yaml:spice.models — модели компонентов этого листа
    (DRV8871, MCP2562, NTC_*, BTS141, DC_MOTOR, LED_*, .model диодов).
  * Каждая модель ссылается на .lib в spice/lib через include:
    (имя файла, без пути). Путь — общая конвенция скриптов, в YAML
    не дублируется.
  * component_types[type].spice.model → имя записи в реестре.

MCU-модель:
  * Электрика кремния — spice/lib/stm32f103rc_helpers.lib (рукописный,
    проверяется в --check).
  * Per-scenario модель МК — spice/<scenario>_mcu.sub, генерируется
    модулем mcu_model.py. Вызов происходит из kicad_to_spice.build_cir
    (шаг 2), не отсюда.

Пути:
  * PROJ       — корень проекта (каталог этого файла).
  * MAIN_YAML  — sheets/main.yaml.
  * LIB_DIR    — spice/lib, константа. Это знание скрипта о своей
                 файловой структуре, в main.yaml не декларируется.

Шаги:
  1. Экспорт нетлистов (kicad-cli) для каждого листа.
  2. Генерация .sub/.cir (kicad_to_spice.py) из нетлиста + YAML.
     Внутри kicad_to_spice → mcu_model.generate_scenario для
     сценариев, дёргающих МК.
  3. Сверка нетлиста и YAML — ОБЯЗАТЕЛЬНЫЙ БЛОКИРУЮЩИЙ ШАГ.
  4. Эмулятор Ngspice (run_tests.py) — только если шаг 3 прошёл.

Запуск:
    python3 run_e2e.py                       # полный цикл
    python3 run_e2e.py --gen                 # только экспорт + генерация
    python3 run_e2e.py --run                 # только прогон
    python3 run_e2e.py --check               # валидация .lib и helpers
    python3 run_e2e.py --net-check           # только сверка
    python3 run_e2e.py --no-net-check        # ОПАСНО: пропустить сверку
    python3 run_e2e.py --sheet power_supply  # один лист по stem'у

Код возврата: 0 если все PASS. Иначе:
  * 1 — расхождение нетлиста и YAML (или ошибка конфигурации);
  * N — число провалов тестов (если сверка прошла, но тесты упали).
"""
import glob
import os
import re
import subprocess
import sys
import yaml

PROJ = os.path.dirname(os.path.abspath(__file__))
SHEETS_DIR = os.path.join(PROJ, "sheets")
MAIN_YAML = os.path.join(SHEETS_DIR, "main.yaml")
SPICE = os.path.join(PROJ, "spice")
LIB_DIR = os.path.join(SPICE, "lib")
PY = sys.executable

# Рукописные библиотеки, обязательные к наличию независимо от того,
# упомянуты ли они в spice.models. stm32f103rc_helpers.lib — база
# для всех <scenario>_mcu.sub, без неё ни один MCU-сценарий не соберётся.
REQUIRED_HELPERS = (
    "stm32f103rc_helpers.lib",
)


def run(cmd, label=None):
    """Запустить процесс. Каждая строка stdout/stderr — с меткой [label]."""
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


def rel(p):
    return os.path.relpath(p, PROJ) if p else "—"


# ─────────────────────────────────────────────────────────────────────
# Резолвер: stem → (yaml, kicad_sch). Единственный в проекте.
# ─────────────────────────────────────────────────────────────────────

def derive_stems(root):
    """Набор stem'ов к прогону — выводится, а не хранится.

    Иерархические: X_*, встречающиеся в nets, → basename(value_sch)
                   без расширения .kicad_sch.
    Standalone:    main.yaml.standalone_sheets (только stem'ы).
    """
    xs_in_components = {
        c for c, v in (root.get("components") or {}).items()
        if v.get("symbol") == "Core:Hierarchical_Sheet"
    }
    xs_in_nets = set()
    for net in (root.get("nets") or {}).values():
        for n in (net.get("nodes") or []):
            c = str(n.get("component", ""))
            if c.startswith("X_"):
                xs_in_nets.add(c)

    orphans = xs_in_components - xs_in_nets
    if orphans:
        raise ValueError(
            "X_* есть в components, но не встречается в nets: "
            + ", ".join(sorted(orphans)))

    unknown = xs_in_nets - xs_in_components
    if unknown:
        raise ValueError(
            "nets ссылается на X_*, которых нет в components: "
            + ", ".join(sorted(unknown)))

    stems = set()
    for xname in xs_in_nets:
        v = root["components"][xname].get("value_sch")
        if not v:
            raise ValueError(f"{xname}: нет value_sch")
        stems.add(os.path.splitext(os.path.basename(v))[0])

    for entry in (root.get("standalone_sheets") or []):
        stem = os.path.splitext(os.path.basename(str(entry)))[0]
        stems.add(stem)

    return sorted(stems)


def resolve_stem(stem):
    """stem → (yaml_path, sch_path, error|None)."""
    yml = os.path.join(SHEETS_DIR, stem + ".yaml")
    if not os.path.exists(yml):
        return None, None, f"нет {rel(yml)}"

    for sch in (os.path.join(PROJ, stem + ".kicad_sch"),
                os.path.join(SHEETS_DIR, stem + ".kicad_sch")):
        if os.path.exists(sch):
            return yml, sch, None
    return yml, None, f"нет {stem}.kicad_sch (ни в корне, ни в sheets/)"


# ─────────────────────────────────────────────────────────────────────
# Порты нетлиста и валидация библиотек
# ─────────────────────────────────────────────────────────────────────

def netlist_ports(netfile):
    """Порты .subckt = именованные цепи нетлиста + GND."""
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


def _models_of(cfg: dict) -> dict:
    """Реестр моделей из root_page или sheet YAML."""
    return (cfg.get("spice") or {}).get("models") or {}


def check_libs():
    """Проверить наличие всех .lib: spice.models корня + листов + helpers.

    Источники include:
      * main.yaml:spice.models[*].include — модели корня;
      * sheets/*.yaml:spice.models[*].include — модели листов;
      * REQUIRED_HELPERS — рукописные .lib, подключаемые
        сгенерированными <scenario>_mcu.sub.

    Путь к .lib — LIB_DIR, константа скрипта (spice/lib).
    """
    missing = []

    # 1. Модели корня
    root = load_main()
    for name, model in _models_of(root).items():
        if not isinstance(model, dict):
            continue
        inc = model.get("include")
        if inc and not os.path.exists(os.path.join(LIB_DIR, inc)):
            missing.append((f"main.yaml:{name}", os.path.join(LIB_DIR, inc)))

    # 2. Модели листов
    for yml in sorted(glob.glob(os.path.join(SHEETS_DIR, "*.yaml"))):
        if os.path.basename(yml) == "main.yaml":
            continue
        try:
            data = yaml.safe_load(open(yml, encoding="utf-8")) or {}
        except Exception:
            continue
        for name, model in _models_of(data).items():
            if not isinstance(model, dict):
                continue
            inc = model.get("include")
            if inc and not os.path.exists(os.path.join(LIB_DIR, inc)):
                missing.append((f"{os.path.basename(yml)}:{name}",
                                os.path.join(LIB_DIR, inc)))

    # 3. Рукописные helpers
    for name in REQUIRED_HELPERS:
        if not os.path.exists(os.path.join(LIB_DIR, name)):
            missing.append(("helpers", os.path.join(LIB_DIR, name)))

    if not missing:
        print("  Все .lib на месте в %s" % rel(LIB_DIR))
        return True, []
    for owner, path in missing:
        print("  WARN: %s: нет %s" % (owner, rel(path)))
    return False, missing


# ─────────────────────────────────────────────────────────────────────
# Очистка stale * _mcu.sub
# ─────────────────────────────────────────────────────────────────────

def clean_stale_mcu_subs(stems):
    """Удалить spice/<scenario>_mcu.sub от сценариев, которых больше нет.

    Файл называется по имени сценария (а не stem'а), поэтому его
    нельзя вывести из stem'ов: переименовали сценарий — старый
    *_mcu.sub остался и будет подхвачен .INCLUDE, если где-то
    в .cir сохранилась на него ссылка. Удаляем всё, что не
    соответствует сценариям, объявленным в YAML сейчас.
    """
    valid = set()
    for stem in stems:
        yml = os.path.join(SHEETS_DIR, stem + ".yaml")
        if not os.path.exists(yml):
            continue
        data = yaml.safe_load(open(yml, encoding="utf-8")) or {}
        for sc in (data.get("scenarios") or []):
            name = sc.get("name")
            if name:
                valid.add(f"{name}_mcu.sub")

    removed = 0
    for path in glob.glob(os.path.join(SPICE, "*_mcu.sub")):
        if os.path.basename(path) in valid:
            continue
        os.unlink(path)
        removed += 1
        print("  удалён stale: %s" % rel(path))
    return removed


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


_PINFUNC_SUFFIX = re.compile(r"_\d+$")


def _norm_pinfunc(fn):
    """Нормализует pinfunction из нетлиста KiCad 10.

    KiCad 10 в экспорте нетлиста добавляет к имени вывода суффикс
    '_<номер>': 'S_2', 'D_3', 'G_1', 'A_2', 'K_1', 'Pin_1_1'.
    В YAML пользователь пишет имя вывода без суффикса ('S', 'D', ...).

    Срезаем '_\\d+$', чтобы pinfunc_index и сравнение с YAML работали
    в одном пространстве имён.
    """
    if not fn:
        return fn
    return _PINFUNC_SUFFIX.sub("", fn)

def parse_netlist_nets(text):
    """{net_name: [(ref, pin, pinfunction_or_None), ...]}.

    pinfunction нормализуется: 'S_2' → 'S', 'D_3' → 'D',
    'Pin_1_1' → 'Pin_1' (KiCad 10 добавляет '_<pin>' к имени
    вывода при экспорте).

    Цепи с именем 'unconnected-*' (висящие пины) отбрасываются —
    они не участвуют в сверке с YAML, потому что в YAML не
    описываются.
    """
    nets = {}
    for m in re.finditer(
        r'\(net\s+\(code "\d+"\)\s+\(name "([^"]+)"\)(.*?)\n\t\t\)',
        text, re.S):
        name = m.group(1).lstrip('/')
        if name.startswith("unconnected-"):
            continue
        nodes = []
        for nm in re.finditer(
            r'\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)'
            r'(?:\s+\(pinfunction "([^"]*)"\))?',
            m.group(2),
        ):
            ref = nm.group(1)
            pin = nm.group(2)
            fn = _norm_pinfunc(nm.group(3) or None)
            nodes.append((ref, pin, fn))
        nets[name] = nodes
    return nets

def pinfunc_index(nl_nets):
    """{(ref, pin_number): pinfunction} — собран из нетлиста.

    Используется для перевода YAML-узла с `pin: 'N'` в канонический
    вид `(ref, 'fn', <pinfunction>)`, если у этого пина pinfunction
    известен. Так сравнение YAML и нетлиста идёт в одном пространстве.
    """
    idx = {}
    for nodes in nl_nets.values():
        for ref, pin, fn in nodes:
            if fn:
                idx[(ref, pin)] = fn
    return idx


def canonical_nl_nets(nl_nets):
    """{net_name: {(ref, kind, value)}} из нетлиста.

    kind = 'fn'  если pinfunction известен,
           'pin' иначе.
    """
    out = {}
    for name, nodes in nl_nets.items():
        keys = set()
        for ref, pin, fn in nodes:
            if fn:
                keys.add((ref, "fn", fn))
            else:
                keys.add((ref, "pin", pin))
        out[name] = keys
    return out

def check_netlist_vs_yaml(yml_path, netfile):
    sheet_yaml = yaml.safe_load(open(yml_path, encoding="utf-8")) or {}
    text = open(netfile, encoding="utf-8").read()

    nl_comps = parse_netlist_components(text)
    nl_nets_raw = parse_netlist_nets(text)
    pf_idx = pinfunc_index(nl_nets_raw)
    nl_nets = netlist_nets_canonical(nl_nets_raw)
    yml_nets_map = yaml_nets(sheet_yaml, pf_idx)

    yml_refs = yaml_component_refs(sheet_yaml)
    diffs = []

    nl_refs = {r for r, c in nl_comps.items()
               if not r.startswith("X_")
               and c.get("part") != "Hierarchical_Sheet"}
    if nl_refs - yml_refs:
        diffs.append("  Компоненты только в нетлисте: " +
                     ", ".join(sorted(nl_refs - yml_refs)))
    if yml_refs - nl_refs:
        diffs.append("  Компоненты только в YAML: " +
                     ", ".join(sorted(yml_refs - nl_refs)))

    # Фильтр X_* — по (ref) в кортеже
    def strip_x(s):
        return {k for k in s if not k[0].startswith("X_")}

    nl_names = set(nl_nets.keys())
    yml_names = set(yml_nets_map.keys())
    if nl_names - yml_names:
        diffs.append("  Сети только в нетлисте: " +
                     ", ".join(sorted(nl_names - yml_names)))
    if yml_names - nl_names:
        diffs.append("  Сети только в YAML: " +
                     ", ".join(sorted(yml_names - nl_names)))

    def fmt(key):
        ref, kind, val = key
        return f"{ref}.{kind}={val}"

    for name in sorted(nl_names & yml_names):
        nl_set = strip_x(nl_nets[name])
        yml_set = strip_x(yml_nets_map[name])
        if nl_set == yml_set:
            continue
        for k in sorted(nl_set - yml_set):
            diffs.append(f"  Сеть {name}: в YAML нет {fmt(k)}")
        for k in sorted(yml_set - nl_set):
            diffs.append(f"  Сеть {name}: в нетлисте нет {fmt(k)}")

    return diffs

def netlist_nets_canonical(nl_nets):
    out = {}
    for name, nodes in nl_nets.items():
        keys = set()
        for ref, pin, fn in nodes:
            if fn:
                keys.add((ref, "fn", fn))
            else:
                keys.add((ref, "pin", pin))
        out[name] = keys
    return out

def yaml_component_refs(sheet_yaml):
    refs = set()
    for ref, comp in (sheet_yaml.get("components") or {}).items():
        if comp.get("symbol") == "Core:Hierarchical_Sheet":
            continue
        if ref.startswith("X_"):
            continue
        refs.add(ref)
    return refs


def yaml_nets(sheet_yaml, pinfunc_idx=None):
    """{net_name: {(ref, kind, value)}} из YAML.

    Приоритет тот же, что в _bind_node: pin, иначе pinfunction.
    Если у узла стоит pin и для (ref, pin) известен pinfunction —
    ключ нормализуется в (ref, 'fn', pinfunction), чтобы сравнение
    с нетлистом было в одном пространстве.

    pinfunc_idx — {(ref, pin): pinfunction} из нетлиста.
    """
    idx = pinfunc_idx or {}
    out = {}
    for net_name, net in (sheet_yaml.get("nets") or {}).items():
        nodes = set()
        for n in net.get("nodes", []):
            if not isinstance(n, dict):
                continue
            ref = n.get("component")
            if not ref:
                continue
            if "pin" in n:
                pin = str(n["pin"])
                fn = idx.get((ref, pin))
                if fn:
                    nodes.add((ref, "fn", fn))
                else:
                    nodes.add((ref, "pin", pin))
            elif "pinfunction" in n:
                nodes.add((ref, "fn", n["pinfunction"]))
        out[net_name] = nodes
    return out


def check_netlist_vs_yaml(yml_path, netfile):
    """Сверка одного листа. yml_path уже известен — не ищем.

    YAML и нетлист нормализуются в одно пространство ключей:
        (ref, 'fn', pinfunction)  если pinfunction известен,
        (ref, 'pin', number)      иначе.

    Это позволяет сравнивать узлы, заданные в YAML как pin, с
    узлами в нетлисте, где есть pinfunction (и наоборот) — без
    ложных срабатываний на «в YAML нет Q2.2» при записи
    pinfunction: 'S'.
    """
    sheet_yaml = yaml.safe_load(open(yml_path, encoding="utf-8")) or {}
    text = open(netfile, encoding="utf-8").read()

    nl_comps = parse_netlist_components(text)
    nl_nets_raw = parse_netlist_nets(text)
    pf_idx = pinfunc_index(nl_nets_raw)
    nl_nets = canonical_nl_nets(nl_nets_raw)
    yml_nets_map = yaml_nets(sheet_yaml, pf_idx)

    yml_refs = yaml_component_refs(sheet_yaml)
    diffs = []

    nl_refs = {r for r, c in nl_comps.items()
               if not r.startswith("X_")
               and c.get("part") != "Hierarchical_Sheet"}
    if nl_refs - yml_refs:
        diffs.append("  Компоненты только в нетлисте: " +
                     ", ".join(sorted(nl_refs - yml_refs)))
    if yml_refs - nl_refs:
        diffs.append("  Компоненты только в YAML: " +
                     ", ".join(sorted(yml_refs - nl_refs)))

    def strip_x(s):
        return {k for k in s if not k[0].startswith("X_")}

    def fmt(key):
        ref, kind, val = key
        return f"{ref}.{kind}={val}"

    nl_names = set(nl_nets.keys())
    yml_names = set(yml_nets_map.keys())
    if nl_names - yml_names:
        diffs.append("  Сети только в нетлисте: " +
                     ", ".join(sorted(nl_names - yml_names)))
    if yml_names - nl_names:
        diffs.append("  Сети только в YAML: " +
                     ", ".join(sorted(yml_names - nl_names)))

    for name in sorted(nl_names & yml_names):
        nl_set = strip_x(nl_nets[name])
        yml_set = strip_x(yml_nets_map[name])
        if nl_set == yml_set:
            continue
        for k in sorted(nl_set - yml_set):
            diffs.append(f"  Сеть {name}: в YAML нет {fmt(k)}")
        for k in sorted(yml_set - nl_set):
            diffs.append(f"  Сеть {name}: в нетлисте нет {fmt(k)}")

    return diffs


# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────

def parse_args(argv):
    opts = {
        "gen": False, "run": False, "check": False,
        "net_check_only": False, "no_net_check": False,
        "sheet": None,
    }
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--gen":
            opts["gen"] = True
        elif a == "--run":
            opts["run"] = True
        elif a == "--check":
            opts["check"] = True
        elif a == "--net-check":
            opts["net_check_only"] = True
        elif a == "--no-net-check":
            opts["no_net_check"] = True
        elif a == "--sheet" and i + 1 < len(argv):
            opts["sheet"] = argv[i + 1]
            i += 1
        elif a.startswith("--sheet="):
            opts["sheet"] = a.split("=", 1)[1]
        i += 1
    return opts


def main():
    opts = parse_args(sys.argv[1:])

    os.makedirs(SPICE, exist_ok=True)
    os.makedirs(LIB_DIR, exist_ok=True)

    if opts["check"]:
        print("== Валидация библиотек ==")
        ok, _ = check_libs()
        return 0 if ok else 1

    # ─── Список stem'ов: выводится, а не хранится ──────────────────
    try:
        root = load_main()
        stems = derive_stems(root)
    except (ValueError, KeyError) as e:
        print("!! Ошибка конфигурации main.yaml: %s" % e)
        return 1

    if opts["sheet"]:
        if opts["sheet"] not in stems:
            print("!! Лист %r не найден среди stem'ов: %s"
                  % (opts["sheet"], ", ".join(stems)))
            return 1
        stems = [opts["sheet"]]

    # ─── Шаг 0: очистка stale MCU-моделей ──────────────────────────
    # Только когда мы собираемся генерировать (полный цикл или --gen).
    # В --run .cir уже собраны, и удалять файлы, на которые они
    # ссылаются, нельзя.
    if not opts["run"]:
        print("== 0. Очистка stale * _mcu.sub ==")
        removed = clean_stale_mcu_subs(stems)
        if removed == 0:
            print("  stale-файлов нет")

    # ─── Шаги 1-2 ──────────────────────────────────────────────────
    netfiles = {}
    if not opts["run"]:
        print("== 1. Экспорт нетлистов (kicad-cli) ==")
        for stem in stems:
            yml, sch, err = resolve_stem(stem)
            if err:
                print("  %-22s %s — пропускаю" % (stem, err))
                continue
            net = os.path.join(SPICE, stem + ".net")
            rc = run(["kicad-cli", "sch", "export", "netlist",
                      "--output", net, sch], label=stem)
            print("  %-22s sch=%-32s yaml=%-30s rc=%d -> %s"
                  % (stem, rel(sch), rel(yml), rc, rel(net)))
            if rc == 0:
                netfiles[stem] = net

        print("== 2. Генерация .sub/.cir (kicad_to_spice.py) ==")
        print("     (внутри — mcu_model.generate_scenario для MCU-сценариев)")
        for stem, net in netfiles.items():
            yml, _, err = resolve_stem(stem)
            if err:
                print("  %-22s %s — пропускаю" % (stem, err))
                continue
            ports = netlist_ports(net)
            cmd = [PY, os.path.join(PROJ, "kicad_to_spice.py"),
                   net, stem, "--yaml", yml] + ports
            rc = run(cmd, label=stem)
            print("  %-22s net=%-24s yaml=%-30s rc=%d (портов: %d)"
                  % (stem, rel(net), rel(yml), rc, len(ports)))

        if opts["gen"]:
            print("\nГотово: .sub/.cir сгенерированы "
                  "(прогон пропущен, используйте --run).")
            return 0

    # ─── Шаг 3: сверка — БЛОКИРУЮЩАЯ ───────────────────────────────
    if not opts["no_net_check"]:
        if opts["run"]:
            for stem in stems:
                net = os.path.join(SPICE, stem + ".net")
                if os.path.exists(net):
                    netfiles[stem] = net

        print("== 3. Сверка нетлистов и YAML ==")
        any_diff = False
        for stem in sorted(netfiles):
            yml, _, err = resolve_stem(stem)
            if err:
                print("  %-22s %s — сверка невозможна" % (stem, err))
                any_diff = True
                continue
            diffs = check_netlist_vs_yaml(yml, netfiles[stem])
            if not diffs:
                print("  %-22s yaml=%-30s OK" % (stem, rel(yml)))
                continue
            any_diff = True
            print("  %-22s yaml=%-30s РАСХОЖДЕНИЯ:" % (stem, rel(yml)))
            for d in diffs:
                print(d)
        if any_diff:
            print()
            print("!! Схема и YAML разошлись — прогон тестов отменён.")
            print("!! Исправьте схему, либо YAML, либо и то и другое.")
            print("!! Если уверены, что расхождения безобидны:")
            print("!!   python3 run_e2e.py --no-net-check  (для отладки)")
            return 1
        print("  Все листы согласованы.")

    if opts["net_check_only"]:
        return 0

    # ─── Шаг 4 ─────────────────────────────────────────────────────
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