#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_tests.py — запуск Ngspice-сценариев и проверка PASS/FAIL по допускам."""
import re, subprocess, os

# сценарий -> (узел, min, max, описание)
CHECKS = {
    "PWR_P1": ("v(vbat_prot)", -1.0, 1.0, "переполюсовка: VBAT_PROT≈0"),
    "PWR_P2": ("v(vcc_12v)", 0.0, 24.0, "40В на входе: TVS клиппит <=24В"),
    "PWR_P3": ("v(vcc_5v)", 4.6, 5.4, "наводка: VCC_5V стабильна"),
    "PWR_P4": ("v(vcc_12v)", 0.0, 2.0, "КЗ шины: шина прижата к 0"),
    "PWR_P6": ("v(vcc_5v)", 4.6, 5.4, "обратный +12В: VCC_5V не запитан снаружи"),
    "UI_TEMP": ("v(temp_set_adc)", 2.8, 3.6, "потенциометр/обрыв -> 3,3В"),
    "UI_ILLUM": ("v(illum_sense)", 1.6, 2.6, "подсветка 12В -> ~2,1В"),
    "UI_FAN": ("v(fan_sel_adc)", 0.0, 3.6, "FAN_SEL в рабочем окне"),
    "SEN_HEAT_HOT": ("v(ntc_heat)", 0.0, 1.5, "труба горячая -> низкий уровень"),
    "SEN_HEAT_COLD": ("v(ntc_heat)", 2.0, 3.6, "труба холодная -> высокий уровень"),
    "SEN_SOLAR_MID": ("v(solar_adc)", 1.4, 1.8, "солнце 2,5В -> 1,65В"),
    "SEN_COND_MID": ("v(cond_adc)", 1.4, 1.8, "конденсат 2,5В -> 1,65В"),
    "ACT_M1_FWD": ("v(motor_1_a)", 11.0, 15.0, "H-мост: OUT1 под напряжением"),
    "CAN_RECESSIVE": ("v(canh)", 2.2, 2.9, "рецессивный уровень ~2,5В"),
    "CAN_DOMINANT": ("v(canh)", 3.0, 4.6, "доминантный уровень"),
    "OUT_FAN_ON": ("v(fan_pwm_out)", 0.0, 1.0, "ШИМ ключ открыт -> 0В"),
    "OUT_FAN_OFF": ("v(fan_pwm_out)", 11.0, 15.0, "ШИМ ключ закрыт -> 12В"),
    "SEN_CABIN_FAN": ("v(sens_fan_sw)", 0.0, 2.0, "вентилятор продувки включён"),
}

def run(cir):
    r = subprocess.run(["ngspice", "-b", cir], capture_output=True, text=True)
    return r.stdout

def parse_vals(out):
    vals = {}
    for m in re.finditer(r'v\(([a-z_0-9]+)\)\s*=\s*([-+0-9.eE]+)', out):
        vals["v("+m.group(1)+")"] = float(m.group(2))
    return vals

def main():
    results = []
    # фильтр: запускаем только сценарии из CHECKS (остальные .cir в spice/ игнорируем)
    for name in sorted(CHECKS):
        cir = os.path.join("spice", name + ".cir")
        if not os.path.exists(cir):
            print("%-14s MISSING (%s)" % (name, os.path.relpath(cir)))
            results.append(False)
            continue
        vals = parse_vals(run(cir))
        node, lo, hi, desc = CHECKS[name]
        if node not in vals:
            print("%-14s SKIP (%s не измерен)" % (name, node))
            results.append(False)
            continue
        v = vals[node]
        ok = lo <= v <= hi
        results.append(ok)
        print("%-14s %s  v(%s)=%+.3e  [%g..%g] %s" % (name, "PASS" if ok else "FAIL", node, v, lo, hi, desc))
    if results:
        print("\nИтого PASS: %d/%d" % (sum(results), len(results)))

if __name__ == "__main__":
    main()
