#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wire_root.py — построение связей на листах схемы по circuit_model.json.

Для каждого вывода каждого компонента листа, входящего в какую-либо цепь,
рисуется короткий провод-отвод от пина и ставится метка с именем цепи:

  * корневая страница (CONTROLLER)             -> обычные метки (label);
  * дочерние листы, у цепи есть пин листа на корне -> иерархические метки
    (hierarchical_label), чтобы связаться с этим пином;
  * дочерние листы, локальная цепь              -> обычные метки.

Метка ставится в направлении вывода (справа/слева/сверху/снизу от пина),
точка соединения метки — на краю текста, поэтому провод не проходит через
надпись: для выводов справа текст идёт вправо от точки (justify left),
для выводов слева — влево (justify right).

Пины листов-ссылок на корне тоже получают провод-отвод и метку (метка
правее пина, текст вправо), чтобы не накладываться на имя пина листа.

Скрипт идемпотентен: перед перестроением удаляет все прежние провода и метки
на листе. Листы-ссылки дополнительно привязываются к сетке 1.27 мм, чтобы
провода от их пинов были на сетке. Для пинов компонентов, не входящих ни в
одну цепь (резерв, свободные выводы МК), ставятся маркеры no_connect.

Запуск:
    python3 wire_root.py          # все листы
    python3 wire_root.py --dry    # показать, что будет сделано, без записи
"""
import json
import os
import re
import sys
import uuid
import importlib.util

PROJ = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(PROJ, "circuit_model.json")
GRID = 1.27
STUB = 2.54  # длина отвода (2 x 1.27 — на сетке схемы)

def uu():
    return str(uuid.uuid4())

spec = importlib.util.spec_from_file_location("g", os.path.join(PROJ, "build_project.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


# --------------------------------------------------------------------------
#  Парсинг текущих .kicad_sch
# --------------------------------------------------------------------------
def parse_symbols(text):
    """Символы листа: {ref: (lib_id, cx, cy)}."""
    out = {}
    for m in re.finditer(
        r'\(symbol\s+\(lib_id "([^"]+)"\)\s+\(at ([\d.]+) ([\d.-]+) 0\)(.*?)\n\s*\(instances',
        text, re.S):
        lib_id, cx, cy, body = m.group(1), float(m.group(2)), float(m.group(3)), m.group(4)
        rm = re.search(r'\(property "Reference" "([^"]+)"', body)
        if rm:
            out[rm.group(1)] = (lib_id, cx, cy)
    return out


def parse_sheet_blocks(text):
    """Листы-ссылки: [{name, file, x, y, w, h, pins:[(name,x,y)]}]."""
    out = []
    for m in re.finditer(r'\(sheet\s+(.*?)\n\s*\(instances', text, re.S):
        block = m.group(1)
        at = re.search(r'\(at ([\d.]+) ([\d.-]+) 0\)', block)
        sz = re.search(r'\(size ([\d.]+) ([\d.-]+)\)', block)
        nm = re.search(r'\(property "Sheetname" "([^"]+)"', block)
        fl = re.search(r'\(property "Sheetfile" "([^"]+)"', block)
        pins = [(p.group(1), float(p.group(2)), float(p.group(3)))
                for p in re.finditer(r'\(pin "([^"]+)"\s+\w+\s+\(at ([\d.]+) ([\d.-]+) 0\)', block)]
        if at and nm and fl:
            out.append({"name": nm.group(1), "file": fl.group(1),
                        "x": float(at.group(1)), "y": float(at.group(2)),
                        "w": float(sz.group(1)) if sz else 80.0,
                        "h": float(sz.group(2)) if sz else 30.0,
                        "pins": pins})
    return out


def snap_sheets(text):
    """Привязать листы-ссылки и их пины к сетке GRID (1.27 мм)."""
    def snap(v):
        return round(round(v / GRID) * GRID, 3)

    def repl_block(m):
        block = m.group(0)
        am = re.search(r'\(at ([\d.]+) ([\d.-]+)\)', block)
        if not am:
            return block
        x, y = float(am.group(1)), float(am.group(2))
        xs, ys = snap(x), snap(y)
        # пины листа: положение должно остаться на границе листа и на сетке
        pinlist = [(p.group(1), p.group(2), p.group(3))
                   for p in re.finditer(r'\(pin "([^"]+)"\s+\w+\s+\(at ([\d.]+) ([\d.-]+) 0\)', block)]
        snapped_pins = []
        for nm, px, py in pinlist:
            snapped_pins.append((nm, snap(float(px)), snap(float(py))))
        # размер листа: правая граница = крайним пинам, нижняя = последнему пину
        if snapped_pins:
            w = max(pp[1] for pp in snapped_pins) - xs
            h = max(pp[2] for pp in snapped_pins) - ys + 2.54
            w = max(round(w / GRID) * GRID, GRID)
            h = max(round(h / GRID) * GRID, GRID)
        else:
            w = round(float(re.search(r'\(size ([\d.]+) ', block).group(1)) / GRID) * GRID
            h = round(float(re.search(r'\(size ([\d.]+) ([\d.-]+)\)', block).group(2)) / GRID) * GRID
        block = block[:am.start()] + "(at %.3f %.3f)" % (xs, ys) + block[am.end():]
        sm = re.search(r'\(size ([\d.]+) ([\d.-]+)\)', block)
        block = block[:sm.start()] + "(size %.3f %.3f)" % (w, h) + block[sm.end():]
        for nm, pxs, pys in snapped_pins:
            pm = re.search(r'(\(pin "%s"\s+\w+\s+)(\(at [\d.-]+ [\d.-]+ 0\))' % re.escape(nm), block)
            if pm:
                block = block[:pm.start()] + pm.group(1) + "(at %.3f %.3f 0)" % (pxs, pys) + block[pm.end():]
        return block
    return re.sub(r'\(sheet\s+.*?\n\s*\(instances', repl_block, text, flags=re.S)


def remove_elements(text, tag):
    """Удалить все элементы `(tag ...)` вместе с предшествующими пробелами."""
    res, i = [], 0
    while True:
        pat = text.find("(%s " % tag, i)
        if pat < 0:
            res.append(text[i:])
            break
        start = pat
        k = pat - 1
        while k >= 0 and text[k] in " \t\n":
            start = k
            k -= 1
        j, depth = pat, 0
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        res.append(text[i:start])
        i = j + 1
    return "".join(res)


def remove_named_pins(text, names):
    """Удалить из листов-ссылок пины с именами из `names` (локальные цепи)."""
    if not names:
        return text
    res, i = [], 0
    while True:
        pat = -1
        for nm in names:
            idx = text.find('(pin "%s" ' % nm, i)
            if idx >= 0 and (pat < 0 or idx < pat):
                pat = idx
        if pat < 0:
            res.append(text[i:])
            break
        start = pat
        k = pat - 1
        while k >= 0 and text[k] in " \t\n":
            start = k
            k -= 1
        j, depth = pat, 0
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        res.append(text[i:start])
        i = j + 1
    return "".join(res)


def lib_symbols_end(text):
    """Индекс сразу после закрывающей скобки блока (lib_symbols ...)."""
    i = text.find("(lib_symbols")
    if i < 0:
        return len(text.rstrip())
    depth, j = 0, i
    while j < len(text):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return j + 1


def stub_side(ang):
    """Направление отвода по углу пина в символе.

    Эмпирически (по символам MCU_ST_STM32F1 и Device): 0 -> влево,
    90 -> вниз, 180 -> вправо, 270 -> вверх. Именно по углу, а не по
    смещению (x, y): угловые пины (например VDD/VDDA на верхней грани)
    иначе получают горизонтальный отвод и замыкаются на соседние пины.
    """
    a = int(round(ang)) % 360
    if a == 0:
        return "left"
    if a == 90:
        return "down"
    if a == 180:
        return "right"
    if a == 270:
        return "up"
    return "right"


def label_pos(gx, gy, side):
    """Конец отвода (точка соединения метки) для пина (gx, gy)."""
    if side == "left":
        return gx - STUB, gy
    if side == "right":
        return gx + STUB, gy
    if side == "up":
        return gx, gy - STUB
    return gx, gy + STUB


def wire_line(x1, y1, x2, y2):
    return ('\t(wire (pts (xy %g %g) (xy %g %g)) '
            '(stroke (width 0) (type solid) (color 0 0 0 0)) (uuid "%s"))'
            % (x1, y1, x2, y2, uu()))


def label_line(net, x, y, hier, justify_right=False):
    if hier:
        fmt = '\t(hierarchical_label "%s" (shape input) (at %g %g 0) (effects (font (size 1.27 1.27))%s) (uuid "%s"))'
    else:
        fmt = '\t(label "%s" (at %g %g 0) (effects (font (size 1.27 1.27))%s) (uuid "%s"))'
    jf = " (justify right)" if justify_right else ""
    return fmt % (net, x, y, jf, uu())


def nc_line(x, y):
    return '\t(no_connect (at %g %g) (uuid "%s"))' % (x, y, uu())


# --------------------------------------------------------------------------
#  PWR_FLAG: источник питания для ERC на силовых цепях
# --------------------------------------------------------------------------
def root_path_uuid(text):
    """UUID корневого пути из первого экземпляра символа."""
    m = re.search(r'\(path "/([0-9a-f-]+)"', text)
    return m.group(1) if m else None


def remove_power_flags(text):
    """Удалить экземпляры PWR_FLAG, добавленные предыдущими запусками."""
    res, i = [], 0
    while True:
        pat = text.find('(symbol\n\t\t(lib_id "power:PWR_FLAG")', i)
        if pat < 0:
            res.append(text[i:])
            break
        start = pat
        k = pat - 1
        while k >= 0 and text[k] in " \t\n":
            start = k
            k -= 1
        j, depth = pat, 0
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        res.append(text[i:start])
        i = j + 1
    return "".join(res)


def remove_lib_symbol(text, name):
    """Удалить все вхождения описания символа `(symbol "name" ...)`."""
    res, i = [], 0
    pat_s = '(symbol "%s"' % name
    while True:
        pat = text.find(pat_s, i)
        if pat < 0:
            res.append(text[i:])
            break
        start = pat
        k = pat - 1
        while k >= 0 and text[k] in " \t\n":
            start = k
            k -= 1
        j, depth = pat, 0
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        res.append(text[i:start])
        i = j + 1
    return "".join(res)


def add_power_flags(text, flags):
    """Добавить PWR_FLAG на силовые цепи корня (GND, VDDA_3V3, VCC_12V).

    flags: [(имя_цепи, ref, x, y)]  — ставится символ PWR_FLAG, его пин
    соединяется проводом-отводом с меткой имени цепи.
    Возвращает (текст, список строк для вставки символов).
    """
    body = g.symbol_body("power", "PWR_FLAG")
    if not body:
        return text, []
    body = re.sub(r'^\(symbol "([^"]+)"', '(symbol "power:PWR_FLAG"', body.strip(), count=1)
    ruid = root_path_uuid(text)
    # перестраиваем описание символа в (lib_symbols ...) начисто
    text = remove_lib_symbol(text, "power:PWR_FLAG")
    i = text.find("(lib_symbols")
    depth, j = 0, i
    while j < len(text):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                break
        j += 1
    text = text[:j] + "\n\t\t" + body + "\n\t" + text[j:]

    lines = []
    for nm, ref, x, y in flags:
        sym = (
            '\t(symbol\n'
            '\t\t(lib_id "power:PWR_FLAG")\n'
            '\t\t(at %g %g 0)\n'
            '\t\t(unit 1)\n'
            '\t\t(exclude_from_sim no)\n'
            '\t\t(in_bom no)\n'
            '\t\t(on_board yes)\n'
            '\t\t(dnp no)\n'
            '\t\t(fields_autoplaced no)\n'
            '\t\t(uuid "%s")\n'
            '\t\t(property "Reference" "%s"\n'
            '\t\t\t(at %g %g 0)\n'
            '\t\t\t(effects (font (size 1.27 1.27)))\n'
            '\t\t)\n'
            '\t\t(property "Value" "PWR_FLAG"\n'
            '\t\t\t(at %g %g 0)\n'
            '\t\t\t(effects (font (size 1.27 1.27)))\n'
            '\t\t)\n'
            '\t\t(pin "1" (uuid "%s"))\n'
            '\t\t(instances\n'
            '\t\t\t(project "CONTROLLER"\n'
            '\t\t\t\t(path "/%s"\n'
            '\t\t\t\t\t(reference "%s")\n'
            '\t\t\t\t\t(unit 1)\n'
            '\t\t\t\t)\n'
            '\t\t\t)\n'
            '\t\t)\n'
            '\t)'
        ) % (x, y, uu(), ref, x, y, x, y, uu(), ruid, ref)
        lines.append(sym)
        lines.append(wire_line(x, y, x, y + STUB))
        lines.append(label_line(nm, x, y + STUB, False, False))
    return text, lines


# --------------------------------------------------------------------------
def wire_sheet(path, sheet_name, is_root, local_nets, sheet_pin_names):
    text = open(path, encoding="utf-8").read()
    if is_root:
        text = snap_sheets(text)
        # пины листов для цепей, локальных для дочернего листа, не нужны —
        # убираем их, чтобы не было "label_dangling"/"hier_label_mismatch"
        text = remove_named_pins(text, local_nets)
    # Полностью перестраиваем слой связей: удаляем прежние провода, метки,
    # иерархические метки, маркеры no_connect и добавленные PWR_FLAG.
    for tag in ("label", "hierarchical_label", "wire", "no_connect"):
        text = remove_elements(text, tag)
    if is_root:
        text = remove_power_flags(text)
    comps = parse_symbols(text)
    if not comps:
        return 0
    refs = set(comps)
    lines = []
    nc_lines = []

    for ref in sorted(refs):
        info = model["components"].get(ref)
        if not info or info.get("virtual"):
            continue
        lib, sym = info["library"], info["sym_name"]
        body = g.symbol_body(lib, sym)
        if body is None:
            continue
        pins = g.extract_pins(body)
        cx, cy = comps[ref][1], comps[ref][2]
        # номер реального пина -> имя цепи (для no_connect и меток)
        real_to_net = {}
        for nm, inf in nets.items():
            for r, mp in inf["nodes"]:
                if r != ref:
                    continue
                try:
                    real_to_net.setdefault(g.resolve_pin(lib, sym, mp, pins), nm)
                except Exception:
                    continue
        for num, _name, _ptype, x, y, ang in pins:
            gx, gy = cx + x, cy - y
            node = real_to_net.get(num)
            if node is None:
                nc_lines.append(nc_line(gx, gy))
                continue
            side = stub_side(ang)
            ex, ey = label_pos(gx, gy, side)
            hier = (not is_root) and node in sheet_pin_names.get(sheet_name, set())
            justify_right = (side == "left")
            lines.append(wire_line(gx, gy, ex, ey))
            lines.append(label_line(node, ex, ey, hier, justify_right))

    if is_root:
        for block in parse_sheet_blocks(text):
            for nm, px, py in block["pins"]:
                ex, ey = px + STUB, py
                lines.append(wire_line(px, py, ex, ey))
                lines.append(label_line(nm, ex, ey, False, False))
        # силовые цепи: PWR_FLAG, чтобы ERC не ругался на недрайверные пины
        pflags = [("GND", "#FLG1", 60.96, 400.05),
                  ("VDDA_3V3", "#FLG2", 121.92, 400.05),
                  ("VCC_12V", "#FLG3", 182.88, 400.05)]
        text, flag_lines = add_power_flags(text, pflags)
        lines.extend(flag_lines)

    if not lines and not nc_lines:
        return 0
    if DRY:
        return (len(lines) + len(nc_lines))
    block = "\n".join(lines + nc_lines) + "\n"
    idx = lib_symbols_end(text)
    text = text[:idx] + block + text[idx:]
    open(path, "w", encoding="utf-8").write(text)
    return len(lines) + len(nc_lines)


def main():
    global model, nets, DRY
    DRY = "--dry" in sys.argv
    model = json.load(open(MODEL_PATH, encoding="utf-8"))
    nets = model["nets"]

    # цепи, существующие только на одном листе (пины листов для них не нужны)
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
    local_nets = {nm for nm, ps in net_pages.items() if len(ps) <= 1}

    # пины листов по имени листа (для выбора типа метки на дочерних листах);
    # пины локальных цепей исключаем — они будут удалены на корне
    root_text = open(os.path.join(PROJ, model["sheets"][0]["file"]), encoding="utf-8").read()
    sheet_pin_names = {}
    for block in parse_sheet_blocks(root_text):
        sheet_pin_names[block["name"]] = {p[0] for p in block["pins"] if p[0] not in local_nets}

    total = 0
    for sh in model["sheets"]:
        path = os.path.join(PROJ, sh["file"])
        if not os.path.exists(path):
            print("  пропуск (нет файла):", sh["file"])
            continue
        n = wire_sheet(path, sh["name"], sh["order"] == 1, local_nets, sheet_pin_names)
        mode = "DRY" if DRY else "ok "
        print("  [%s] %-6s %-24s элементов: %4d" % (mode, sh["order"], sh["name"], n))
        total += n
    print("итого: %d элементов связей" % total)


if __name__ == "__main__":
    main()