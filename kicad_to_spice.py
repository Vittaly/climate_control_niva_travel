#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kicad_to_spice.py — генерация Ngspice-тестов из нетлиста KiCad.

Источник данных:
  * нетлист KiCad (для pin-маппинга и состава компонентов);
  * main.yaml → spice.component_models (сложные .SUBCKT);
  * <sheet>.yaml → component_types, components, nets, scenarios, spice.

Каждая страница → .sub + по одному .cir на сценарий.

Запуск:  python3 kicad_to_spice.py <netlist.net> <sheet> [port1 ... portN]
"""
import os
import re
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
    """Найти yaml по page_name (перебор components.X_* в main.yaml)."""
    root = load_main()
    for comp_name, comp in root.get("components", {}).items():
        if comp.get("symbol") != "Core:Hierarchical_Sheet":
            continue
        if comp_name != "X_" + sheet and comp_name[2:] != sheet:
            continue
        yml_path = os.path.splitext(comp["value_sch"])[0] + ".yaml"
        return yaml.safe_load(open(os.path.join(PROJ, yml_path), encoding="utf-8"))
    # если не нашли в components — попробовать одноимённый yaml в sheets/
    guess = os.path.join(PROJ, "sheets", sheet.lower() + ".yaml")
    if os.path.exists(guess):
        return yaml.safe_load(open(guess, encoding="utf-8"))
    return {}


# ─────────────────────────────────────────────────────────────────────
# Парсинг нетлиста
# ─────────────────────────────────────────────────────────────────────

def parse_netlist(text):
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
        nodes = re.findall(
            r'\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)(?:\s+\(pinfunction "([^"]*)"\))?',
            m.group(2))
        nets[name] = nodes
    return comps, nets


def parse_val(v):
    v = re.sub(r"[А-Яа-яЁё ].*$", "", str(v).strip())
    v = v.replace(",", ".")
    m = re.match(r"([\d.]+)\s*(u|n|p|k|meg|m|M|G)?", v)
    return m.group(0) if m else "1"


def net_of(nets, ref, pin):
    for nm, nds in nets.items():
        for nd in nds:
            if nd[0] == ref and nd[1] == pin:
                return "GND" if nm == "GND" else nm
    return None


def cname(nm):
    return "GND" if nm == "GND" else nm


# ─────────────────────────────────────────────────────────────────────
# Генерация элементов .sub
# ─────────────────────────────────────────────────────────────────────

def component_type(sheet_yaml, comp):
    """Вернуть описание типа (component_types[type]) или {}."""
    return sheet_yaml.get("component_types", {}).get(comp.get("_type", ""), {})


def spice_el(ref, comp, nets, sheet_yaml, main_cfg):
    """SPICE-строка одного компонента внутри .sub."""
    part = comp["part"]
    cm = main_cfg.get("spice", {}).get("component_models", {})
    ctype = component_type(sheet_yaml, comp)
    spice_meta = ctype.get("spice", {})

    # 1. Сложный компонент из component_models (DRV8871, MCP2562, NTC, DC_MOTOR, BTS141, …)
    if part in cm:
        model = cm[part]
        nodes = model.get("nodes", {})
        args = []
        params = []
        for spice_port, spec in nodes.items():
            pin = spec["pin"] if isinstance(spec, dict) else spec
            net = net_of(nets, ref, pin) or "GND"
            args.append(cname(net))
        # параметры из required_params — оставляем ссылки на переменные
        # верхнего уровня (передаются через PARAMS: субсхемы)
        for p in model.get("required_params", []):
            pname = p["name"]
            params.append(f"{pname}={{{ref}_{pname}}}")
        line = f'X{ref} {" ".join(args)} {model["subckt"]}'
        if params:
            line += " " + " ".join(params)
        return line

    # 2. Резистор / конденсатор / индуктивность
    if part in ("R", "C", "L"):
        # тип определяем по символу — в KiCad обычно Device:R → part == "R"
        v = parse_val(comp["value"])
        p1 = cname(net_of(nets, ref, "1") or "GND")
        p2 = cname(net_of(nets, ref, "2") or "GND")
        return f'{ref} {p1} {p2} {v}'

    # 3. Диод
    if part in ("D", "D_Schottky", "D_Zener"):
        a = cname(net_of(nets, ref, "1") or "GND")
        k = cname(net_of(nets, ref, "2") or "GND")
        mdl = spice_meta.get("model", "MyD")
        return f'{ref} {a} {k} {mdl}'

    # 4. Транзистор NMOS / NPN / PNP
    if part in ("Q_NMOS", "Q_NMOS_GSD", "Q_NPN", "Q_PNP"):
        # порядок портов KiCad для Q_NMOS_GSD: 1=G, 2=D, 3=S
        g = cname(net_of(nets, ref, "1") or "GND")
        d = cname(net_of(nets, ref, "2") or "GND")
        s = cname(net_of(nets, ref, "3") or "GND")
        mdl = spice_meta.get("model", "SW_GP")
        if part in ("Q_NPN", "Q_PNP"):
            # BJT: 1=B, 2=C, 3=E — порядок в .model NPN/PNP: C B E
            b = g; c = d; e = s
            return f'Q{ref} {c} {b} {e} {mdl}'
        return f'M{ref} {d} {g} {s} {s} {mdl}'

    # 5. NTC (если не описан в component_models — упрощённый случай)
    if part == "Thermistor_NTC":
        a = cname(net_of(nets, ref, "1") or "GND")
        b = cname(net_of(nets, ref, "2") or "GND")
        return f'X{ref} {a} {b} NTC_10K_3435'

    # 6. Разъёмы и прочее — не моделируется
    return f'* {ref}: {part} ({comp["value"]}) — не моделируется'


# ─────────────────────────────────────────────────────────────────────
# Сборка .sub
# ─────────────────────────────────────────────────────────────────────

def collect_subckt_params(comps, sheet_yaml, main_cfg):
    """Найти все параметры сложных компонентов, которые нужно вынести в PARAMS: субсхемы."""
    cm = main_cfg.get("spice", {}).get("component_models", {})
    params = []  # список (subckt_param_name, default_value)
    for ref, comp in comps.items():
        part = comp["part"]
        if part not in cm:
            continue
        for p in cm[part].get("required_params", []):
            name = p["name"]
            default = p.get("default", "")
            params.append((f"{ref}_{name}", default))
    return params


def build_subckt(sheet, comps, nets, sheet_yaml, main_cfg, ports):
    params = collect_subckt_params(comps, sheet_yaml, main_cfg)
    header = f".subckt {sheet} {' '.join(ports)}"
    if params:
        # переносим параметры на отдельную строку с продолжением
        header += " PARAMS:"
        for pname, pval in params:
            header += f" {pname}={pval}" if pval != "" else f" {pname}"

    lines = [f"* {sheet} — субсхема из нетлиста KiCad + YAML"]
    lines.append(header)
    for ref in sorted(comps):
        lines.append("  " + spice_el(ref, comps[ref], nets, sheet_yaml, main_cfg))
    lines.append(f".ends {sheet}")
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


def emit_deck_entry(entry, main_cfg):
    """Один элемент deck → список SPICE-строк (+ комментарий из description)."""
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
            model = body["model"]
            cm = main_cfg["spice"]["component_models"][model]
            sub = cm["subckt"]
            # порядок портов: In+ In- Speed
            nets = [body["net_pos"], body["net_neg"], body.get("net_speed", "0")]
            params = body.get("params", {})
            pstr = " ".join(f"{k}={v}" for k, v in params.items())
            line = f'{ref} {" ".join(nets)} {sub}'
            if pstr:
                line += " " + pstr
            lines.append(line)

        elif kind == "subckt":
            model = body["model"]
            cm = main_cfg["spice"]["component_models"][model]
            sub = cm["subckt"]
            args = []
            for spice_port, spec in cm["nodes"].items():
                # соединяем по именам из body["connect"]
                kicad_key = spice_port
                target = body.get("connect", {}).get(kicad_key, "0")
                args.append(str(target))
            params = body.get("params", {})
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


def emit_deck(deck, main_cfg):
    lines = []
    for entry in deck or []:
        lines += emit_deck_entry(entry, main_cfg)
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


# ─────────────────────────────────────────────────────────────────────
# Сборка .cir
# ─────────────────────────────────────────────────────────────────────

def collect_includes(sheet_yaml, main_cfg, has_override_models=None):
    """Собрать .INCLUDE из component_models и spice.models листа."""
    lib_dir = os.path.join(PROJ, main_cfg.get("spice", {}).get("lib_dir", "spice/lib"))
    includes = []

    # модели, использованные в deck (по имени .subckt)
    used_models = set(has_override_models or [])

    cm = main_cfg.get("spice", {}).get("component_models", {})
    for name, model in cm.items():
        if name in used_models or model.get("include") in sheet_yaml.get("spice", {}).get("includes", []):
            inc = os.path.join(lib_dir, model["include"])
            if inc not in includes:
                includes.append(inc)

    # явные includes из spice.models листа (если заданы строкой с include:)
    for inc in sheet_yaml.get("spice", {}).get("includes", []):
        inc_path = os.path.join(lib_dir, inc)
        if inc_path not in includes:
            includes.append(inc_path)

    return includes


def collect_model_defs(sheet_yaml):
    """Собрать .model-строки из component_types[].spice.model_def и spice.models."""
    defs = []
    seen = set()

    # из component_types
    for ct in sheet_yaml.get("component_types", {}).values():
        md = ct.get("spice", {}).get("model_def")
        if md and md not in seen:
            defs.append(md)
            seen.add(md)

    # из spice.models (список строк)
    for line in sheet_yaml.get("spice", {}).get("models", []):
        if line not in seen:
            defs.append(line)
            seen.add(line)

    return defs


def build_cir(sheet, sc, sheet_yaml, main_cfg, ports):
    """Полный .cir для одного сценария."""
    lines = [f"* Ngspice тест: {sheet} / {sc['name']}"]
    if sc.get("description"):
        for dl in sc["description"].strip().splitlines():
            lines.append(f"* {dl}")

    # определить, какие сложные компоненты использованы в deck
    used_models = set()
    for entry in sc.get("deck", []):
        for kind, body in entry.items():
            if kind in ("motor", "subckt") and "model" in body:
                used_models.add(body["model"])

    for inc in collect_includes(sheet_yaml, main_cfg, used_models):
        lines.append(f".INCLUDE {inc}")

    for md in collect_model_defs(sheet_yaml):
        lines.append(md)

    lines.append(f".INCLUDE spice/{sheet}.sub")
    lines.append("")
    lines.append("* Порты: " + " ".join(ports))
    lines.append("")

    # deck из YAML
    lines += emit_deck(sc.get("deck"), main_cfg)

    # инстанс субсхемы
    cargs = " ".join("0" if p == "GND" else p for p in ports)
    xinst = f"X{sheet} {cargs} {sheet}"

    # overrides — передаём параметрами в субсхему
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

    # measures
    for m in sc.get("measures", []):
        lines.append("." + m)

    # анализ
    an = sc.get("analysis", "op")
    if an == "op":
        lines.append(".op")
    elif an == "tran":
        lines.append(".tran " + sc["tran"])
    elif an == "ac":
        lines.append(".ac " + sc["ac"])
    elif an == "dc":
        lines.append(".dc " + sc["dc"])

    # control
    lines.append(".control")
    lines.append("run")
    if sc.get("control"):
        lines += sc["control"].strip().splitlines()
    else:
        # печатаем все проверяемые узлы
        check_nodes = [c["node"] for c in sc.get("checks", []) if "node" in c]
        if check_nodes:
            lines.append("print " + " ".join(check_nodes))
    lines += [".endc", ".end"]
    return lines


# ─────────────────────────────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    path, sheet = sys.argv[1], sys.argv[2]
    ports = list(sys.argv[3:])
    if "GND" not in ports:
        ports.append("GND")

    os.makedirs(os.path.join(PROJ, "spice"), exist_ok=True)

    main_cfg = load_main()
    sheet_yaml = load_sheet_yaml(sheet)
    if not sheet_yaml:
        print(f"WARN: не найден YAML для листа {sheet}, генерирую только .sub")

    text = open(path, encoding="utf-8").read()
    comps, nets = parse_netlist(text)

    # 1. .sub
    sub_lines = build_subckt(sheet, comps, nets, sheet_yaml, main_cfg, ports)
    with open(os.path.join(PROJ, "spice", f"{sheet}.sub"), "w", encoding="utf-8") as f:
        f.write("\n".join(sub_lines) + "\n")

    # 2. .cir на каждый сценарий
    scenarios = sheet_yaml.get("scenarios") or []
    if not scenarios:
        stub = [
            f"* Ngspice тест: {sheet} (заглушка)",
            f".INCLUDE spice/{sheet}.sub",
            "* (сценарии для этого листа ещё не описаны)",
            ".control", "run", ".endc", ".end",
        ]
        with open(os.path.join(PROJ, "spice", f"{sheet}.cir"), "w", encoding="utf-8") as f:
            f.write("\n".join(stub) + "\n")
    else:
        for sc in scenarios:
            cir_lines = build_cir(sheet, sc, sheet_yaml, main_cfg, ports)
            with open(os.path.join(PROJ, "spice", f"{sc['name']}.cir"),
                      "w", encoding="utf-8") as f:
                f.write("\n".join(cir_lines) + "\n")

    print("OK -> spice/%s.sub + %d сценариев" % (sheet, len(scenarios)))


if __name__ == "__main__":
    main()