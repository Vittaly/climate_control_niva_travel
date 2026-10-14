#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kicad_to_spice.py — генерация Ngspice-тестов из нетлиста KiCad.

Источник данных (единственный):
  * нетлист KiCad (pin-маппинг, состав компонентов, Sim.* properties);
  * <stem>.yaml → scenarios (deck, checks, analysis, overrides, params.U1);
  * корневой YAML (<ROOT_STEM>.yaml) → nets, component_types.

Сценарии читаются так:
  * если в YAML есть root_page: — берём <root_page>.scenarios;
  * иначе — <top>.scenarios.

.sub и .cir — разделение ролей:

  * spice/<stem>.sub — «что такое лист». Содержит только структуру:
    элементы, узлы, X-ссылки на модели по имени. Никаких PARAMS:
    в header — если у X-компонента есть параметры (например, 60
    MODE_* у MCU), они пишутся явными значениями прямо в X-строке.

  * spice/<scenario>_<stem>.sub — копия общего .sub для конкретного
    сценария, где значения параметров заменены на те, что заданы
    в этом сценарии (overrides: или params.U1:). Генерируется
    только если у сценария есть такие overrides.

  * spice/<scenario>.cir — тест. Инклюдит per-scenario .sub, если
    он существует (для сценариев с overrides), иначе общий .sub.
    Никаких overrides в X<stem> — все значения уже в .sub.

  Смысл разделения:
    - .sub не знает ни про какие сценарии. Он описывает лист.
    - per-scenario .sub — артефакт конкретного теста, лежит рядом
      с .cir для удобства отладки.
    - .cir тонкий: INCLUDE + deck + .op/.tran.

Почему параметры MCU в явном виде, а не через формальные PARAMS::

  Раньше XU1 внутри .sub писал MODE_PB2={U1_MODE_PB2}, а header
  .subckt корня объявлял 60 формальных U1_MODE_*, и .cir
  переопределял их на X-строке X<stem>. Работало, но:

    * header .sub раздувался на 60 имён, которые нужны только
      на уровне теста, а не на уровне листа;
    * XU1 в общем .sub содержал отсылки, которые надо было
      сводить с header'ом;
    * overrides в .cir были разбросаны по X-строке инстанса.

  Теперь: параметры X-компонента пишутся явными значениями.
  Для сценариев без override'ов — это дефолт из Sim.Params
  (для MCU — из .lib, заполняется _fill_sim_params_from_lib).
  Для сценариев с override'ами — под каждый генерируется свой .sub.

SPICE-модели компонентов БЕРУТСЯ ИЗ НЕТЛИСТА — как properties
символа, которые записал writer при генерации .kicad_sch.
kicad-cli выгружает их двумя формами:

    (property (name "Sim.Device") (value "X"))
    (field    (name "Sim.Device") "X")

Парсер нетлиста читает обе. Поля: Sim.Device, Sim.Name, Sim.Library,
Sim.Pins, Sim.Params, Sim.Model.

Синтаксис X-строк: ПОЗИЦИОННЫЙ (spice-стандарт).
    Ngspice принимает узлы X-инстанса только позиционно, в порядке
    портов из .SUBCKT:

        XU1 IN1 IN2 MOTOR_A MOTOR_B VCC_12V GND DRV8871

    Порядок портов берётся из .SUBCKT <Name> в Sim.Library
    (через _port_order_from_lib). Узлы — из Sim.Pins (pin=port)
    плюс net_of(ref, pin).

Refdes-пространства (per-page vs project):
  .kicad_sch листа хранит ДВЕ системы имён — YAML-канонические
  (property "Reference") и проектные в instance-путях. Генератор
  работает с YAML листа, поэтому refdes нетлиста приводятся к
  YAML-пространству через build_reverse_refdes_maps_from_sch().

Выходные файлы:
  * spice/<stem>.sub                  — общая подсхема листа;
  * spice/<scenario>_<stem>.sub       — per-scenario (если есть overrides);
  * spice/<scenario>.cir              — тест;
  * spice/<scenario>_mcu.sub          — per-scenario МК (mcu_model.py,
                                        только для MCU в deck).

Запуск:
    python3 kicad_to_spice.py <netlist.net> <stem> --yaml <path> \
            [--sch <path>] [port1 ... portN]
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
# Загрузка YAML с авторазворотом root_page:
# ─────────────────────────────────────────────────────────────────────

def _unwrap_root(doc):
    """Вернуть содержимое страницы независимо от формы YAML."""
    if isinstance(doc, dict) and "root_page" in doc:
        return doc.get("root_page") or {}
    return doc or {}


def load_main():
    doc = yaml.safe_load(open(MAIN_YAML, encoding="utf-8")) or {}
    return _unwrap_root(doc)


def load_sheet(yaml_path):
    doc = yaml.safe_load(open(yaml_path, encoding="utf-8")) or {}
    return _unwrap_root(doc)


# ─────────────────────────────────────────────────────────────────────
# Per-page нормализация refdes: kicad-cli → YAML-пространство страницы
# ─────────────────────────────────────────────────────────────────────

def build_reverse_refdes_maps_from_sch(sch_path):
    """{instance_ref: top_ref} для одного .kicad_sch."""
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
    """Привести refdes нетлиста в YAML-пространство страницы."""
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
# Чтение .lib: единый разбор logical lines
# ─────────────────────────────────────────────────────────────────────

def _read_lib_logical(path: str) -> str:
    """Прочитать .lib и склеить SPICE continuation lines ('+' в начале)."""
    try:
        raw = open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return ""
    logical: list[str] = []
    for line in raw.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("+"):
            if logical:
                logical[-1] = logical[-1] + " " + stripped[1:].strip()
            continue
        logical.append(line)
    return "\n".join(logical)


def _find_subckt_header(text: str, subckt_name: str):
    """Хвост строки .SUBCKT <subckt_name> … из текста."""
    pat = re.compile(
        r'^\s*\.SUBCKT\s+' + re.escape(subckt_name) + r'[ \t]+([^\n]+)',
        re.IGNORECASE | re.MULTILINE,
    )
    m = pat.search(text)
    return m.group(1) if m else None


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
    """Порядок портов .SUBCKT <subckt_name> из .lib."""
    key = (lib_path, subckt_name)
    if key in _PORT_ORDER_CACHE:
        return _PORT_ORDER_CACHE[key]

    path = _expand_include(lib_path)
    if not path or not os.path.exists(path):
        _PORT_ORDER_CACHE[key] = None
        return None

    text = _read_lib_logical(path)
    tail = _find_subckt_header(text, subckt_name)
    if tail is None:
        _PORT_ORDER_CACHE[key] = None
        return None

    if re.search(r'\bPARAMS:', tail, re.IGNORECASE):
        tail = re.split(r'\bPARAMS:', tail, maxsplit=1,
                        flags=re.IGNORECASE)[0]
    ports = [p for p in tail.split() if p != "+"]
    _PORT_ORDER_CACHE[key] = ports
    return ports


_PARAMS_FROM_LIB_CACHE = {}


def _params_from_lib(lib_path: str, subckt_name: str):
    """Список (name, default) из хвоста PARAMS: в .SUBCKT <name>."""
    key = (lib_path, subckt_name)
    if key in _PARAMS_FROM_LIB_CACHE:
        return _PARAMS_FROM_LIB_CACHE[key]

    path = _expand_include(lib_path)
    if not path or not os.path.exists(path):
        _PARAMS_FROM_LIB_CACHE[key] = None
        return None

    text = _read_lib_logical(path)
    tail = _find_subckt_header(text, subckt_name)
    if tail is None:
        _PARAMS_FROM_LIB_CACHE[key] = None
        return None

    pm = re.search(r'\bPARAMS:\s*(.+)$', tail, re.IGNORECASE)
    if not pm:
        _PARAMS_FROM_LIB_CACHE[key] = None
        return None

    out = []
    for tok in pm.group(1).split():
        if "=" in tok:
            n, d = tok.split("=", 1)
            out.append((n.strip(), d.strip()))
    _PARAMS_FROM_LIB_CACHE[key] = out
    return out


def _fill_sim_params_from_lib(comps):
    """Дописать Sim.Params X-компонентам из .lib, если он пуст.

    Нужно, чтобы у U1 был полный список MODE_* (60 имён) с дефолтами
    к моменту spice_el: он пишет их явными значениями в X-строку.
    Источник истины — .lib, схема остаётся чистой.
    """
    for ref, comp in comps.items():
        sim = comp.get("sim") or {}
        if sim.get("Sim.Device") != "X":
            continue
        if (sim.get("Sim.Params") or "").strip():
            continue
        lib = (sim.get("Sim.Library") or "").strip()
        sub = sim.get("Sim.Name")
        if not lib or not sub:
            continue
        plist = _params_from_lib(lib, sub)
        if plist:
            sim["Sim.Params"] = " ".join(f"{n}={d}" for n, d in plist)


def _model_type_for(dev: str) -> str:
    """SPICE-тип для .model-директивы по Sim.Device."""
    return {
        "D": "D", "Z": "D",
        "Q": "NPN",
        "M": "NMOS",
        "J": "NJF",
    }.get(dev, "D")


def _expand_include(name: str) -> str:
    """Развернуть Sim.Library в путь для .include."""
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
    """Возвращает (comps, nets)."""
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
        for pm in re.finditer(
            r'\(property\s+\(name\s+"(Sim\.[^"]+)"\)\s+'
            r'\(value\s+"([^"]*)"\)',
            block,
        ):
            sim[pm.group(1)] = pm.group(2)
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
    """Имя сети, на которой сидит пин (или pinfunction) компонента."""
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
    """Разбор value из KiCad-нотации (10k, 1u, 100n) → SPICE."""
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
    """X-префикс для X-инстанса и т.п."""
    if ref and ref[0].upper() == prefix.upper():
        return ref
    return prefix + ref


# ─────────────────────────────────────────────────────────────────────
# MCU: модели, порты, stimulus, трансляция params.U1
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
    """Подсхемы-MCU в deck сценария."""
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
    """Аргументы X-строки для инстанса МК (для MCU в deck)."""
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


# Алиасы значений MODE для пинов MCU.
_MCU_MODE_ALIASES = {
    "hiz": "0", "hi_z": "0", "z": "0",
    "adc": "1", "analog": "1",
    "pullup": "2", "pull_up": "2", "pu": "2",
    "pulldn": "3", "pulldown": "3", "pull_dn": "3", "pull_down": "3", "pd": "3",
    "out_high": "4", "high": "4", "h": "4",
    "out_low": "5", "low": "5", "l": "5",
    "pwm": "6",
}


def _mcu_pin_alias_to_mode(val):
    """params.U1.<pin> → (mode_str, [(suffix, value), …])."""
    if isinstance(val, bool):
        raise ValueError(f"unknown MCU pin mode: {val!r}")
    if isinstance(val, int):
        return str(val), []
    if isinstance(val, dict):
        inner = val.get("mode")
        extra = []
        if inner == "pwm" or str(inner).lower() == "pwm":
            if "freq" in val:
                extra.append(("FREQ", val["freq"]))
            if "duty" in val:
                extra.append(("DUTY", val["duty"]))
            return "6", extra
        mode_str, sub_extra = _mcu_pin_alias_to_mode(inner)
        return mode_str, sub_extra + extra

    key = str(val).strip().lower()
    if key in _MCU_MODE_ALIASES:
        return _MCU_MODE_ALIASES[key], []
    if key.isdigit():
        return key, []
    raise ValueError(
        f"unknown MCU pin mode: {val!r}. Допустимо: "
        f"hiz/adc/pullup/pulldn/out_high/out_low/pwm "
        f"(или число 0..6), либо {{mode: pwm, freq: …, duty: …}}."
    )


def _mcu_overrides_from_params(sc):
    """overrides для U1 из sc.params.U1 → {U1: {MODE_<pin>: …}}."""
    u1_params = (sc.get("params") or {}).get("U1") or {}
    if not u1_params:
        return {}

    out = {}
    for pin, val in u1_params.items():
        mode, extra = _mcu_pin_alias_to_mode(val)
        out[f"MODE_{pin}"] = mode
        for suffix, v in extra:
            out[f"{suffix}_{pin}"] = v
    return {"U1": out}


# ─────────────────────────────────────────────────────────────────────
# Генерация элементов .sub
# ─────────────────────────────────────────────────────────────────────

def _legacy_device(part: str):
    """Угадать Sim.Device по libsource.part, если Sim.Device пуст."""
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
    """'T=25 R25=10k' → [('T','25'), ('R25','10k')]. Без '=' → (name, None)."""
    out = []
    for tok in (params or "").split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out.append((k.strip(), v.strip()))
        else:
            out.append((tok.strip(), None))
    return out


def spice_el(ref, comp, nets, xinst_overrides=None):
    """SPICE-строка одного компонента.

    xinst_overrides — {ref: {param: value}} — карта значений для
    X-компонентов. Применяется при генерации per-scenario .sub:
    для параметра, найденного в карте, пишется явное значение вместо
    дефолта из Sim.Params. Для общего .sub карта пуста — все
    параметры пишутся со своими дефолтами.
    """
    overrides = (xinst_overrides or {}).get(ref) or {}
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
            return (f"* {ref}: {name} — модель per-scenario "
                    f"(инстанс добавляется в .cir)")

        pins_list = _parse_sim_pins(pins_str)
        if not pins_list:
            raise ValueError(
                f"{ref}: Sim.Device=X, но Sim.Pins пуст — "
                f"не могу подставить узлы"
            )

        port_order = _port_order_from_lib(lib, name)

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
            args = [port_to_node[port] for _, port in pins_list]

        xref = _element_ref("X", ref)
        line = f'{xref} {" ".join(args)} {name}'

        # Параметры X-инстанса — явными значениями.
        # Приоритет: override сценария > дефолт из Sim.Params.
        # Никаких {ref_param}-отсылок и PARAMS: в header — так .sub
        # остаётся чистым, а per-scenario .sub подставляет значения.
        for pname, pdefault in _param_tokens(params):
            actual = overrides.get(pname)
            if actual is not None:
                line += f" {pname}={actual}"
            elif pdefault is not None:
                line += f" {pname}={pdefault}"
            # pdefault is None и нет override — параметр без значения
            # просто не передаётся (модель возьмёт свой внутренний дефолт).

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
    """Уникальные .model-директивы из Sim.* компонентов."""
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
            line = f".model {model} {params}"
        elif params:
            mtype = _model_type_for(dev)
            line = f".model {model} {mtype}({params})"
        else:
            mtype = _model_type_for(dev)
            line = f".model {model} {mtype}()"

        if line not in seen:
            defs.append(line)
            seen.add(line)
    return defs


def collect_includes_from_comps(comps, sc, sheet_yaml, main_cfg):
    """Файлы для .include."""
    includes, seen = [], set()

    def add(name):
        if not name:
            return
        p = _expand_include(name)
        if not p or p in seen:
            return
        includes.append(p)
        seen.add(p)

    for _ref, comp in comps.items():
        sim = comp.get("sim") or {}
        if sim.get("Sim.Device") == "X":
            add(sim.get("Sim.Library"))

    for entry in (sc.get("deck") or []):
        for _kind, body in entry.items():
            add(body.get("include"))

    for inc in (sheet_yaml.get("spice") or {}).get("includes", []) or []:
        add(inc)

    for _tn, ctype in (sheet_yaml.get("component_types") or {}).items():
        add((ctype.get("spice") or {}).get("include"))

    for _tn, ctype in (main_cfg.get("component_types") or {}).items():
        add((ctype.get("spice") or {}).get("include"))

    for _n, m in _sheet_models(sheet_yaml).items():
        if isinstance(m, dict):
            add(m.get("include"))

    for _n, m in _root_models(main_cfg).items():
        if isinstance(m, dict):
            add(m.get("include"))

    return includes


def build_subckt(stem, comps, nets, ports, xinst_overrides=None):
    """Собрать .subckt <stem> <ports> … .ends.

    Без PARAMS: в header. Все параметры X-компонентов пишутся явными
    значениями прямо в их X-строках (см. spice_el). Значения —
    либо дефолт из Sim.Params (для общего .sub), либо переопределены
    картой xinst_overrides (для per-scenario .sub).

    Такой .sub — чистое описание структуры листа: сеть, имена
    компонентов, ссылки на модели. Никаких формальных параметров
    «на будущее» от возможных сценариев.
    """
    lines = [f"* {stem} — субсхема из нетлиста KiCad"]
    lines.append(f".subckt {stem} {' '.join(ports)}")
    for ref in sorted(comps):
        lines.append("  " + spice_el(
            ref, comps[ref], nets, xinst_overrides=xinst_overrides,
        ))
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
    """X-инстанс для motor / subckt в deck."""
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
    """Эмит одной записи deck."""
    lines = []
    for kind, body in entry.items():
        if kind == "control":
            continue

        ref = body.get("ref", "?") if isinstance(body, dict) else "?"
        desc = body.get("description", "") if isinstance(body, dict) else ""
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
# Overrides для per-scenario .sub
# ─────────────────────────────────────────────────────────────────────

def collect_xinst_overrides(sc):
    """{ref: {param: value}} — значения параметров X-компонентов
    для конкретного сценария.

    Источники:
      * sc.overrides — явные пары ref → {param: value};
      * sc.params.U1 — трансляция в U1 → {MODE_<pin>: …,
                       FREQ_<pin>: …, DUTY_<pin>: …}.

    Явные sc.overrides приоритетнее — если пользователь задал
    U1.MODE_PB2 руками, params.U1.PB2 то же поле не перепишет.
    """
    ovr = {}
    for ref, params in (sc.get("overrides") or {}).items():
        ovr[ref] = dict(params)

    auto = _mcu_overrides_from_params(sc)
    for ref, params in auto.items():
        dst = ovr.setdefault(ref, {})
        for k, v in params.items():
            dst.setdefault(k, v)

    return ovr


# ─────────────────────────────────────────────────────────────────────
# Сборка .cir
# ─────────────────────────────────────────────────────────────────────

def _sub_include_name(sc, stem):
    """Имя файла .sub для инклюда в .cir.

    Если для сценария сгенерирован per-scenario .sub
    (<scenario>_<stem>.sub) — берём его. Иначе — общий <stem>.sub.

    Проверка по факту файла на диске: main() генерирует все .sub
    до запуска build_cir.
    """
    per_path = os.path.join(PROJ, "spice", f"{sc['name']}_{stem}.sub")
    if os.path.exists(per_path):
        return f"{sc['name']}_{stem}.sub"
    return f"{stem}.sub"


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

    # .model-директивы
    for md in collect_model_defs_from_comps(comps):
        lines.append(md)

    # Субсхема листа: per-scenario, если для сценария есть overrides,
    # иначе — общий <stem>.sub. Никаких PARAMS: в .sub и никаких
    # overrides на X<stem> — значения уже внутри .sub.
    sub_name = _sub_include_name(sc, stem)
    lines.append(f".INCLUDE spice/{sub_name}")
    lines.append("")
    lines.append("* Порты: " + " ".join(ports))
    lines.append("")

    # Deck сценария
    lines += emit_deck(sc.get("deck"), sheet_yaml, main_cfg)

    # Инстанс субсхемы листа (позиционно). Без overrides — они
    # внутри .sub.
    cargs = " ".join("0" if p == "GND" else p for p in ports)
    xinst = f"X{stem} {cargs} {stem}"
    lines.append(xinst)
    lines.append("")

    for m in sc.get("measures", []):
        lines.append(".measure " + m)

    an = sc.get("analysis", "op")
    if an == "op":
        lines.append(".op")
    elif an == "tran":
        if "tran" not in sc:
            raise ValueError(
                f"scenario {sc['name']!r}: analysis=tran, но ключ "
                f"'tran' не задан (например, tran: \"1m 200m\")"
            )
        lines.append(".tran " + sc["tran"])
    elif an == "ac":
        if "ac" not in sc:
            raise ValueError(
                f"scenario {sc['name']!r}: analysis=ac, но ключ "
                f"'ac' не задан"
            )
        lines.append(".ac " + sc["ac"])
    elif an == "dc":
        if "dc" not in sc:
            raise ValueError(
                f"scenario {sc['name']!r}: analysis=dc, но ключ "
                f"'dc' не задан"
            )
        lines.append(".dc " + sc["dc"])
    else:
        raise ValueError(
            f"scenario {sc['name']!r}: неизвестный analysis={an!r}"
        )

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
    try:
        sheet_yaml = load_sheet(yaml_path)
    except Exception as e:
        sys.exit(f"kicad_to_spice.py: не смог прочитать {yaml_path}: {e}")

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

    # Заполнить Sim.Params у X-компонентов из .lib — чтобы spice_el
    # знал полный список параметров (у MCU это 60 MODE_*).
    _fill_sim_params_from_lib(comps)

    # ─── 1. Общий <stem>.sub ───
    # Без PARAMS: в header. Параметры X-компонентов — явные дефолты.
    try:
        sub_lines = build_subckt(stem, comps, nets, ports)
    except ValueError as e:
        sys.exit(f"ERROR: {stem}: {e}")
    with open(os.path.join(PROJ, "spice", f"{stem}.sub"),
              "w", encoding="utf-8") as f:
        f.write("\n".join(sub_lines) + "\n")

    scenarios = sheet_yaml.get("scenarios") or []

    # ─── 2. Per-scenario <scenario>_<stem>.sub ───
    # Для сценариев с overrides/params.U1 — копия общего .sub,
    # где значения параметров заменены на выбранные тестом.
    per_sub_written = 0
    for sc in scenarios:
        xovr = collect_xinst_overrides(sc)
        if not xovr:
            continue
        try:
            per_lines = build_subckt(stem, comps, nets, ports,
                                     xinst_overrides=xovr)
        except ValueError as e:
            print(f"ERROR: {stem}/{sc.get('name')}: per-scenario .sub: {e}",
                  file=sys.stderr)
            continue
        per_path = os.path.join(PROJ, "spice",
                                f"{sc['name']}_{stem}.sub")
        with open(per_path, "w", encoding="utf-8") as f:
            f.write("\n".join(per_lines) + "\n")
        per_sub_written += 1

    # ─── 3. Сценарии: заглушка или .cir ───
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
        print("OK -> spice/%s.sub + 0 сценариев (заглушка)" % stem)
        return

    errors = []
    written = []
    for sc in scenarios:
        sc_name = sc.get("name") or "?"
        try:
            cir_lines = build_cir(stem, sc, sheet_yaml, main_cfg,
                                  ports, comps)
        except (ValueError, RuntimeError) as e:
            errors.append((sc_name, str(e)))
            continue
        out_path = os.path.join(PROJ, "spice", f"{sc_name}.cir")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(cir_lines) + "\n")
        written.append(sc_name)

    print("OK -> spice/%s.sub + %d/%d сценариев (per-scenario: %d)"
          % (stem, len(written), len(scenarios), per_sub_written))
    if errors:
        for name, err in errors:
            print(f"ERROR: {stem}/{name}: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()