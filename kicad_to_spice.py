#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kicad_to_spice.py — генерация Ngspice-тестов из нетлиста KiCad.

Источник данных:
  * нетлист KiCad (pin-маппинг, состав компонентов);
  * <stem>.yaml → component_types, components, nets, scenarios;
  * main.yaml → component_types, mcu_pin_map, j1_pinout (только для MCU).

Где живут модели:
  * Компонент НА СХЕМЕ → модель в component_types[type].spice:
      - subckt-модель: subckt + nodes + required_params + include;
      - primitive M/Q/D: primitive + model_def (узлы — из нетлиста
        по конвенциям SPICE↔KiCad);
      - R/C/L: без spice-секции, узлы pin 1/2 из нетлиста.
  * Модель ТОЛЬКО В ТЕСТЕ (deck, без .kicad_sch) → inline в deck.

Конвенции распиновки (для primitive M/Q/D):

    primitive   SPICE-порты    Откуда берутся узлы
    M           D G S B        pinfunction 'D'/'G'/'S' в KiCad-символе
                               (bulk = source)
    Q           C B E          pinfunction 'C'/'B'/'E'
    D           A K            pin 1 = K, pin 2 = A (Device:D конвенция)

  spice.nodes для примитивов НЕ нужен и не читается. Он остался
  только у subckt — там порядок портов не выводится из символа.

Роль типов и моделей:
  component_types[type].spice — всё о модели этого типа:
    * subckt       — имя .subckt для X-инстанса;
    * nodes        — только для subckt: SPICE-порт → {pin|pinfunction};
    * primitive    — M | Q | D: emit примитива (первая буква строки);
    * model_def    — inline .model для примитивов;
    * include      — .lib, который нужно .INCLUDE-ить в .cir;
    * value        — SPICE-значение (override для R/C/L с текстовым value);
    * params       — фиксированные значения для subckt;
    * auto_ports   — (только MCU) маркер, что порты берутся из mcu_pin_map.
  Значения параметров на конкретный прогон — через scenario.overrides.

Приоритет эмита одного компонента в spice_el():
  1. sp["primitive"] in ("M","Q","D") → M/Q/D-строка по конвенции;
  2. sp["subckt"]                     → X-строка по sp["nodes"];
  3. legacy spice.models[model]       → X или .model по структуре;
  4. part in ("R","C","L")            → R/C/L-строка, pin 1/2;
  5. part в диодах/транзисторах       → fallback для legacy-схем.

Имена элементов:
  SPICE определяет тип элемента по первой букве. KiCad-reference может
  не совпадать с ожидаемой буквой (LED1 → L, FB1 → F), поэтому имя
  элемента собирается через _element_ref(): приставляет префикс по типу,
  если его ещё нет.

Выходные файлы:
  * spice/<stem>.sub          — подсхема листа;
  * spice/<scenario>.cir      — по одному на scenarios[i];
  * spice/<scenario>_mcu.sub  — per-scenario модель МК (mcu_model.py).

Пути:
  LIB_DIR = <PROJ>/spice/lib — общая конвенция скриптов.

Запуск:
    python3 kicad_to_spice.py <netlist.net> <stem> --yaml <path> [port1 ... portN]
"""
import os
import re
import sys
import yaml

import mcu_model

PROJ = os.path.dirname(os.path.abspath(__file__))
YAML_DIR = os.path.join(PROJ, "sheets")
MAIN_YAML = os.path.join(YAML_DIR, "main.yaml")
LIB_DIR = os.path.join(PROJ, "spice", "lib")


# ─────────────────────────────────────────────────────────────────────
# Загрузка main.yaml
# ─────────────────────────────────────────────────────────────────────

def load_main():
    return yaml.safe_load(open(MAIN_YAML, encoding="utf-8"))["root_page"]


# ─────────────────────────────────────────────────────────────────────
# Legacy: реестры spice.models
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


def _inline_model_name(model_def):
    m = re.match(r"\.\s*(?:model|subckt)\s+([^\s(]+)", model_def or "", re.I)
    return m.group(1) if m else None


# ─────────────────────────────────────────────────────────────────────
# Парсинг нетлиста
# ─────────────────────────────────────────────────────────────────────

_PINFUNC_SUFFIX = re.compile(r"_\d+$")

def _norm_pinfunc(fn):
    """KiCad 10 экспортирует pinfunction как '<name>_<pin>'.
    Убираем суффикс: 'S_2' → 'S', 'D_3' → 'D', 'Pin_1_1' → 'Pin_1'."""
    if not fn:
        return fn
    return _PINFUNC_SUFFIX.sub("", fn)

def parse_netlist(text):
    """Парсит нетлист KiCad.

    Возвращает (comps, nets):
        comps[ref] = {"value": ..., "lib": ..., "part": ...}
        nets[name] = [(ref, pin, pinfunction_or_None), ...]

    pinfunction нормализуется: 'S_2' → 'S', 'D_3' → 'D',
    'Pin_1_1' → 'Pin_1' (KiCad 10 добавляет '_<pin>' к имени
    вывода при экспорте).
    """
    comps = {}
    for m in re.finditer(
        r'\(comp\s+\(ref "([^"]+)"\).*?\(value "([^"]*)"\).*?'
        r'\(libsource\s+\(lib "([^"]+)"\)\s+\(part "([^"]+)"\)',
        text, re.S):
        ref, value, lib, part = m.groups()
        comps[ref] = {"value": value, "lib": lib, "part": part}

    nets = {}
    for m in re.finditer(r'\(net\s+\(code "\d+"\)\s+\(name "([^"]+)"\)(.*?)\n\t\t\)',
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
    return comps, nets


def parse_val(v, ref="?"):
    """Строгое KiCad → SPICE.

    Принимает: 1u, 10k, 100n, 4k7, 1M, 0.1, 1R5, 220
    Отвергает: 'Феррит...', '10 кОм', '1uF 25V', пустое, 'DNP'.
    """
    s = str(v).strip().replace(",", ".")
    s = re.sub(r"[А-Яа-яЁё].*$", "", s).strip()
    m = re.match(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*"
                 r"(meg|[GMkmunp])?", s)
    if not m or not m.group(1):
        raise ValueError(
            f"{ref}: value={v!r} не в KiCad-нотации (примеры: "
            f"'10k', '1u', '100n', '4k7'). Если в value осмысленный "
            f"текст — задайте spice.value в component_types[type]."
        )
    return m.group(1) + (m.group(2) or "")


def net_of(nets, ref, key, by="pin"):
    """Поиск цепи для (ref, key).

    by="pin"         — key это номер пина ('1','2','3');
    by="pinfunction" — key это семантическое имя вывода ('D','G','S',
                       'A','K','C','B','E').
    """
    for nm, nds in nets.items():
        for nd in nds:
            if nd[0] != ref:
                continue
            value = nd[1] if by == "pin" else (nd[2] if len(nd) > 2 else "")
            if value and value == key:
                return "GND" if nm == "GND" else nm
    return None


def cname(nm):
    return "GND" if nm == "GND" else nm


def _resolve_node(nets, ref, spec, default="GND"):
    """Узел для nodes[port] subckt-модели.

    spec:
      * None                                → default;
      * str ('3')                           → по номеру пина;
      * {pin: '3'}                          → по номеру пина;
      * {pinfunction: 'IN'}                 → по семантическому имени.

    Используется ТОЛЬКО в ветке subckt. Для primitive M/Q/D/R/C/L
    узлы берутся по конвенции напрямую через net_of().
    """
    if spec is None:
        return default
    if isinstance(spec, dict):
        if "pin" in spec:
            net = net_of(nets, ref, str(spec["pin"]), by="pin")
        elif "pinfunction" in spec:
            net = net_of(nets, ref, spec["pinfunction"], by="pinfunction")
        else:
            return default
    else:
        net = net_of(nets, ref, str(spec), by="pin")
    return cname(net) if net else default


# ─────────────────────────────────────────────────────────────────────
# Тип компонента
# ─────────────────────────────────────────────────────────────────────

def _sheet_type_of(sheet_yaml, ref):
    comp_def = (sheet_yaml.get("components") or {}).get(ref) or {}
    type_name = comp_def.get("type")
    if not type_name:
        return None, {}
    ctype = (sheet_yaml.get("component_types") or {}).get(type_name) or {}
    return type_name, ctype


def _type_params(ctype):
    return (ctype.get("spice") or {}).get("params") or {}


def _spice_meta_of(sheet_yaml, ref):
    _tn, ctype = _sheet_type_of(sheet_yaml, ref)
    return ctype.get("spice") or {}


# ─────────────────────────────────────────────────────────────────────
# Имя SPICE-элемента
# ─────────────────────────────────────────────────────────────────────

def _element_ref(prefix: str, ref: str) -> str:
    if ref and ref[0].upper() == prefix.upper():
        return ref
    return prefix + ref


# ─────────────────────────────────────────────────────────────────────
# MCU: хелперы
# ─────────────────────────────────────────────────────────────────────

def _mcu_model_names(main_cfg):
    found = set()
    for ctype in (main_cfg.get("component_types") or {}).values():
        sp = ctype.get("spice") or {}
        if sp.get("auto_ports"):
            name = sp.get("subckt") or sp.get("model")
            if name:
                found.add(name)
    for name, m in _root_models(main_cfg).items():
        if isinstance(m, dict) and m.get("auto_ports"):
            found.add(name)
    return found


def _mcu_instances(sc, main_cfg):
    names = _mcu_model_names(main_cfg)
    result = []
    for entry in sc.get("deck", []):
        for kind, body in entry.items():
            if kind == "subckt" and body.get("model") in names:
                result.append(body)
    return result


def _mcu_args(main_cfg, connect, ref="XU1"):
    ports = mcu_model.mcu_ports(main_cfg)
    pin_map = main_cfg.get("mcu_pin_map") or {}
    sig_by_net = {p["net"]: p.get("signal")
                  for p in pin_map.values() if p.get("net")}
    valid_keys = set(ports) | {s for s in sig_by_net.values() if s}

    unknown = set(connect) - valid_keys
    if unknown:
        raise ValueError(
            f"{ref}: connect содержит неизвестные ключи "
            f"(нет ни в mcu_pin_map.net, ни в mcu_pin_map.signal): "
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

def spice_el(ref, comp, nets, sheet_yaml, main_cfg):
    """SPICE-строка одного компонента внутри .sub.

    Приоритет:
      1. sp["primitive"] in ("M","Q","D") → M/Q/D по конвенции;
      2. sp["subckt"]                     → X-инстанс по sp["nodes"];
      3. legacy spice.models[model]       → X или .model;
      4. part in ("R","C","L")            → R/C/L pin 1/2;
      5. part в диодах/транзисторах       → fallback для legacy-схем.
    """
    part = comp["part"]
    type_name, ctype = _sheet_type_of(sheet_yaml, ref)
    sp = ctype.get("spice") or {}
    legacy_name = sp.get("model")
    legacy = _lookup_legacy(sheet_yaml, main_cfg, legacy_name)

    # ─── 1. primitive — M / Q / D по конвенциям SPICE↔KiCad ───
    prim = sp.get("primitive")
    if prim in ("M", "Q", "D"):
        mdl = _inline_model_name(sp.get("model_def", ""))
        if not mdl and legacy_name and _model_kind(legacy) == "model":
            mdl = _inline_model_name(legacy.get("model_def", "")) or legacy_name
        if not mdl:
            raise ValueError(
                f"{ref} (type={type_name}): primitive={prim}, "
                f"но нет model_def"
            )

        if prim == "D":
            # KiCad Device:D: pin 1 = K (катод), pin 2 = A (анод)
            k = cname(net_of(nets, ref, "1", by="pin") or "GND")
            a = cname(net_of(nets, ref, "2", by="pin") or "GND")
            dref = _element_ref("D", ref)
            return f'{dref} {a} {k} {mdl}'

        if prim == "M":
            # KiCad Transistor_FET:*: pinfunction D/G/S
            d = cname(net_of(nets, ref, "D", by="pinfunction") or "GND")
            g = cname(net_of(nets, ref, "G", by="pinfunction") or "GND")
            s = cname(net_of(nets, ref, "S", by="pinfunction") or "GND")
            b = s   # bulk = source
            mref = _element_ref("M", ref)
            return f'{mref} {d} {g} {s} {b} {mdl}'

        # prim == "Q"
        # KiCad Transistor_BJT:*: pinfunction C/B/E
        c = cname(net_of(nets, ref, "C", by="pinfunction") or "GND")
        b = cname(net_of(nets, ref, "B", by="pinfunction") or "GND")
        e = cname(net_of(nets, ref, "E", by="pinfunction") or "GND")
        qref = _element_ref("Q", ref)
        return f'{qref} {c} {b} {e} {mdl}'

    # ─── 2. subckt — X-инстанс по sp["nodes"] ───
    if sp.get("subckt"):
        nodes = sp.get("nodes") or {}
        if not nodes:
            raise ValueError(
                f"{ref} (type={type_name}): subckt={sp['subckt']!r}, "
                f"но нет nodes — порядок портов subckt не выводится"
            )
        args = [_resolve_node(nets, ref, spec) for spec in nodes.values()]
        params = []
        for p in sp.get("required_params", []):
            pname = p["name"]
            params.append(f"{pname}={{{ref}_{pname}}}")
        xref = _element_ref("X", ref)
        line = f'{xref} {" ".join(args)} {sp["subckt"]}'
        if params:
            line += " " + " ".join(params)
        return line

    # ─── 2b. legacy: subckt через spice.models ───
    if _model_kind(legacy) == "subckt":
        nodes = legacy.get("nodes") or {}
        args = [_resolve_node(nets, ref, spec) for spec in nodes.values()]
        params = []
        for p in legacy.get("required_params", []):
            pname = p["name"]
            params.append(f"{pname}={{{ref}_{pname}}}")
        xref = _element_ref("X", ref)
        line = f'{xref} {" ".join(args)} {legacy["subckt"]}'
        if params:
            line += " " + " ".join(params)
        return line

    # ─── 3. R / C / L — pin 1 / pin 2 ───
    if part in ("R", "C", "L"):
        v = sp.get("value") or parse_val(comp["value"], ref=ref)
        p1 = cname(net_of(nets, ref, "1", by="pin") or "GND")
        p2 = cname(net_of(nets, ref, "2", by="pin") or "GND")
        eref = _element_ref(part, ref)
        return f'{eref} {p1} {p2} {v}'

    # ─── 4. Диод / LED — fallback для legacy-схем без primitive ───
    if part in ("D", "D_Schottky", "D_Zener", "LED"):
        k = cname(net_of(nets, ref, "K", by="pinfunction")
                  or net_of(nets, ref, "1", by="pin") or "GND")
        a = cname(net_of(nets, ref, "A", by="pinfunction")
                  or net_of(nets, ref, "2", by="pin") or "GND")
        mdl = _inline_model_name(sp.get("model_def", ""))
        if not mdl and legacy_name and _model_kind(legacy) == "model":
            mdl = _inline_model_name(legacy.get("model_def", "")) or legacy_name
        if not mdl:
            raise ValueError(
                f"{ref} (part={part!r}, value={comp['value']!r}): "
                f"в component_types[{type_name!r}].spice нет model_def"
            )
        dref = _element_ref("D", ref)
        return f'{dref} {a} {k} {mdl}'

    # ─── 5. Транзистор — fallback для legacy-схем без primitive ───
    if part in ("Q_NMOS", "Q_NMOS_GSD", "Q_NPN", "Q_PNP"):
        mdl = _inline_model_name(sp.get("model_def", ""))
        if not mdl and legacy_name and _model_kind(legacy) == "model":
            mdl = _inline_model_name(legacy.get("model_def", "")) or legacy_name
        if not mdl:
            raise ValueError(
                f"{ref} (part={part!r}): нет model_def "
                f"в component_types[{type_name!r}].spice"
            )
        if part in ("Q_NPN", "Q_PNP"):
            c = cname(net_of(nets, ref, "C", by="pinfunction")
                      or net_of(nets, ref, "2", by="pin") or "GND")
            b = cname(net_of(nets, ref, "B", by="pinfunction")
                      or net_of(nets, ref, "1", by="pin") or "GND")
            e = cname(net_of(nets, ref, "E", by="pinfunction")
                      or net_of(nets, ref, "3", by="pin") or "GND")
            qref = _element_ref("Q", ref)
            return f'{qref} {c} {b} {e} {mdl}'
        d = cname(net_of(nets, ref, "D", by="pinfunction")
                  or net_of(nets, ref, "2", by="pin") or "GND")
        g = cname(net_of(nets, ref, "G", by="pinfunction")
                  or net_of(nets, ref, "1", by="pin") or "GND")
        s = cname(net_of(nets, ref, "S", by="pinfunction")
                  or net_of(nets, ref, "3", by="pin") or "GND")
        mref = _element_ref("M", ref)
        return f'{mref} {d} {g} {s} {s} {mdl}'

    return f'* {ref}: {part} ({comp["value"]}) — не моделируется'


# ─────────────────────────────────────────────────────────────────────
# Сборка .sub
# ─────────────────────────────────────────────────────────────────────

def collect_subckt_params(comps, sheet_yaml, main_cfg):
    out = []
    for ref, _comp in comps.items():
        sp = _spice_meta_of(sheet_yaml, ref)
        if sp.get("primitive"):
            continue
        model = None
        if sp.get("subckt") or "nodes" in sp:
            model = sp
        else:
            model = _lookup_legacy(sheet_yaml, main_cfg, sp.get("model"))
        if _model_kind(model) != "subckt":
            continue
        type_params = _type_params(_sheet_type_of(sheet_yaml, ref)[1])
        for p in model.get("required_params", []):
            name = p["name"]
            if name in type_params:
                value = type_params[name]
            else:
                value = p.get("default")
            out.append((f"{ref}_{name}", value))
    return out


def build_subckt(stem, comps, nets, sheet_yaml, main_cfg, ports):
    params = collect_subckt_params(comps, sheet_yaml, main_cfg)
    header = f".subckt {stem} {' '.join(ports)}"
    if params:
        header += " PARAMS:"
        for pname, pval in params:
            if pval is None:
                header += f" {pname}"
            else:
                header += f" {pname}={pval}"

    lines = [f"* {stem} — субсхема из нетлиста KiCad + YAML"]
    lines.append(header)
    for ref in sorted(comps):
        lines.append("  " + spice_el(ref, comps[ref], nets, sheet_yaml, main_cfg))
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
# Сборка .cir
# ─────────────────────────────────────────────────────────────────────

def collect_includes(sheet_yaml, main_cfg, sc):
    includes = []

    def add_inc(name):
        if not name:
            return
        p = os.path.join(LIB_DIR, name)
        if p not in includes:
            includes.append(p)

    for entry in (sc.get("deck") or []):
        for _kind, body in entry.items():
            add_inc(body.get("include"))

    for _tn, ctype in (sheet_yaml.get("component_types") or {}).items():
        add_inc((ctype.get("spice") or {}).get("include"))

    for inc in (sheet_yaml.get("spice") or {}).get("includes", []) or []:
        add_inc(inc)
    for _n, m in _sheet_models(sheet_yaml).items():
        if isinstance(m, dict):
            add_inc(m.get("include"))
    for _n, m in _root_models(main_cfg).items():
        if isinstance(m, dict):
            add_inc(m.get("include"))

    return includes


def collect_model_defs(sheet_yaml, main_cfg):
    defs, seen = [], set()

    def add(line):
        s = (line or "").strip()
        if not s:
            return
        if not s.startswith("."):
            s = ".model " + s
        if s not in seen:
            defs.append(s)
            seen.add(s)

    for _tn, ctype in (sheet_yaml.get("component_types") or {}).items():
        add((ctype.get("spice") or {}).get("model_def"))

    for _n, m in _sheet_models(sheet_yaml).items():
        if isinstance(m, dict):
            add(m.get("model_def"))
    for _n, m in _root_models(main_cfg).items():
        if isinstance(m, dict):
            add(m.get("model_def"))

    return defs


def _check_required_params(stem, sc, comps, sheet_yaml, main_cfg):
    ovr = sc.get("overrides") or {}
    missing = []
    for ref, _comp in comps.items():
        sp = _spice_meta_of(sheet_yaml, ref)
        if sp.get("primitive"):
            continue
        model = None
        if sp.get("subckt") or "nodes" in sp:
            model = sp
        else:
            model = _lookup_legacy(sheet_yaml, main_cfg, sp.get("model"))
        if _model_kind(model) != "subckt":
            continue
        type_params = _type_params(_sheet_type_of(sheet_yaml, ref)[1])
        for p in model.get("required_params", []):
            name = p["name"]
            if name in type_params:
                continue
            if str(p.get("default", "")).strip() != "":
                continue
            if name not in (ovr.get(ref) or {}):
                missing.append(f"{ref}.{name}")
    if missing:
        example_ref = missing[0].split(".")[0]
        example_params = "\n".join(
            f"            {m.split('.', 1)[1]}: <значение>"
            for m in missing if m.startswith(example_ref + ".")
        )
        raise ValueError(
            f"{stem}/{sc['name']}: обязательные параметры без значения "
            f"в типе не переданы через overrides: {missing}.\n"
            f"    Добавьте в сценарий блок overrides, например:\n"
            f"        overrides:\n"
            f"          {example_ref}:\n"
            f"{example_params}"
        )


def build_cir(stem, sc, sheet_yaml, main_cfg, ports, comps):
    lines = [f"* Ngspice тест: {stem} / {sc['name']}"]
    if sc.get("description"):
        for dl in sc["description"].strip().splitlines():
            lines.append(f"* {dl}")

    _check_required_params(stem, sc, comps, sheet_yaml, main_cfg)

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

    for inc in collect_includes(sheet_yaml, main_cfg, sc):
        lines.append(f".INCLUDE {inc}")

    for md in collect_model_defs(sheet_yaml, main_cfg):
        lines.append(md)

    lines.append(f".INCLUDE spice/{stem}.sub")
    lines.append("")
    lines.append("* Порты: " + " ".join(ports))
    lines.append("")

    lines += emit_deck(sc.get("deck"), sheet_yaml, main_cfg)

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
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--yaml" and i + 1 < len(argv):
            yaml_path = argv[i + 1]; i += 2; continue
        if a.startswith("--yaml="):
            yaml_path = a.split("=", 1)[1]; i += 1; continue
        rest.append(a); i += 1
    return rest, yaml_path


def main():
    rest, yaml_path = parse_argv(sys.argv[1:])
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

    try:
        sub_lines = build_subckt(stem, comps, nets, sheet_yaml, main_cfg, ports)
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