#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор многостраничной схемы KiCad из circuit_model.json (v4).

Страницы плоские (одного уровня). Первая страница (корневой файл проекта)
содержит J1 + питание + листы-ссылки на остальные страницы.
Связи между страницами - ГЛОБАЛЬНЫЕ метки; внутри страницы - локальные метки.
Символы берутся из установленных библиотек KiCad и встраиваются в каждый файл.
"""
import json
import os
import re
import uuid

def uu():
    return str(uuid.uuid4())

SYMBOL_DIRS = [
    "/usr/share/kicad/symbols",
    os.path.expanduser("~/.local/share/kicad/8.0/symbols"),
    os.path.expanduser("~/.local/share/kicad/7.0/symbols"),
]

_libcache = {}
def load_lib(lib):
    if lib in _libcache:
        return _libcache[lib]
    for d in SYMBOL_DIRS:
        p = os.path.join(d, lib + ".kicad_sym")
        if os.path.exists(p):
            s = open(p, encoding="utf-8").read()
            _libcache[lib] = s
            return s
    _libcache[lib] = None
    return None

def symbol_body(lib, sym):
    s = load_lib(lib)
    if s is None:
        return None
    i = s.find('(symbol "%s"' % sym)
    if i < 0:
        return None
    seg = s[i:]
    j = seg.find('\n\t(symbol "', 10)
    return seg if j < 0 else seg[:j]

def extract_pins(block):
    out = []
    lines = block.splitlines()
    k = 0
    while k < len(lines):
        line = lines[k]
        if '(pin ' in line:
            buf = line
            kk = k + 1
            while buf.count('(') != buf.count(')'):
                if kk >= len(lines):
                    break
                buf += ' ' + lines[kk]
                kk += 1
            m = re.search(r'\s*\(pin\s+(\w+)\s+(\w+)\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)\s+\(length\s+([\d.]+)\)', buf)
            nm = re.search(r'\(name\s+"([^"]*)"', buf)
            nu = re.search(r'\(number\s+"([^"]+)"', buf)
            if m and nm and nu:
                ptype, shape, x, y, ang, ln = m.groups()
                out.append((nu.group(1), nm.group(1), ptype, float(x), float(y), int(ang)))
            k = kk
        else:
            k += 1
    return out

NAME_BY_PIN = {
    ("Device", "LED"):        {"1": "A", "2": "K"},
    ("Device", "D"):          {"1": "A", "2": "K"},
    ("Device", "D_Schottky"): {"1": "A", "2": "K"},
    ("Device", "D_Zener"):    {"1": "A", "2": "K"},
    ("Device", "Q_NMOS"):     {"1": "G", "2": "D", "3": "S"},
    ("Device", "Q_NPN"):      {"1": "B", "2": "C", "3": "E"},
    ("Device", "Q_PNP"):      {"1": "B", "2": "C", "3": "E"},
    ("Regulator_Linear", "LM78M05_TO252"): {"1": "VI", "2": "GND", "3": "VO"},
    ("Regulator_Linear", "AP1117-15"):     {"1": "VI", "2": "GND", "3": "VO"},
}

def resolve_pin(lib, sym, model_pin, pins):
    model_pin = str(model_pin)
    mp = NAME_BY_PIN.get((lib, sym), {})
    if mp and model_pin in mp:
        func = mp[model_pin]
        for num, name, *_ in pins:
            if name == func:
                return num
        raise SystemExit("Пин %s (%s) не найден в %s:%s" % (model_pin, func, lib, sym))
    for num, *_ in pins:
        if num == model_pin:
            return num
    raise SystemExit("Пин %s не найден в %s:%s" % (model_pin, lib, sym))

def pin_coord(pins, num):
    for n, _name, _t, x, y, _a in pins:
        if n == num:
            return x, y
    raise SystemExit("Нет координаты пина %s" % num)

def nominal_of(value):
    tokens = str(value).split()
    if not tokens:
        return ""
    acc = []
    for t in tokens:
        c0 = t[0]
        cyr = '\u0400' <= c0 <= '\u04FF'
        if not acc and cyr:
            return str(value)
        if acc and (cyr or c0 in '(\u2116'):
            break
        if not acc and c0 in '(\u2116':
            return str(value)
        acc.append(t)
    return ' '.join(acc) if acc else str(value)

# ============================================================================
#  ЗАГОЛОВОК ФАЙЛА ЛИСТА
# ============================================================================

SIM_MAP = {
    ("Device", "D"): "D", ("Device", "D_Schottky"): "D", ("Device", "D_Zener"): "D",
    ("Device", "Q_NMOS"): "NMOS", ("Device", "Q_NPN"): "NPN", ("Device", "Q_PNP"): "PNP",
    ("Driver_Motor", "DRV8871DDA"): ("DRV8871", "DRV8871_ngspice"),
    ("Interface_CAN_LIN", "MCP2562-E-SN"): ("MCP2562", "MCP2562_ngspice"),
}

def file_header(title, rev="4.0", spec="Climate Control Niva Travel"):
    md = spec
    return [
        '(kicad_sch (version 20231120) (generator eeschema)',
        '  (uuid "%s")' % uu(),
        '  (paper "A0")',
        '  (title_block',
        '    (title "%s")' % title,
        '    (company "DIY / Climate Control Niva Travel")',
        '    (rev "%s")' % rev,
        '  )',
    ]

# ============================================================================
#  ГЕНЕРАЦИЯ ОДНОГО ЛИСТА
# ============================================================================
def write_page(model, page, page_path, is_root, other_pages):
    comps = model["components"]
    nets = model["nets"]
    members = set(page["components"])
    placed = [r for r in members if not comps[r].get("virtual")]
    cat = ["Power_Protection", "Regulator_5V", "Regulator_3V3", "Filter_Power",
           "Filter_Decoupling", "Filter_Analog", "RC_Reset", "MCU", "Motor_Driver",
           "Switch_OpenDrain", "Switch_Load", "Switch_12V", "Connector_Main",
           "Connector_UI", "Debug_Connector", "Sensor_Cabin", "Analog_Condition",
           "UI_Button", "UI_LED"]
    def okey(r):
        t = comps[r].get("type", "")
        return (cat.index(t), r) if t in cat else (len(cat), r)
    placed.sort(key=okey)

    # ---- загрузка символов, используемых на этом листе
    ref_lib = {r: (comps[r]["library"], comps[r]["sym_name"]) for r in placed}
    bodies, pinlist = {}, {}
    for r in placed:
        lib, sym = ref_lib[r]
        if (lib, sym) not in bodies:
            b = symbol_body(lib, sym)
            if b is None:
                raise SystemExit("Нет символа %s:%s" % (lib, sym))
            bodies[(lib, sym)] = b
            pinlist[(lib, sym)] = extract_pins(b)
    node_pin = {}
    for nm, inf in nets.items():
        for ref, mp in inf["nodes"]:
            if ref not in ref_lib:
                continue
            lib, sym = ref_lib[ref]
            node_pin[(ref, mp)] = resolve_pin(lib, sym, mp, pinlist[(lib, sym)])

    # ---- компоновка (одна-две колонки на лист)
    def size(r):
        pp = pinlist[ref_lib[r]]
        xs = [p[3] for p in pp]; ys = [p[4] for p in pp]
        if not pp:
            return 15.0, 15.0
        return max(max(xs) - min(xs) + 12, 15), max(max(ys) - min(ys) + 12, 15)

    X0, Y0 = 60.0, 55.0
    COLC = 92.0; GAP = 14.0; MAXHB = 330.0
    pos = {}
    blocks = []
    if model.get("_groups"):
        OFF = 30.0
        # фаза 1: раскладка внутри каждого блока в локальных координатах (x от 0)
        local = []
        for grp in model["_groups"]:
            grefs = [r for r in grp["components"] if r in placed]
            col_x, cur_y = OFF, Y0
            ncol = 0
            ymax = Y0
            lpos = {}
            for r in grefs:
                w, h = size(r)
                if cur_y + h + GAP > Y0 + MAXHB:
                    ncol += 1; col_x = OFF + ncol * COLC; cur_y = Y0
                lpos[r] = (col_x, cur_y + h / 2)
                cur_y += h + GAP
                ymax = max(ymax, cur_y)
            local.append((grp["name"], grefs, lpos, ncol * COLC + 60.0 + OFF, ymax - Y0 + 10.0))
        # фаза 2: сетка блоков - по 3 в ряд
        row_y = Y0
        row = []
        row_w = 0.0
        row_h = 0.0
        for (name, grefs, lpos, w, h) in local:
            if len(row) == 3:
                # поставить ряд
                ox = X0
                for (nm2, gr2, lp2, w2, h2) in row:
                    for r in gr2:
                        pos[r] = (ox + lp2[r][0], row_y + lp2[r][1] - Y0)
                    blocks.append((nm2, ox, row_y - 10.0, w2, h2 + 10.0))
                    ox += w2 + 70.0
                row_y += row_h + 120.0
                row = []; row_w = 0.0; row_h = 0.0
            row.append((name, grefs, lpos, w, h))
            row_w += w
            row_h = max(row_h, h)
        if row:
            ox = X0
            for (nm2, gr2, lp2, w2, h2) in row:
                for r in gr2:
                    pos[r] = (ox + lp2[r][0], row_y + lp2[r][1] - Y0)
                blocks.append((nm2, ox, row_y - 10.0, w2, h2 + 10.0))
                ox += w2 + 70.0
    else:
        col_x, cur_y = X0, Y0
        ncol = 0
        ymax = Y0
        for r in placed:
            w, h = size(r)
            if cur_y + h + GAP > Y0 + MAXHB:
                ncol += 1; col_x = X0 + ncol * COLC; cur_y = Y0
            cy = cur_y + h / 2
            pos[r] = (col_x, cy)
            cur_y += h + GAP
            ymax = max(ymax, cur_y)
        blocks.append(("SCHEME", X0, Y0 - 10.0, ncol * COLC + 60.0, ymax - Y0 + 20.0))
    # ---- страницы, которых касается каждая цепь (для глобальных меток)
    if model.get("_single"):
        net_pages = {nm: {"MAIN"} for nm in nets}
    else:
        page_of = {}
        for sh in model["sheets"]:
            for r in sh["components"]:
                page_of[r] = sh["name"]
        net_pages = {}
        for nm, inf in nets.items():
            ps = set()
            for r, _mp in inf["nodes"]:
                if r in page_of:
                    ps.add(page_of[r])
            net_pages[nm] = ps

    _meta = model.get("metadata", {})
    L = file_header(page["name"], rev=_meta.get("version", "4.0"),
                    spec=_meta.get("specification", "Climate Control Niva Travel"))
    L.append('  (lib_symbols')
    for (lib, sym), b in sorted(bodies.items()):
        bb = re.sub(r'^\(symbol "([^"]+)"', '(symbol "%s:%s"' % (lib, sym), b.strip(), count=1)
        L.append('    ' + bb)
    L.append('  )')

    for r in placed:
        lib, sym = ref_lib[r]
        info = comps[r]
        cx, cy = pos[r]
        h = size(r)[1]
        L.append('  (symbol (lib_id "%s:%s") (at %g %g 0) (unit 1)' % (lib, sym, cx, cy))
        L.append('    (in_bom yes) (on_board yes) (uuid "%s")' % uu())
        L.append('    (property "Reference" "%s" (at %g %g 0) (id 0) (effects (font (size 1.27 1.27))))'
                 % (r, cx, cy + h/2 + 2.0))
        L.append('    (property "Value" "%s" (at %g %g 0) (id 1) (effects (font (size 1.27 1.27))))'
                 % (nominal_of(info.get("value", "")), cx, cy - h/2 - 2.0))
        _sim = SIM_MAP.get((lib, sym))
        if _sim:
            if isinstance(_sim, tuple):
                _dev, _lib = _sim
                _fields = (("Sim.Device", _dev), ("Sim.Library", _lib), ("Sim.Name", _dev))
            else:
                _fields = (("Sim.Device", _sim), ("Sim.Library", "Simulation_SPICE"), ("Sim.Name", _sim))
            for _k, _v in _fields:
                L.append('    (property "%s" "%s" (at %g %g 0) (effects (font (size 1.27 1.27)) hide))'
                         % (_k, _v, cx, cy))
        for pnum, *_ in pinlist[(lib, sym)]:
            L.append('    (pin "%s" (uuid "%s"))' % (pnum, uu()))
        L.append('  )')

    for (tname, bx, by, bw, bh) in blocks:
        L.append('  (polyline (pts (xy %g %g) (xy %g %g) (xy %g %g) (xy %g %g) (xy %g %g)) (stroke (width 0.3) (type dash)) (uuid "%s"))'
                 % (bx, by - 20.0, bx + bw, by - 20.0, bx + bw, by + bh, bx, by + bh, bx, by - 20.0, uu()))
        L.append('  (text "%s" (at %g %g 0) (effects (font (size 5 5))) (uuid "%s"))'
                 % (tname, bx + 5.0, by - 28.0, uu()))

    # ---- связи на этом листе
    # карта "реф -> зона" и правая шина каждой зоны (для проводов)
    zone_by_ref = {}
    ztrunk = {}
    if model.get("_groups"):
        for grp in model["_groups"]:
            for r in grp["components"]:
                zone_by_ref[r] = grp["name"]
        for (zname, zx, zy, zw, zh) in blocks:
            ztrunk[zname] = zx + zw - 8.0
    # собрать узлы каждой цепи на этом листе (реф, реальный пин, координаты)
    net_items = {}
    for nm, inf in nets.items():
        items = []
        for ref, mp in inf["nodes"]:
            if ref not in ref_lib:
                continue
            lib, sym = ref_lib[ref]
            real = node_pin[(ref, mp)]
            x, y = pin_coord(pinlist[(lib, sym)], real)
            cx, cy = pos[ref]
            gx, gy = cx + x, cy - y
            if x <= -2.0:
                ex, ey = gx - 3.0, gy
            elif x >= 2.0:
                ex, ey = gx + 3.0, gy
            elif y >= 2.0:
                ex, ey = gx, gy - 3.0
            else:
                ex, ey = gx, gy + 3.0
            items.append((ref, real, gx, gy, ex, ey))
        net_items[nm] = items

    zcounter = {}
    for nm, inf in nets.items():
        items = net_items.get(nm, [])
        if not items:
            continue
        # рисуем проводом, если вся цепь в одной зоне
        wired = False
        if zone_by_ref and ztrunk:
            zones = set(zone_by_ref.get(it[0], "") for it in items)
            zname = next(iter(zones)) if (len(zones) == 1 and "" not in zones) else None
            if zname and zname in ztrunk:
                zcounter[zname] = zcounter.get(zname, 0) + 1
                tx = ztrunk[zname] + zcounter[zname] * 1.6
                ys = [it[3] for it in items]
                L.append('  (wire (pts (xy %g %g) (xy %g %g)) (stroke (width 0) (type solid) (color 0 0 0 0)) (uuid "%s"))'
                         % (tx, min(ys), tx, max(ys), uu()))
                for it in items:
                    L.append('  (wire (pts (xy %g %g) (xy %g %g)) (stroke (width 0) (type solid) (color 0 0 0 0)) (uuid "%s"))'
                             % (it[2], it[3], tx, it[3], uu()))
                wired = True
        if wired:
            continue
        # иначе: короткий проводок + метка (для межзональных цепей)
        for it in items:
            L.append('  (wire (pts (xy %g %g) (xy %g %g)) (stroke (width 0) (type solid) (color 0 0 0 0)) (uuid "%s"))'
                     % (it[2], it[3], it[4], it[5], uu()))
            if model.get("_single"):
                L.append('  (label "%s" (at %g %g 0) (effects (font (size 1.27 1.27))) (uuid "%s"))'
                         % (nm, it[4], it[5], uu()))
            else:
                L.append('  (hierarchical_label "%s" (at %g %g 0) (effects (font (size 1.27 1.27))) (uuid "%s"))'
                         % (nm, it[4], it[5], uu()))

    # ---- листы-ссылки: НЕ ГЕНЕРИРУЕМ (формат не читается этой сборкой),
    #      страницы добавляются вручную в KiCad (Place -> Hierarchical Sheet)
    if False and is_root:
        SIZES = {"CAN":30,"PWR":85,"UI":80,"SEN_CABIN":30,"SEN_HEAT":25,
                 "SEN_SOLAR":22,"SEN_COND":22,"OUT":45,"ACT":92}
        for i, sh in enumerate(other_pages):
            h = SIZES.get(sh["name"], 40)
            bx = 90 + (i % 3) * 150
            by = 30 + (i // 3) * (h + 60)
            W = 80.0
            L.append('  (sheet')
            L.append('    (at %g %g 0)' % (bx, by))
            L.append('    (size %g %g)' % (W, h))
            L.append('    (fields_autoplaced yes)')
            L.append('    (stroke')
            L.append('      (width 0.1524)')
            L.append('      (type solid)')
            L.append('      (color 0 0 0 0)')
            L.append('    )')
            L.append('    (fill')
            L.append('      (color 0 0 0 0.0)')
            L.append('    )')
            L.append('    (uuid "%s")' % uu())
            L.append('    (property "Sheetname" "%s"' % sh["name"])
            L.append('      (at %g %g 0)' % (bx, by))
            L.append('      (effects (font (size 1.27 1.27)) (justify left bottom))')
            L.append('    )')
            L.append('    (property "Sheetfile" "%s"' % sh["file"])
            L.append('      (at %g %g 0)' % (bx, by))
            L.append('      (effects (font (size 1.27 1.27)) (justify left top))')
            L.append('    )')
            L.append('    (instances')
            L.append('      (project ""')
            L.append('        (path "/"')
            L.append('          (page "%d")' % sh["order"])
            L.append('        )')
            L.append('      )')
            L.append('    )')
            L.append('  )')

    L.append(')')
    with open(page_path, "w", encoding="utf-8") as f:
        f.write('\n'.join(L))
    return len(placed)

# ============================================================================
#  СБОРКА ВСЕХ ЛИСТОВ
# ============================================================================
def compile_kicad_schematic_from_json(sch_path, model_path):
    with open(model_path, "r", encoding="utf-8") as f:
        model = json.load(f)
    if os.environ.get("CC_MULTI") and "sheets" in model:
        sheets = model["sheets"]
    else:
        # Режим одного листа (по умолчанию): все компоненты на одном листе,
        # но раскладка - функциональными блоками из model["sheets"]
        groups = model.get("sheets")
        all_refs = sorted(r for r, i in model["components"].items() if not i.get("virtual"))
        if groups:
            model["_groups"] = groups
        model["_single"] = True
        model["sheets"] = [{"order": 1, "name": "MAIN", "file": "climate_control_niva_travel.kicad_sch",
                            "components": all_refs}]
    sheets = model["sheets"]
    root = sheets[0]
    others = sheets[1:]
    base = os.path.dirname(os.path.abspath(sch_path)) or "."
    total = 0
    for i, sh in enumerate(sheets):
        path = os.path.join(base, sh["file"])
        is_root = (i == 0 and not model.get("_single"))
        n = write_page(model, sh, path, is_root, others if is_root else [])
        print("  страница %d %-10s -> %s (%d комп.)" % (sh["order"], sh["name"], sh["file"], n))
        total += n
    print("✅ Сформировано страниц: %d, компонентов на страницах: %d" % (len(sheets), total))

# ============================================================================
def import_dxf_contour_to_board(pcb_path, dxf_path):
    pass

if __name__ == "__main__":
    PROJECT_DIR = "/home/vitaly-pc/kicad/climate_control_niva_travel"
    JSON_MODEL = os.path.join(PROJECT_DIR, "circuit_model.json")
    SCH_FILE = os.path.join(PROJECT_DIR, "climate_control_niva_travel.kicad_sch")
    compile_kicad_schematic_from_json(SCH_FILE, JSON_MODEL)
