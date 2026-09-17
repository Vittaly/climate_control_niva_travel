#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор многостраничной схемы KiCad из circuit_model.json (kicad-sch-api).

Что делает генератор:

1. Внутри КАЖДОЙ страницы (в т.ч. дочерних) компоненты, принадлежащие одной
   цепи из JSON, соединяются ПРОВОДАМИ (орто-маршрут с обходом корпусов),
   а не только подписываются метками.

2. Компоновка определяется ВЗАИМОСВЯЗЯМИ компонентов:
   - сигнальные (не шинные) цепи образуют кластеры; внутри кластера раскладка
     слоями (BFS) СЛЕВА НАПРАВО от корневого компонента, поэтому связанные
     компоненты стоят рядом и провода короткие;
   - шинные цепи (GND, VCC_12V, VCC_5V, VCC_3V3, V5_SENS, VDDA_3V3) рисуются
     горизонтальными ШИНАМИ сверху/снизу страницы, каждый потребитель
     подключается коротким отводом;
   - межстраничные/внешние цепи (на другие листы или виртуальные устройства)
     получают короткий проводок + иерархическую метку (пин листа).

3. Корневая страница дополнительно получает иерархические листы-ссылки
   на дочерние страницы с пинами (каждой граничной цепи - пин на рамке листа).

Запуск:
    env/bin/python gen_schematic.py
"""
import json
import math
import os
import re
import sys
from collections import defaultdict, deque

from kicad_sch_api import Schematic

_REF_RE = re.compile(r"^(#[A-Z]+[0-9]+|[A-Z]+[0-9]*[A-Z]?|[A-Z]+\?)$")


def re_match_ref(ref):
    return bool(_REF_RE.match(ref))

PROJ = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(PROJ, "circuit_model.json")
OUT_DIR = PROJ

# ============================================================================
#  КОНСТАНТЫ КОМПОНОВКИ (мм; все - кратные 1.27, чтобы концы проводов были на сетке)
# ============================================================================
GRID = 1.27
X0, Y0 = 63.5, 76.2                    # начало контента (50, 60)
COL_SP = 76.2                          # шаг колонки внутри кластера (BFS-слой)
ROW_SP = 45.72                         # шаг строки внутри слоя
CLUSTER_GAP_X = 101.6                  # зазор между кластерами по горизонтали
CLUSTER_GAP_Y = 88.9                   # зазор между рядами кластеров
MAX_ROW_W = 1143.0                     # макс. ширина ряда кластеров (900)
STUB_LEN = 3.81                        # длина отвода для граничной цепи
BODY_MARGIN = 3.0                      # запас корпуса при проверке пересечений
OFFSETS = (5.08, 10.16, 15.24, 22.86, 35.56, 50.8, 76.2, 127.0)  # выносы маршрута

BUS_NETS = {"GND", "VCC_12V", "VCC_5V", "VCC_3V3", "V5_SENS", "VDDA_3V3"}

# номера выводов транзисторов в модели (1/2/3) -> имена выводов в символах
TRAN_PIN = {
    "Q_NMOS": {"1": "G", "2": "D", "3": "S"},
    "Q_NPN":  {"1": "B", "2": "C", "3": "E"},
    "Q_PNP":  {"1": "B", "2": "C", "3": "E"},
}

CAT_RANK = {
    "MCU": 0, "Motor_Driver": 1, "Regulator_5V": 2, "Regulator_3V3": 3,
    "Power_Protection": 4, "Filter_Power": 5, "Filter_Decoupling": 6,
    "Filter_Analog": 7, "Connector_Main": 8, "Connector_UI": 9,
    "Debug_Connector": 10, "Switch_OpenDrain": 11, "Switch_Load": 12,
    "Switch_12V": 13, "Analog_Condition": 14, "RC_Reset": 15,
    "Sensor_Cabin": 16, "UI_Button": 17, "UI_LED": 18, "CAN_Transceiver": 19,
}

PAPERS = [("A4", 297, 210), ("A3", 420, 297), ("A2", 594, 420),
          ("A1", 841, 594), ("A0", 1189, 841)]

# В символах Device:D*/D_Schottky/D_Zener вывод 1 = КАТОД (K), 2 = АНОД (A),
# в модели принято наоборот (1 = анод).
DIODE_SWAP = {"D", "D_Schottky", "D_Zener"}


def real_pin(info, model_pin):
    """Модельный пин -> номер вывода символа."""
    sym = info.get("sym_name")
    mp = str(model_pin)
    if sym in DIODE_SWAP:
        # в символах Device:D*/D_Schottky/D_Zener вывод 1 = КАТОД, 2 = АНОД,
        # в модели принято наоборот (1 = анод) - меняем местами
        return {"1": "2", "2": "1"}.get(mp, mp)
    t = TRAN_PIN.get(sym)
    return t.get(mp, mp) if t else mp


def sanitize_ref(ref):
    """KiCad требует ссылки вида 'буквы+цифры' (C_GATE/L_OUT/C_OUT стенда FAN_KEY)."""
    if re_match_ref(ref):
        return ref
    s = re.sub(r"[^A-Za-z0-9]", "", ref.upper())
    if not s:
        return "X1"
    if not s[-1].isdigit():
        s += "1"
    return s


def nominal_of(value):
    """Обрезать скобки/кириллицу в значении (для поля Value)."""
    tokens = str(value).split()
    if not tokens:
        return ""
    acc = []
    for t in tokens:
        c0 = t[0]
        cyr = "\u0400" <= c0 <= "\u04FF"
        if not acc and cyr:
            return str(value)
        if acc and (cyr or c0 in "(\u2116"):
            break
        if not acc and c0 in "(\u2116":
            return str(value)
        acc.append(t)
    return " ".join(acc) if acc else str(value)


# ============================================================================
#  ГЕОМЕТРИЯ / МАРШРУТИЗАЦИЯ
# ============================================================================
def clip_t(p1, p2, rect):
    """Параметрический отрезок [p1,p2] против rect; вернуть (t0,t1) или None."""
    x1, y1 = p1
    x2, y2 = p2
    xmin, ymin, xmax, ymax = rect
    t0, t1 = 0.0, 1.0
    dx, dy = x2 - x1, y2 - y1

    def upd(lo, hi, d, c):
        nonlocal t0, t1
        if abs(d) < 1e-9:
            return lo <= c <= hi
        ta, tb = (lo - c) / d, (hi - c) / d
        if ta > tb:
            ta, tb = tb, ta
        t0 = max(t0, ta)
        t1 = min(t1, tb)
        return t0 <= t1

    if not (upd(xmin, xmax, dx, x1) and upd(ymin, ymax, dy, y1)):
        return None
    return (t0, t1)


def segment_clear(p1, p2, bodies, allow=None, cap=1.6):
    """True, если отрезок не пересекает корпуса (кроме малой зоны у своих выводов).

    bodies: list[(xmin, ymin, xmax, ymax, owner_ref)]
    allow:  dict {point: ref} - точки-концы, которым разрешена зона cap у своего корпуса
    """
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    L = math.hypot(dx, dy) or 1e-9
    for rect in bodies:
        xmin, ymin, xmax, ymax, owner = rect
        cl = clip_t(p1, p2, (xmin, ymin, xmax, ymax))
        if cl is None:
            continue
        t0, t1 = cl
        ov = (t1 - t0) * L
        if ov <= 0.05:
            continue
        # разрешена только малая зона у собственного вывода
        if allow:
            o1 = allow.get(p1)
            if o1 == owner and t0 < 0.5 and t1 <= cap / L:
                continue
            o2 = allow.get(p2)
            if o2 == owner and t1 > 0.5 and t0 >= 1 - cap / L:
                continue
        return False
    return True


def poly_length(poly):
    return sum(abs(poly[i + 1][0] - poly[i][0]) + abs(poly[i + 1][1] - poly[i][1])
               for i in range(len(poly) - 1))


def snap_poly(poly, fixed=None, g=GRID):
    """Привести полилинию к сетке, сохраняя ортогональность сегментов.

    Точки с индексами из fixed не сдвигаются (это выводы/точки контакта).
    """
    if fixed is None:
        fixed = {0, len(poly) - 1}
    pts = [list(p) for p in poly]
    for i in range(len(pts)):
        if i not in fixed:
            pts[i][0] = round(pts[i][0] / g) * g
            pts[i][1] = round(pts[i][1] / g) * g
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = poly[i], poly[i + 1]
        if abs(y1 - y2) < 1e-9:          # горизонтальный сегмент: выровнять Y
            pts[i][1] = pts[i + 1][1] = pts[i][1]
        elif abs(x1 - x2) < 1e-9:        # вертикальный: выровнять X
            pts[i][0] = pts[i + 1][0] = pts[i][0]
    return [tuple(p) for p in pts]


def point_on_segment(p, p1, p2, tol=0.13):
    """Точка p лежит на отрезке p1-p2 (допуск tol, мм)."""
    px, py = p
    x1, y1 = p1
    x2, y2 = p2
    if abs(x1 - x2) < 1e-9:                      # вертикальный
        return abs(px - x1) < tol and min(y1, y2) - tol <= py <= max(y1, y2) + tol
    if abs(y1 - y2) < 1e-9:                      # горизонтальный
        return abs(py - y1) < tol and min(x1, x2) - tol <= px <= max(x1, x2) + tol
    # диагональ - проверим расстояние до отрезка
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return (px - x1) ** 2 + (py - y1) ** 2 < tol * tol
    t = ((px - x1) * dx + (py - y1) * dy) / L2
    t = max(0.0, min(1.0, t))
    cx, cy = x1 + t * dx, y1 + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2 < tol * tol


def route_between(a, b, bodies, allow=None, dirs=None, pin_pts=None):
    """Орто-маршрут от вывода a к выводу b.

    Приоритеты: (1) не касаться чужих выводов (иначе это электрическое
    соединение); (2) не пересекать корпуса; (3) короче. Пересечение проводов
    допускается.
    """
    cands = []
    if abs(a[0] - b[0]) < 0.1 or abs(a[1] - b[1]) < 0.1:
        cands.append([a, b])
    cands.append([a, (b[0], a[1]), b])
    cands.append([a, (a[0], b[1]), b])
    da = (dirs or {}).get(a, (1, 0))
    db = (dirs or {}).get(b, (-1, 0))
    for O in OFFSETS:
        ax, ay = a[0] + da[0] * O, a[1] + da[1] * O
        bx, by = b[0] + db[0] * O, b[1] + db[1] * O
        cands.append([a, (ax, ay), (bx, ay), b])
        cands.append([a, (ax, ay), (ax, by), b])
        cands.append([a, (ax, ay), (bx, ay), (bx, by), b])
        cands.append([a, (ax, ay), (ax, by), (bx, by), b])

    own = {a, b}
    pin_pts = pin_pts or []
    safe_pts = [p for p in pin_pts if p not in own]

    def touch_count(poly):
        n = 0
        for i in range(len(poly) - 1):
            for pp in safe_pts:
                if point_on_segment(pp, poly[i], poly[i + 1]):
                    n += 1
        return n

    def body_clear(poly):
        return all(segment_clear(poly[i], poly[i + 1], bodies, allow)
                   for i in range(len(poly) - 1))

    clean = [c for c in cands if body_clear(c) and touch_count(c) == 0]
    if clean:
        poly = min(clean, key=poly_length)
    else:
        # пересечение корпусов допустимо, но нельзя задевать чужие выводы
        safe = [c for c in cands if touch_count(c) == 0]
        if safe:
            poly = min(safe, key=poly_length)
        else:
            poly = min(cands, key=lambda c: (touch_count(c), poly_length(c)))
    return snap_poly(poly, fixed={0, len(poly) - 1})


# ============================================================================
# ============================================================================
#  КОМПОНОВКА СТРАНИЦЫ
# ============================================================================
def layout_cluster(refs, adj, sizes):
    """BFS-раскладка кластера слоями слева направо. Возвращает pos: ref->(x,y)."""
    root = max(refs, key=lambda r: (len(adj[r]), -CAT_RANK.get(comps[r]["type"], 99)))
    layer = {root: 0}
    order = []
    q = deque([root])
    while q:
        r = q.popleft()
        order.append(r)
        for nb in sorted(adj[r]):
            if nb not in layer:
                layer[nb] = layer[r] + 1
                q.append(nb)
    L = max(layer.values())
    layers = defaultdict(list)
    for r in order:
        layers[layer[r]].append(r)

    pos = {}
    n0 = len(layers[0])
    for i, r in enumerate(layers[0]):
        pos[r] = (0.0, (i - (n0 - 1) / 2.0) * ROW_SP)
    placed = set(layers[0])
    for l in range(1, L + 1):
        row = layers[l]
        scored = []
        for r in row:
            nb = [x for x in adj[r] if x in placed]
            bc = sum(pos[x][1] for x in nb) / len(nb) if nb else 0.0
            scored.append((bc, r))
        scored.sort(key=lambda t: (t[0], t[1]))
        n = len(scored)
        for i, (_bc, r) in enumerate(scored):
            pos[r] = (l * COL_SP, (i - (n - 1) / 2.0) * ROW_SP)
        placed.update(row)
    return pos


def cluster_bbox(refs, pos, sizes):
    xs0 = [pos[r][0] - sizes[r][0] / 2 for r in refs]
    xs1 = [pos[r][0] + sizes[r][0] / 2 for r in refs]
    ys0 = [pos[r][1] - sizes[r][1] / 2 for r in refs]
    ys1 = [pos[r][1] + sizes[r][1] / 2 for r in refs]
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def paper_for(w, h):
    for name, pw, ph in PAPERS:
        if w <= pw - 60 and h <= ph - 60:
            return name
    return "A0"


# ============================================================================
#  ГЕНЕРАЦИЯ ОДНОЙ СТРАНИЦЫ
# ============================================================================
def build_page(model, sheet, is_root=False):
    global comps, nets
    comps = model["components"]
    nets = model["nets"]
    placed = [r for r in sheet["components"] if r in comps and not comps[r].get("virtual")]
    if not placed:
        # страница целиком виртуальная (напр. тестовый стенд FAN_KEY) - рисуем всё равно
        placed = [r for r in sheet["components"] if r in comps]
    if not placed:
        return None

    sch = Schematic.create(name=sheet["name"], paper="A0")
    comp_obj, sizes = {}, {}
    pin_local = {}      # ref -> {real_pin: (lx, ly)}  локальные координаты вывода
    pin_dir = {}        # ref -> {real_pin: (dx, dy)}
    for r in placed:
        info = comps[r]
        lib_id = "%s:%s" % (info["library"], info["sym_name"])
        try:
            c = sch.components.add(lib_id, reference=sanitize_ref(r),
                                   value=nominal_of(info.get("value", "")),
                                   position=(0.0, 0.0))
        except Exception as e:
            print("  ! комп %s: %s" % (r, e))
            continue
        comp_obj[r] = c
        pins = c.list_pins()
        xs = [p["position"].x for p in pins]
        ys = [p["position"].y for p in pins]
        minx, maxx = (min(xs), max(xs)) if xs else (-2.54, 2.54)
        miny, maxy = (min(ys), max(ys)) if ys else (-2.54, 2.54)
        # паддинг кратен 1.27, чтобы полуширина оставалась на сетке (и центры - на сетке)
        w = max(maxx - minx, 5.08) + 5.08
        h = max(maxy - miny, 5.08) + 5.08
        sizes[r] = (w, h)
        pin_local[r] = {}
        pin_dir[r] = {}
        for p in pins:
            num = p["number"]
            lx, ly = p["position"].x, p["position"].y
            pin_local[r][num] = (lx, ly)
            if abs(lx - maxx) < 0.01:
                d = (1, 0)
            elif abs(lx - minx) < 0.01:
                d = (-1, 0)
            elif abs(ly - maxy) < 0.01:
                d = (0, 1)
            elif abs(ly - miny) < 0.01:
                d = (0, -1)
            else:
                d = (1, 0) if lx > 0 else (-1, 0)
            # KiCad ассоциирует провода с выводами по ЗЕРКАЛЬНОЙ по Y координате
            # (ось Y в KiCad направлена вверх). Наружное направление - тоже зеркально.
            pin_dir[r][num] = (d[0], -d[1])

    if not comp_obj:
        return None

    # ---- классификация цепей на этой странице ----
    onpage = {}       # net -> [(ref, model_pin)]
    spans = {}        # net -> bool
    for nm, inf in nets.items():
        op = []
        sp = False
        for ref, mp in inf["nodes"]:
            if ref in comp_obj:
                op.append((ref, str(mp)))
            else:
                sp = True
        onpage[nm] = op
        spans[nm] = sp or bool(op) == 0

    def is_bus(nm):
        return nm in BUS_NETS

    def distributed_bus(nm):
        # шина, уходящая на другие страницы/устройства (рисуется метками);
        # полностью локальная шина (напр. VDDA_3V3 на корневой) - это обычная цепь
        return is_bus(nm) and (spans.get(nm) or len(onpage.get(nm, [])) < 2)

    # функциональные рёбра (сигнальные цепи с >=2 узлами на странице)
    adj = defaultdict(set)
    for nm, op in onpage.items():
        if distributed_bus(nm) or len(op) < 2:
            continue
        for (r1, _p1), (r2, _p2) in combinations_pairs(op):
            adj[r1].add(r2)
            adj[r2].add(r1)

    # ---- кластеры (связные компоненты функционального графа) ----
    seen = set()
    clusters = []
    for r in comp_obj:
        if r in seen:
            continue
        comp_ = [r]
        stack = [r]
        seen.add(r)
        while stack:
            x = stack.pop()
            for nb in adj[x]:
                if nb not in seen:
                    seen.add(nb)
                    comp_.append(nb)
                    stack.append(nb)
        clusters.append(comp_)

    def cluster_key(c):
        root = max(c, key=lambda r: (len(adj[r]), -CAT_RANK.get(comps[r]["type"], 99)))
        return (CAT_RANK.get(comps[root]["type"], 99), min(c))
    clusters.sort(key=cluster_key)

    # ---- раскладка кластеров и сборка страницы ----
    final_pos = {}
    rx, ry = X0, Y0
    row_h = 0.0
    for c in clusters:
        pos = layout_cluster(c, adj, sizes)
        bx0, by0, bx1, by1 = cluster_bbox(c, pos, sizes)
        cw, ch = bx1 - bx0, by1 - by0
        if rx + cw > X0 + MAX_ROW_W:
            rx = X0
            ry += row_h + CLUSTER_GAP_Y
            row_h = 0.0
        offx, offy = rx - bx0, ry - by0
        for r in c:
            final_pos[r] = (pos[r][0] + offx, pos[r][1] + offy)
        rx += cw + CLUSTER_GAP_X
        row_h = max(row_h, ch)

    for r, (x, y) in final_pos.items():
        comp_obj[r].move(x, y)

    # ---- тела (корпуса) компонентов для маршрутизации ----
    # ЗЕРКАЛЬНО по Y: провода рисуем в том же кадре, где KiCad видит выводы.
    bodies = []
    for r in comp_obj:
        x, y = final_pos[r]
        w, h = sizes[r]
        m = BODY_MARGIN
        bodies.append((x - w / 2 - m, -(y + h / 2 + m),
                       x + w / 2 + m, -(y - h / 2 - m), r))

    content_x0 = min(b[0] for b in bodies)
    content_y0 = min(b[1] for b in bodies)
    content_x1 = max(b[2] for b in bodies)
    content_y1 = max(b[3] for b in bodies)

    # все точки-выводы страницы (нельзя задевать проводом чужие выводы)
    pin_pts = set()
    for r in comp_obj:
        info = comps[r]
        for lp in pin_local[r].values():
            pin_pts.add((round((final_pos[r][0] + lp[0]) / GRID) * GRID,
                         round((final_pos[r][1] - lp[1]) / GRID) * GRID))

    def pin_abs(ref, model_pin):
        """Позиция вывода в пространстве схемы (штатный метод библиотеки,
        учитывает инверсию оси Y KiCad и поворот/зеркалирование компонента)."""
        info = comps[ref]
        rp = real_pin(info, model_pin)
        p = sch.get_component_pin_position(sanitize_ref(ref), rp)
        if p is None:
            return None, None
        return rp, (p.x, p.y)

    # ---- 1) функциональные цепи: провода между выводами ----
    for nm, op in onpage.items():
        if distributed_bus(nm) or len(op) < 2:
            continue
        items = []
        for ref, mp in op:
            rp, ap = pin_abs(ref, mp)
            if ap is None:
                continue
            items.append((ref, rp, ap))
        if len(items) < 2:
            continue
        # MST (максимально короткая связность) по манхэттену
        mst = []
        used = {0}
        while len(used) < len(items):
            best = None
            for i in used:
                for j in range(len(items)):
                    if j in used:
                        continue
                    d = abs(items[i][2][0] - items[j][2][0]) + abs(items[i][2][1] - items[j][2][1])
                    if best is None or d < best[0]:
                        best = (d, i, j)
            _d, i, j = best
            mst.append((i, j))
            used.add(j)
        for i, j in mst:
            (r1, rp1, ap1), (r2, rp2, ap2) = items[i], items[j]
            # встроенный маршрутизатор библиотеки (manhattan) сам учитывает
            # систему координат KiCad (инверсию оси Y) и положение/поворот
            # компонентов.
            try:
                sch.auto_route_pins(sanitize_ref(r1), rp1, sanitize_ref(r2), rp2,
                                    routing_strategy="manhattan")
            except Exception as e:
                print("  ! провод %s-%s..%s-%s: %s" % (r1, rp1, r2, rp2, e))
                continue
        # подписать цепь её именем из модели: метка - как отдельная точка,
        # подключённая коротким отводом от ПОСЛЕДНЕГО компонента сети
        lr, lrp, lap = items[-1]
        _add_net_label(sch, nm, lr, lrp, lap, pin_dir[lr][lrp])
        # если цепь уходит на другие страницы/устройства - подписать каждый узел
        if spans.get(nm) and not is_root:
            for ref, rp, ap in items:
                _add_boundary(sch, nm, ref, rp, ap, pin_dir[ref][rp])

    # ---- 2) шинные цепи (GND, VCC_*): короткий отвод + иерархическая метка
    #       на каждом выводе (стандартная практика KiCad для шин; не создаёт
    #       ложных объединений сетей в отличие от протяжки шины через контент).
    #       На корневой странице шины подводятся проводами к пинам листов.
    if not is_root:
        for nm, op in onpage.items():
            if not distributed_bus(nm):
                continue
            for ref, mp in op:
                rp, ap = pin_abs(ref, mp)
                if ap is None:
                    continue
                _add_boundary(sch, nm, ref, rp, ap, pin_dir[ref][rp])

    # ---- 3) прочие граничные цепи: отвод + иерархическая метка ----
    #      (на корневой странице граничные цепи вместо меток получают провода
    #       к пинам листов-ссылок в add_hierarchy)
    if not is_root:
        for nm, op in onpage.items():
            if distributed_bus(nm):
                continue
            if len(op) >= 2:
                continue
            for ref, mp in op:
                rp, ap = pin_abs(ref, mp)
                if ap is None:
                    continue
                _add_boundary(sch, nm, ref, rp, ap, pin_dir[ref][rp])

    # ---- размер бумаги под контент ----
    all_x = [b[0] for b in bodies] + [b[2] for b in bodies]
    all_y = [b[1] for b in bodies] + [b[3] for b in bodies]
    w = max(all_x) - min(all_x)
    h = max(all_y) - min(all_y)
    sch.set_paper_size(paper_for(w, h))
    return sch, comp_obj, sizes, final_pos, bodies, onpage, spans


def _add_boundary(sch, net, ref, rp, ap, d):
    """Короткий отвод от вывода + иерархическая метка (метка - точка сети,
    подключённая штатным add_wire_to_pin)."""
    ex = ap[0] + d[0] * STUB_LEN
    ey = ap[1] + d[1] * STUB_LEN
    ex = round(ex / GRID) * GRID
    ey = round(ey / GRID) * GRID
    sch.add_wire_to_pin((ex, ey), sanitize_ref(ref), rp)
    sch.add_hierarchical_label(net, (ex, ey), shape="input")


def _add_net_label(sch, net, ref, rp, ap, d):
    """Отвод от вывода + обычная метка с именем цепи (метка - отдельная точка
    сети, как компонент с выводом)."""
    ex = ap[0] + d[0] * STUB_LEN
    ey = ap[1] + d[1] * STUB_LEN
    ex = round(ex / GRID) * GRID
    ey = round(ey / GRID) * GRID
    sch.add_wire_to_pin((ex, ey), sanitize_ref(ref), rp)
    sch.add_label(net, (ex, ey))


def combinations_pairs(items):
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            yield items[i], items[j]


# ============================================================================
#  КОРНЕВАЯ СТРАНИЦА + ИЕРАРХИЯ
# ============================================================================
def add_hierarchy(model, root_info, children):
    """Добавить листы-ссылки на дочерние страницы с пинами и проводами.

    Каждая граничная цепь получает на корневой странице связность:
    - корневые узлы цепи (напр. выводы U1) подводятся проводами к пинам листов;
    - если корневых узлов нет (цепь между двумя дочерними листами, напр. CANH),
      пины листов соединяются между собой.
    Подача провода к пину листа - ГОРИЗОНТАЛЬНАЯ (перпендикулярно кромке),
    чтобы провод не задевал остальные пины на кромке листа.
    """
    sch = root_info[0]
    comp_obj, final_pos, bodies = root_info[1], root_info[3], root_info[4]
    comps_all = model["components"]
    nets = model["nets"]
    sheet_of = {}
    for sh in model["sheets"]:
        for r in sh["components"]:
            sheet_of[r] = sh["name"]

    def root_pins(nm):
        """Все корневые узлы цепи: [(ref, зеркальная позиция пина)]."""
        out = []
        for ref, mp in nets[nm]["nodes"]:
            if ref in comp_obj:
                c = comp_obj[ref]
                rp = real_pin(comps_all[ref], mp)
                for p in c.list_pins():
                    if p["number"] == rp:
                        out.append((ref, (c.position.x + p["position"].x,
                                          c.position.y - p["position"].y)))
                        break
        return out

    # точки-выводы корневой страницы (нельзя задевать проводом)
    pin_pts = set()
    for r in comp_obj:
        for p in comp_obj[r].list_pins():
            lx, ly = p["position"].x, p["position"].y
            pin_pts.add((round((final_pos[r][0] + lx) / GRID) * GRID,
                         round((final_pos[r][1] - ly) / GRID) * GRID))

    # листы размещаем справа от контента корневой страницы
    bx = round((max(b[2] for b in bodies) + 100.0) / GRID) * GRID
    by = round(min(b[1] for b in bodies) / GRID) * GRID

    def labels_on_sheet(nm, sheet_name):
        """Цепи, которые получают иерархическую метку на листе (как в build_page)."""
        op = []
        spans = False
        for ref, mp in nets[nm]["nodes"]:
            if ref in sheet_of and sheet_of[ref] == sheet_name and not comps_all[ref].get("virtual"):
                op.append((ref, mp))
            else:
                spans = True
        if not op:
            return False
        if nm in BUS_NETS:
            return True
        if len(op) >= 2:
            return spans
        return True

    # ---- 1) листы + пины ----
    sheet_pins = {}   # net -> [(pos, sheet_name)]
    for ch in children:
        touch = [nm for nm in nets if labels_on_sheet(nm, ch["name"])]
        touch = sorted(touch)
        h = max(30.48, 12.7 + len(touch) * 5.08)
        if by + h > 760.0:
            by = round(min(b[1] for b in bodies) / GRID) * GRID
            bx += 180.34          # кратно 1.27 (сетка KiCad)
        su = sch.add_sheet(name=ch["name"], filename=ch["file"],
                           position=(bx, by), size=(80.0, h))
        for k, nm in enumerate(touch):
            pin_y = by + 6.35 + k * 5.08
            sch.add_sheet_pin(su, nm, "input", "left", (by + h) - pin_y)
        # прочитать фактические позиции пинов листа
        for sh_data in sch._data["sheets"]:
            if sh_data.get("name") == ch["name"]:
                for p in sh_data.get("pins", []):
                    sheet_pins.setdefault(p["name"], []).append(
                        ((p["position"]["x"], p["position"]["y"]), ch["name"]))
        by += h + 40.64

    # все точки-пины листов тоже нельзя задевать проводом
    for nm, plist in sheet_pins.items():
        for pos, _nm in plist:
            pin_pts.add(pos)

    # ---- 2) связность каждой граничной цепи на корневой странице ----
    def approach_wire(p1, p2_sheet_pin, owner=None):
        """Провод от p1 к пину листа p2 (финальный сегмент горизонтальный)."""
        px, py = p2_sheet_pin
        ap = (px - 25.4, py)
        allow = {p1: owner} if owner else None
        poly = route_between(p1, ap, bodies, allow, {}, pin_pts)
        for j in range(len(poly) - 1):
            sch.add_wire(poly[j], poly[j + 1])
        sch.add_wire(ap, (px, py))

    for nm in sheet_pins:
        rps = root_pins(nm)
        plist = sheet_pins[nm]
        if not rps:
            # цепь между дочерними листами: соединяем пины листов попарно
            for i in range(len(plist) - 1):
                a = plist[i][0]
                b = plist[i + 1][0]
                poly = route_between(a, b, bodies, None, {}, pin_pts)
                for j in range(len(poly) - 1):
                    sch.add_wire(poly[j], poly[j + 1])
            continue
        # корневые узлы подводим к первому пину листа
        target = plist[0][0]
        for owner, pos in rps:
            approach_wire(pos, target, owner)
        # остальные пины листа соединяем с первым
        for pos, _sn in plist[1:]:
            approach_wire(target, pos)


# ============================================================================
def main():
    model = json.load(open(MODEL_PATH, encoding="utf-8"))
    sheets = model["sheets"]
    root = sheets[0]
    children = [sh for sh in sheets[1:]]
    # FAN_KEY - виртуальный стенд, в иерархию не входит
    hier_children = [sh for sh in children if sh["name"] != "FAN_KEY"]

    infos = {}
    for sh in sheets:
        print("страница %-4d %-10s -> %s" % (sh["order"], sh["name"], sh["file"]))
        info = build_page(model, sh, is_root=(sh["name"] == root["name"]))
        infos[sh["name"]] = info
        if info is None:
            print("   (нет реальных компонентов)")
            continue
        sch = info[0]
        sch.save(os.path.join(OUT_DIR, sh["file"]))
        v = sch.validate()
        print("   компонентов: %d, проводов: %d, ошибок validate: %d"
              % (len(list(sch.components)), len(list(sch.wires)), len(v)))
        for issue in v[:8]:
            print("     -", issue)

    # корень: добавить иерархию (листы + пины) и пересохранить
    root_info = infos.get(root["name"])
    if root_info is not None:
        add_hierarchy(model, root_info, hier_children)
        sch = root_info[0]
        sch.save(os.path.join(OUT_DIR, root["file"]))
        v = sch.validate()
        print("\nкорневая %s: validate ошибок: %d" % (root["name"], len(v)))
        for issue in v[:12]:
            print("   -", issue)


if __name__ == "__main__":
    main()
