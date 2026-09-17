#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_kicad_project.py — генератор многостраничной схемы KiCad из YAML.

Ключевые решения:
  - API: Schematic.create(), sch.components.add(), sch.get_component_pin_position(),
    sch.add_hierarchical_label(), sch.add_wire(), sch.add_wire_to_pin(), sch.save().
  - Компоненты кэшируются при добавлении (sch.components.get() у части версий
    библиотеки возвращает None).
  - Разводка: собственный ManhattanRouter (A* по сетке с обходом корпусов).
  - Отводы (стабы) портов и пинов — лесенкой, чтобы маршруты не сливались.
  - Лог пишется в gen.log самим генератором (через logging.FileHandler).
"""
import os
import re
import sys
import math
import logging
import yaml

# --- единое логирование -----------------------------------------------------
LOG_FILE = "gen.log"
LOG_DIR  = os.environ.get("GEN_LOG_DIR", "logs")
LOG_LEVEL = os.environ.get("GEN_LOG_LEVEL", "DEBUG").upper()
LOG_LEVEL_NUM = getattr(logging, LOG_LEVEL, logging.DEBUG)

# очистка перед стартом
try:
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
except Exception:
    pass

_fmt = logging.Formatter(
    "%(asctime)s [%(levelname)-7s] %(message)s", datefmt="%H:%M:%S")

_root = logging.getLogger()
_root.setLevel(LOG_LEVEL_NUM)
for h in list(_root.handlers):
    _root.removeHandler(h)

_fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
_fh.setLevel(LOG_LEVEL_NUM)
_fh.setFormatter(_fmt)
_root.addHandler(_fh)

_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(LOG_LEVEL_NUM)
_sh.setFormatter(_fmt)
_root.addHandler(_sh)

log = logging.getLogger("kicad_gen")
log.setLevel(LOG_LEVEL_NUM)


# --- trace (детальная отладка маршрутов) -----------------------------------
TRACE_ON   = os.environ.get("GEN_TRACE", "").lower() in ("1", "true", "yes", "on")
TRACE_FILE = os.environ.get("GEN_TRACE_FILE", "trace.log")
TRACE_PAGE = os.environ.get("GEN_TRACE_PAGE", "")
TRACE_NET  = os.environ.get("GEN_TRACE_NET", "")

trace = logging.getLogger("kicad_gen.trace")
trace.setLevel(logging.DEBUG)
trace.propagate = False          # НЕ льём в gen.log / stdout
if TRACE_ON:
    _tfh = logging.FileHandler(TRACE_FILE, mode="w", encoding="utf-8")
    _tfh.setLevel(logging.DEBUG)
    _tfh.setFormatter(_fmt)
    trace.addHandler(_tfh)
    # короткая шапка в trace.log
    trace.debug("=" * 70)
    trace.debug("TRACE enabled: file=%s page=%r net=%r",
                TRACE_FILE, TRACE_PAGE, TRACE_NET)
    trace.debug("=" * 70)
else:
    trace.addHandler(logging.NullHandler())

# --- зависимости -------------------------------------------------------------
try:
    from kicad_sch_api import Schematic
    HAS_API = True
except ImportError:
    HAS_API = False
    log.warning("kicad_sch_api не установлен — только математическая матрица")

try:
    from manhattan_router import ManhattanRouter
    HAS_ROUTER = True
except ImportError:
    HAS_ROUTER = False
    ManhattanRouter = None
    log.warning("manhattan_router.py не найден — разводка невозможна")


# --- константы ---------------------------------------------------------------
# GRID — единственный источник шага сетки KiCad. Все размеры и координаты
# в этом модуле выражаются через GRID (или через snap()).
GRID = 1.27                       # мм

CELL     = 32 * GRID              # ячейка размещения (32*1.27=40.64 мм)
ORIGIN   = 16 * GRID              # начальный отступ  (16*1.27=20.32 мм)
SHEET_W  = 47 * GRID              # ширина листа-символа  (~59.69 мм)
SHEET_H  = 24 * GRID              # высота листа-символа  (~30.48 мм)

PIN_STUB_BASE  = 6 * GRID         # 7.62 мм
PIN_STUB_STEP  = 4 * GRID         # 5.08 мм
PORT_STUB_BASE = 6 * GRID
PORT_STUB_STEP = 4 * GRID

POWER_SYMBOL_MAP = {
    "GND": "GND", "VCC_3V3": "+3V3", "VCC_5V": "+5V",
    "VCC_12V": "+12V", "VDDA_3V3": "VDDA",
}
DEFAULT_SHAPE_MAP = {
    "POWER": "passive", "GND": "passive",
    "INPUT": "input", "OUTPUT": "output",
    "BIDIR": "bidirectional", "ANALOG": "passive",
    "DIGITAL_SIGNAL": "input",
}



# --- v16/v17: габариты символов (мм) для расчёта сетки --------------------
SYMBOL_SIZES = {
    "Device:R":                            (5.08, 10.16),
    "Device:C":                            (5.08,  7.62),
    "Device:L":                            (5.08, 10.16),
    "Device:LED":                          (5.08,  5.08),
    "Device:D":                            (5.08,  5.08),
    "Device:Q_NMOS_GSD":                   (7.62,  7.62),
    "Device:Q_NPN_BCE":                    (7.62,  7.62),
    "Device:Q_PNP_BCE":                    (7.62,  7.62),
    "MCU_ST_STM32F1:STM32F103R_C-D-E_Tx": (35.56, 35.56),
    "Connector_Generic:Conn_01x02":        (7.62, 10.16),
    # v29: фоллбэк для популярных Transistor_FET / Diode_SMD —
    # если .kicad_sym недоступен или парсер споткнулся на extends.
    # Размеры — по данным KiCad Symbol Editor (bbox + 2мм запас).
    "Transistor_FET:AO3400A":       (10.16, 10.16),
    "Transistor_FET:BSS138":        (10.16, 10.16),
    "Transistor_FET:IRLML2502":     (10.16, 10.16),
    "Transistor_FET:Si2302":        (10.16, 10.16),
    "Transistor_FET:2N7002":        (10.16, 10.16),
    "Transistor_FET:IRLZ44N":       (12.70, 12.70),
    "Transistor_FET:IRF3205":       (12.70, 12.70),
    "Diode_SMD:D_SOD-123":          ( 5.08,  5.08),
    "Diode_SMD:D_SOD-323":          ( 5.08,  5.08),
    "Diode_SMD:D_SMA":              ( 7.62,  5.08),
}
DEFAULT_SYMBOL_SIZE = (10.16, 10.16)

# --- v17: поиск габаритов в библиотеках KiCad -----------------------------
SYMBOL_LIB_PATHS = [
    "/usr/share/kicad/symbols",
    "/usr/local/share/kicad/symbols",
    "/opt/kicad/share/kicad/symbols",
    os.path.expanduser("~/.local/share/kicad/symbols"),
    os.path.expanduser("~/.kicad/symbols"),
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
    "C:/Program Files/KiCad/9.0/share/kicad/symbols",
    "C:/Program Files/KiCad/8.0/share/kicad/symbols",
    "C:/Program Files/KiCad/7.0/share/kicad/symbols",
]
_env_libs = os.environ.get("GEN_SYMBOL_LIBS", "")
if _env_libs:
    _extra = [p for p in _env_libs.split(os.pathsep) if p]
    SYMBOL_LIB_PATHS = _extra + SYMBOL_LIB_PATHS

_symbol_size_cache = {}


def _parse_sexpr(text):
    n = len(text)
    pos = [0]

    def skip_ws():
        while pos[0] < n and text[pos[0]] in " \t\r\n":
            pos[0] += 1

    def parse():
        skip_ws()
        if pos[0] >= n:
            return None
        ch = text[pos[0]]
        if ch == "(":
            pos[0] += 1
            items = []
            while True:
                skip_ws()
                if pos[0] >= n:
                    break
                if text[pos[0]] == ")":
                    pos[0] += 1
                    break
                sub = parse()
                if sub is not None:
                    items.append(sub)
            return items
        if ch == '"':
            pos[0] += 1
            buf = []
            while pos[0] < n and text[pos[0]] != '"':
                if text[pos[0]] == "\\" and pos[0] + 1 < n:
                    buf.append(text[pos[0] + 1])
                    pos[0] += 2
                else:
                    buf.append(text[pos[0]])
                    pos[0] += 1
            pos[0] += 1
            return "".join(buf)
        start = pos[0]
        while pos[0] < n and text[pos[0]] not in " \t\r\n()\"":
            pos[0] += 1
        return text[start:pos[0]]

    return parse()


def _find_symbol_node(tree, name):
    if not isinstance(tree, list):
        return None
    for ch in tree:
        if (isinstance(ch, list) and len(ch) >= 2
                and ch[0] == "symbol" and ch[1] == name):
            return ch
        # v29: KiCad вкладывает символы в под-контейнеры: (symbol "Lib"
        # (symbol "NAME" ...) (symbol "NAME2" ...)). Заходим на уровень глубже.
        if isinstance(ch, list) and ch and ch[0] == "symbol":
            sub = _find_symbol_node(ch[2:], name)
            if sub is not None:
                return sub
    return None


def _get_extends(node):
    """Возвращает имя родителя, если у символа (extends "NAME"), иначе None."""
    if not isinstance(node, list):
        return None
    for ch in node:
        if isinstance(ch, list) and len(ch) >= 2 and ch[0] == "extends":
            return str(ch[1])
    return None


def _walk_collect(node, rects, pins):
    if not isinstance(node, list):
        return
    head = node[0] if node else None
    if head == "rectangle":
        start = end = None
        for ch in node:
            if isinstance(ch, list):
                if ch[0] == "start" and len(ch) >= 3:
                    start = (float(ch[1]), float(ch[2]))
                elif ch[0] == "end" and len(ch) >= 3:
                    end = (float(ch[1]), float(ch[2]))
        if start and end:
            rects.append((min(start[0], end[0]), min(start[1], end[1]),
                          max(start[0], end[0]), max(start[1], end[1])))
    elif head == "pin":
        at = None
        length = 0.0
        for ch in node:
            if isinstance(ch, list):
                if ch[0] == "at" and len(ch) >= 4:
                    at = (float(ch[1]), float(ch[2]), float(ch[3]))
                elif ch[0] == "length" and len(ch) >= 2:
                    length = float(ch[1])
        if at is not None:
            pins.append((at[0], at[1], at[2], length))
    for ch in node:
        if isinstance(ch, list):
            _walk_collect(ch, rects, pins)


def _collect_geometry(tree, name, max_depth=5):
    """Возвращает (rects, pins) с учётом цепочки (extends "PARENT").
    Парсит сам символ, а если у него нет pin/rectangle — родителя и т.д."""
    if max_depth <= 0 or not name:
        return [], []
    sym = _find_symbol_node(tree, name)
    if sym is None:
        return [], []
    rects, pins = [], []
    _walk_collect(sym, rects, pins)
    if rects or pins:
        return rects, pins
    parent = _get_extends(sym)
    if parent:
        return _collect_geometry(tree, parent, max_depth - 1)
    return [], []


def _size_from_library(lib_id):
    if ":" not in lib_id:
        return None
    lib, name = lib_id.split(":", 1)
    for base in SYMBOL_LIB_PATHS:
        path = os.path.join(base, lib + ".kicad_sym")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except Exception:
            continue
        try:
            tree = _parse_sexpr(text)
        except Exception:
            continue
        # v29: идём по цепочке extends в этом же файле
        rects, pins = _collect_geometry(tree, name, max_depth=5)
        if not rects and not pins:
            continue
        xs = []
        ys = []
        for (x0, y0, x1, y1) in rects:
            xs.extend([x0, x1])
            ys.extend([y0, y1])
        for (px, py, ang, L) in pins:
            xs.append(px)
            ys.append(py)
            ex = px + math.cos(math.radians(ang)) * L
            ey = py + math.sin(math.radians(ang)) * L
            xs.append(ex)
            ys.append(ey)
        if not xs:
            continue
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        return (round(w + 2.0, 2), round(h + 2.0, 2))
    return None


def _symbol_size(lib_id):
    """Габариты символа (мм). Сначала SYMBOL_SIZES, затем — поиск в
    библиотеках KiCad (.kicad_sym). Если нигде нет — KeyError."""
    if lib_id in SYMBOL_SIZES:
        return SYMBOL_SIZES[lib_id]
    if lib_id in _symbol_size_cache:
        return _symbol_size_cache[lib_id]
    sz = _size_from_library(lib_id)
    if sz is not None:
        _symbol_size_cache[lib_id] = sz
        return sz
    raise KeyError(
        "Нет габаритов для символа %r: нет в SYMBOL_SIZES и не найден "
        "в библиотеках KiCad %s. Проверьте GEN_SYMBOL_LIBS "
        "или допишите символ в SYMBOL_SIZES." % (lib_id, SYMBOL_LIB_PATHS))


def snap(v):
    """Округлить координату (мм) к ближайшему кратному GRID."""
    return round(float(v) / GRID) * GRID


def _model_to_real_pin(ref, model_pin):
    """Модельный номер пина -> номер пина символа KiCad."""
    mp = str(model_pin)
    if ref.startswith("D") and not ref.startswith("DRV"):
        return {"1": "2", "2": "1"}.get(mp, mp)
    return mp


_REF_RE = re.compile(r"^[A-Z]+[0-9]+$")


def sanitize_ref(ref):
    """KiCad требует reference вида [A-Z]+[0-9]+ без подчёркиваний.
    R_SCALE_1 -> RSCALE1, LED_SCALE_1_1 -> LEDSCALE11, C_GATE -> CGATE1."""
    s = str(ref)
    if _REF_RE.match(s):
        return s
    s = re.sub(r"[^A-Za-z0-9]", "", s.upper())
    if not s:
        s = "X1"
    if not s[-1].isdigit():
        s += "1"
    return s


class SchematicGenerator:
    def __init__(self, main_yaml_path="./main.yaml"):
        self.main_yaml_path = main_yaml_path
        self.base_dir = os.path.dirname(main_yaml_path) or "."
        self._pwr_counter = 1
        self._all_wires = []   # [((x1,y1),(x2,y2)), ...] — для junction-детекции
        self.density_scale = 1.0   # routing_driven
        # v16: динамическая матричная раскладка (расчёт по размерам)
        self.use_matrix_layout = True
        self._trace_ctx = None     # {"net":..., "from":..., "to":...}
        self._init_trace()

    # --------------------------------------------------------------- trace
    def _init_trace(self):
        """trace.log: без env, всегда пишет. Формат — блоки по маршрутам."""
        self.trace = logging.getLogger(f"kicad_gen.trace.{id(self)}")
        self.trace.setLevel(logging.DEBUG)
        self.trace.propagate = False
        for h in list(self.trace.handlers):
            self.trace.removeHandler(h)
        tf = os.environ.get("GEN_TRACE_FILE", "trace.log")
        fh = logging.FileHandler(tf, mode="w", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(_fmt)
        self.trace.addHandler(fh)
        self.trace_file = tf
        self.trace_page = os.environ.get("GEN_TRACE_PAGE", "")
        self.trace_net  = os.environ.get("GEN_TRACE_NET",  "")
        self._route_nr = 0
        print(f"[TRACE] file={tf} page={self.trace_page!r} net={self.trace_net!r}")

    # ------------------------------------------------------- page logging
    def _setup_page_logger(self, page_name):
        """Отдельный лог-файл на страницу: logs/<page_name>.log.
        Логгер propagate=True -> дублируется в gen.log и stdout."""
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, f"{page_name}.log")

        lg = logging.getLogger(f"kicad_gen.{page_name}")
        lg.setLevel(LOG_LEVEL_NUM)
        lg.propagate = True

        for h in list(lg.handlers):
            if getattr(h, "_page_log", False):
                lg.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass

        fh = logging.FileHandler(path, mode="w", encoding="utf-8")
        fh.setLevel(LOG_LEVEL_NUM)
        fh.setFormatter(_fmt)
        fh._page_log = True
        lg.addHandler(fh)

        lg.info("=" * 70)
        lg.info("Страница [%s] — лог: %s", page_name, path)
        lg.info("=" * 70)
        return lg, path

    # ------------------------------------------------------------------ YAML
    def load_project_data(self):
        if not os.path.exists(self.main_yaml_path):
            log.error("Не найден %s", self.main_yaml_path)
            return None, {}
        with open(self.main_yaml_path, encoding="utf-8") as f:
            main = yaml.safe_load(f) or {}
        root_page = main.get("root_page", {})
        sheets = {}
        sheets_dir = os.path.join(self.base_dir, "sheets")
        if os.path.isdir(sheets_dir):
            for name in sorted(os.listdir(sheets_dir)):
                if not name.endswith(".yaml"):
                    continue
                with open(os.path.join(sheets_dir, name), encoding="utf-8") as sf:
                    data = yaml.safe_load(sf) or {}
                if data:
                    sheets[data.get("page_name", name)] = data
        return root_page, sheets

    # ---------------------------------------------------------- размещение
    def calculate_force_layout(self, components, nets):
        conn = {ref: 0 for ref in components}
        for _nm, info in nets.items():
            for n in info.get("nodes", []):
                c = n.get("component")
                if c in conn:
                    conn[c] += 1
        return [r for r, _ in sorted(conn.items(), key=lambda kv: kv[1], reverse=True)]

    # ---------------------------------------------- dynamic matrix (v16)
    def build_dynamic_matrix(self, components, ports, nets,
                             sheet_widths, sheet_heights,
                             component_types=None):
        """Детерминированная раскладка с расчётом ширины колонок и высоты
        строк. Возвращает placement = {ref: {"x", "y", "type"}}.

        Для обычных компонентов x,y — центр ячейки (их так и ставит
        sch.components.add). Для X_* листов x,y — TOP-LEFT листа
        (add_sheet ждёт top-left, а центрируем мы его в ячейке сами).

        Схема:
          1. Компоненты раскладываются в cols_cmp x rows_cmp.
          2. U1 (или самый связанный) — обменом в центр сетки.
          3. X_* — сверху рядами, над сеткой компонентов.
          4. Порты — крайние колонки.
          5. Ширина колонки = max(W элементов в ней) + PAD.
             Высота строки = max(H элементов в ней) + PAD.
          6. Центр ячейки = кумулятивная сумма + полуразмер.
        """
        import math

        PAD = 4 * GRID   # 5.08 мм

        # 1. классификация
        comp_refs = [r for r in components if not str(r).startswith("X_")]
        x_refs = sorted([r for r in components if str(r).startswith("X_")])
        in_ports = [p for p in ports
                    if p.get("type", "INPUT") in ("INPUT", "POWER")]
        out_ports = [p for p in ports
                     if p.get("type", "INPUT") not in ("INPUT", "POWER")]

        # 2. центральный компонент
        if "U1" in comp_refs:
            main_ref = "U1"
        elif comp_refs and nets:
            conn = {r: 0 for r in comp_refs}
            for _nm, _info in nets.items():
                for _n in _info.get("nodes", []):
                    _c = _n.get("component")
                    if _c in conn:
                        conn[_c] += 1
            main_ref = max(conn, key=conn.get) if conn else comp_refs[0]
        elif comp_refs:
            main_ref = comp_refs[0]
        else:
            main_ref = None

        n_cmp = len(comp_refs)
        n_x = len(x_refs)

        # 3. размеры сетки компонентов (нечётные — чёткий центр)
        if n_cmp > 0:
            cols_cmp = max(3, int(math.ceil(math.sqrt(n_cmp))))
            if cols_cmp % 2 == 0:
                cols_cmp += 1
            rows_cmp = max(1, int(math.ceil(n_cmp / cols_cmp)))
            if rows_cmp % 2 == 0:
                rows_cmp += 1
        else:
            cols_cmp, rows_cmp = 3, 1

        # сколько X_* в ряду — по их средней ширине
        _w_avg = (sum(sheet_widths.values()) / max(len(sheet_widths), 1)
                  if sheet_widths else 60.0)
        x_per_row = max(1, int(cols_cmp * CELL / max(_w_avg + PAD, 1.0)))
        x_rows = (n_x + x_per_row - 1) // x_per_row if n_x else 0

        col_off = 2 if in_ports else 0
        row_off = (x_rows + 1) if x_rows > 0 else 1

        # 5. индексы
        idx = {}

        if n_cmp > 0:
            ordered = list(comp_refs)
            center_i = (rows_cmp // 2) * cols_cmp + (cols_cmp // 2)
            if main_ref and center_i < n_cmp:
                i_main = ordered.index(main_ref)
                if i_main != center_i:
                    ordered[i_main], ordered[center_i] = (
                        ordered[center_i], ordered[i_main])
            for i, ref in enumerate(ordered):
                r = i // cols_cmp
                c = i % cols_cmp
                idx[ref] = (col_off + c, row_off + r, "COMP")

        for i, ref in enumerate(x_refs):
            rr = i // x_per_row
            cc = i % x_per_row
            idx[ref] = (col_off + cc * 2, rr, "COMP")

        def _spread_ports(plist, col):
            n = len(plist)
            if n == 0:
                return
            total = row_off + rows_cmp
            if n == 1:
                rr = max(1, total // 2)
                lbl = plist[0].get("net_label", "")
                idx["PORT_" + lbl] = (col, rr, "PORT")
                return
            step = max(1.0, (total - 2) / (n - 1))
            for i, p in enumerate(plist):
                lbl = p.get("net_label", "")
                rr = 1 + int(round(i * step))
                idx["PORT_" + lbl] = (col, rr, "PORT")

        n_cols_est = (max(c for c, _r, _k in idx.values()) + 1) if idx else 0
        _spread_ports(in_ports, 0)
        _spread_ports(out_ports, n_cols_est + 1)

        # 6. размеры элементов
        def _el_size(ref):
            if ref in components and "placement" in (components[ref] or {}):
                return None
            if str(ref).startswith("X_"):
                sn = str(ref)[2:]
                return (sheet_widths.get(sn, SHEET_W),
                        sheet_heights.get(sn, SHEET_H))
            info = components.get(ref, {}) or {}
            lib_id = self._guess_lib_id(ref, info, component_types or {})
            return _symbol_size(lib_id)

        col_w = {}
        row_h = {}
        for ref, (c, r, _k) in idx.items():
            sz = _el_size(ref)
            if sz is None:
                continue
            w, h = sz
            col_w[c] = max(col_w.get(c, 0.0), w)
            row_h[r] = max(row_h.get(r, 0.0), h)

        # 7. кумулятивные суммы -> центры
        if col_w:
            for c in range(0, max(col_w.keys()) + 2):
                col_w.setdefault(c, DEFAULT_SYMBOL_SIZE[0])
        else:
            col_w = {0: DEFAULT_SYMBOL_SIZE[0]}

        col_center = {}
        x_cur = ORIGIN
        for c in sorted(col_w.keys()):
            w = col_w[c] + PAD
            col_center[c] = x_cur + w / 2.0
            x_cur += w

        if row_h:
            for r in range(0, max(row_h.keys()) + 2):
                row_h.setdefault(r, DEFAULT_SYMBOL_SIZE[1])
        else:
            row_h = {0: DEFAULT_SYMBOL_SIZE[1]}

        row_center = {}
        y_cur = ORIGIN
        for r in sorted(row_h.keys()):
            h = row_h[r] + PAD
            row_center[r] = y_cur + h / 2.0
            y_cur += h

        # 8. placement
        placement = {}
        for ref, (c, r, kind) in idx.items():
            info = components.get(ref, {}) or {}
            if "placement" in info:
                p = info["placement"]
                placement[ref] = {
                    "x": snap(float(p["x"])),
                    "y": snap(float(p["y"])),
                    "type": kind,
                }
                continue
            cx = col_center.get(c, ORIGIN)
            cy = row_center.get(r, ORIGIN)
            if str(ref).startswith("X_"):
                sn = str(ref)[2:]
                w = sheet_widths.get(sn, SHEET_W)
                h = sheet_heights.get(sn, SHEET_H)
                placement[ref] = {
                    "x": snap(cx - w / 2.0),
                    "y": snap(cy - h / 2.0),
                    "type": kind,
                }
            else:
                placement[ref] = {
                    "x": snap(cx),
                    "y": snap(cy),
                    "type": kind,
                }
        return placement

    def build_topological_matrix(self, components, sorted_refs, ports,
                                  nets=None):
        """Силовое размещение (Fruchterman-Reingold) с коэффициентом
        разреженности self.density_scale. Связные компоненты тянутся
        друг к другу, слабо связанные — отталкиваются."""
        import random, math
        random.seed(42)

        S = float(getattr(self, "density_scale", 1.0))
        refs = list(components.keys())
        m = {}

        # Порты — по краям листа
        ly, ry = 2, 2
        for p in ports:
            label = p.get("net_label", "")
            if p.get("type", "INPUT") in ("INPUT", "POWER"):
                m[f"PORT_{label}"] = {"col": 1, "row": ly, "type": "PORT"}
                ly += 1
            else:
                m[f"PORT_{label}"] = {"col": 30, "row": ry, "type": "PORT"}
                ry += 1

        if not refs:
            return m

        # Матрица связей
        edge_weight = {}
        for _nm, info in (nets or {}).items():
            nodes = [n.get("component") for n in info.get("nodes", [])]
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    a, b = sorted((nodes[i], nodes[j]))
                    if a == b or a not in components or b not in components:
                        continue
                    edge_weight[(a, b)] = edge_weight.get((a, b), 0) + 1

        n = len(refs)
        base_k = 40.0
        radius0 = base_k * math.sqrt(n) * 1.2 * S
        pos = {}
        for i, r in enumerate(refs):
            ang = 2 * math.pi * i / n
            pos[r] = [radius0 * math.cos(ang), radius0 * math.sin(ang)]

        area = (base_k * math.sqrt(n)) ** 2 * S * S
        k = max(math.sqrt(area / max(n, 1)) * 1.8, base_k * 4) * S

        # виновники предыдущего прохода: {ref: сколько раз попал в FAIL-DIAG}
        blame = getattr(self, "_failed_blame_bias", {}) or {}
        max_b = max(blame.values()) if blame else 1
        cx0 = sum(p[0] for p in pos.values()) / max(len(pos), 1)
        cy0 = sum(p[1] for p in pos.values()) / max(len(pos), 1)

        temp = base_k * 5 * S
        for _it in range(300):
            disp = {r: [0.0, 0.0] for r in refs}
            for i, a in enumerate(refs):
                ax, ay = pos[a]
                for b in refs[i + 1:]:
                    bx, by = pos[b]
                    dx, dy = ax - bx, ay - by
                    d2 = dx * dx + dy * dy
                    if d2 < 1e-6:
                        dx = random.random() - 0.5
                        dy = random.random() - 0.5
                        d2 = max(dx * dx + dy * dy, 1e-6)
                    d = math.sqrt(d2)
                    force = k * k / d
                    ux, uy = dx / d, dy / d
                    disp[a][0] += ux * force; disp[a][1] += uy * force
                    disp[b][0] -= ux * force; disp[b][1] -= uy * force
            # постоянное расталкивание виновников от центра масс
            for r, b in blame.items():
                if r not in pos:
                    continue
                dx = pos[r][0] - cx0
                dy = pos[r][1] - cy0
                d = math.sqrt(dx * dx + dy * dy) or 1e-6
                force = base_k * S * (b / max_b) * 2.5
                disp[r][0] += dx / d * force
                disp[r][1] += dy / d * force

            for (a, b), w in edge_weight.items():
                if a not in pos or b not in pos:
                    continue
                ax, ay = pos[a]; bx, by = pos[b]
                dx, dy = ax - bx, ay - by
                d = math.sqrt(dx * dx + dy * dy) or 1e-6
                force = d * d / k * min(w, 6)
                ux, uy = dx / d, dy / d
                disp[a][0] -= ux * force; disp[a][1] -= uy * force
                disp[b][0] += ux * force; disp[b][1] += uy * force
            for r in refs:
                dx, dy = disp[r]
                d = math.sqrt(dx * dx + dy * dy) or 1e-6
                step = min(d, temp)
                pos[r][0] += dx / d * step
                pos[r][1] += dy / d * step
            temp *= 0.97
            if temp < 1.0:
                break

        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        min_x, min_y = min(xs), min(ys)
        step_x = GRID * 20.0 * S
        step_y = GRID * 20.0 * S
        for r in refs:
            gx = round((pos[r][0] - min_x) / step_x) + 2
            gy = round((pos[r][1] - min_y) / step_y) + 2
            m[r] = {"col": gx, "row": gy, "type": "COMP"}
        return m
    def _guess_lib_id(self, ref, info, component_types):
        if component_types:
            ct = component_types.get(info.get("type"))
            if isinstance(ct, dict):
                sym = ct.get("symbol")
                if isinstance(sym, str) and ":" in sym:
                    return sym
        r = str(ref); t = str(info.get("type", "")).upper()
        if r.startswith("U") and "STM32" in t:
            return "MCU_ST_STM32F1:STM32F103R_C-D-E_Tx"
        if r.startswith("LED"): return "Device:LED"
        if r.startswith("R"):   return "Device:R"
        if r.startswith("C"):   return "Device:C"
        if r.startswith("L"):   return "Device:L"
        if r.startswith("D"):   return "Device:D"
        if r.startswith("Q"):
            if "NMOS" in t or "BSS138" in t: return "Device:Q_NMOS_GSD"
            if "PNP" in t:                   return "Device:Q_PNP_BCE"
            return "Device:Q_NPN_BCE"
        if r.startswith(("J", "P", "X")):
            return "Connector_Generic:Conn_01x02"
        return "Device:R"

    # --------------------------------------------------------------- отрисовка
    def compile_sheet_to_kicad(self, page_name, page_info):
        log, _page_log_path = self._setup_page_logger(page_name)
        components = page_info.get("components", {})
        nets = page_info.get("nets", {})
        ports = page_info.get("ports", [])
        component_types = page_info.get("component_types", {})

        if page_name == "MAIN_ROOT":
            output_file = page_info.get("file", "climate_control_niva_travel.kicad_sch")
        else:
            os.makedirs("schematics", exist_ok=True)
            output_file = os.path.join(
                "schematics",
                page_info.get("file", f"{page_name.lower()}.kicad_sch"),
            )

        log.info("=" * 70)
        log.info("Лист [%s] -> %s  (компонентов=%d, цепей=%d, портов=%d)",
                 page_name, output_file, len(components), len(nets), len(ports))

        # v16: считаем размеры X_* листов ДО матрицы (нужны для раскладки).
        _raw_sheets = ((page_info.get("sheets_raw") or {})
                       if isinstance(page_info, dict) else {})
        sheet_widths = {}
        sheet_heights = {}
        for _ref16, _info16 in (components or {}).items():
            if not str(_ref16).startswith("X_"):
                continue
            _sn16 = str(_ref16)[2:]
            _sy16 = _raw_sheets.get(_sn16, {}) or {}
            _pl16 = _sy16.get("ports", []) or []
            _ln16 = sum(1 for p in _pl16
                        if str(p.get("type", "INPUT")).upper() != "OUTPUT")
            _rn16 = sum(1 for p in _pl16
                        if str(p.get("type", "INPUT")).upper() == "OUTPUT")
            _nmax16 = max(_ln16, _rn16, 1)
            _need_h16 = 5 * GRID + (_nmax16 - 1) * 2 * GRID + 3 * GRID
            _h16 = max(SHEET_H, round(_need_h16 / GRID) * GRID)
            _labels16 = [len(str(p.get("net_label", ""))) for p in _pl16] or [0]
            _mx16 = max(_labels16)
            _need_w16 = 12 * GRID + _mx16 * 1.27
            _w16 = max(30 * GRID, round(_need_w16 / GRID) * GRID)
            sheet_widths[_sn16] = _w16
            sheet_heights[_sn16] = _h16
            log.info("  sheet %-12s: left=%d right=%d h=%.2f w=%.2f label_max=%d",
                     _sn16, _ln16, _rn16, _h16, _w16, _mx16)

        # 1. Размещение
        sorted_refs = self.calculate_force_layout(components, nets)
        if getattr(self, "use_matrix_layout", False):
            matrix = self.build_dynamic_matrix(
                components, ports, nets,
                sheet_widths, sheet_heights,
                component_types=page_info.get("component_types", {}))
        else:
            matrix = self.build_topological_matrix(components, sorted_refs,
                                                   ports, nets)
        final_placement = {}
        for ref, m in matrix.items():
            if "x" in m and "y" in m:
                x = snap(m["x"])
                y = snap(m["y"])
            else:
                x = snap(m["col"] * CELL + ORIGIN)
                y = snap(m["row"] * CELL + ORIGIN)
            if ref in components and "placement" in (components[ref] or {}):
                p = components[ref]["placement"]
                x, y = snap(float(p["x"])), snap(float(p["y"]))
            final_placement[ref] = {"x": x, "y": y, "type": m["type"]}

        if not HAS_API:
            log.warning("kicad_sch_api отсутствует — только матрица")
            return 0, 0

        # 2. Создаём схему
        sch = Schematic.create(
            name=page_name,
            paper="A3" if page_name == "MAIN_ROOT" else "A4",
        )

        # 3. Компоненты
        comp_cache = {}
        sheet_objs = {}     # {sheet_name: (sheet_obj, pos)}
        sheet_uuids = {}    # {sheet_name: uuid_or_id}
        # v16: sheet_widths/sheet_heights уже посчитаны выше, до матрицы.

        for ref, pos in final_placement.items():
            if pos["type"] != "COMP":
                continue
            info = components.get(ref, {})
            if str(ref).startswith("X_"):
                if hasattr(sch, "add_sheet"):
                    sname = str(ref)[2:]
                    try:
                        sobj = sch.add_sheet(
                            name=sname,
                            filename=info.get(
                                "value_sch",
                                f"schematics/{sname.lower()}.kicad_sch",
                            ),
                            position=(pos["x"], pos["y"]),
                            size=(sheet_widths.get(sname, SHEET_W),
                                  sheet_heights.get(sname, SHEET_H)),
                        )
                        _uuid = (getattr(sobj, "uuid", None)
                                 or getattr(sobj, "id", None))
                        if _uuid is None and isinstance(sobj, str):
                            _uuid = sobj
                        sheet_objs[sname] = (sobj, pos)
                        if _uuid is not None:
                            sheet_uuids[sname] = _uuid
                            log.debug("    sheet %s uuid=%r",
                                      sname, _uuid)
                        else:
                            log.warning("    sheet %s: не удалось "
                                        "извлечь uuid из %r",
                                        sname, type(sobj).__name__)
                    except Exception as e:
                        log.error("add_sheet %s: %s", ref, e)
                continue
            lib_id = self._guess_lib_id(ref, info, component_types)
            ref_kicad = sanitize_ref(ref)
            try:
                c = sch.components.add(
                    lib_id,
                    reference=ref_kicad,
                    value=str(info.get("type", "Generic")),
                    position=(pos["x"], pos["y"]),
                )
                comp_cache[ref] = c
            except Exception as e:
                log.error("components.add %s (%s): %s", ref, lib_id, e)

        # 3b. add_sheet_pins_v1: пины на рамке каждого дочернего листа.
        # Для MAIN_ROOT — из sheets_raw берём ports каждого листа и ставим
        # sheet_pins. От каждого пина — короткий отвод + локальная метка,
        # чтобы одноимённые цепи листов соединились на корне.
        if page_name == "MAIN_ROOT" and sheet_objs:
            sheets_raw = page_info.get("sheets_raw", {}) or {}
            log.info("  добавляю sheet_pins для %d листов", len(sheet_objs))
            for sname, (sobj, spos) in sheet_objs.items():
                s_yaml = sheets_raw.get(sname, {}) or {}
                ports = s_yaml.get("ports", []) or []
                if not ports:
                    log.info("    лист %s: портов нет", sname)
                    continue
                sx, sy = spos["x"], spos["y"]
                w = sheet_widths.get(sname, SHEET_W)
                h = sheet_heights.get(sname, SHEET_H)
                # разделим по сторонам
                left = []
                right = []
                for p in ports:
                    t = str(p.get("type", "INPUT")).upper()
                    if t == "OUTPUT":
                        right.append(p)
                    else:
                        left.append(p)
                # сортировка по имени — стабильный порядок
                left.sort(key=lambda p: p.get("net_label", ""))
                right.sort(key=lambda p: p.get("net_label", ""))

                def _add_pin(p, side, idx):
                    net_label = p.get("net_label", "")
                    ptype = str(p.get("type", "INPUT")).upper()
                    shape = DEFAULT_SHAPE_MAP.get(ptype, "input")
                    if side == "left":
                        py = sy + 5 * GRID + idx * 2 * GRID
                        if py > sy + h - 2 * GRID:
                            log.warning(
                                "    sheet %s: порт %s не влез "
                                "(side=left, idx=%d, y=%.2f > %.2f)",
                                sname, net_label, idx, py,
                                sy + h - 2 * GRID)
                            return
                        pin_x = sx
                        pin_pos = (pin_x, py)
                        stub_end = (pin_x - 4 * GRID, py)
                    else:
                        py = sy + 5 * GRID + idx * 2 * GRID
                        if py > sy + h - 2 * GRID:
                            log.warning(
                                "    sheet %s: порт %s не влез "
                                "(side=right, idx=%d, y=%.2f > %.2f)",
                                sname, net_label, idx, py,
                                sy + h - 2 * GRID)
                            return
                        pin_x = sx + w
                        pin_pos = (pin_x, py)
                        stub_end = (pin_x + 4 * GRID, py)

                    # --- v3: правильная сигнатура kicad_sch_api ---
                    # sch.sheets.add_sheet_pin(sheet_uuid, name,
                    #                            pin_type, side, offset)
                    #   * первый аргумент — UUID листа (строка), не объект;
                    #   * пятый аргумент — СМЕЩЕНИЕ от угла вдоль стороны
                    #     (для left/right: Y - sy от верхнего угла листа).
                    _uid = None
                    try:
                        _uid = sheet_uuids.get(sname)
                    except NameError:
                        _uid = None
                    if _uid is None:
                        _uid = (getattr(sobj, "uuid", None)
                                or getattr(sobj, "id", None))
                    if _uid is None and isinstance(sobj, str):
                        _uid = sobj
                    if _uid is None:
                        log.warning("    sheet_pin %s.%s: не могу "
                                    "получить UUID листа (sobj=%r)",
                                    sname, net_label,
                                    type(sobj).__name__)
                        return

                    # v5: асимметричный offset — разные углы для left/right.
                    # Эмпирика (см. листы MAIN_ROOT после v3):
                    #   side=right (angle=0):   API отсчитывает от
                    #       ВЕРХНЕГО угла  →  offset = py - sy
                    #   side=left  (angle=180): API отсчитывает от
                    #       НИЖНЕГО угла  →  offset = (sy + h) - py
                    # top/bottom — по аналогии, но у нас не используется.
                    if side == "right":
                        _offset = pin_pos[1] - sy
                    elif side == "left":
                        _offset = (sy + h) - pin_pos[1]
                    elif side == "bottom":
                        _offset = pin_pos[0] - sx
                    else:  # top
                        _offset = (sx + w) - pin_pos[0]

                    _pin_type = shape if shape in (
                        "input", "output", "bidirectional",
                        "tri_state", "passive", "unspecified"
                    ) else "input"

                    _sheets_mgr = getattr(sch, "sheets", None)
                    _attempts = []
                    if _sheets_mgr is not None and hasattr(
                            _sheets_mgr, "add_sheet_pin"):
                        _attempts.append(("sch.sheets",
                                          _sheets_mgr.add_sheet_pin))
                    if hasattr(sch, "add_sheet_pin"):
                        _attempts.append(("sch", sch.add_sheet_pin))

                    if not _attempts:
                        log.warning("    sheet_pin %s.%s: нет "
                                    "add_sheet_pin ни на sch, ни "
                                    "на sch.sheets", sname, net_label)
                        return

                    # v34: диагностика параметров создания sheet_pin
                    log.info(
                        "    [SHEETPIN-CREATE] %s.%s: "
                        "uid=%s side=%s offset=%.3f pin_abs=(%.3f,%.3f) "
                        "type=%s stub_end=(%.3f,%.3f) sheet_tl=(%.3f,%.3f) "
                        "sheet_size=(%.2f,%.2f)",
                        sname, net_label, str(_uid)[:12], side, _offset,
                        pin_pos[0], pin_pos[1], _pin_type,
                        stub_end[0], stub_end[1], sx, sy, w, h)
                    _placed = False
                    _last_err = None
                    for _via, _fn in _attempts:
                        try:
                            _fn(_uid, net_label, _pin_type,
                                side, _offset)
                            _placed = True
                            log.info(
                                "    sheet_pin %s.%s ok "
                                "(via=%s uuid=%s side=%s "
                                "offset=%.3f abs=(%.3f,%.3f) "
                                "type=%s)",
                                sname, net_label, _via,
                                str(_uid)[:12], side, _offset,
                                pin_pos[0], pin_pos[1], _pin_type)
                            break
                        except TypeError as _e:
                            _last_err = _e
                            continue
                        except Exception as _e:
                            _last_err = _e
                            log.warning("    sheet_pin %s.%s "
                                        "(via=%s): %s: %s",
                                        sname, net_label, _via,
                                        type(_e).__name__, _e)
                            break
                    if not _placed:
                        log.warning("    sheet_pin %s.%s: не "
                                    "установлен (%s)",
                                    sname, net_label,
                                    _last_err or "все варианты "
                                    "отвалились по TypeError")
                        return

                    # Карта ожидаемых позиций — на случай, если API
                    # всё ещё клампит в угол; _fix_sheet_pin_positions
                    # поправит (at X Y) в файле.
                    if not hasattr(self, "_expected_sheet_pins"):
                        self._expected_sheet_pins = {}
                    self._expected_sheet_pins[(sname, net_label)] = (
                        pin_pos[0], pin_pos[1], side)

                    # отвод + label
                    log.debug(
                        "    [STUB-LABEL] %s.%s: add_label(%r, (%.3f,%.3f))",
                        sname, net_label, net_label,
                        stub_end[0], stub_end[1])
                    try:
                        self._add_wire(sch, pin_pos, stub_end)
                        sch.add_label(net_label, stub_end)
                    except Exception as e:
                        log.warning("    label %s.%s: %s",
                                    sname, net_label, e)

                for i, p in enumerate(left):
                    _add_pin(p, "left", i)
                for i, p in enumerate(right):
                    _add_pin(p, "right", i)

        # 4. Порты
        # Ориентация порта (0/180) и направление отвода определяется
        # положением ОТНОСИТЕЛЬНО КОМПОНЕНТОВ, а не относительно bbox
        # самих портов: если все порты на одной стороне, mid_x совпадает
        # с их x, и все они разворачиваются наружу.
        _comp_xs = [p["x"] for p in final_placement.values()
                    if p["type"] == "COMP"]
        _ref_x = (sum(_comp_xs) / len(_comp_xs)) if _comp_xs else 340.0
        mid_x = _ref_x

        for ref, pos in final_placement.items():
            if pos["type"] != "PORT":
                continue
            net_label = str(ref).replace("PORT_", "")
            meta = next((p for p in ports if p.get("net_label") == net_label), {})
            ptype = str(meta.get("type", "INPUT")).upper()
            shape = meta.get("shape") or DEFAULT_SHAPE_MAP.get(ptype, "input")
            rotation = 180 if pos["x"] < mid_x else 0

            # Отвод метки в направлении "внутрь листа":
            #   слева от середины — вправо (pdir=+1), справа — влево (pdir=-1).
            # Рисуем отвод всегда, чтобы метка не висела "голой" даже если
            # роутер не смог провести остальной маршрут.
            _pdir = 1 if pos["x"] < _ref_x else -1
            _port_stub_end = (snap(pos["x"] + _pdir * PORT_STUB_BASE), pos["y"])
            if (self.trace_page == "" or page_name == self.trace_page):
                self.trace.debug("")
                self.trace.debug("[PORT-STUB] %-20s label=(%.3f,%.3f)  "
                                 "stub_end=(%.3f,%.3f)  pdir=%+d  ref_x=%.2f",
                                 net_label, pos["x"], pos["y"],
                                 _port_stub_end[0], _port_stub_end[1],
                                 _pdir, _ref_x)
            self._trace_ctx = {"net": net_label, "from": None, "to": None}
            try:
                self._add_wire(sch, (pos["x"], pos["y"]), _port_stub_end)
            except Exception as e:
                log.warning("port stub %s: %s", net_label, e)
            self._trace_ctx = None

            # v33: явный effects={'justify': ...} — без него rotation=180
            # не разворачивает текст, и левая метка наезжает на лист.
            _justify = "right" if rotation == 180 else "left"
            # v34: диагностика параметров создания hier-метки
            _justify_dbg = ("right" if rotation == 180 else "left")
            log.info(
                "    [LABEL-CREATE] hier %s: pos=(%.3f,%.3f) "
                "shape=%s rotation=%s justify=%s x<mid(%.2f)=%s",
                net_label, pos["x"], pos["y"], shape, rotation,
                _justify_dbg, mid_x, pos["x"] < mid_x)
            placed = False
            _hier_via = None
            for _via_label, attempt in (
                ("effects+rotation", lambda: sch.add_hierarchical_label(
                    net_label, (pos["x"], pos["y"]),
                    shape=shape, rotation=rotation,
                    effects={"justify": _justify_dbg})),
                ("rotation-only", lambda: sch.add_hierarchical_label(
                    net_label, (pos["x"], pos["y"]),
                    shape=shape, rotation=rotation)),
                ("shape-only", lambda: sch.add_hierarchical_label(
                    net_label, (pos["x"], pos["y"]),
                    shape=shape)),
            ):
                try:
                    attempt()
                    placed = True
                    _hier_via = _via_label
                    log.info("    [LABEL-CREATE] %s ok via=%s",
                             net_label, _via_label)
                    break
                except TypeError as _te:
                    log.debug("    [LABEL-CREATE] %s via=%s TypeError: %s",
                              net_label, _via_label, _te)
                    continue
                except Exception as e:
                    log.error("hierarchical_label %s: %s", net_label, e)
                    break
            if not placed:
                log.warning("    [LABEL-CREATE] %s: ни один вариант не сработал",
                            net_label)

        # 5. Разводка
        _routed_total, _failed_total = self._route_all(
            sch, comp_cache, final_placement, components, nets, page_name,
            log=log)

        # 6. Сохранение
        # 3d. Junction-точки: T-образные контакты проводов страницы.
        # Собираем точки и сохраняем их для пост-обработки файла
        # (API junctions.add в разных версиях требует разных типов
        # аргументов — проще вписать (junction ...) прямо в .kicad_sch).

        def _collect_wires(sch_obj):
            # Провода из API недоступны — используем свой список self._all_wires.
            return list(getattr(self, "_all_wires", []))

        def _on_seg(p, a, b, tol=0.05):
            px, py = p; ax, ay = a; bx, by = b
            if abs(ax - bx) < 1e-6:
                return abs(px - ax) < tol and min(ay, by) + tol < py < max(ay, by) - tol
            if abs(ay - by) < 1e-6:
                return abs(py - ay) < tol and min(ax, bx) + tol < px < max(ax, bx) - tol
            return False

        try:
            segs = _collect_wires(sch)
        except Exception:
            segs = []
        junctions = set()
        for i, (a, b) in enumerate(segs):
            for ep in (a, b):
                for j, (c, d) in enumerate(segs):
                    if i == j:
                        continue
                    if ep == c or ep == d:
                        continue
                    if _on_seg(ep, c, d):
                        junctions.add((round(ep[0], 2), round(ep[1], 2)))

        if not hasattr(self, "_pending_junctions"):
            self._pending_junctions = []
        if junctions:
            log.info("  junctions: %d T-контактов (к записи в файл)", len(junctions))
            for (jx, jy) in sorted(junctions):
                self._pending_junctions.append((output_file, jx, jy))
        else:
            log.info("  junctions: нет")

        log.info("sch.save(%s)", output_file)
        sch.save(output_file)
        self._verify_sheet_pins(output_file, page_name, log)
        self._fix_sheet_pin_rotation(output_file, log=log)
        self._write_pending_junctions(log=log)
        self._fix_hier_label_rotation(output_file, ref_x=_ref_x, log=log)
        self._fix_hier_justify(output_file, log=log)
        self._all_wires = []   # очищаем для следующей страницы
        log.info("Сохранено: %s", output_file)
        return _routed_total, _failed_total

    # --------------------------------------------------------------- verify
    def _verify_sheet_pins(self, path, page_name, log):
        '''Проверяет сохранённый .kicad_sch: сколько в файле
        реальных sheet_pin-ов (pin "NAME" <shape> (at ...)).
        Если листы есть, а пинов нет — эскалирует warning.'''
        try:
            with open(path, encoding='utf-8') as f:
                text = f.read()
        except Exception as e:
            log.warning('  [verify] не могу прочитать %s: %s', path, e)
            return
        n_sheets = len(re.findall(r'\(sheet\s+\(at', text))
        n_sheet_pins = len(re.findall(
            r'\(pin\s+"[^"]*"\s+'
            r'(?:input|output|bidirectional|tri_state|passive)\s',
            text))
        log.info('  [verify] %s: sheet-блоков=%d, sheet_pin-ов=%d',
                 os.path.basename(path), n_sheets, n_sheet_pins)
        if n_sheets > 0 and n_sheet_pins == 0:
            log.warning(
                '  [verify] %s: листы есть (%d), а sheet_pin-ов нет. '
                'add_sheet_pin в этой сборке kicad_sch_api молча no-op. '
                'Проверьте сигнатуру: '
                'python -c "import inspect; '
                'from kicad_sch_api import Schematic; '
                'print(inspect.signature(Schematic.add_sheet_pin))"',
                os.path.basename(path), n_sheets)

    def _fix_sheet_pin_rotation(self, path, log=None):
        """Постобработка .kicad_sch: левым sheet_pin-ам ставит angle=180
        и justify=right, правым — angle=0 и justify=left.

        Опирается на карту self._expected_sheet_pins, которую заполняет
        код добавления sheet_pin-ов: {(sheet_name, pin_name): (x, y, side)}.
        """
        if log is None:
            log = logging.getLogger("kicad_gen")
        expected = getattr(self, "_expected_sheet_pins", {}) or {}
        if not expected:
            log.info("  [sheet-pin-rot] нечего править (нет ожидаемых пинов)")
            return
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            log.warning("  [sheet-pin-rot] не могу прочитать %s: %s", path, e)
            return

        # (round(x,2), round(y,2)) -> side
        xy_to_side = {}
        for (_sn, _pn), (_ex, _ey, _side) in expected.items():
            xy_to_side[(round(float(_ex), 2), round(float(_ey), 2))] = _side

        # Sheet pin header: (pin "NAME" TYPE (at X Y ANGLE)
        header_re = re.compile(
            r'\(pin\s+"([^"]+)"\s+'
            r'(input|output|bidirectional|tri_state|passive|unspecified)\s+'
            r'\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)'
        )

        mods = []   # (start, end, new_block)
        for m in header_re.finditer(text):
            x = round(float(m.group(3)), 2)
            y = round(float(m.group(4)), 2)
            side = xy_to_side.get((x, y))
            if side is None:
                continue
            # Найти конец блока pin (баланс скобок)
            start = m.start()
            i = m.end()
            depth = 1
            while i < len(text) and depth > 0:
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                i += 1
            block = text[start:i]

            want_ang = "180" if side == "left" else "0"
            want_jus = "right" if side == "left" else "left"
            old_ang = m.group(5)

            new_block = block
            if old_ang != want_ang:
                old_at = "(at %s %s %s)" % (m.group(3), m.group(4), old_ang)
                new_at = "(at %s %s %s)" % (m.group(3), m.group(4), want_ang)
                new_block = new_block.replace(old_at, new_at, 1)

            jm = re.search(r'\(justify\s+(\w+)\)', new_block)
            if jm:
                cur = jm.group(1)
                if cur != want_jus:
                    new_block = (new_block[:jm.start(1)] + want_jus +
                                 new_block[jm.end(1):])

            if new_block != block:
                mods.append((start, i, new_block))

        if not mods:
            log.info("  [sheet-pin-rot] %s: все sheet_pin-ы уже корректны",
                     os.path.basename(path))
            return

        # применить моды с конца — чтобы смещения не поехали
        new_text = text
        for start, end, blk in sorted(mods, reverse=True):
            new_text = new_text[:start] + blk + new_text[end:]

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        log.info("  [sheet-pin-rot] %s: повёрнуто %d sheet_pin-ов",
                 os.path.basename(path), len(mods))

    def _fix_hier_justify(self, path, log=None):
        """Проходит по всем (hierarchical_label ...) и выставляет
        justify в соответствии с углом в (at X Y ANGLE):
            angle == 0   -> justify left
            angle == 180 -> justify right
        """
        if log is None:
            log = logging.getLogger("kicad_gen")
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            log.warning("  [hier-justify] не могу прочитать %s: %s", path, e)
            return

        # Найти все блоки hierarchical_label и обработать
        starts = [m.start() for m in
                  re.finditer(r'\(hierarchical_label\s+"', text)]
        if not starts:
            log.info("  [hier-justify] %s: hier-меток нет",
                     os.path.basename(path))
            return

        mods = []
        for s in starts:
            i = s
            depth = 0
            while i < len(text):
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            block = text[s:i]

            mat = re.search(
                r'\(at\s+[-\d.]+\s+[-\d.]+\s+([-\d.]+)\)', block)
            if not mat:
                continue
            ang = mat.group(1)
            want = "right" if ang in ("180", "180.0") else "left"

            jm = re.search(r'\(justify\s+(\w+)\)', block)
            if not jm:
                # вставляем (justify ...) внутрь (effects ...) перед ) effects
                # Не будем усложнять — пропускаем
                continue
            cur = jm.group(1)
            if cur == want:
                continue
            new_block = (block[:jm.start(1)] + want +
                         block[jm.end(1):])
            mods.append((s, i, new_block))

        if not mods:
            log.info("  [hier-justify] %s: все hier-метки уже согласованы",
                     os.path.basename(path))
            return

        new_text = text
        for s, i, blk in sorted(mods, reverse=True):
            new_text = new_text[:s] + blk + new_text[i:]

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        log.info("  [hier-justify] %s: поправлено %d justify",
                 os.path.basename(path), len(mods))

    def _add_wire(self, sch, a, b):
        """sch.add_wire + регистрация сегмента в self._all_wires."""
        tr = getattr(self, "trace", None)
        if tr is not None:
            ctx = getattr(self, "_trace_ctx", None) or {}
            net = ctx.get("net", "-")
            _dx = abs(a[0] - b[0]); _dy = abs(a[1] - b[1])
            _orient = "H" if _dy < 1e-6 else ("V" if _dx < 1e-6 else "DIAG!")
            tr.debug("    WIRE %s (%.3f,%.3f) -> (%.3f,%.3f)  L=%.3f  net=%s",
                     _orient, a[0], a[1], b[0], b[1], _dx + _dy, net)
        try:
            sch.add_wire(a, b)   # ВАЖНО: прямая ссылка на API, не рекурсия
        except Exception as e:
            log.warning("add_wire %s->%s: %s", a, b, e)
            return
        self._all_wires.append(((float(a[0]), float(a[1])),
                                (float(b[0]), float(b[1]))))

    # --------------------------------------------------------------- роутер
    def _route_all(self, sch, comp_cache, final_placement, components, nets, page_name,
                   log=None):
        if log is None:
            log = logging.getLogger("kicad_gen")
        # собираем пины всех компонентов через list_pins() + позицию символа.
        # НЕ используем get_component_pin_position — в этой сборке API он
        # стабильно возвращает None.
        pin_xy = {}
        pin_dir = {}
        all_pins = set()
        for ref, c in comp_cache.items():
            try:
                cpos = c.position
                cx, cy = float(cpos.x), float(cpos.y)
            except Exception:
                cx = final_placement[ref]["x"]
                cy = final_placement[ref]["y"]
            try:
                for p in c.list_pins():
                    num = str(p["number"])
                    lp = p["position"]
                    lx = float(lp.x); ly = float(lp.y)
                    # KiCad: локальная Y инвертирована относительно абсолютной.
                    # НИКАКОГО snap(): kicad_sch_api ставит пин в pos + local_pin
                    # без округления, и local_pin у ряда символов не кратен 1.27.
                    # Округление даёт провод, оторванный от реального пина.
                    # A* работает по сетке внутри (метод _g); если пин не на
                    # сетке, _pts_from_grid сшивает путь микро-сегментом.
                    px = cx + lx
                    py = cy - ly
                    pin_xy[(ref, num)] = (px, py)
                    all_pins.add((round(px, 2), round(py, 2)))
                    dx, dy = px - cx, py - cy
                    if abs(dx) >= abs(dy):
                        pin_dir[(ref, num)] = (-1 if dx < 0 else 1, 0)
                    else:
                        pin_dir[(ref, num)] = (0, -1 if dy < 0 else 1)
            except Exception as e:
                log.warning("list_pins %s: %s", ref, e)

        log.info("  собрано пинов: %d у %d компонентов",
                 len(pin_xy), len(set(r for r, _n in pin_xy)))

        # дамп пинов: что видит роутер + off-grid флаг
        if self.trace_page == "" or page_name == self.trace_page:
            self.trace.debug("")
            self.trace.debug("=" * 78)
            self.trace.debug("[%s] pin_xy: %d пинов", page_name, len(pin_xy))
            self.trace.debug("=" * 78)
            off = 0
            for (r, n), (x, y) in sorted(pin_xy.items()):
                on_x = abs(x / GRID - round(x / GRID)) < 1e-6
                on_y = abs(y / GRID - round(y / GRID)) < 1e-6
                flag = "" if (on_x and on_y) else "  <-- OFF-GRID"
                if flag:
                    off += 1
                self.trace.debug("  %-10s #%-3s (%.3f,%.3f)%s",
                                 r, n, x, y, flag)
            self.trace.debug("  off-grid: %d / %d", off, len(pin_xy))

        if TRACE_ON and (not TRACE_PAGE or page_name == TRACE_PAGE):
            trace.debug("")
            trace.debug("=" * 70)
            trace.debug("[%s] pin_xy dump (%d pins):", page_name, len(pin_xy))
            for (r, n), (x, y) in sorted(pin_xy.items()):
                _off_grid = (abs(x / GRID - round(x / GRID)) > 1e-6 or
                             abs(y / GRID - round(y / GRID)) > 1e-6)
                trace.debug(
                    "  PIN %-10s #%-3s  world=(%10.3f, %10.3f)  grid=(%d, %d)%s",
                    r, n, x, y, round(x / GRID), round(y / GRID),
                    "   <-- OFF-GRID" if _off_grid else "")

        if not HAS_ROUTER:
            log.error("  manhattan_router недоступен — разводка невозможна "
                      "(fallback отключён)")
            return 0, 0

        # копилка виновников неудач на этой странице
        self._failed_blame_page = {}
        if not hasattr(self, "_failed_blame"):
            self._failed_blame = {}
        # СБРОС _net_cells на каждый вызов _route_all (страницу и проход).
        # Иначе клетки прошлого прохода остаются и hit_tree срабатывает
        # рядом со стартом — A* финиширует через 1 шаг, трасса не доходит.
        self._net_cells = {}

        # центр компонентов — относительно него определяем "лево/право"
        # для портов (как в compile_sheet_to_kicad)
        _comp_xs = [p["x"] for p in final_placement.values()
                    if p["type"] == "COMP"]
        _ref_x = (sum(_comp_xs) / len(_comp_xs)) if _comp_xs else 500.0

        # роутер (fallback-путей нет)
        router = ManhattanRouter(
            grid=GRID, clearance=0.1 * GRID, turn_penalty=2.0,
            max_iter=5_000_000, verbose=False,
            log_prefix=f"[{page_name}] ", logger=log,
            h_weight=1.3,
        )
        for ref in comp_cache:
            pts = [pin_xy[k] for k in pin_xy if k[0] == ref]
            if not pts:
                continue
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            m = 1.0
            router.add_obstacle(min(xs)-m, min(ys)-m, max(xs)+m, max(ys)+m,
                                owner=ref)
            for (_r, _n) in pin_xy:
                if _r == ref:
                    _px, _py = pin_xy[(_r, _n)]
                    router.add_pin(_px, _py, ref=ref)
        # Регистрируем концы отводов портов как пины роутера: чужие
        # отводы становятся препятствием, вертикальная "шина" из
        # stub_end-ов разваливается — маршруты обходят её.
        _port_stub_pins = 0
        for _r, _p in final_placement.items():
            if _p["type"] != "PORT":
                continue
            _pdir = 1 if _p["x"] < _ref_x else -1
            _pe = (snap(_p["x"] + _pdir * PORT_STUB_BASE), _p["y"])
            router.add_pin(_pe[0], _pe[1], ref=_r)
            _port_stub_pins += 1
        log.info("  роутер: obstacles=%d, pins=%d (+%d stub_end)",
                 len(router._obstacles), len(router._pins), _port_stub_pins)

        if TRACE_ON and (not TRACE_PAGE or page_name == TRACE_PAGE):
            trace.debug("")
            trace.debug("[%s] PORT placements (final):", page_name)
            for _r, _p in sorted(final_placement.items()):
                if _p["type"] != "PORT":
                    continue
                _pdir = 1 if _p["x"] < _ref_x else -1
                _pe = (snap(_p["x"] + _pdir * PORT_STUB_BASE), _p["y"])
                trace.debug(
                    "  PORT %-20s  label=(%10.3f,%10.3f)  stub_end=(%10.3f,%10.3f)"
                    "  pdir=%+d  ref_x=%.2f",
                    _r, _p["x"], _p["y"], _pe[0], _pe[1], _pdir, _ref_x)

        # bbox каждого компонента — для проверки, что стаб выходит наружу
        _comp_bbox = {}
        for _ref in comp_cache:
            _pts = [pin_xy[k] for k in pin_xy if k[0] == _ref]
            if not _pts:
                continue
            _xs = [p[0] for p in _pts]
            _ys = [p[1] for p in _pts]
            _m = 1.0
            _comp_bbox[_ref] = (min(_xs) - _m, min(_ys) - _m,
                                max(_xs) + _m, max(_ys) + _m)

        def _stub_to_exit_bbox(ref, px, py, sdx, sdy, base=PIN_STUB_BASE,
                               step=PIN_STUB_STEP, cap=200.0):
            """Возвращает длину стаба, при которой конец выходит за bbox
            своего компонента. Если компонента в карте нет — вернуть base."""
            bb = _comp_bbox.get(ref)
            if bb is None:
                return base
            x0, y0, x1, y1 = bb
            L = base
            while L < cap:
                ex = px + sdx * L
                ey = py + sdy * L
                if not (x0 <= ex <= x1 and y0 <= ey <= y1):
                    return L
                L += step
            return cap  # не вышли — очень длинный стаб (аномалия)

        # лесенка стабов пинов
        from collections import defaultdict
        by_dir = defaultdict(list)
        for (ref, num), d in pin_dir.items():
            by_dir[(ref, d)].append((num, pin_xy[(ref, num)][0], pin_xy[(ref, num)][1]))
        pin_stub_len = {}
        for (ref, d), items in by_dir.items():
            items.sort(key=lambda t: t[2] if d[0] != 0 else t[1])
            n = len(items)
            for i, (num, _px, _py) in enumerate(items):
                pin_stub_len[(ref, num)] = PIN_STUB_BASE + (n - 1 - i) * PIN_STUB_STEP
                # учёт выхода за bbox: длина не меньше, чем нужно для выхода
                _dx, _dy = pin_dir.get((ref, num), (1, 0))
                _px, _py = pin_xy[(ref, num)]
                _need = _stub_to_exit_bbox(ref, _px, _py, _dx, _dy)
                if _need > pin_stub_len[(ref, num)]:
                    pin_stub_len[(ref, num)] = _need

        # лесенка стабов портов
        by_side = {"L": [], "R": []}
        px_all = [p["x"] for p in final_placement.values() if p["type"] == "PORT"]
        if px_all:
            mid = (min(px_all) + max(px_all)) / 2.0
            for r, p in final_placement.items():
                if p["type"] == "PORT":
                    by_side["L" if p["x"] < mid else "R"].append((p["y"], r))
        port_stub_len = {}
        for side, items in by_side.items():
            items.sort()
            for i, (_y, r) in enumerate(items):
                port_stub_len[r] = PORT_STUB_BASE + i * PORT_STUB_STEP

        # маршрутизация цепей
        routed = 0
        _route_all_failed = 0

        # --- Проход 1: собрать items и MST-рёбра каждой цепи ----------------
        net_items = {}
        all_edges = []
        for net_name, info in nets.items():
            items = []
            for n in info.get("nodes", []):
                c = n.get("component")
                if c in comp_cache:
                    rp = _model_to_real_pin(c, n.get("pin", "1"))
                    if (c, rp) in pin_xy:
                        items.append((c, rp, pin_xy[(c, rp)], "comp"))
            port_ref = f"PORT_{net_name}"
            if port_ref in final_placement:
                _pxp = final_placement[port_ref]["x"]
                _pyp = final_placement[port_ref]["y"]
                _pdir = 1 if _pxp < _ref_x else -1
                _pstub_end = (snap(_pxp + _pdir * PORT_STUB_BASE), _pyp)
                items.append((port_ref, "1", _pstub_end, "port"))
            if len(items) < 2:
                continue

            # MST
            used = {0}; edges = []
            while len(used) < len(items):
                best = None
                for i in used:
                    for j in range(len(items)):
                        if j in used:
                            continue
                        d = (abs(items[i][2][0] - items[j][2][0])
                             + abs(items[i][2][1] - items[j][2][1]))
                        if best is None or d < best[0]:
                            best = (d, i, j)
                if best is None:
                    break
                _, i, j = best
                edges.append((i, j)); used.add(j)

            net_items[net_name] = items
            for i, j in edges:
                a = items[i]; b = items[j]
                d = abs(a[2][0] - b[2][0]) + abs(a[2][1] - b[2][1])
                all_edges.append((-d, net_name, i, j))

        # --- Проход 2: длинные рёбра первыми --------------------------------
        # Длинные цепи прокладываются, пока поле свободно. Иначе они идут
        # последними, когда короткие отводы забили коридор, и A* упирается
        # в maxiter при h=1..3.
        all_edges.sort()
        if all_edges:
            log.info("  рёбер всего: %d, самое длинное: %.0f мм",
                     len(all_edges), -all_edges[0][0])

        # --- Проход 3: разводка в порядке убывания длины --------------------
        net_connected = {}
        for _negd, net_name, i, j in all_edges:
            items = net_items[net_name]
            connected = net_connected.setdefault(net_name, set())
            a = items[i]; b = items[j]
            _net_cells_here = getattr(self, "_net_cells", {}).get(net_name, set())

            # g1 должен быть ЕЩЁ НЕ подключённым концом. После сортировки
            # рёбер "i" может быть уже в дереве (тогда роутим ОТ нового j)
            # или наоборот — проверяем оба конца.
            _pass_nc = _net_cells_here
            if (i in connected) and _net_cells_here:
                p_from, p_to = b, a
            elif (j in connected) and _net_cells_here:
                p_from, p_to = a, b
            else:
                p_from, p_to = a, b
                # v23 (бывший v21): ни один конец ещё не в дереве —
                # передаём в route() ПУСТОЙ net_cells. Иначе роутер
                # подменит цель на 'ближайшую клетку дерева' и уйдёт
                # от порта/пина, который надо было подключить.
                _pass_nc = set()

            _from_dir = pin_dir.get((p_from[0], p_from[1])) \
                if p_from[3] == "comp" else None
            _to_dir = pin_dir.get((p_to[0], p_to[1])) \
                if p_to[3] == "comp" else None
            _from_owner = p_from[0]
            _to_owner = p_to[0]
            _own = set()
            if _from_owner: _own.add(_from_owner)
            if _to_owner: _own.add(_to_owner)

            _tr = (TRACE_ON
                   and (not TRACE_PAGE or page_name == TRACE_PAGE)
                   and (not TRACE_NET or net_name == TRACE_NET))
            if _tr:
                trace.debug("")
                trace.debug(">>> [%s] ROUTE net=%r", page_name, net_name)
                trace.debug("    from = %-10s pin=%-3s  (%10.3f,%10.3f)  dir=%s owner=%s",
                            p_from[0], p_from[1],
                            p_from[2][0], p_from[2][1],
                            _from_dir, _from_owner)
                trace.debug("    to   = %-10s pin=%-3s  (%10.3f,%10.3f)  dir=%s owner=%s",
                            p_to[0], p_to[1],
                            p_to[2][0], p_to[2][1],
                            _to_dir, _to_owner)
                trace.debug("    net_cells_here = %d cells", len(_net_cells_here))
                if _net_cells_here:
                    _bx = round(p_from[2][0] / GRID)
                    _by = round(p_from[2][1] / GRID)
                    _bests = sorted(_net_cells_here,
                                    key=lambda c: abs(c[0]-_bx) + abs(c[1]-_by))[:3]
                    for _c in _bests:
                        _d = abs(_c[0]-_bx) + abs(_c[1]-_by)
                        trace.debug("      near net_cell %s  world=(%.3f,%.3f)  d=%d",
                                    _c, _c[0]*GRID, _c[1]*GRID, _d)

            self._route_nr += 1
            self._trace_ctx = {
                "net": net_name,
                "from": (p_from[0], p_from[1], p_from[2]),
                "to": (p_to[0], p_to[1], p_to[2]),
            }
            show = ((self.trace_page == "" or page_name == self.trace_page)
                    and (self.trace_net == "" or net_name == self.trace_net))
            if show:
                self.trace.debug("")
                self.trace.debug("=" * 78)
                self.trace.debug("ROUTE #%d  net=%r  page=%s",
                                 self._route_nr, net_name, page_name)
                self.trace.debug("  from  %-10s #%-3s  (%10.3f,%10.3f)  "
                                 "dir=%s owner=%s",
                                 p_from[0], p_from[1],
                                 p_from[2][0], p_from[2][1],
                                 _from_dir, _from_owner)
                self.trace.debug("  to    %-10s #%-3s  (%10.3f,%10.3f)  "
                                 "dir=%s owner=%s",
                                 p_to[0], p_to[1],
                                 p_to[2][0], p_to[2][1],
                                 _to_dir, _to_owner)
                self.trace.debug("  net_cells=%d", len(_net_cells_here))
                # ближайшая клетка дерева (что роутер подставит)
                if _net_cells_here:
                    bx, by = int(round(p_from[2][0] / GRID)), int(round(p_from[2][1] / GRID))
                    best = min(_net_cells_here,
                               key=lambda c: abs(c[0]-bx) + abs(c[1]-by))
                    self.trace.debug(
                        "  nearest net_cell=%s world=(%.3f,%.3f) d=%d",
                        best, best[0]*GRID, best[1]*GRID,
                        abs(best[0]-bx) + abs(best[1]-by))

            try:
                path = router.route(
                    p_from[2], p_to[2],
                    own_refs=_own if _own else None,
                    p1_dir=_from_dir, p2_dir=_to_dir,
                    p1_owner=_from_owner, p2_owner=_to_owner,
                    net_name=net_name,
                    net_cells=_pass_nc)
            except Exception as e:
                _route_all_failed += 1
                log.error("  [FAIL] %s: %s -> %s (%s: %s)",
                          net_name, p_from[2], p_to[2],
                          type(e).__name__, e)
                continue

            if path is None:
                _route_all_failed += 1
                blame = getattr(router, "_last_fail_blame", set()) or set()
                for ref in blame:
                    self._failed_blame_page[ref] = \
                        self._failed_blame_page.get(ref, 0) + 1
                    self._failed_blame[ref] = \
                        self._failed_blame.get(ref, 0) + 1
                if _tr:
                    trace.debug("    PATH = None (FAIL)")
                log.error("  [FAIL] %s: %s -> %s (диагностика выше)",
                          net_name, p_from[2], p_to[2])
                continue

            # v22: path не None, но проверим, дошёл ли он ДО ЦЕЛИ.
            # Роутер мог закончить на промежуточной клетке дерева
            # (hit_tree), а не в p_to — тогда p_to остаётся висящим.
            _end = path[-1]
            _end_ok = (abs(_end[0] - p_to[2][0]) < 0.05 and
                       abs(_end[1] - p_to[2][1]) < 0.05)
            # v22fix: _pass_nc вводится v21 и может отсутствовать.
            # Используем _net_cells_here — она есть всегда.
            if not _end_ok and _net_cells_here:
                _ex = int(round(_end[0] / GRID))
                _ey = int(round(_end[1] / GRID))
                # v23: _pass_nc не определена (v21 не применялся).
                # Используем _net_cells_here — она есть всегда.
                if (_ex, _ey) in _net_cells_here:
                    _end_ok = True
            if not _end_ok:
                _route_all_failed += 1
                log.error(
                    "  [FAIL-DANGLE] %s: path заканчивается в (%.3f,%.3f), "
                    "а цель была (%.3f,%.3f) — ребро НЕ разведено",
                    net_name, _end[0], _end[1],
                    p_to[2][0], p_to[2][1])
                # Провода всё же рисуем — пусть будут частью дерева
                # (следующее ребро этой же сети сможет к ним подстыковаться).
                for _k in range(len(path) - 1):
                    self._add_wire(sch, path[_k], path[_k + 1])
                self._trace_ctx = None
                try:
                    router.block_path(path, net_name=net_name)
                except Exception:
                    pass
                if not hasattr(self, "_net_cells"):
                    self._net_cells = {}
                _cs = self._net_cells.setdefault(net_name, set())
                for _k in range(len(path) - 1):
                    _x1, _y1 = path[_k]
                    _x2, _y2 = path[_k + 1]
                    _gx1 = int(round(_x1 / GRID))
                    _gy1 = int(round(_y1 / GRID))
                    _gx2 = int(round(_x2 / GRID))
                    _gy2 = int(round(_y2 / GRID))
                    _st = max(abs(_gx2 - _gx1), abs(_gy2 - _gy1))
                    for _s in range(_st + 1):
                        _gx = round(_gx1 + (_gx2 - _gx1) * _s / _st) if _st else _gx1
                        _gy = round(_gy1 + (_gy2 - _gy1) * _s / _st) if _st else _gy1
                        _cs.add((_gx, _gy))
                # ВАЖНО: НЕ добавляем i,j в connected — пусть следующие
                # рёбра этой сети снова попробуют подключить p_to.
                continue

            if show:
                self.trace.debug("  PATH %d pts:", len(path))
                for _i, _pt in enumerate(path):
                    self.trace.debug("    [%2d] (%.3f,%.3f)",
                                     _i, _pt[0], _pt[1])
                _f_ok = (abs(path[0][0]-p_from[2][0]) < 1e-6 and
                         abs(path[0][1]-p_from[2][1]) < 1e-6)
                _t_ok = (abs(path[-1][0]-p_to[2][0]) < 1e-6 and
                         abs(path[-1][1]-p_to[2][1]) < 1e-6)
                self.trace.debug("  PATH[0] == from ? %s (d=%.3f,%.3f)",
                                 _f_ok,
                                 path[0][0]-p_from[2][0],
                                 path[0][1]-p_from[2][1])
                self.trace.debug("  PATH[-1]== to   ? %s (d=%.3f,%.3f)",
                                 _t_ok,
                                 path[-1][0]-p_to[2][0],
                                 path[-1][1]-p_to[2][1])

            for k in range(len(path) - 1):
                self._add_wire(sch, path[k], path[k+1])
            self._trace_ctx = None
            try:
                router.block_path(path, net_name=net_name)
            except Exception:
                pass
            if not hasattr(self, "_net_cells"):
                self._net_cells = {}
            cellset = self._net_cells.setdefault(net_name, set())
            for k in range(len(path) - 1):
                x1, y1 = path[k]; x2, y2 = path[k+1]
                gx1 = int(round(x1 / GRID)); gy1 = int(round(y1 / GRID))
                gx2 = int(round(x2 / GRID)); gy2 = int(round(y2 / GRID))
                steps = max(abs(gx2 - gx1), abs(gy2 - gy1))
                for s in range(steps + 1):
                    gx = round(gx1 + (gx2 - gx1) * s / steps) if steps else gx1
                    gy = round(gy1 + (gy2 - gy1) * s / steps) if steps else gy1
                    cellset.add((gx, gy))

            connected.add(i); connected.add(j)
            routed += 1

        if router is not None:
            router.report()
            router.close()
        if self._failed_blame_page:
            top = sorted(self._failed_blame_page.items(),
                         key=lambda kv: -kv[1])[:8]
            log.error("  FAIL-виновники [%s]: %s", page_name, top)
        else:
            log.info("  [%s]: все рёбра разведены", page_name)
        log.info("  Разведено: %d, не разведено: %d",
                 routed, _route_all_failed)
        return routed, _route_all_failed

    # --------------------------------------------------------------- верхний
    def _write_pending_junctions(self, log=None):
        if log is None:
            log = logging.getLogger("kicad_gen")
        """Постобработка .kicad_sch: читаем записанный файл, парсим
        (wire ...), ищем T-контакты в файловых координатах и вписываем
        (junction ...) ровно в те же точки."""
        import uuid as _uuid
        if not hasattr(self, "_pending_junctions"):
            return
        # _pending_junctions: [(path, x, y), ...]; нас интересуют только пути
        files = []
        seen = set()
        for (path, _x, _y) in self._pending_junctions:
            if path not in seen:
                seen.add(path)
                files.append(path)
        self._pending_junctions = []

        for path in files:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
            except Exception as e:
                log.warning("  [junc] не могу прочитать %s: %s", path, e)
                continue

            # 1. Все провода из файла
            wires = []
            for m in re.finditer(
                r'\(wire\s*\(pts\s*\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s*'
                r'\(xy\s+([-\d.]+)\s+([-\d.]+)\)', text):
                x1, y1, x2, y2 = map(float, m.groups())
                wires.append(((round(x1, 4), round(y1, 4)),
                              (round(x2, 4), round(y2, 4))))

            if not wires:
                log.info("  [junc] %s: проводов нет", path)
                continue

            # 2. T-контакты в файловых координатах
            def on_seg(p, a, b, tol=0.001):
                px, py = p; ax, ay = a; bx, by = b
                if abs(ax - bx) < 1e-6:
                    return abs(px - ax) < tol and min(ay, by) + tol < py < max(ay, by) - tol
                if abs(ay - by) < 1e-6:
                    return abs(py - ay) < tol and min(ax, bx) + tol < px < max(ax, bx) - tol
                return False

            junctions = set()

            # (1) T-контакты: конец одного провода лежит на середине другого
            for i, (a, b) in enumerate(wires):
                for ep in (a, b):
                    for j, (c, d) in enumerate(wires):
                        if i == j:
                            continue
                        if ep == c or ep == d:
                            continue
                        if on_seg(ep, c, d):
                            junctions.add(ep)

            # (2) Узлы с 3+ концами проводов: там KiCad рисует junction,
            #     даже если это не T-контакт.
            from collections import Counter
            end_count = Counter()
            for (a, b) in wires:
                end_count[(round(a[0], 4), round(a[1], 4))] += 1
                end_count[(round(b[0], 4), round(b[1], 4))] += 1
            for pt, n in end_count.items():
                if n >= 3:
                    junctions.add(pt)

            if not junctions:
                log.info("  [junc] %s: T-контактов в файле нет", path)
                continue

            # 3. Запись junctions в тех же координатах
            lines = []
            for (x, y) in sorted(junctions):
                lines.append(
                    '\t(junction (at %s %s) (diameter 0) (color 0 0 0 0) '
                    '(uuid "%s"))\n' % (x, y, _uuid.uuid4())
                )
            block = "".join(lines)
            m = re.search(r"\n\s*\(sheet_instances", text)
            idx = m.start() if m else text.rfind(")")
            text = text[:idx] + "\n" + block + text[idx:]
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            log.info("  [junc] %s: записано %d junctions", path, len(junctions))

    def _fix_hier_label_rotation(self, path, ref_x=None, log=None):
        """Постобработка .kicad_sch: левым (x < ref_x) hier-меткам ставит
        angle=180, правым — angle=0. Делается в тексте файла, потому что
        kicad_sch_api может молча игнорировать kwarg rotation= в
        add_hierarchical_label. ref_x — центр компонентов; если None,
        используется середина между крайними метками."""
        if log is None:
            log = logging.getLogger("kicad_gen")
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            log.warning("  [label-rot] не могу прочитать %s: %s", path, e)
            return

        pat = re.compile(
            r'(\(hierarchical_label\s+"[^"]*"\s+\(shape\s+\w+\)\s+'
            r'\(at\s+([-\d.]+)\s+([-\d.]+)\s+)([-\d.]+)(\))')
        matches = list(pat.finditer(text))
        if not matches:
            log.info("  [label-rot] %s: hier-меток нет", path)
            return

        if ref_x is None:
            xs = [float(m.group(2)) for m in matches]
            mid = (min(xs) + max(xs)) / 2.0
        else:
            mid = float(ref_x)

        def _sub(m):
            x = float(m.group(2))
            angle = 180 if x < mid else 0
            return f"{m.group(1)}{angle}{m.group(5)}"

        new_text = pat.sub(_sub, text)
        if new_text == text:
            log.info("  [label-rot] %s: ориентация уже корректна", path)
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        log.info("  [label-rot] %s: повёрнуто %d меток (ref_x=%.2f)",
                 path, len(matches), mid)

    def build_entire_project(self, max_passes=5):
        """routing_driven: внешний цикл по коэффициенту разреженности."""
        root_page, sheets = self.load_project_data()
        if not root_page:
            return
        log.info("=" * 70)
        log.info("Начало компиляции: главный лист + %d дочерних", len(sheets))
        log.info("=" * 70)

        best = None
        blame_bias = {}
        for _pass in range(max_passes):
            S = 1.0 + 0.15 * _pass
            log.info("=" * 70)
            log.info("routing_driven: проход %d/%d, S=%.2f",
                     _pass + 1, max_passes, S)
            log.info("=" * 70)
            self.density_scale = S
            self._failed_blame_bias = blame_bias
            self._failed_blame = {}

            try:
                total_routed, total_failed = 0, 0
                main_info = {
                    "components": root_page.get("components", {}),
                    "nets": root_page.get("nets", {}),
                    "ports": [],
                    "file": root_page.get(
                        "file", "climate_control_niva_travel.kicad_sch"),
                    "sheets_raw": sheets,
                }
                _r = self.compile_sheet_to_kicad("MAIN_ROOT", main_info)
                if isinstance(_r, tuple):
                    r, f = _r
                else:
                    r, f = 0, 0
                total_routed += r; total_failed += f
                for name, info in sheets.items():
                    _r = self.compile_sheet_to_kicad(name, info)
                    if isinstance(_r, tuple):
                        r, f = _r
                    else:
                        r, f = 0, 0
                    total_routed += r; total_failed += f
                log.info(
                    "routing_driven: проход S=%.2f -> routed=%d, failed=%d",
                    S, total_routed, total_failed)
                if self._failed_blame:
                    top = sorted(self._failed_blame.items(),
                                 key=lambda kv: -kv[1])[:10]
                    log.error(
                        "routing_driven: проход S=%.2f — главные виновники: %s",
                        S, top)
                else:
                    log.info(
                        "routing_driven: проход S=%.2f — неудач нет", S)
                blame_bias = dict(self._failed_blame)
            except Exception as e:
                log.error("routing_driven: проход S=%.2f упал: %s", S, e)
                import traceback
                log.error(traceback.format_exc()[:800])
                continue

            score = (total_failed, -total_routed)
            if best is None or score < best["score"]:
                best = {"score": score, "S": S,
                        "routed": total_routed, "failed": total_failed}

            if total_failed == 0:
                log.info("🎉 Все связи разведены на S=%.2f", S)
                break

        if best is None:
            log.error("routing_driven: ни один проход не завершился")
            return
        log.info("routing_driven: лучший S=%.2f, routed=%d, failed=%d",
                 best["S"], best["routed"], best["failed"])
        log.info("🎉 Проект скомпилирован.")




if __name__ == "__main__":
    SchematicGenerator("./main.yaml").build_entire_project()

# --- PATCHED-BY patch_generator.py ---

# --- PATCHED-BY patch_generator_v3.py ---

# --- PATCHED-BY patch_generator_v5.py ---

# --- PATCHED-BY patch_generator_v6.py ---

# --- PATCHED-BY patch_generator_v9.py ---

# --- PATCHED-BY patch_generator_v13.py ---

# --- PATCHED-BY patch_v16.py ---

# --- PATCHED-BY patch_v17.py ---

# --- PATCHED-BY patch_v22.py ---

# --- PATCHED-BY patch_v22fix.py ---

# --- PATCHED-BY patch_v23.py ---

# --- PATCHED-BY patch_v29.py ---

# --- PATCHED-BY patch_v30.py ---

# --- PATCHED-BY patch_v33.py ---

# --- PATCHED-BY patch_v34.py ---

# --- PATCHED-BY patch_v35.py ---
