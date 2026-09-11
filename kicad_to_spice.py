#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kicad_to_spice.py — генерация Ngspice-тестов из нетлиста KiCad.

Каждая страница -> .sub (субсхема, порты = пины листа) + по одному .cir на сценарий.
Запуск:  python3 kicad_to_spice.py <netlist.net> <sheet> [port1 ... portN]
"""
import re
import sys

def parse_netlist(text):
    comps = {}
    for m in re.finditer(r'\(comp\s+\(ref "([^"]+)"\).*?\(value "([^"]*)"\).*?\(libsource\s+\(lib "([^"]+)"\)\s+\(part "([^"]+)"\)', text, re.S):
        ref, value, lib, part = m.groups()
        comps[ref] = {"value": value, "lib": lib, "part": part}
    nets = {}
    for m in re.finditer(r'\(net\s+\(code "\d+"\)\s+\(name "([^"]+)"\)(.*?)\n\t\t\)', text, re.S):
        name = m.group(1).lstrip('/')
        nodes = re.findall(r'\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)(?:\s+\(pinfunction "([^"]*)"\))?', m.group(2))
        nets[name] = nodes
    return comps, nets

def parse_val(v):
    v = re.sub(r"[А-Яа-яВ ].*$", "", v.strip())
    v = v.replace(",", ".")
    m = re.match(r"([\d.]+)\s*(u|n|p|k|m|M)?", v)
    return m.group(0) if m else "1"

def pin_map(ref, nets):
    pm, pf = {}, {}
    for nm, nds in nets.items():
        for nd in nds:
            r, p = nd[0], nd[1]
            if r == ref:
                pm[p] = nm
                pf.setdefault(p, "").join(nd[2] if len(nd) > 2 else "")
    return pm, pf

def diode_nodes(ref, nets):
    anode = cathode = None
    for nm, nds in nets.items():
        for nd in nds:
            if nd[0] != ref:
                continue
            f = nd[2] if len(nd) > 2 else ""
            if f.lower().startswith("a"):
                anode = nm
            elif f.lower().startswith("k"):
                cathode = nm
    def c(nm):
        return "GND" if nm == "GND" else nm
    return c(anode), c(cathode)

def spice_el(ref, comp, nets):
    lib, part = comp["lib"], comp["part"]
    v = parse_val(comp["value"])
    pm, _pf = pin_map(ref, nets)
    def cname(nm):
        return "GND" if nm == "GND" else nm
    p1 = cname(pm.get("1", "GND"))
    p2 = cname(pm.get("2", "GND"))
    if part in ("R", "C", "L"):
        return f'{ref} {p1} {p2} {v}'
    if part in ("D_Schottky", "D_Zener", "D"):
        a, k = diode_nodes(ref, nets)
        if part == "D_Zener":
            mdl = "TVS5" if "5.0" in comp["value"] else "TVS24"
        else:
            mdl = "MyD"
        return f'{ref} {a} {k} {mdl}'
    if part == "Thermistor_NTC":
        return f'* {ref}: NTC (R задаётся в сценарии)'
    if part in ("Q_NMOS", "Q_NPN", "Q_PNP"):
        node = {}
        for nm, nds in nets.items():
            for nd in nds:
                if nd[0] == ref and len(nd) > 2:
                    node[nd[2].split("_")[0].lower()] = nm if nm != "GND" else "GND"
        g = node.get("g", node.get("b", "GND"))
        d = node.get("d", node.get("c", "GND"))
        s_ = node.get("s", node.get("e", "GND"))
        return f'S{ref} {d} {s_} {g} 0 SW_GP'
    if part == "DRV8871DDA":
        order = ["IN1", "IN2", "OUT1", "OUT2", "VM", "GND"]
        node = {}
        for nm, nds in nets.items():
            for nd in nds:
                if nd[0] == ref and len(nd) > 2:
                    f = nd[2].split("_")[0]
                    node[f] = nm if nm != "GND" else "GND"
        args = " ".join(node.get(k, "GND") for k in order)
        return f'X{ref} {args} DRV8871'
    if part == "MCP2562-E-SN":
        order = ["TXD", "RXD", "CANH", "CANL", "STBY", "VDD", "VIO", "GND"]
        node = {}
        for nm, nds in nets.items():
            for nd in nds:
                if nd[0] == ref and len(nd) > 2:
                    node[nd[2].split("_")[0].lower()] = nm if nm != "GND" else "GND"
        args = " ".join(node.get(k.lower(), "GND") for k in order)
        return f'X{ref} {args} MCP2562'
    if part in ("LM78M05_TO252", "AP1117-15"):
        mdl = "MC78M05" if part == "LM78M05_TO252" else "AMS1117_33"
        node = {}
        for nm, nds in nets.items():
            for nd in nds:
                if nd[0] == ref and len(nd) > 2:
                    node[nd[2].split("_")[0].lower()] = nm if nm != "GND" else "GND"
        i = node.get("vi", node.get("in", "GND"))
        g = node.get("gnd", "GND")
        o = node.get("vo", node.get("out", "GND"))
        return f'X{ref} {i} {g} {o} {mdl}'
    return f'* {ref}: {lib}:{part} (не моделируется)'

def scenarios_for(sheet):
    if sheet == "PWR":
        return scenarios_pwr
    return {
        "UI": [
            {"name": "UI_TEMP", "deck": ["VS VCC_3V3 0 DC 3.3", ".op",
              "* PASS: TEMP_SET_ADC ~3.3В (потенциометр выкручен/обрыв)"], "print": "V(TEMP_SET_ADC)"},
            {"name": "UI_FAN", "deck": ["VS VCC_3V3 0 DC 3.3", ".op",
              "* PASS: FAN_SEL_ADC в рабочем окне (AUTO)"], "print": "V(FAN_SEL_ADC)"},
            {"name": "UI_ILLUM", "deck": ["VS ILLUM_IN_RAW 0 DC 12", ".op",
              "* PASS: ILLUM_SENSE ~2,1В (делитель 47k/10k, подсветка включена)"], "print": "V(ILLUM_SENSE)"},
        ],
        "SEN_HEAT": [
            {"name": "SEN_HEAT_HOT", "deck": ["VS VCC_3V3 0 DC 3.3", "VN NTC_HEAT_W 0 DC 0.6", ".op",
              "* PASS: NTC_HEAT < 1.5В (труба горячая)"], "print": "V(NTC_HEAT)"},
            {"name": "SEN_HEAT_COLD", "deck": ["VS VCC_3V3 0 DC 3.3", "VN NTC_HEAT_W 0 DC 3.0", ".op",
              "* PASS: NTC_HEAT > 2.0В (труба холодная)"], "print": "V(NTC_HEAT)"},
        ],
        "SEN_SOLAR": [
            {"name": "SEN_SOLAR_MID", "deck": ["VS SOLAR_RAW 0 DC 2.5", ".op",
              "* PASS: SOLAR_ADC ~1.6В (делитель 5->3,3)"], "print": "V(SOLAR_ADC)"},
        ],
        "SEN_COND": [
            {"name": "SEN_COND_MID", "deck": ["VS COND_RAW 0 DC 2.5", ".op",
              "* PASS: COND_ADC ~1.6В (делитель 5->3,3)"], "print": "V(COND_ADC)"},
        ],
        "ACT": [
            {"name": "ACT_M1_FWD", "deck": ["VS VCC_12V 0 DC 14.4", "V1 M1_IN1 0 DC 3.3", "V2 M1_IN2 0 DC 0", ".op",
              "* PASS: MOTOR_1_A ~12В (H-мост, прямое вращение)"], "print": "V(MOTOR_1_A)"},
        ],
        "OUT": [
            {"name": "OUT_FAN_ON", "deck": ["VS VCC_12V 0 DC 14.4", "V1 FAN_PWM_CTL 0 DC 3.3", ".op",
              "* PASS: FAN_PWM_OUT низкий (ключ открыт)"], "print": "V(FAN_PWM_OUT)"},
            {"name": "OUT_FAN_OFF", "deck": ["VS VCC_12V 0 DC 14.4", "V1 FAN_PWM_CTL 0 DC 0", ".op",
              "* PASS: FAN_PWM_OUT ~12В (ключ закрыт)"], "print": "V(FAN_PWM_OUT)"},
        ],
        "CAN": [
            {"name": "CAN_RECESSIVE", "deck": ["VS VCC_5V 0 DC 5", "V1 CAN_TX 0 DC 5", ".op",
              "* PASS: CANH ~2,5В (рецессивный уровень)"], "print": "V(CANH)"},
            {"name": "CAN_DOMINANT", "deck": ["VS VCC_5V 0 DC 5", "V1 CAN_TX 0 DC 0", ".op",
              "* PASS: CANH подтянут к ~4В (доминантный)"], "print": "V(CANH)"},
        ],
        "SEN_CABIN": [
            {"name": "SEN_CABIN_FAN", "deck": ["VS VCC_12V 0 DC 14.4", "V1 M_FAN_CTL 0 DC 3.3", ".op",
              "* PASS: SENS_FAN_SW ~0 (вентилятор включён)"], "print": "V(SENS_FAN_SW)"},
        ],
    }.get(sheet, [])

def scenarios_pwr(nets, comps):
    return [
        {"name": "PWR_P1", "deck": ["VIN VBAT_IN 0 DC -14", ".op",
            "* PASS: V(VBAT_PROT)~0 и I(VIN)~0 (переполюсовка)"], "print": "V(VBAT_PROT)"},
        {"name": "PWR_P2", "deck": ["VIN VBAT_IN 0 DC 40", ".op",
            "* PASS: V(VCC_12V)<=24 (TVS D2, load-dump)"], "print": "V(VCC_12V)"},
        {"name": "PWR_P3", "deck": ["VIN VBAT_IN 0 DC 14.4 SIN(1M 2)", ".tran 0.02u 10u",
            "* PASS: размах VCC_5V в допуске (L1+C20 фильтр)"], "print": "V(VCC_5V)"},
        {"name": "PWR_P4", "deck": ["VIN VBAT_IN 0 DC 14.4", "Rshort VCC_12V 0 0.01", ".op",
            "* PASS: ток ограничен, защита держит (КЗ шины)"], "print": "V(VCC_12V)"},
        {"name": "PWR_P6", "deck": ["VIN VBAT_IN 0 DC 14.4", "VSENS V5_SENS 0 DC 12", ".op",
            "* PASS: V5_SENS<=5.6 (D5), D4 закрыт (обратный +12В)"], "print": "V(V5_SENS) V(VCC_5V)"},
    ]

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    path, sheet = sys.argv[1], sys.argv[2]
    ports = [p for p in sys.argv[3:]]
    if "GND" not in ports:
        ports.append("GND")
    text = open(path, encoding="utf-8").read()
    comps, nets = parse_netlist(text)

    lib = ["* %s (субсхема из нетлиста KiCad)" % sheet]
    lib.append(".subckt %s %s" % (sheet, " ".join(ports)))
    for ref in sorted(comps):
        lib.append("  " + spice_el(ref, comps[ref], nets))
    lib.append(".ends %s" % sheet)
    libfile = "spice/%s.sub" % sheet
    with open(libfile, "w", encoding="utf-8") as f:
        f.write("\n".join(lib) + "\n")

    has_drv = any(c["part"] == "DRV8871DDA" for c in comps.values())
    has_mcp = any(c["part"] == "MCP2562-E-SN" for c in comps.values())
    has_mc78 = any(c["part"] == "LM78M05_TO252" for c in comps.values())
    has_ams = any(c["part"] == "AP1117-15" for c in comps.values())
    base = ["* Ngspice тест: %s (порт-интерфейс из KiCad)" % sheet,
            ".INCLUDE drv8871_ngspice.lib" if has_drv else "",
            ".INCLUDE mcp2562_ngspice.lib" if has_mcp else "",
            ".INCLUDE mc78m05_ngspice.lib" if has_mc78 else "",
            ".INCLUDE ams1117_33_ngspice.lib" if has_ams else "",
            ".INCLUDE spice/%s.sub" % sheet,
            ".model MyD D(IS=4.35e-9 RS=0.64 BV=110)",
            ".model TVS24 D(IS=4.35e-9 RS=0.64 BV=8)",
            ".model TVS5 D(IS=4.35e-9 RS=0.64 BV=5.6)\n.model SW_GP SW(Ron=0.1 Roff=1Meg Vt=1.5 Vh=0.5)",
            "",
            "* Порты: " + " ".join(ports)]
    cargs = " ".join("0" if p == "GND" else p for p in ports)
    base.append("X%s %s %s" % (sheet, cargs, sheet))
    base.append("")

    scns = scenarios_for(sheet)(nets, comps) if sheet == "PWR" else scenarios_for(sheet)
    if not scns:
        S = base + ["* (сценарии для этого листа - в TODO)",
                    ".control", "run", ".endc", ".end"]
        with open("spice/%s.cir" % sheet, "w", encoding="utf-8") as f:
            f.write("\n".join(S) + "\n")
    else:
        for sc in scns:
            S = base + sc["deck"] + [".control", "op",
                                     "print " + sc["print"], "run",
                                     ".endc", ".end"]
            with open("spice/%s.cir" % sc["name"], "w", encoding="utf-8") as f:
                f.write("\n".join(S) + "\n")
    print("OK -> spice/%s.sub + %d сценариев" % (sheet, len(scns)))

if __name__ == "__main__":
    main()