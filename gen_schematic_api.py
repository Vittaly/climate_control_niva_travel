#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_schematic_api.py — генерация страниц и иерархии через kicad_sch_api."""
import json, os, importlib.util
from kicad_sch_api import Schematic

PROJ = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("g", os.path.join(PROJ, "build_project.py"))
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

def add_page(s, comps, page, nets, net_pages):
    ix = 0
    for ref in sorted(comps):
        info = comps[ref]
        x = 60 + (ix % 3) * 90
        y = 40 + (ix // 3) * 70
        lib, sym = info["library"], info["sym_name"]
        try:
            s.components.add(f"{lib}:{sym}", reference=ref, value=str(info.get("value", "")),
                             position=(x, y))
        except Exception as e:
            print("  comp", ref, "->", e)
        ix += 1
    # метки на выводах (локальные/иерархические по граничным цепям)
    for nm, inf in nets.items():
        boundary = len(net_pages.get(nm, {page})) > 1
        for ref, mp in inf["nodes"]:
            if ref not in comps:
                continue
            if True:  # все цепи страниц делаем иерархическими (для портов)
                s.add_hierarchical_label(nm, (200 + ix, 40))
        ix += 1

U1_PIN_NAME = {
 "14":"PA0","15":"PA1","16":"PA2","17":"PA3","20":"PA4","21":"PA5","22":"PA6","23":"PA7",
 "26":"PB0","27":"PB1","28":"PB2","29":"PB10","30":"PB11","33":"PB12","34":"PB13","35":"PB14","36":"PB15",
 "41":"PA8","42":"PA9","43":"PA10","44":"PA11","45":"PA12","46":"PA13","49":"PA14","50":"PA15",
 "55":"PB3","56":"PB4","57":"PB5","58":"PB6","59":"PB7","61":"PB8","62":"PB9",
 "2":"PC13","3":"PC14","4":"PC15","37":"PC6","38":"PC7","39":"PC8","40":"PC9","51":"PC10","52":"PC11","53":"PC12",
 "5":"PD0","54":"PD2","1":"VBAT","7":"NRST","9":"VDDA","12":"VSSA","13":"VDDA","60":"BOOT0",
 "18":"VSS","19":"VDD","31":"VSS","32":"VDD","47":"VSS","48":"VDD","63":"VSS","64":"VDD",
}

def main():
    m = json.load(open(os.path.join(PROJ, "circuit_model.json"), encoding="utf-8"))
    comps_all = m["components"]
    sheets = m["sheets"]
    nets = m["nets"]
    # страницы каждой цепи
    page_of = {}
    for sh in sheets:
        for r in sh["components"]:
            page_of[r] = sh["name"]
    net_pages = {}
    for nm, inf in nets.items():
        ps = set()
        for r, _ in inf["nodes"]:
            if r in page_of:
                ps.add(page_of[r])
        net_pages[nm] = ps

    SIZES = {"CAN":30,"PWR":85,"UI":80,"SEN_CABIN":30,"SEN_HEAT":25,"SEN_SOLAR":22,"SEN_COND":22,"OUT":45,"ACT":92}
    # сначала дочерние страницы
    for sh in sheets[1:]:
        page_comps = {r: comps_all[r] for r in sh["components"] if r in comps_all}
        s = Schematic.create(name=sh["name"])
        add_page(s, page_comps, sh["name"], nets, net_pages)
        s.save(os.path.join(PROJ, sh["file"]))
    # корень: контроллер + листы-ссылки + пины + метки на U1
    root = sheets[0]
    rc = {r: comps_all[r] for r in root["components"] if r in comps_all}
    r = Schematic.create(name=root["name"])
    add_page(r, rc, root["name"], nets, net_pages)
    for i, sh in enumerate(sheets[1:]):
        h = SIZES.get(sh["name"], 40)
        bx = 90 + (i % 3) * 150
        by = 30 + (i // 3) * (h + 60)
        r.add_sheet(name=sh["name"], filename=sh["file"], position=(bx, by), size=(80, h))
        su = r.sheets.get_sheet_by_name(sh["name"])["uuid"]
        pi = 0
        for nm, ps in sorted(net_pages.items()):
            if sh["name"] in ps:
                r.add_sheet_pin(su, nm, "passive", "right", 2.54 + pi * 2.54)
                pi += 1
    u1 = None
    try:
        u1 = r.components.get("U1")
    except Exception:
        pass
    for nm, inf in nets.items():
        for ref, mp in inf["nodes"]:
            if ref == "U1" and u1 is not None:
                try:
                    p = u1.get_pin_position(str(mp))
                    if p:
                        r.add_label(nm, (p.x, p.y))
                except Exception as e:
                    print("U1 label", nm, e)
                break
    print("root validate:", len(r.validate()))
    r.save(os.path.join(PROJ, root["file"]))
    print("OK root", root["name"], len(rc), "комп.")
    r.save(os.path.join(PROJ, root["file"]))
    print("OK root", root["name"], len(rc), "комп.")

if __name__ == "__main__":
    main()
