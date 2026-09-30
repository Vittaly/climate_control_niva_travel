#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_e2e.py — сквозной тестовый прогон аналоговой части через Ngspice.

Модель идентификации листов:
  * Первоисточник — sheets/<stem>.yaml. Stem = имя файла без .yaml.
  * Схема листа   — <stem>.kicad_sch (в out/ или в корне проекта).
  * Компонент в корневом YAML — X_<STEM_UPPER> (одиночный лист)
                                X_<STEM_UPPER>_<INST> (мульти-инстанс).
  * value_sch у X_* — единственная связь компонента со схемой.
  * Список листов к прогону НЕ хранится отдельно: он выводится как
    {X_*, встречающиеся в nets} ∪ standalone_sheets ∪ {ROOT_STEM}.
  * Stem корня совпадает с именем проекта KiCad (и .kicad_sch):
    climate_control_niva_travel. Имя файла .kicad_sch менять нельзя.

Реестр моделей:
  * <ROOT_STEM>.yaml:spice.models — модели корневой страницы и общие.
  * sheets/<stem>.yaml:spice.models — модели компонентов этого листа.
  * Каждая модель ссылается на .lib в spice/lib через include.
  * component_types[type].spice.model → имя записи в реестре.

MCU-модель:
  * Электрика кремния — spice/lib/stm32g071rb_helpers.lib.
  * Per-scenario модель МК — spice/<scenario>_mcu.sub, генерируется
    модулем mcu_model.py. Вызов — из kicad_to_spice.build_cir.

Пути:
  * PROJ      — корень проекта.
  * MAIN_YAML — sheets/<ROOT_STEM>.yaml.
  * LIB_DIR   — spice/lib, константа.
  * OUT_DIR   — out/, куда Project.save() пишет сгенерированные схемы.

Сверка схемы и YAML:

  Перед сверкой имена компонентов в нетлисте нормализуются в
  YAML-пространство. Причины:
    * Multi-instance: kicad-cli при экспорте .kicad_sch, на который
      ссылаются несколько X_*, подставляет refdes одного из
      инстансов (наблюдение — последнего по порядку в instances).
      YAML листа описывает канонические refdes (первого инстанса).
    * Standalone-экспорт .kicad_sch не различает, от какого
      родителя он «пришёл»; top-level Reference игнорируется,
      когда есть блок (instances ...).

  Карта нормализации строится ПО ФАКТИЧЕСКОМУ .kicad_sch, который
  экспортировался (build_reverse_refdes_maps_from_sch):
    * для каждого символа читается top-level
      (property "Reference" "X") и все (reference "Y") из
      (instances ...);
    * получается {Y: X} — отображение instance_ref → top_ref;
    * к нетлисту применяется замена refdes до сверки с YAML.

  Это работает независимо от того, какой именно инстанс выбрал
  kicad-cli, и не зависит от того, совпадает ли .kicad_sch с
  текущим YAML. Если схему правили в KiCad GUI и refdes разошлись
  с YAML — расхождение отразится как «Компоненты только в
  нетлисте / только в YAML», что и требуется.

  3a. Per-file сверка листьев — для каждого stem, чей YAML НЕ
      содержит вложенных X_*. kicad-cli при экспорте такого
      .kicad_sch нечего схлопывать, нетлист соответствует YAML
      после нормализации refdes.

  3b. Плоская сверка корневой схемы — для листов с вложенными
      X_*. Строит ожидаемую карту сетей из графа Project
      (net_map.build_from_project) и сравнивает с плоским
      нетлистом kicad-cli по РАЗБИЕНИЮ множества пинов — без
      имён сетей. Имена в плоском нетлисте нестабильны (KiCad
      переименовывает VCC_12V → /X_FOO/VCC_12V), классы
      эквивалентности пинов — стабильны.

Шаги:
  0. Очистка stale * _mcu.sub.
  1. Экспорт per-file нетлистов (kicad-cli).
  2. Генерация .sub/.cir (kicad_to_spice.py) из нетлиста + YAML.
  3. Сверка — БЛОКИРУЮЩИЙ ШАГ (3a per-file + 3b плоская).
  4. Эмулятор Ngspice (run_tests.py) — только если шаг 3 прошёл.

Запуск:
    python3 run_e2e.py                       # полный цикл
    python3 run_e2e.py --gen                 # только экспорт + генерация
    python3 run_e2e.py --run                 # только прогон (3 + 4)
    python3 run_e2e.py --check               # валидация .lib и helpers
    python3 run_e2e.py --net-check           # только сверка (3)
    python3 run_e2e.py --no-net-check        # ОПАСНО: пропустить сверку
    python3 run_e2e.py --sheet power_supply  # только один stem
    python3 run_e2e.py --sheet climate_control_niva_travel   # корень

Код возврата: 0 если все PASS. Иначе:
  * 1 — расхождение YAML и схемы (или ошибка конфигурации);
  * N — число провалов тестов (если сверка прошла, но тесты упали).
"""
import glob
import os
import re
import subprocess
import sys
import yaml
import contextlib, io

_SUPPRESS = (
    "pins_unbound count=",
    "pin_unbound des=",
    "библиотечный orientation=",
)

def _emit_stream(stream, text, label=None):
    tag = f"[{label}] " if label else ""
    for line in text.splitlines():
        if any(p in line for p in _SUPPRESS):
            continue
        low = line.lower()
        if "warning" in low:
            stream.write(f"{tag}WARN: {line}\n")
        elif "error" in low:
            stream.write(f"{tag}ERROR: {line}\n")
        else:
            stream.write(f"{tag}{line}\n")

def _call_captured(fn, *args, label=None):
    """Вызвать fn(*args) in-process, перехватив stdout/stderr,
    и пропустить вывод через тот же emit(), что и run().

    Возвращает (result, error). Если fn выбросил — error непуст,
    result=None.
    """
    buf_out, buf_err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(buf_out), \
             contextlib.redirect_stderr(buf_err):
            result = fn(*args)
    except Exception as e:
        # вывод до исключения всё равно пропускаем через emit
        _emit_stream(sys.stdout, buf_out.getvalue(), label)
        _emit_stream(sys.stderr, buf_err.getvalue(), label)
        return None, e
    _emit_stream(sys.stdout, buf_out.getvalue(), label)
    _emit_stream(sys.stderr, buf_err.getvalue(), label)
    return result, None

PROJ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJ, "make_scr"))
from component import _norm_pin_name


SHEETS_DIR = os.path.join(PROJ, "sheets")
SPICE = os.path.join(PROJ, "spice")
LIB_DIR = os.path.join(SPICE, "lib")
OUT_DIR = os.path.join(PROJ, "out")
PY = sys.executable


# ─── Корневая страница ──────────────────────────────────────────────
ROOT_STEM = "climate_control_niva_travel"
MAIN_YAML = os.path.join(SHEETS_DIR, ROOT_STEM + ".yaml")

# Рукописные библиотеки, обязательные к наличию независимо от того,
# упомянуты ли они в spice.models.
REQUIRED_HELPERS = (
    "stm32g071rb_helpers.lib",
)


_PINFUNC_SUFFIX = re.compile(r"_\d+$")


def _norm_pinfunc(fn):
    """Нормализация pinfunction из нетлиста KiCad.

    KiCad 10 добавляет '_<номер>' (срезаем). Затем применяем ту же
    нормализацию, что и component.pin_by_name: '/', '-', '[', '('.
    Так нетлист и YAML попадают в одно пространство имён.
    """
    if not fn:
        return fn
    fn = _PINFUNC_SUFFIX.sub("", fn)
    return _norm_pin_name(fn)


def run(cmd, label=None):
    """Запустить процесс. Каждая строка stdout/stderr — с меткой [label]."""
    r = subprocess.run(cmd, cwd=PROJ, capture_output=True, text=True)
    tag = f"[{label}] " if label else ""



    

    if r.stdout:
        _emit_stream(sys.stdout, r.stdout)
    if r.stderr:
        _emit_stream(sys.stderr, r.stderr)
    return r.returncode


def load_main():
    return yaml.safe_load(open(MAIN_YAML, encoding="utf-8"))["root_page"]


def rel(p):
    return os.path.relpath(p, PROJ) if p else "—"


# ─────────────────────────────────────────────────────────────────────
# Резолвер: stem → (yaml, kicad_sch)
# ─────────────────────────────────────────────────────────────────────

def derive_stems(root):
    """Набор stem'ов к прогону — выводится, а не хранится.

    Всегда включает ROOT_STEM.
    Иерархические: X_*, встречающиеся в nets, → basename(value_sch).
    Standalone:    <ROOT_STEM>.yaml:standalone_sheets.
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

    stems = {ROOT_STEM}
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
    """stem → (yaml_path, sch_path, error|None).

    Приоритет поиска .kicad_sch: out/ (свежий) → PROJ → SHEETS_DIR.
    """
    if stem == ROOT_STEM:
        if not os.path.exists(MAIN_YAML):
            return MAIN_YAML, None, f"нет {rel(MAIN_YAML)}"
        try:
            root = load_main()
        except Exception as e:
            return MAIN_YAML, None, f"не удалось прочитать {rel(MAIN_YAML)}: {e}"
        sch_name = root.get("file")
        if not sch_name:
            return MAIN_YAML, None, "root_page.file не задан в YAML"
        for base in (OUT_DIR, PROJ):
            sch = os.path.join(base, sch_name)
            if os.path.exists(sch):
                return MAIN_YAML, sch, None
        return MAIN_YAML, None, f"нет {sch_name} (ни в out/, ни в корне)"

    yml = os.path.join(SHEETS_DIR, stem + ".yaml")
    if not os.path.exists(yml):
        return None, None, f"нет {rel(yml)}"

    for sch in (
        os.path.join(OUT_DIR, stem + ".kicad_sch"),
        os.path.join(PROJ, stem + ".kicad_sch"),
        os.path.join(SHEETS_DIR, stem + ".kicad_sch"),
    ):
        if os.path.exists(sch):
            return yml, sch, None
    return yml, None, f"нет {stem}.kicad_sch"


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
    return (cfg.get("spice") or {}).get("models") or {}


def check_libs():
    """Проверить наличие всех .lib: spice.models корня + листов + helpers."""
    missing = []
    root_yaml_name = os.path.basename(MAIN_YAML)

    root = load_main()
    for name, model in _models_of(root).items():
        if not isinstance(model, dict):
            continue
        inc = model.get("include")
        if inc and not os.path.exists(os.path.join(LIB_DIR, inc)):
            missing.append((f"{root_yaml_name}:{name}",
                            os.path.join(LIB_DIR, inc)))

    for yml in sorted(glob.glob(os.path.join(SHEETS_DIR, "*.yaml"))):
        if os.path.basename(yml) == root_yaml_name:
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

def _sheet_scenarios(stem):
    if stem == ROOT_STEM:
        yml = MAIN_YAML
    else:
        yml = os.path.join(SHEETS_DIR, stem + ".yaml")
    if not os.path.exists(yml):
        return []
    try:
        data = yaml.safe_load(open(yml, encoding="utf-8")) or {}
    except Exception:
        return []
    if stem == ROOT_STEM and "root_page" in data:
        data = data.get("root_page") or {}
    return data.get("scenarios") or []


def clean_stale_mcu_subs(stems):
    """Удалить spice/<scenario>_mcu.sub от сценариев, которых больше нет."""
    valid = set()
    for stem in stems:
        for sc in _sheet_scenarios(stem):
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
# Карта нормализации refdes — из фактического .kicad_sch
# ─────────────────────────────────────────────────────────────────────

def build_reverse_refdes_maps_from_sch(sch_path: str) -> dict[str, str]:
    """{instance_ref: top_ref} для одного .kicad_sch.

    Читает файл .kicad_sch. Для каждого символа-экземпляра
    (symbol (lib_id "...") ...) находит top-level
    (property "Reference" "X") и все (reference "Y") из блока
    (instances ...). Возвращает {Y: X} для каждого Y.

    Смысл: kicad-cli при standalone-экспорте .kicad_sch, у которого
    в символе есть блок (instances ...), подставляет refdes одного
    из инстансов (наблюдение: последнего в блоке). top-level
    Reference — то, что записано в файле как «каноническое» имя
    символа. Сверка приводит нетлист в это пространство.

    Работает по данным файла, а не по данным YAML: если схему
    правили в KiCad GUI и refdes разошлись с YAML — карта всё равно
    отражает реальность в файле. Расхождение с YAML тогда видно
    отдельно как «Компоненты только в нетлисте / только в YAML».
    """
    if not sch_path or not os.path.exists(sch_path):
        return {}
    try:
        text = open(sch_path, encoding="utf-8").read()
    except OSError:
        return {}

    out: dict[str, str] = {}

    # Символы-экземпляры начинаются с (symbol (lib_id "...") ...
    # Определения в (lib_symbols ...) начинаются с (symbol "NAME" ...)
    # без lib_id — их не трогаем.
    for m in re.finditer(
        r'\(symbol\s+\(lib_id\s+"[^"]+"\)(.*?)(?=\(symbol\s+\(lib_id|$)',
        text, re.S,
    ):
        block = m.group(1)

        ref_m = re.search(
            r'\(property\s+"Reference"\s+"([^"]+)"', block,
        )
        if not ref_m:
            continue
        top = ref_m.group(1)

        for inst_ref in re.findall(
            r'\(path\s+"[^"]+"\s*\(reference\s+"([^"]+)"\)',
            block,
        ):
            out.setdefault(inst_ref, top)

    return out


# ─────────────────────────────────────────────────────────────────────
# Разбор нетлиста
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
    """{net_name: [(ref, pin, pinfunction_or_None), ...]}.

    pinfunction нормализуется ('S_2' → 'S').
    Цепи 'unconnected-*' отбрасываются.
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
    """{(ref, pin_number): pinfunction} — собран из нетлиста."""
    idx = {}
    for nodes in nl_nets.values():
        for ref, pin, fn in nodes:
            if fn:
                idx[(ref, pin)] = fn
    return idx


def netlist_nets_canonical(nl_nets):
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
    ключ нормализуется в (ref, 'fn', pinfunction).
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


# ─────────────────────────────────────────────────────────────────────
# Сверка нетлиста и YAML (один лист)
# ─────────────────────────────────────────────────────────────────────

def _unwrap_root(sheet_yaml_raw):
    """Если в YAML есть root_page — это корневая страница."""
    if isinstance(sheet_yaml_raw, dict) and "root_page" in sheet_yaml_raw:
        return (sheet_yaml_raw.get("root_page") or {}, True)
    return (sheet_yaml_raw, False)


def check_netlist_vs_yaml(yml_path, netfile, is_root=None, reverse_map=None):
    """Сверка одного листа.

    YAML и нетлист нормализуются в одно пространство ключей:
        (ref, 'fn', pinfunction)  если pinfunction известен,
        (ref, 'pin', number)      иначе.

    reverse_map — {instance_ref: top_ref}, применяется к refdes
    нетлиста перед сверкой. Для multi-instance листьев: kicad-cli
    подставляет refdes одного из инстансов, а YAML описывает
    канонические. Карта строится по .kicad_sch (см.
    build_reverse_refdes_maps_from_sch), а не по YAML — нормализация
    отражает реальность в файле.

    Для корневой страницы (is_root=True) проверка асимметрична:
    YAML ⊆ нетлист. Плоский нетлист корня содержит компоненты всех
    подлистов; требовать обратного включения нельзя. Плоская сверка
    через net_map (шаг 3b) даёт полную картину по разбиению сетей.
    """
    sheet_yaml_raw = yaml.safe_load(open(yml_path, encoding="utf-8")) or {}
    sheet_yaml, auto_root = _unwrap_root(sheet_yaml_raw)
    if is_root is None:
        is_root = auto_root

    text = open(netfile, encoding="utf-8").read()
    nl_comps = parse_netlist_components(text)
    nl_nets_raw = parse_netlist_nets(text)

    # Нормализация refdes нетлиста в пространство файла .kicad_sch.
    if reverse_map:
        def _m(r):
            return reverse_map.get(r, r)

        nl_comps = {_m(r): c for r, c in nl_comps.items()}
        nl_nets_raw = {
            net: [(_m(r), pin, fn) for r, pin, fn in nodes]
            for net, nodes in nl_nets_raw.items()
        }

    pf_idx = pinfunc_index(nl_nets_raw)
    nl_nets = netlist_nets_canonical(nl_nets_raw)
    yml_nets_map = yaml_nets(sheet_yaml, pf_idx)
    yml_refs = yaml_component_refs(sheet_yaml)

    diffs = []

    nl_refs = {r for r, c in nl_comps.items()
               if not r.startswith("X_")
               and c.get("part") != "Hierarchical_Sheet"}

    if is_root:
        if yml_refs - nl_refs:
            diffs.append(
                "  Компоненты в YAML, отсутствующие в нетлисте: " +
                ", ".join(sorted(yml_refs - nl_refs)))
    else:
        if nl_refs - yml_refs:
            diffs.append("  Компоненты только в нетлисте: " +
                         ", ".join(sorted(nl_refs - yml_refs)))
        if yml_refs - nl_refs:
            diffs.append("  Компоненты только в YAML: " +
                         ", ".join(sorted(yml_refs - nl_refs)))

    def fmt(key):
        ref, kind, val = key
        return f"{ref}.{kind}={val}"

    nl_names = set(nl_nets.keys())
    yml_names = set(yml_nets_map.keys())

    if is_root:
        if yml_names - nl_names:
            diffs.append(
                "  Сети в YAML, отсутствующие в нетлисте: " +
                ", ".join(sorted(yml_names - nl_names)))
    else:
        if nl_names - yml_names:
            diffs.append("  Сети только в нетлисте: " +
                         ", ".join(sorted(nl_names - yml_names)))
        if yml_names - nl_names:
            diffs.append("  Сети только в YAML: " +
                         ", ".join(sorted(yml_names - nl_names)))

    for name in sorted(nl_names & yml_names):
        nl_set = nl_nets[name]
        yml_set = yml_nets_map[name]
        if is_root:
            for k in sorted(yml_set - nl_set):
                diffs.append(f"  Сеть {name}: в нетлисте нет {fmt(k)}")
        else:
            if nl_set == yml_set:
                continue
            for k in sorted(nl_set - yml_set):
                diffs.append(f"  Сеть {name}: в YAML нет {fmt(k)}")
            for k in sorted(yml_set - nl_set):
                diffs.append(f"  Сеть {name}: в нетлисте нет {fmt(k)}")

    return diffs


# ─────────────────────────────────────────────────────────────────────
# Применимость per-file сверки
# ─────────────────────────────────────────────────────────────────────

def sheet_has_children(stem: str) -> bool:
    """Есть ли в листе X_* (значит, это не лист дерева)."""
    yml = os.path.join(SHEETS_DIR, stem + ".yaml")
    if not os.path.exists(yml):
        return False
    try:
        data = yaml.safe_load(open(yml, encoding="utf-8")) or {}
    except Exception:
        return False

    # Корневой YAML обёрнут в root_page:. Разворачиваем перед
    # чтением components, иначе для корня получим пусто и он
    # ошибочно попадёт в per-file сверку.
    if isinstance(data, dict) and "root_page" in data:
        data = data.get("root_page") or {}

    for cdef in (data.get("components") or {}).values():
        if cdef.get("symbol") == "Core:Hierarchical_Sheet":
            return True
    return False


def per_file_applicable(stem: str) -> tuple[bool, str]:
    """Можно ли проверять stem автономным нетлистом.

    Нельзя только для узлов с вложенными X_*: kicad-cli схлопнет
    поддерево, и нетлист перестанет соответствовать YAML листа.
    Multi-instance не мешает — refdes нормализуются через карту из
    фактического .kicad_sch.
    """
    if sheet_has_children(stem):
        return False, "есть вложенные X_*"
    return True, ""


# ─────────────────────────────────────────────────────────────────────
# Плоская сверка корня
# ─────────────────────────────────────────────────────────────────────

def run_flat_check():
    """Плоская сверка корневой схемы.

    Строит ожидаемую карту сетей из графа YAML
    (net_map.build_from_project) и сравнивает с плоским нетлистом
    kicad-cli. Сверка идёт по РАЗБИЕНИЮ множества пинов — без имён
    сетей; KiCad переименовывает сети, но классы эквивалентности
    пинов сохраняет.

    Project загружается здесь же: он нужен только для этой сверки,
    и per-file (3a) его не использует.

    Возвращает (ok: bool, diffs: list[str], error: str | None).
    """
    try:
        from project import Project, ProjectLoadError
        from net_map import (
            build_from_project, diff_against_kicad,
            parse_kicad_netlist_to_pinrefs,
        )
    except ImportError as e:
        return False, [], f"не удалось импортировать net_map/project: {e}"

    try:
        _buf = io.StringIO()
        with contextlib.redirect_stdout(_buf), \
            contextlib.redirect_stderr(_buf):
            proj = Project(MAIN_YAML).load()
            _emit_stream(sys.stdout, _buf.getvalue(), label="root-flat")
    except ProjectLoadError as e:
        _emit_stream(sys.stdout, _buf.getvalue(), label="root-flat")
        return False, [], f"Project.load() упал: {e}"
    except Exception as e:
        _emit_stream(sys.stdout, _buf.getvalue(), label="root-flat")
        return False, [], f"Project.load() упал неожиданно: {e}"

    try:
        _buf = io.StringIO()
        with contextlib.redirect_stdout(_buf), \
            contextlib.redirect_stderr(_buf):
            expected = build_from_project(proj)
        _emit_stream(sys.stdout, _buf.getvalue(), label="root-flat")
    except Exception as e:
        _emit_stream(sys.stdout, _buf.getvalue(), label="root-flat")
        return False, [], f"build_from_project упал: {e}"

    root_yaml = load_main()
    root_file = root_yaml.get("file") or (ROOT_STEM + ".kicad_sch")

    root_sch = None
    for base in (OUT_DIR, PROJ):
        cand = os.path.join(base, root_file)
        if os.path.exists(cand):
            root_sch = cand
            break
    if root_sch is None:
        return False, [], f"нет {root_file} (ни в out/, ни в корне)"

    flat_net = os.path.join(SPICE, ROOT_STEM + "_flat.net")
    rc = run(["kicad-cli", "sch", "export", "netlist",
              "--output", flat_net, root_sch], label="root-flat")
    if rc != 0:
        return False, [], f"kicad-cli вернул {rc}"
    if not os.path.exists(flat_net):
        return False, [], f"нет {rel(flat_net)} после экспорта"

    try:
        actual = parse_kicad_netlist_to_pinrefs(flat_net)
    except Exception as e:
        return False, [], f"не разобрал плоский нетлист: {e}"

    diffs = diff_against_kicad(expected, actual)
    return (not diffs), diffs, None


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

    try:
        root = load_main()
        stems = derive_stems(root)
    except (ValueError, KeyError) as e:
        print("!! Ошибка конфигурации %s: %s"
              % (os.path.basename(MAIN_YAML), e))
        return 1

    if opts["sheet"]:
        if opts["sheet"] not in stems:
            print("!! Лист %r не найден среди stem'ов: %s"
                  % (opts["sheet"], ", ".join(stems)))
            return 1
        stems = [opts["sheet"]]

    # ─── Шаг 0: очистка stale MCU-моделей ──────────────────────────
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
                print("  %-32s %s — пропускаю" % (stem, err))
                continue
            net = os.path.join(SPICE, stem + ".net")
            rc = run(["kicad-cli", "sch", "export", "netlist",
                      "--output", net, sch], label=stem)
            print("  %-32s sch=%-40s yaml=%-40s rc=%d -> %s"
                  % (stem, rel(sch), rel(yml), rc, rel(net)))
            if rc == 0:
                netfiles[stem] = net

        print("== 2. Генерация .sub/.cir (kicad_to_spice.py) ==")
        print("     (внутри — mcu_model.generate_scenario для MCU-сценариев)")
        for stem, net in netfiles.items():
            yml, sch, err = resolve_stem(stem)   # ← sch больше не отбрасываем
            if err:
                print("  %-32s %s — пропускаю" % (stem, err))
                continue
            ports = netlist_ports(net)
            cmd = [PY, os.path.join(PROJ, "kicad_to_spice.py"),
                   net, stem, "--yaml", yml, "--sch", sch] + ports
            rc = run(cmd, label=stem)
            print("  %-32s net=%-28s yaml=%-40s rc=%d (портов: %d)"
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

        print("== 3. Сверка YAML и схем ==")

        any_diff = False

        # ── 3a. Per-file сверка листьев ──
        print("  -- 3a. Per-file сверка листьев --")
        skipped: list[tuple[str, str]] = []
        checked = 0
        for stem in sorted(stems):
            applicable, reason = per_file_applicable(stem)
            if not applicable:
                skipped.append((stem, reason))
                continue

            yml, sch, err = resolve_stem(stem)
            if err:
                print("    %-30s %s — сверка невозможна" % (stem, err))
                any_diff = True
                continue
            net = netfiles.get(stem)
            if not net:
                print("    %-30s нет нетлиста — сверка невозможна" % stem)
                any_diff = True
                continue

            # Карта нормализации строится по .kicad_sch, который
            # экспортировался. Не по YAML и не по Project — по факту
            # файла на диске.
            reverse_map = build_reverse_refdes_maps_from_sch(sch)

            diffs = check_netlist_vs_yaml(
                yml, net, is_root=False, reverse_map=reverse_map,
            )
            checked += 1
            if not diffs:
                print("    %-30s OK" % stem)
            else:
                any_diff = True
                print("    %-30s РАСХОЖДЕНИЯ:" % stem)
                for d in diffs:
                    print(d)

        if skipped:
            print("    Пропущены (покрыты плоской сверкой корня):")
            for stem, reason in skipped:
                print("      %-30s %s" % (stem, reason))
        if checked == 0 and not skipped:
            print("    нет листьев для per-file сверки")

        # ── 3b. Плоская сверка корня ──
        # Запускается при полном прогоне или при явном --sheet ROOT_STEM.
        do_flat_check = (
            opts["sheet"] is None or opts["sheet"] == ROOT_STEM
        )
        if do_flat_check:
            print("  -- 3b. Плоская сверка корневой схемы --")
            ok, diffs, error = run_flat_check()
            if error is not None:
                print("    Сверка не выполнена: %s" % error)
                any_diff = True
            elif not ok:
                any_diff = True
                print("    РАСХОЖДЕНИЯ (по разбиению пинов):")
                for d in diffs:
                    print(d)
            else:
                print("    OK")

        if any_diff:
            print()
            print("!! Схема и YAML разошлись — прогон тестов отменён.")
            print("!! Исправьте схему, либо YAML, либо и то и другое.")
            print("!! Для отладки можно пропустить сверку:")
            print("!!   python3 run_e2e.py --no-net-check")
            return 1

        print("  Все сверки пройдены.")

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