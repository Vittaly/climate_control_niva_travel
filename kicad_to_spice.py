#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kicad_to_spice.py — генерация Ngspice-тестов из нетлиста KiCad.

Источник данных (единственный):
  * нетлист KiCad (pin-маппинг, состав компонентов, Sim.* properties);
  * <stem>.yaml → scenarios (deck, checks, analysis, overrides);
  * корневой YAML (<ROOT_STEM>.yaml) → nets, component_types
    (нужны только для MCU: auto_ports и список портов).

SPICE-модели компонентов БЕРУТСЯ ИЗ НЕТЛИСТА — как properties
символа, которые записал writer при генерации .kicad_sch.
kicad-cli выгружает их двумя разными формами:

    (property
        (name "Sim.Device")
        (value "X"))

    (field
        (name "Sim.Device") "X")

Парсер нетлиста читает обе. Поля:

    Sim.Device   R/C/L/D/Q/M/X — ярус элемента в SPICE.
    Sim.Name     имя .subckt (для X-инстанса).
    Sim.Library  ${KIPRJMOD}/spice/lib/x.lib (для X-инстанса).
    Sim.Pins     pin=port, в порядке портов .SUBCKT (для X).
    Sim.Params   R=10k / L=1u / IS=1e-5 N=1.04 / T=25 R25=10k (для R/C/L/D/Q/M/X).
    Sim.Model    имя .model-записи (для D/Q/M).

Синтаксис X-строк: ПОЗИЦИОННЫЙ (spice-стандарт).
    Ngspice принимает узлы X-инстанса только позиционно, в порядке
    портов из .SUBCKT:

        XU1 IN1 IN2 MOTOR_A MOTOR_B VCC_12V GND DRV8871

    Никаких 'port=node' — это расширение других симуляторов, не
    Ngspice. Порядок портов берётся из .SUBCKT <Name> в Sim.Library
    (файл .lib читается через _port_order_from_lib). Узлы —
    из Sim.Pins (pin=port) + net_of(ref, pin).

Параметры subckt:
    У X-компонента Sim.Params содержит параметры .SUBCKT в формате
    "name=default name2=default2 …" (объединение spice.params и
    required_params из YAML). В X-строке эти параметры передаются
    ОТСЫЛКАМИ на формальные параметры родительской субсхемы:
    "name={<ref>_<name>} name2={<ref>_<name2>}". Сами формальные
    параметры объявляются в header .subckt (см. build_subckt).
    Значения приходят из overrides сценария через X<stem>.
    Никакие конкретные значения в X-строке не пишутся — их место
    занимают отсылки; иначе Ngspice видит "0 formal but 1 actual params".

Что остаётся из YAML:
  * deck / checks / analysis / overrides в сценариях;
  * nets корня — для MCU (pinfunction U1 ↔ net_name);
  * component_types корня — только чтобы найти типы с auto_ports
    (STM32G071RBT6), для которых .subckt генерируется per-scenario
    через mcu_model.py.

Refdes-пространства (per-page vs project):
  .kicad_sch листа хранит ДВЕ системы имён:
    * (property "Reference" "X")      — YAML-канонические имена листа;
    * (instances … (reference "Y"))   — проектные имена в конкретных
                                        instance-путях.
  kicad-cli при per-file экспорте подставляет в нетлист одно из
  instances. Генератор .sub/.cir работает с YAML листа, поэтому
  refdes нетлиста приводится в YAML-пространство ЭТОЙ страницы —
  через --sch и build_reverse_refdes_maps_from_sch().

  Для корня карта вырождается в тождество. Механизм локален для
  per-page пути: это не «глобальная нормализация», а «перевод имён
  одной страницы в её собственное YAML-пространство».

Выходные файлы:
  * spice/<stem>.sub          — подсхема листа;
  * spice/<scenario>.cir      — по одному на scenarios[i];
  * spice/<scenario>_mcu.sub  — per-scenario модель МК (mcu_model.py).

Запуск:
    python3 kicad_to_spice.py <netlist.net> <stem> --yaml <path> \
            [--sch <path>] [port1 ... portN]

    --sch — путь к .kicad_sch, из которого экспортирован нетлист.
            Если задан — refdes нетлиста нормализуются в YAML-пространство
            страницы. Если не задан — refdes используются как есть.
"""
import os
import re
import sys
from pathlib import Path

import yaml

import mcu_model


# ─────────────────────────────────────────────────────────────────────
# Корневой YAML: имя проекта = stem <PROJ>/*.kicad_pro
# ─────────────────────────────────────────────────────────────────────

PROJ = os.path.dirname(os.path.abspath(__file__))
YAML_DIR = os.path.join(PROJ, "sheets")
LIB_DIR = os.path.join(PROJ, "spice", "lib")


def _detect_root_stem(root: Path) -> str:
    pro_files = sorted(root.glob("*.kicad_pro"))
    if not pro_files:
        raise FileNotFoundError(
            f"В {root} нет *.kicad_pro — не могу определить имя проекта."
        )
    if len(pro_files) > 1:
        names = ", ".join(p.name for p in pro_files)
        raise RuntimeError(
            f"В {root} несколько .kicad_pro ({names}); нужен ровно один."
        )
    return pro_files[0].stem


try:
    ROOT_STEM = _detect_root_stem(Path(PROJ))
except (FileNotFoundError, RuntimeError) as e:
    sys.exit(f"kicad_to_spice.py: {e}")

MAIN_YAML = os.path.join(YAML_DIR, f"{ROOT_STEM}.yaml")


# ─────────────────────────────────────────────────────────────────────
# Загрузка корневого YAML
# ─────────────────────────────────────────────────────────────────────

def load_main():
    doc = yaml.safe_load(open(MAIN_YAML, encoding="utf-8")) or {}
    if isinstance(doc, dict) and "root_page" in doc:
        return doc.get("root_page") or {}
    return doc


# ─────────────────────────────────────────────────────────────────────
# Per-page нормализация refdes: kicad-cli → YAML-пространство страницы
# ─────────────────────────────────────────────────────────────────────

def build_reverse_refdes_maps_from_sch(sch_path):
    """{instance_ref: top_ref} для одного .kicad_sch.

    Для каждого символа-экземпляра находит top-level Reference и все
    reference из (instances …). Возвращает {Y: X}.

    Для корня карта вырождается в тождество (top-level = instances =
    project refdes), поэтому вызов безопасен и не меняет поведение.
    """
    if not sch_path or not os.path.exists(sch_path):
        return {}
    try:
        text = open(sch_path, encoding="utf-8").read()
    except OSError:
        return {}

    out = {}
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


def _apply_reverse_map(comps, nets, rmap):
    """Привести refdes нетлиста в YAML-пространство страницы.

    rmap = {instance_ref: top_ref}. Если карта пуста — структуры
    возвращаются как есть. Узел, чей refdes не попал в карту,
    остаётся без изменений — данные не теряются.
    """
    if not rmap:
        return comps, nets

    comps2 = {rmap.get(r, r): c for r, c in comps.items()}
    nets2 = {}
    for name, nodes in nets.items():
        nets2[name] = [
            (rmap.get(r, r), pin, fn) for r, pin, fn in nodes
        ]
    return comps2, nets2


# ─────────────────────────────────────────────────────────────────────
# Помощники Sim.*
# ─────────────────────────────────────────────────────────────────────

def _parse_sim_pins(s: str):
    """'3=IN1 2=IN2 6=OUT1' → [('3','IN1'), ('2','IN2'), ('6','OUT1')].

    Порядок сохраняется как в строке: writer пишет Sim.Pins
    в порядке портов .SUBCKT, ngspice принимает X-инстанс
    позиционно. Сортировать нельзя.
    """
    out = []
    for tok in (s or "").split():
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        out.append((k.strip(), v.strip()))
    return out


_PORT_ORDER_CACHE = {}


def _port_order_from_lib(lib_path: str, subckt_name: str):
    """Порядок портов .SUBCKT <subckt_name> из .lib-файла.

    Читает файл, ищет строку:
        .SUBCKT <subckt_name> <p1> <p2> <p3> …
    и возвращает список портов [p1, p2, p3, …]. Хвост PARAMS: …
    отбрасывается. Кэш — файл в рамках прогона не меняется.

    Возвращает None, если файл недоступен или .SUBCKT не найден.
    """
    key = (lib_path, subckt_name)
    if key in _PORT_ORDER_CACHE:
        return _PORT_ORDER_CACHE[key]

    path = _expand_include(lib_path)
    if not path or not os.path.exists(path):
        _PORT_ORDER_CACHE[key] = None
        return None

    try:
        text = open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        _PORT_ORDER_CACHE[key] = None
        return None

    pat = re.compile(
        r'^\s*\.SUBCKT\s+' + re.escape(subckt_name) + r'\s+([^\n]+)',
        re.IGNORECASE | re.MULTILINE,
    )
    m = pat.search(text)
    if not m:
        _PORT_ORDER_CACHE[key] = None
        return None

    tail = m.group(1)
    if re.search(r'\bPARAMS:', tail, re.IGNORECASE):
        tail = re.split(r'\bPARAMS:', tail, maxsplit=1,
                        flags=re.IGNORECASE)[0]
    ports = tail.split()
    _PORT_ORDER_CACHE[key] = ports
    return ports


def _model_type_for(dev: str) -> str:
    """SPICE-тип для .model-директивы по Sim.Device.

    D  → D      (диод, стабилитрон)
    Z  → D      (зенер — тоже диод)
    Q  → NPN    (BJT; при PNP — надо явно задавать)
    M  → NMOS   (MOSFET)
    J  → NJF    (JFET)
    """
    return {
        "D": "D", "Z": "D",
        "Q": "NPN",
        "M": "NMOS",
        "J": "NJF",
    }.get(dev, "D")


def _expand_include(name: str) -> str:
    """Развернуть Sim.Library в путь для .include.

    ${KIPRJMOD}/spice/lib/x.lib → /path/to/PROJ/spice/lib/x.lib.
    Относительные имена без ${KIPRJMOD} трактуются как имена внутри
    spice/lib/. Абсолютные пути возвращаются как есть.
    """
    if not name:
        return ""
    if name.startswith("${KIPRJMOD}/"):
        rel = name[len("${KIPRJMOD}/"):]
        return os.path.join(PROJ, rel)
    if os.path.isabs(name):
        return name
    return os.path.join(LIB_DIR, name)


# ─────────────────────────────────────────────────────────────────────
# Парсинг нетлиста
# ─────────────────────────────────────────────────────────────────────

_PINFUNC_SUFFIX = re.compile(r"_\d+$")


def _norm_pinfunc(fn):
    if not fn:
        return fn
    return _PINFUNC_SUFFIX.sub("", fn)


def parse_netlist(text):
    """Возвращает (comps, nets).

    comps[ref] = {
        "value": str,          # top-level (value "...")
        "lib":   str,          # libsource.lib
        "part":  str,          # libsource.part
        "sim":   dict,         # все Sim.Xxx → value (property или field)
    }

    nets[name] = [(ref, pin, pinfunction_or_None), ...]

    Sim.* — источник SPICE-модели компонента. Пишет их writer
    в .kicad_sch; kicad-cli выгружает двумя формами:
        (property (name "Sim.Xxx") (value "Y"))
        (field (name "Sim.Xxx") "Y")
    Читаем обе; при совпадении property имеет приоритет.
    """
    comps = {}

    for m in re.finditer(
        r'\(comp\s+\(ref "([^"]+)"\)(.*?)\n\t\t\)',
        text, re.S,
    ):
        ref = m.group(1)
        block = m.group(2)

        vm = re.search(r'\(value\s+"([^"]*)"\)', block)
        value = vm.group(1) if vm else ""

        lm = re.search(
            r'\(libsource\s+\(lib\s+"([^"]+)"\)\s+\(part\s+"([^"]+)"\)',
            block,
        )
        lib = lm.group(1) if lm else ""
        part = lm.group(2) if lm else ""

        sim = {}

        # Формат 1: (property (name "Sim.Xxx") (value "Y"))
        for pm in re.finditer(
            r'\(property\s+\(name\s+"(Sim\.[^"]+)"\)\s+'
            r'\(value\s+"([^"]*)"\)',
            block,
        ):
            sim[pm.group(1)] = pm.group(2)

        # Формат 2: (field (name "Sim.Xxx") "Y")
        # kicad-cli выгружает так properties, добавленные через
        # add_properties(hidden=True). setdefault — property приоритетнее.
        for fm in re.finditer(
            r'\(field\s+\(name\s+"(Sim\.[^"]+)"\)\s+"([^"]*)"',
            block,
        ):
            sim.setdefault(fm.group(1), fm.group(2))

        comps[ref] = {
            "value": value,
            "lib": lib,
            "part": part,
            "sim": sim,
        }

    nets = {}
    for m in re.finditer(
        r'\(net\s+\(code "\d+"\)\s+\(name "([^"]+)"\)(.*?)\n\t\t\)',
        text, re.S,
    ):
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
    return comps, nets


def net_of(nets, ref, key, by="pin"):
    """Имя сети, на которой сидит пин (или pinfunction) компонента.

    Возвращает имя сети как есть, либо None.
    """
    for nm, nds in nets.items():
        for nd in nds:
            if nd[0] != ref:
                continue
            value = nd[1] if by == "pin" else (nd[2] if len(nd) > 2 else "")
            if value and value == key:
                return nm
    return None


def cname(nm):
    """Нормализация имени узла. GND → 'GND'; остальное без изменений."""
    return nm if nm else "GND"


def parse_val(v, ref="?"):
    """Разбор value из KiCad-нотации (10k, 1u, 100n) → SPICE.

    Используется как fallback для R/C/L/D/Q/M, когда Sim.Params
    в схеме не задан (компонент добавлен в KiCad GUI вручную, или
    старый .kicad_sch без Sim.*).
    """
    s = str(v).strip().replace(",", ".")
    s = re.sub(r"[А-Яа-яЁё].*$", "", s).strip()
    m = re.match(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*"
                 r"(meg|[GMkmunp])?", s)
    if not m or not m.group(1):
        raise ValueError(
            f"{ref}: value={v!r} не в KiCad-нотации (примеры: "
            f"'10k', '1u', '100n', '4k7')."
        )
    return m.group(1) + (m.group(2) or "")


# ─────────────────────────────────────────────────────────────────────
# Имя SPICE-элемента
# ─────────────────────────────────────────────────────────────────────

def _element_ref(prefix: str, ref: str) -> str:
    """X-префикс для X-инстанса и т.п.

    SPICE требует, чтобы имя элемента начиналось с буквы типа
    (R, C, L, D, Q, M, X). Если designator уже с этой буквы —
    оставляем как есть.
    """
    if ref and ref[0].upper() == prefix.upper():
        return ref
    return prefix + ref


# ─────────────────────────────────────────────────────────────────────
# MCU: модели, порты, stimulus — только для МК (auto_ports)
# ─────────────────────────────────────────────────────────────────────

def _mcu_model_names(main_cfg):
    """Имена subckt-моделей с auto_ports (объявленные в корневом YAML)."""
    found = set()
    for ctype in (main_cfg.get("component_types") or {}).values():
        sp = ctype.get("spice") or {}
        if sp.get("auto_ports"):
            name = sp.get("subckt") or sp.get("model")
            if name:
                found.add(name)
    for name, m in ((main_cfg.get("spice") or {}).get("models") or {}).items():
        if isinstance(m, dict) and m.get("auto_ports"):
            found.add(name)
    return found


def _mcu_instances(sc, main_cfg):
    """Подсхемы-MCU в deck сценария.

    Возвращает список body-словарей entry["subckt"] тех, чей
    model попал в _mcu_model_names. Для них generate_scenario
    делает свежий <scenario>_mcu.sub.
    """
    names = _mcu_model_names(main_cfg)
    result = []
    for entry in sc.get("deck", []):
        for kind, body in entry.items():
            if kind == "subckt" and body.get("model") in names:
                result.append(body)
    return result


def _mcu_sig_by_net(main_cfg: dict) -> dict:
    """{net_name → pinfunction} для узлов U1 в корневом YAML."""
    sig_by_net = {}
    for net_name, ndef in (main_cfg.get("nets") or {}).items():
        for n in ndef.get("nodes") or []:
            if not isinstance(n, dict):
                continue
            if n.get("component") != "U1":
                continue
            pf = n.get("pinfunction")
            if pf:
                sig_by_net[net_name] = pf
            break
    return sig_by_net


def _mcu_args(main_cfg, connect, ref="XU1"):
    """Аргументы X-строки для инстанса МК.

    Порядок — как в mcu_model.mcu_ports(main_cfg). Для каждого порта
    берём узел из connect: сначала по имени порта, потом по pinfunction.
    Не указанное — сам порт. GND → 0.
    """
    ports = mcu_model.mcu_ports(main_cfg)
    sig_by_net = _mcu_sig_by_net(main_cfg)
    valid_keys = set(ports) | {s for s in sig_by_net.values() if s}

    unknown = set(connect) - valid_keys
    if unknown:
        raise ValueError(
            f"{ref}: connect содержит неизвестные ключи "
            f"(нет ни среди портов МК, ни среди pinfunction U1): "
            f"{sorted(unknown)}"
        )

    args = []
    for net in ports:
        sig = sig_by_net.get(net)
        target = connect.get(net)
        if target is None and sig:
            target = connect.get(sig)
        if target is None:
            target = net
        if target == "GND":
            target = "0"
        args.append(str(target))
    return args


def _validate_mcu_state(sc):
    """Если в mcu_state есть pwm — analysis должен быть tran."""
    state = sc.get("mcu_state") or {}
    has_pwm = any(isinstance(v, dict) and "pwm" in v for v in state.values())
    if has_pwm and sc.get("analysis") != "tran":
        raise ValueError(
            f"scenario {sc.get('name')!r}: mcu_state содержит pwm, "
            f"но analysis={sc.get('analysis')!r} (требуется 'tran')"
        )


# ─────────────────────────────────────────────────────────────────────
# Генерация элементов .sub
# ─────────────────────────────────────────────────────────────────────

def _legacy_device(part: str):
    """Угадать Sim.Device по libsource.part, если Sim.Device пуст.

    Для компонентов, добавленных в KiCad GUI без Sim.* (legacy).
    """
    if part in ("R", "C", "L"):
        return part
    if part in ("D", "D_Schottky", "D_Zener", "LED"):
        return "D"
    if part in ("Q_NPN", "Q_PNP"):
        return "Q"
    if part in ("Q_NMOS", "Q_NMOS_GSD"):
        return "M"
    return None


def _param_tokens(params: str):
    """'T=25 R25=10k BETA=3435' → [('T','25'), ('R25','10k'), ('BETA','3435')].

    Параметры без '=' (объявлены, но дефолт пуст) возвращаются
    как (name, None).
    """
    out = []
    for tok in (params or "").split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out.append((k.strip(), v.strip()))
        else:
            out.append((tok.strip(), None))
    return out


def spice_el(ref, comp, nets):
    """SPICE-строка одного компонента.

    Источник — Sim.* properties из нетлиста (fallback на libsource.part
    для legacy). Разбор по Sim.Device:

        X       → X_<ref> <node1> <node2> … <Name> [<param refs>]
                  узлы позиционно, в порядке портов .SUBCKT <Name>;
                  узлы — из Sim.Pins (pin=port) + net_of(ref, pin).
                  Параметры — отсылки <name>={<ref>_<name>};
                  формальные параметры объявлены в header .subckt
                  (см. build_subckt), значения приходят из
                  X<stem> через overrides в .cir.
                  Sim.Library пуст → per-scenario модель (МК),
                  в .sub листа не пишем.

        R/C/L   → <ref> <node1> <node2> <value>
                  value — из Sim.Params (R=10k → 10k), fallback value.

        D / Z   → D<ref> <a> <k> <Model>
        Q       → Q<ref> <c> <b> <e> <Model>
        M       → M<ref> <d> <g> <s> <s> <Model>

        (пусто) → комментарий, компонент не моделируется
    """
    sim = comp.get("sim") or {}
    part = comp.get("part") or ""
    value = comp.get("value") or ""

    dev = sim.get("Sim.Device") or _legacy_device(part)
    if not dev:
        return f"* {ref}: {part} ({value}) — не моделируется"

    name = sim.get("Sim.Name")
    model = sim.get("Sim.Model") or ""
    params = (sim.get("Sim.Params") or "").strip()
    pins_str = (sim.get("Sim.Pins") or "").strip()

    # ─── X: .subckt ───
    if dev == "X":
        if not name:
            raise ValueError(f"{ref}: Sim.Device=X, но Sim.Name пуст")

        lib = (sim.get("Sim.Library") or "").strip()
        if not lib:
            # Per-scenario модель (МК): генерация в .cir через mcu_model.
            return (f"* {ref}: {name} — модель per-scenario "
                    f"(инстанс добавляется в .cir)")

        pins_list = _parse_sim_pins(pins_str)   # [(pin, port), …]
        if not pins_list:
            raise ValueError(
                f"{ref}: Sim.Device=X, но Sim.Pins пуст — "
                f"не могу подставить узлы"
            )

        # Порядок портов — из .SUBCKT <name> в lib.
        port_order = _port_order_from_lib(lib, name)

        # port → node
        port_to_node = {}
        for pin_num, port in pins_list:
            net = net_of(nets, ref, pin_num, by="pin")
            port_to_node[port] = cname(net) if net else "GND"

        if port_order:
            args = []
            for port in port_order:
                node = port_to_node.get(port)
                if node is None:
                    raise ValueError(
                        f"{ref}: порт {port!r} есть в .SUBCKT {name}, "
                        f"но не сопоставлен ни с одним пином в Sim.Pins "
                        f"({pins_str!r})"
                    )
                args.append(node)
        else:
            # .lib недоступен — используем порядок Sim.Pins как есть.
            args = [port_to_node[port] for _, port in pins_list]

        xref = _element_ref("X", ref)
        line = f'{xref} {" ".join(args)} {name}'

        # Параметры — отсылки на формальные параметры родительской
        # субсхемы: T={RT1_T} R25={RT1_R25} …
        # Формальные параметры объявлены в header .subckt (build_subckt),
        # значения подставлены снаружи через X<stem> (overrides в .cir).
        for pname, _pval in _param_tokens(params):
            line += f" {pname}={{{ref}_{pname}}}"
        return line

    # ─── .model: диод / стабилитрон ───
    if dev in ("D", "Z"):
        if not model:
            raise ValueError(
                f"{ref}: Sim.Device={dev}, но Sim.Model пуст. "
                f"Имя модели должно быть задано spice.model в "
                f"component_types[{part!r}] или выводиться из имени "
                f"типа (TYPE_XXX → XXX). value={value!r} как имя "
                f"модели не используется."
            )
        k = cname(net_of(nets, ref, "1", by="pin"))
        a = cname(net_of(nets, ref, "2", by="pin"))
        dref = _element_ref("D", ref)
        return f"{dref} {a} {k} {model}"

    # ─── .model: BJT ───
    if dev == "Q":
        if not model:
            raise ValueError(
                f"{ref}: Sim.Device=Q, но Sim.Model пуст."
            )
        c = cname(net_of(nets, ref, "C", by="pinfunction")
                  or net_of(nets, ref, "2", by="pin"))
        b = cname(net_of(nets, ref, "B", by="pinfunction")
                  or net_of(nets, ref, "1", by="pin"))
        e = cname(net_of(nets, ref, "E", by="pinfunction")
                  or net_of(nets, ref, "3", by="pin"))
        qref = _element_ref("Q", ref)
        return f"{qref} {c} {b} {e} {model}"

    # ─── .model: MOSFET ───
    if dev == "M":
        if not model:
            raise ValueError(
                f"{ref}: Sim.Device=M, но Sim.Model пуст."
            )
        d = cname(net_of(nets, ref, "D", by="pinfunction")
                  or net_of(nets, ref, "2", by="pin"))
        g = cname(net_of(nets, ref, "G", by="pinfunction")
                  or net_of(nets, ref, "1", by="pin"))
        s = cname(net_of(nets, ref, "S", by="pinfunction")
                  or net_of(nets, ref, "3", by="pin"))
        mref = _element_ref("M", ref)
        return f"{mref} {d} {g} {s} {s} {model}"

    # ─── R / C / L ───
    if dev in ("R", "C", "L"):
        p1 = cname(net_of(nets, ref, "1", by="pin"))
        p2 = cname(net_of(nets, ref, "2", by="pin"))
        if "=" in params:
            val = params.split("=", 1)[-1].strip()
        elif params:
            val = params
        else:
            val = parse_val(value, ref=ref)
        eref = _element_ref(dev, ref)
        return f"{eref} {p1} {p2} {val}"

    return f'* {ref}: {part} ({value}) — не моделируется'

def collect_model_defs_from_comps(comps):
    """Уникальные .model-директивы из Sim.* компонентов.

    Для каждого D/Z/Q/M с непустым Sim.Model собирается строка
    .model. Формат Sim.Params от component.py — "TYPE(params)":
    тип модели (NPN/PNP/NMOS/PMOS/D/VDMOS/…) уже в строке, взят
    из YAML model_def. Здесь тип НЕ перезаписывается: жёсткий
    _model_type_for превратил бы PNP в NPN.

    Возможные формы Sim.Params:

        "NPN(IS=1e-14 BF=200 VAF=100)"  ← тип + параметры (штатная)
        "IS=1e-14 BF=200 VAF=100"        ← только параметры (legacy,
                                           тип через _model_type_for)
        ""                                ← пусто (только .model NAME T())

    Уникальность по тексту строки — дубликаты не пишутся.
    """
    defs, seen = [], set()
    for _ref, comp in comps.items():
        sim = comp.get("sim") or {}
        part = comp.get("part") or ""

        dev = sim.get("Sim.Device") or _legacy_device(part)
        if not dev or dev in ("X", "R", "C", "L"):
            continue

        model = sim.get("Sim.Model") or ""
        if not model:
            continue

        params = (sim.get("Sim.Params") or "").strip()

        if params and "(" in params:
            # Уже "TYPE(params)" — как есть.
            # MMBT3906 → PNP(...), BSS138 → NMOS(...), SS54 → D(...).
            line = f".model {model} {params}"
        elif params:
            # Только параметры — тип из _model_type_for.
            mtype = _model_type_for(dev)
            line = f".model {model} {mtype}({params})"
        else:
            # Ничего нет — дефолтный тип с пустыми параметрами.
            mtype = _model_type_for(dev)
            line = f".model {model} {mtype}()"

        if line not in seen:
            defs.append(line)
            seen.add(line)
    return defs

def collect_includes_from_comps(comps, sc, sheet_yaml, main_cfg):
    """Файлы для .include.

    Источники:
      * Sim.Library у X-компонентов (X через Sim.*);
      * include: в deck сценария;
      * sheet_yaml.spice.includes (legacy);
      * component_types[type].spice.include (legacy — subckt через
        component_types, например mc78m05, ntc_10k_3435);
      * main_cfg.component_types[type].spice.include (legacy, корневой);
      * sheet_yaml.spice.models[*].include (legacy);
      * main_cfg.spice.models[*].include (legacy, корневой).
    """
    includes, seen = [], set()

    def add(name):
        if not name:
            return
        p = _expand_include(name)
        if not p or p in seen:
            return
        includes.append(p)
        seen.add(p)

    # 1. Sim.Library у X-компонентов
    for _ref, comp in comps.items():
        sim = comp.get("sim") or {}
        if sim.get("Sim.Device") == "X":
            add(sim.get("Sim.Library"))

    # 2. deck сценария
    for entry in (sc.get("deck") or []):
        for _kind, body in entry.items():
            add(body.get("include"))

    # 3. sheet_yaml.spice.includes
    for inc in (sheet_yaml.get("spice") or {}).get("includes", []) or []:
        add(inc)

    # 4. component_types[type].spice.include (лист)
    for _tn, ctype in (sheet_yaml.get("component_types") or {}).items():
        add((ctype.get("spice") or {}).get("include"))

    # 4b. component_types[type].spice.include (корневой)
    for _tn, ctype in (main_cfg.get("component_types") or {}).items():
        add((ctype.get("spice") or {}).get("include"))

    # 5. sheet_yaml.spice.models[*].include
    for _n, m in _sheet_models(sheet_yaml).items():
        if isinstance(m, dict):
            add(m.get("include"))

    # 6. main_cfg.spice.models[*].include
    for _n, m in _root_models(main_cfg).items():
        if isinstance(m, dict):
            add(m.get("include"))

    return includes


def _collect_subckt_header_params(comps):
    """Собрать формальные параметры субсхемы листа.

    Для каждого X-компонента берём Sim.Params ("name=default …") и
    формируем формальный параметр <ref>_<name>=<default>.

    Возвращает список токенов для header:
        ['RT1_T=25', 'RT1_R25=10k', 'RT1_BETA=3435']
    """
    out = []
    for ref in sorted(comps):
        sim = comps[ref].get("sim") or {}
        if sim.get("Sim.Device") != "X":
            continue
        params = (sim.get("Sim.Params") or "").strip()
        if not params:
            continue
        for pname, pval in _param_tokens(params):
            if pval is None:
                out.append(f"{ref}_{pname}")
            else:
                out.append(f"{ref}_{pname}={pval}")
    return out


def build_subckt(stem, comps, nets, ports):
    """Собрать .subckt <stem> <ports> [PARAMS: …] … .ends.

    Header получает PARAMS: … — формальные параметры, унаследованные
    от параметров внутренних X-компонентов (см.
    _collect_subckt_header_params). X-строки ссылаются на эти
    формальные параметры через {<ref>_<name>}; конкретные значения
    приходят снаружи, через X<stem> в .cir (overrides сценария).
    """
    lines = [f"* {stem} — субсхема из нетлиста KiCad"]

    header = f".subckt {stem} {' '.join(ports)}"
    header_params = _collect_subckt_header_params(comps)
    if header_params:
        header += " PARAMS: " + " ".join(header_params)
    lines.append(header)

    for ref in sorted(comps):
        lines.append("  " + spice_el(ref, comps[ref], nets))
    lines.append(f".ends {stem}")
    return lines


# ─────────────────────────────────────────────────────────────────────
# Разбор deck из YAML-сценария
# ─────────────────────────────────────────────────────────────────────

def emit_source(body):
    ref = body["ref"]
    net = body["net"]
    t = body["type"]
    if t == "dc":
        return [f'{ref} {net} 0 DC {body["value"]}']
    if t == "pulse":
        p = body["pulse"]
        return [f'{ref} {net} 0 PULSE({p["v1"]} {p["v2"]} {p["td"]} '
                f'{p["tr"]} {p["tf"]} {p["pw"]} {p["per"]})']
    if t == "sin":
        return [f'{ref} {net} 0 SIN({body["offset"]} {body["ampl"]} {body["freq"]})']
    if t == "ac":
        return [f'{ref} {net} 0 AC {body["value"]}']
    raise ValueError(f"source type: {t}")


def _emit_subckt_body(body, sheet_yaml, main_cfg, ref):
    """X-инстанс для motor / subckt в deck.

    Для inline (nodes) — просто X <nodes> <subckt>.
    Для model: <имя МК> — через _mcu_args.
    Для legacy model: <имя> — через sheet_yaml.spice.models.
    """
    if body.get("subckt") and body.get("nodes"):
        nodes = body["nodes"]
        args = [str(nodes[k]) for k in nodes]
        return args, body["subckt"]

    model_name = body.get("model")
    if model_name and model_name in _mcu_model_names(main_cfg):
        args = _mcu_args(main_cfg, body.get("connect") or {}, ref=ref)
        return args, model_name

    if model_name:
        legacy = _lookup_legacy(sheet_yaml, main_cfg, model_name)
        if _model_kind(legacy) == "subckt":
            nodes = legacy.get("nodes") or {}
            connect = body.get("connect") or {}
            args = [str(connect.get(k, "0")) for k in nodes]
            return args, legacy["subckt"]

    raise ValueError(
        f"subckt/motor {ref}: не удалось определить модель. "
        f"Ожидается inline (include/subckt/nodes) или model: <имя МК>."
    )


def emit_deck_entry(entry, sheet_yaml, main_cfg):
    lines = []
    for kind, body in entry.items():
        ref = body.get("ref", "?")
        desc = body.get("description", "")
        if desc:
            lines.append(f"* {ref}: {desc.strip().splitlines()[0]}")

        if kind == "source":
            lines += emit_source(body)
        elif kind == "resistor":
            lines.append(f'{ref} {body["net_pos"]} {body["net_neg"]} {body["value"]}')
        elif kind == "inductor":
            lines.append(f'{ref} {body["net_pos"]} {body["net_neg"]} {body["value"]}')
        elif kind == "capacitor":
            lines.append(f'{ref} {body["net_pos"]} {body["net_neg"]} {body["value"]}')
        elif kind == "diode":
            lines.append(f'{ref} {body["net_a"]} {body["net_k"]} {body["model"]}')
        elif kind == "motor":
            args, sub = _emit_subckt_body(body, sheet_yaml, main_cfg, ref)
            params = body.get("params", {})
            pstr = " ".join(f"{k}={v}" for k, v in params.items())
            line = f'{ref} {" ".join(args)} {sub}'
            if pstr:
                line += " " + pstr
            lines.append(line)
        elif kind == "subckt":
            args, sub = _emit_subckt_body(body, sheet_yaml, main_cfg, ref)
            params = body.get("params") or {}
            pstr = " ".join(f"{k}={v}" for k, v in params.items())
            line = f'{ref} {" ".join(args)} {sub}'
            if pstr:
                line += " " + pstr
            lines.append(line)
        elif kind == "raw":
            lines.append(body["line"])
        else:
            raise ValueError(f"deck: неизвестный тип {kind}")
    return lines


def emit_deck(deck, sheet_yaml, main_cfg):
    lines = []
    for entry in deck or []:
        lines += emit_deck_entry(entry, sheet_yaml, main_cfg)
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


# ─────────────────────────────────────────────────────────────────────
# Legacy: реестры spice.models (используются только deck-эмитом)
# ─────────────────────────────────────────────────────────────────────

def _root_models(main_cfg):
    return (main_cfg.get("spice") or {}).get("models") or {}


def _sheet_models(sheet_yaml):
    return (sheet_yaml.get("spice") or {}).get("models") or {}


def _lookup_legacy(sheet_yaml, main_cfg, name):
    if not name:
        return None
    m = _sheet_models(sheet_yaml).get(name)
    if m is not None:
        return m
    return _root_models(main_cfg).get(name)


def _model_kind(m):
    if not m:
        return None
    if m.get("primitive"):
        return "model"
    if "subckt" in m or "nodes" in m:
        return "subckt"
    if "model_def" in m:
        return "model"
    return "subckt"


# ─────────────────────────────────────────────────────────────────────
# Сборка .cir
# ─────────────────────────────────────────────────────────────────────

def build_cir(stem, sc, sheet_yaml, main_cfg, ports, comps):
    lines = [f"* Ngspice тест: {stem} / {sc['name']}"]
    if sc.get("description"):
        for dl in sc["description"].strip().splitlines():
            lines.append(f"* {dl}")

    # MCU: сгенерировать per-scenario .sub и подключить его.
    mcu_insts = _mcu_instances(sc, main_cfg)
    if mcu_insts:
        _validate_mcu_state(sc)
        path = mcu_model.generate_scenario(
            main_cfg, stem, sc,
            out_dir=os.path.join(PROJ, "spice"),
        )
        if path is None:
            raise RuntimeError(
                f"scenario {sc['name']!r}: MCU в deck есть, "
                f"но mcu_model.generate_scenario вернул None"
            )
        lines.append(f".INCLUDE spice/{os.path.basename(path)}")

    # .include для .lib-файлов моделей
    for inc in collect_includes_from_comps(comps, sc, sheet_yaml, main_cfg):
        lines.append(f".INCLUDE {inc}")

    # .model-директивы (собраны из Sim.* компонентов)
    for md in collect_model_defs_from_comps(comps):
        lines.append(md)

    # Сама субсхема листа
    lines.append(f".INCLUDE spice/{stem}.sub")
    lines.append("")
    lines.append("* Порты: " + " ".join(ports))
    lines.append("")

    # Deck сценария
    lines += emit_deck(sc.get("deck"), sheet_yaml, main_cfg)

    # Инстанс субсхемы листа (позиционно).
    # Параметры через overrides: RT1_T=25 и т.п. — перекрывают
    # формальные параметры из header .subckt листа.
    cargs = " ".join("0" if p == "GND" else p for p in ports)
    xinst = f"X{stem} {cargs} {stem}"

    ovr = sc.get("overrides") or {}
    if ovr:
        pstr = []
        for ref, params in ovr.items():
            for pname, pval in params.items():
                pstr.append(f"{ref}_{pname}={pval}")
        if pstr:
            xinst += " " + " ".join(pstr)
    lines.append(xinst)
    lines.append("")

    for m in sc.get("measures", []):
        lines.append(".measure " + m)

    an = sc.get("analysis", "op")
    if an == "op":
        lines.append(".op")
    elif an == "tran":
        lines.append(".tran " + sc["tran"])
    elif an == "ac":
        lines.append(".ac " + sc["ac"])
    elif an == "dc":
        lines.append(".dc " + sc["dc"])

    lines.append(".control")
    lines.append("run")
    if sc.get("control"):
        lines += sc["control"].strip().splitlines()
    else:
        check_nodes = [c["node"] for c in sc.get("checks", []) if "node" in c]
        if check_nodes:
            lines.append("print " + " ".join(check_nodes))
    lines += [".endc", ".end"]
    return lines


# ─────────────────────────────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────────────────────────────

def parse_argv(argv):
    yaml_path = None
    sch_path = None
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--yaml" and i + 1 < len(argv):
            yaml_path = argv[i + 1]; i += 2; continue
        if a.startswith("--yaml="):
            yaml_path = a.split("=", 1)[1]; i += 1; continue
        if a == "--sch" and i + 1 < len(argv):
            sch_path = argv[i + 1]; i += 2; continue
        if a.startswith("--sch="):
            sch_path = a.split("=", 1)[1]; i += 1; continue
        rest.append(a); i += 1
    return rest, yaml_path, sch_path


def main():
    rest, yaml_path, sch_path = parse_argv(sys.argv[1:])
    if len(rest) < 2:
        print(__doc__)
        sys.exit(1)

    path, stem = rest[0], rest[1]
    ports = rest[2:]
    if "GND" not in ports:
        ports.append("GND")

    if not yaml_path:
        sys.exit("kicad_to_spice.py: нужен --yaml <path>")
    if not os.path.exists(yaml_path):
        sys.exit(f"kicad_to_spice.py: --yaml {yaml_path}: файла нет")

    os.makedirs(os.path.join(PROJ, "spice"), exist_ok=True)

    main_cfg = load_main()
    sheet_yaml = yaml.safe_load(open(yaml_path, encoding="utf-8")) or {}

    names = [s.get("name") for s in (sheet_yaml.get("scenarios") or [])]
    dups = {n for n in names if names.count(n) > 1}
    if dups:
        sys.exit(f"{yaml_path}: дублирующиеся имена сценариев: {sorted(dups)}")

    text = open(path, encoding="utf-8").read()
    comps, nets = parse_netlist(text)

    # Refdes нетлиста → YAML-пространство страницы.
    rmap = build_reverse_refdes_maps_from_sch(sch_path)
    if rmap:
        comps, nets = _apply_reverse_map(comps, nets, rmap)

    try:
        sub_lines = build_subckt(stem, comps, nets, ports)
    except ValueError as e:
        sys.exit(f"ERROR: {stem}: {e}")
    with open(os.path.join(PROJ, "spice", f"{stem}.sub"),
              "w", encoding="utf-8") as f:
        f.write("\n".join(sub_lines) + "\n")

    scenarios = sheet_yaml.get("scenarios") or []
    if not scenarios:
        stub = [
            f"* Ngspice тест: {stem} (заглушка)",
            f".INCLUDE spice/{stem}.sub",
            "* (сценарии для этого листа ещё не описаны)",
            ".control", "run", ".endc", ".end",
        ]
        with open(os.path.join(PROJ, "spice", f"{stem}.cir"),
                  "w", encoding="utf-8") as f:
            f.write("\n".join(stub) + "\n")
    else:
        for sc in scenarios:
            try:
                cir_lines = build_cir(stem, sc, sheet_yaml, main_cfg,
                                      ports, comps)
            except (ValueError, RuntimeError) as e:
                sys.exit(f"ERROR: {stem}/{sc.get('name')}: {e}")
            with open(os.path.join(PROJ, "spice", f"{sc['name']}.cir"),
                      "w", encoding="utf-8") as f:
                f.write("\n".join(cir_lines) + "\n")

    print("OK -> spice/%s.sub + %d сценариев" % (stem, len(scenarios)))


if __name__ == "__main__":
    main()