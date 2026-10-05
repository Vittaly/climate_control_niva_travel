# component.py
"""Компонент: собирается из YAML-описания типа.

Компонент знает свою страницу (двусторонняя связь Sheet ↔ Component).

Проектные refdes и instance-пути:
    Помимо локального designator'а ("U1") компонент может быть
    инстанцирован несколько раз (если лист переиспользуется).
    Каждое присутствие — это SheetInstance, в котором компонент
    присутствует. Список self.instances: List[SheetInstance]
    заполняется Sheet.register_instance в момент загрузки.

    Refdes — производное: make_refdes(self.designator, inst.page).
    Path — тоже производное: инстанс знает свой path через цепочку
    parent'ов. Компонент не хранит ни то, ни другое — только
    ссылки на SheetInstance, где он присутствует.

Alias-пины:
    Схлопывание пинов, сидящих на одном паде, выполняет Netlist
    (см. netlist.assign_pin_to_net). Компонент только:
      - владеет пинами и их геометрией,
      - умеет считать abs_pin_mm,
      - логирует дефекты библиотеки, но НЕ схлопывает их.

Системы координат:
    Символ (KiCad lib):     Y↑, 0 в anchor (точке привязки).
    Страница:               Y↓, 0 в верхнем-левом углу сетки.

    При загрузке из библиотеки координаты пинов немедленно
    конвертируются в систему СТРАНИЦЫ (Y↓) и сохраняются как
    СМЕЩЕНИЕ ОТ ЯКОРЯ:
        pin.offset_mm.x = x_lib - anchor_sym.x
        pin.offset_mm.y = anchor_sym.y - y_lib   (Y↓)

    где anchor_sym = (0, 0) в системе символа.

    После конвертации pin.offset_mm — всегда в системе страницы (Y↓),
    отсчитывается ОТ ЯКОРЯ.

    bbox_size (cols, rows) покрывает ВСЕ клетки пинов.
    Границы bbox по каждой оси снапаются к сетке:
        min — floor вниз, max — ceil вверх,
    и берётся диапазон [min_cell .. max_cell] ВКЛЮЧИТЕЛЬНО
    (то есть bbox_cols = max_cell - min_cell + 1).
    Это гарантирует, что клетка любого пина (в смысле abs_pin_cell,
    который округляет по round) лежит внутри bbox, даже если пин
    стоит не кратно сетке.

    Если ширина/высота bbox меньше клетки (все пины в одной точке),
    bbox СИММЕТРИЧНО расширяется на одну клетку С КАЖДОЙ СТОРОНЫ.

    Смещения пинов от якоря НЕ меняются. При расширении меняется
    только anchor_offset_mm (якорь сдвигается относительно левого-
    верхнего угла bbox).

    Точка якоря на странице (anchor_page_mm) вычисляется из
    bbox_origin (переданного placer'ом) и anchor_offset_mm:
        anchor_page_mm = bbox_origin_mm + anchor_offset_mm
    и сохраняется в компоненте через set_position().
    Сам bbox_origin НЕ хранится.

Направление пина (direction):
    Считается в from_yaml из ГЕОМЕТРИИ, но на СЫРЫХ координатах
    символа (Y↑, до конвертации). Библиотечный orientation
    используется только для сравнения.

Ориентация экземпляра (rotation, mirror):
    По умолчанию rotation=0, mirror=None. Задаются Placer'ом при
    расстановке (или из YAML). Пересчёт bbox, координат пинов и
    клеток при не-дефолтных значениях — TODO (см. _apply_orientation).

Логирование:
    Префикс формируется через ctx(page, net, comp, pin) из
    logging_setup. В from_yaml page передаётся вызывающим кодом
    (Sheet / Project); во внутренних методах берётся из
    self.sheet_path.

Контракт from_yaml:
    Либо возвращает построенный Component, либо бросает:
      - DesignatorError      — designator не проходит валидацию KiCad;
      - ComponentLoadError   — компонент в принципе не собирается
                               (нет type, type не описан, нет symbol,
                               symbol отсутствует в библиотеке).
    Возврат None запрещён: молчаливая потеря компонента приводила
    к «расхождениям в сетях» (node_skipped reason=no_component)
    без внятной причины.

SPICE-привязка:
    На этапе from_yaml из component_types[type].spice собирается
    simProperties: Dict[str, str] — готовые пары "Sim.Xxx" → "value".
    Writer проецирует их в .kicad_sch как properties символа;
    kicad-cli выгружает их в нетлист; kicad_to_spice.py читает
    оттуда.

    Ветки spice-секции (по порядку проверки):

        primitive + model_def   → встроенный прибор с явной моделью:
            primitive: D
            model_def: ".model LED_WHITE D(IS=1e-22 N=2.5 RS=6)"
            → Sim.Device=D, Sim.Model=LED_WHITE,
              Sim.Params="IS=1e-22 N=2.5 RS=6"
            Значения IS/N/RS идут в .model; .cir собирает строку
            ".model LED_WHITE D(IS=1e-22 N=2.5 RS=6)" и D<ref> на неё.
            Если primitive есть, а model_def пуст — Sim.Model из
            spice.model или type_name без TYPE_, Sim.Params из
            spice.params. value НЕ используется: у диодов/транзисторов
            value — парт-номер или описание, не SPICE-идентификатор.

        subckt+include          → X-инстанс:
            Sim.Device=X, Sim.Name, Sim.Library,
            Sim.Pins (pin=port, порядок из spice.nodes),
            Sim.Params (spice.params + required_params с дефолтами),
            Sim.Enable=1.

        model (spice.model)     → встроенный прибор + .model:
            Sim.Device из spice.device или lib_id,
            Sim.Model из spice.model,
            Sim.Params из spice.params.

        lib_id Device:D/LED/…   → без spice-секции:
            Sim.Device из _infer_spice_device,
            Sim.Model из type_name без TYPE_,
            Sim.Params из spice.params.

        lib_id Device:R/C/L     → примитивы без модели:
            Sim.Device=R/C/L,
            Sim.Params="<dev>=<value>" (spice.value → value типа).

        иначе                   → пусто, kicad_to_spice пропустит
                                  компонент или выведет «не моделируется».

    Спец-случай U1 (STM32G071RBT6): тип несёт subckt+auto_ports,
    но Sim.Library зависит от сценария (сгенерированный per-scenario
    .sub). Здесь пишется только Sim.Device/Sim.Name; Sim.Library
    подставляет kicad_to_spice.py на этапе сборки .cir.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple, TYPE_CHECKING

from cell import Cell
from constants import (
    Axis,
    DEFAULT_DIRECTION,
    DEFAULT_GRID_MM,
    GRID_EPSILON_MM,
    ComponentKind,
    Direction,
    WireAngle,
    new_uuid,
    orientation_to_direction,
    opposite_direction,
    wire_angle_to_direction,
)
from logging_setup import get_logger, ctx
from primitive import Primitive
from pin import Pin

from designators import validate_component_designator

if TYPE_CHECKING:
    from kicad_source import KiCadSource
    from sheet import Sheet
    from sheet_instance import SheetInstance

log = get_logger(__name__)


# Эпсилон для floor/ceil при снапе границ bbox к сетке.
# Нужен, чтобы пины, стоящие ровно на линии сетки, не «уезжали»
# в соседнюю клетку из-за float-погрешности деления.
_SNAP_EPS = 1e-6


# =========================================================
# Ошибки загрузки компонента
# =========================================================

class ComponentLoadError(Exception):
    """Component.from_yaml не смог собрать компонент из YAML.

    В отличие от DesignatorError (валидация имени), эта ошибка
    означает, что компонент в принципе не может быть построен:
    неизвестный type, отсутствующий symbol в библиотеке,
    отсутствующий symbol в описании типа и т.п.

    Несёт структурированный контекст — designator, type, symbol,
    value, reason, hint — чтобы Project мог собрать читаемое
    сообщение и НЕ терял компонент молча.
    """

    def __init__(
        self,
        designator: str,
        reason: str,
        *,
        type_name: Optional[str] = None,
        symbol: Optional[str] = None,
        value: Optional[str] = None,
        hint: Optional[str] = None,
    ):
        self.designator = designator
        self.reason = reason
        self.type_name = type_name
        self.symbol = symbol
        self.value = value
        self.hint = hint

        parts = [f"components.{designator}:"]
        if type_name is not None:
            parts.append(f"type={type_name!r}")
        if symbol is not None:
            parts.append(f"symbol={symbol!r}")
        if value is not None:
            parts.append(f"value={value!r}")
        parts.append(f"— {reason}")
        if hint:
            parts.append(f"({hint})")
        super().__init__(" ".join(parts))


# =========================================================
# Геометрия пина: направление «наружу от bbox» в системе СИМВОЛА
# =========================================================

def _compute_outward_angle(
    x_mm: float, y_mm: float,
    min_x: float, min_y: float,
    max_x: float, max_y: float,
) -> WireAngle:
    """Направление наружу от bbox в системе СИМВОЛА (Y вверх).

    Возвращает WireAngle:
        NORTH = вверх (y+), SOUTH = вниз (y−),
        WEST  = влево (x−), EAST  = вправо (x+).

    Логика:
        - расстояния от пина до каждой грани bbox;
        - минимум — единственный кандидат, если пин на одной грани;
        - при ничье (пин в углу bbox) — идём вдоль длинной оси.

    Args:
        x_mm, y_mm:  координаты пина в системе символа (Y вверх).
        min_x, min_y, max_x, max_y:  bbox символа (Y вверх).

    Returns:
        WireAngle — направление «наружу» в системе символа.
    """
    dist_left   = x_mm - min_x
    dist_right  = max_x - x_mm
    dist_top    = max_y - y_mm
    dist_bottom = y_mm - min_y

    candidates = [
        (dist_left,   WireAngle.WEST,  "h"),
        (dist_right,  WireAngle.EAST,  "h"),
        (dist_top,    WireAngle.NORTH, "v"),
        (dist_bottom, WireAngle.SOUTH, "v"),
    ]
    min_dist = min(c[0] for c in candidates)
    closest = [c for c in candidates if abs(c[0] - min_dist) < 1e-6]

    if len(closest) == 1:
        return closest[0][1]

    width  = max_x - min_x
    height = max_y - min_y
    priority = {"v": 0, "h": 1} if height >= width else {"h": 0, "v": 1}
    closest.sort(key=lambda c: priority[c[2]])
    return closest[0][1]


# =========================================================
# Нормализация имён выводов KiCad-символа
# =========================================================

def _norm_pin_name(name: Optional[str]) -> str:
    """Нормализует имя вывода KiCad-символа.

    Отрезает суффиксы, которые добавляют генераторы символов
    (EasyEDA / JLC2KiCadLib, CubeMX-импортёры и т.п.):

        'VSS/VSSA'             → 'VSS'
        'VDD/VDDA'             → 'VDD'
        'PF2 - NRST'           → 'PF2'
        'PF2-NRST'             → 'PF2'
        'PA14-BOOT0'           → 'PA14'
        'PA11[PA9]'            → 'PA11'
        'PA12[PA10]'           → 'PA12'
        'PC14-OSC32_IN (PC14)' → 'PC14'
        'PC15-OSC32_OUT (PC15)'→ 'PC15'
        'PF0-OSC_IN (PF0)'     → 'PF0'

    Порядок срезания: '[' → '/' → '-' → '('. Все разделители
    однозначны, порядок не влияет на результат. В конце — strip,
    чтобы убрать пробел после '-', как в 'PF2 - NRST'.

    Возвращает пустую строку, если name пуст/None.
    """
    if not name:
        return ""
    s = str(name).strip().strip("'\"")
    s = s.split("[", 1)[0]         # PA11[PA9]
    s = s.split("/", 1)[0]         # VSS/VSSA
    s = s.split("-", 1)[0]         # PF2 - NRST, PC15-OSC32_OUT
    s = s.split("(", 1)[0]         # ... (PC15)
    return s.strip()


# =========================================================
# Разбор строки .model из spice.model_def
# =========================================================

def _parse_model_def(
    model_def: Optional[str],
) -> Tuple[Optional[str], Optional[str], str]:
    """Разобрать строку .model из spice.model_def.

    Возвращает (имя_модели, тип_модели, строка_параметров):

        '.model LED_WHITE D(IS=1e-22 N=2.5 RS=6 BV=5 CJO=10p)'
            → ('LED_WHITE', 'D', 'IS=1e-22 N=2.5 RS=6 BV=5 CJO=10p')
        '.model MMBT3906 PNP(BF=200 VAF=100)'
            → ('MMBT3906', 'PNP', 'BF=200 VAF=100')
        '.model BSS138 NMOS(VTO=1.3 KP=0.5)'
            → ('BSS138', 'NMOS', 'VTO=1.3 KP=0.5')
        '.model SS54 D'
            → ('SS54', 'D', '')
        мусор/None
            → (None, None, '')

    Тип модели — второе слово в .model: D, NPN, PNP, NMOS, PMOS,
    VDMOS, NJF, PJF, … Извлекается ВСЕГДА, потому что иначе
    kicad_to_spice.py не может отличить PNP от NPN и подставляет
    дефолт по префиксу элемента (Q → NPN), ломая PNP-транзисторы.

    Регистр .MODEL/.model не важен.
    """
    if not model_def:
        return None, None, ""

    s = str(model_def).strip()

    # Вариант с параметрами: .model NAME TYPE(...)
    m = re.match(
        r'\.\s*model\s+(\S+)\s+(\w+)\s*\(([^)]*)\)',
        s, re.IGNORECASE,
    )
    if m:
        return m.group(1), m.group(2), m.group(3).strip()

    # Вариант без параметров: .model NAME TYPE
    m = re.match(
        r'\.\s*model\s+(\S+)\s+(\w+)\s*(.*)',
        s, re.IGNORECASE,
    )
    if m:
        tail = m.group(3).strip().strip("()").strip()
        return m.group(1), m.group(2), tail

    return None, None, ""


# =========================================================
# Компонент
# =========================================================

@dataclass(eq=False)
class Component(Primitive):
    """Экземпляр компонента на странице.

    Attributes:
        designator:        локальное обозначение ("U1", "R3").
        name:              человекочитаемое value ("10k", "STM32F103").
        lib_id:            KiCad lib_id символа ("Device:R").
        bbox_size:         (cols, rows) — размер габарита в клетках.
        pins:              список Pin со смещением от якоря (мм, Y↓).
        fields:            дополнительные поля из YAML.
        sheet:             страница-владелец.
        instances:         SheetInstance[] — присутствия компонента
                           в инстансах его листа. Заполняется
                           Sheet.register_instance в момент загрузки.
                           Пустой до регистрации. Refdes и path —
                           производные от (designator, inst.page)
                           и (inst.path); собственных копий нет.
        rotation:          угол поворота экземпляра (0/90/180/270).
        mirror:            отражение экземпляра: None / "x" / "y".
        anchor_offset_mm:  (x_mm, y_mm) — смещение якоря от левого-верхнего
                           угла bbox (система страницы, Y↓).
        anchor_page_mm:    (x_mm, y_mm) — координаты якоря на странице (мм),
                           заполняются Placer'ом через set_position().
        grid_mm:           шаг сетки в мм.
        simProperties:     пары "Sim.Xxx" → "value" — SPICE-привязка
                           компонента. Заполняется в from_yaml из
                           component_types[type].spice; writer
                           проецирует их в .kicad_sch как properties,
                           kicad-cli выгружает в нетлист.
    """
    designator: str
    name: str
    lib_id: str
    bbox_size: Tuple[int, int]              # (cols, rows) в клетках
    pins: List[Pin] = field(default_factory=list)
    fields: Dict[str, str] = field(default_factory=dict)
    sheet: Optional["Sheet"] = field(default=None, repr=False)
    instances: List["SheetInstance"] = field(
        default_factory=list, repr=False,
    )
    rotation: int = 0
    mirror: Optional[str] = None
    anchor_offset_mm: Tuple[float, float] = (0.0, 0.0)
    anchor_page_mm: Optional[Tuple[float, float]] = None
    grid_mm: float = DEFAULT_GRID_MM
    simProperties: Dict[str, str] = field(default_factory=dict, repr=False)

    # ---------- удобные свойства ----------

    @property
    def bbox_cols(self) -> int:
        """Ширина bbox в клетках."""
        return self.bbox_size[Axis.X]

    @property
    def bbox_rows(self) -> int:
        """Высота bbox в клетках."""
        return self.bbox_size[Axis.Y]

    # ---------- хэш / идентичность ----------

    def __hash__(self) -> int:
        """Хэш по designator'у. Уникален в пределах страницы."""
        return hash(self.designator)

    @property
    def sheet_path(self) -> str:
        """Путь страницы-владельца ("" для корня, если sheet не задан)."""
        return self.sheet.sheet_path if self.sheet else ""

    @property
    def fqn(self) -> str:
        if self.sheet is None:
            return self.designator
        prefix = self.sheet.fqn_prefix
        return f"{prefix}/{self.designator}" if prefix else self.designator

    def fqn_pin(self, pin: Pin) -> str:
        """FQN пина этого компонента: "X_ACT/U2:5"."""
        return f"{self.fqn}:{pin.number}"

    # ---------- инстансы и проектные refdes ----------

    @property
    def has_instances(self) -> bool:
        """Есть ли у компонента хотя бы один зарегистрированный инстанс."""
        return bool(self.instances)

    @property
    def sheet_instances(self) -> List["SheetInstance"]:
        """Все SheetInstance, в которых присутствует компонент.

        Порядок — как в self.instances, то есть в порядке регистрации
        (DFS-обход дерева).
        """
        return list(self.instances)

    @property
    def project_refdes(self) -> List[str]:
        """Все проектные имена компонента, по одному на инстанс.

        Refdes — производное от (designator, inst.page); не хранится.
        """
        from refdes import make_refdes
        return [make_refdes(self.designator, inst.page)
                for inst in self.instances]

    def refdes_in(self, inst: "SheetInstance") -> Optional[str]:
        """Проектное имя компонента в конкретном инстансе листа.

        Возвращает None, если компонент в этом инстансе не присутствует.
        """
        from refdes import make_refdes
        for i in self.instances:
            if i is inst:
                return make_refdes(self.designator, inst.page)
        return None

    def refdes_at_page(self, page: int) -> Optional[str]:
        """Проектное имя компонента на странице с указанным номером.

        Удобно, когда известен только номер страницы (например, из
        E2E-сценария). Возвращает None, если ни один инстанс не
        имеет этого page.
        """
        from refdes import make_refdes
        for i in self.instances:
            if i.page == page:
                return make_refdes(self.designator, i.page)
        return None

    def path_in(self, inst: "SheetInstance") -> Optional[str]:
        """Instance-путь листа в конкретном инстансе.

        Делегация к inst.path — сам компонент path не хранит.
        Возвращает None, если компонент в этом инстансе не присутствует.
        """
        for i in self.instances:
            if i is inst:
                return i.path
        return None

    def path_at_page(self, page: int) -> Optional[str]:
        """Instance-путь листа на странице с указанным номером."""
        for i in self.instances:
            if i.page == page:
                return i.path
        return None

    def add_instance(self, inst: "SheetInstance") -> None:
        """Зарегистрировать присутствие компонента в инстансе листа.

        Хранит ссылку на SheetInstance. Refdes и path — производные,
        не хранятся. Идемпотентно: повторный вызов с тем же inst — no-op.
        """
        for existing in self.instances:
            if existing is inst:
                return
        self.instances.append(inst)

    # ---------- поиск пинов ----------

    def pin_by_number(self, number: str) -> Optional[Pin]:
        """Возвращает пин по номеру ("1", "A", ...) или None."""
        for p in self.pins:
            if p.number == number:
                return p
        return None

    def pin_by_name(self, name: str) -> Optional[Pin]:
        """Пин по имени (pinfunction). None, если не найден/неоднозначен.

        Порядок поиска:
        1. Точное совпадение. Найдено ровно одно — возвращаем.
        2. Совпадение без учёта регистра. Найдено ровно одно — возвращаем
        с WARNING (чтобы автор знал о расхождении и мог поправить YAML).
        3. Совпадение после нормализации имени (_norm_pin_name). Найдено
        ровно одно — возвращаем с DEBUG. Это покрывает символы, где
        имя вывода содержит суффиксы ('VSS/VSSA', 'PF2-NRST',
        'PA14-BOOT0', 'PA11[PA9]' и т.п.).
        4. Не найдено или неоднозначно — None и WARNING.
        """
        if not name:
            return None

        # 1. Точное совпадение
        exact = [p for p in self.pins if p.name == name]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            log.warning(
                "%s: pinfunction=%r неоднозначен, найдено %d пинов "
                "(номера: %s). Используйте pin: '<номер>'.",
                ctx(page=self.sheet_path or None, comp=self.designator),
                name, len(exact),
                ", ".join(p.number for p in exact),
            )
            return None

        # 2. Fallback без учёта регистра
        lower = name.lower()
        ci = [p for p in self.pins
              if p.name and p.name.lower() == lower]
        if len(ci) == 1:
            log.warning(
                "%s: pinfunction=%r найдено как %r — "
                "регистр отличается. В YAML лучше писать точно как в символе.",
                ctx(page=self.sheet_path or None, comp=self.designator),
                name, ci[0].name,
            )
            return ci[0]
        if len(ci) > 1:
            log.warning(
                "%s: pinfunction=%r — несколько кандидатов по регистру: %s",
                ctx(page=self.sheet_path or None, comp=self.designator),
                name, [p.name for p in ci],
            )
            return None

        # 3. Fallback через нормализацию имени
        target = _norm_pin_name(name)
        if not target:
            return None
        normed = [p for p in self.pins
                  if p.name and _norm_pin_name(p.name) == target]
        if len(normed) == 1:
            log.debug(
                "%s: pinfunction=%r найдено как %r — через нормализацию.",
                ctx(page=self.sheet_path or None, comp=self.designator),
                name, normed[0].name,
            )
            return normed[0]
        if len(normed) > 1:
            log.warning(
                "%s: pinfunction=%r нормализуется в %r, но кандидатов "
                "несколько: %s. Используйте pin: '<номер>'.",
                ctx(page=self.sheet_path or None, comp=self.designator),
                name, target, [p.name for p in normed],
            )
            return None

        return None

    def pin_by_local_key(self, local_key: str) -> Optional[Pin]:
        """Возвращает пин по локальному ключу "U1:42" или None."""
        for p in self.pins:
            if p.local_key == local_key:
                return p
        return None

    def pin_by_identifier(self, ident: str) -> Optional[Pin]:
        """Находит пин по идентификатору без уточнения его природы.

        Идентификатор приходит из внешнего источника, где неизвестно,
        номер это или имя:
            * из FQN: "U1:42", "X_POWER_SUPPLY:VCC_12V";
            * из local_key: "U1:42";
            * из ключа словаря сети.

        Приоритет — номер, затем имя.
        """
        if not ident:
            return None
        by_num = self.pin_by_number(ident)
        if by_num is not None:
            return by_num
        return self.pin_by_name(ident)

    # ---------- построение из YAML ----------

    @classmethod
    def from_yaml(
        cls,
        designator: str,
        cdef: dict,
        types: dict,
        source: "KiCadSource",
        grid_mm: float = DEFAULT_GRID_MM,
        page: Optional[str] = None,
    ) -> "Component":
        """Собирает компонент из описания типа в component_types.

        См. докстринг модуля — расчёт bbox, anchor_offset_mm,
        pin.offset_mm, pin.direction, simProperties.

        Raises:
            ComponentLoadError: тип не указан, тип не описан,
                symbol не указан в типе, symbol не найден в
                библиотеке.
            DesignatorError: designator не проходит валидацию KiCad.
        """
        # --- 1. type обязателен ---
        tname = cdef.get("type")
        if not tname:
            raise ComponentLoadError(
                designator=designator,
                reason="в YAML не указано поле type",
                value=cdef.get("value"),
            )

        # --- 2. type должен быть описан в component_types ---
        if tname not in types:
            known = sorted(types.keys())
            if known:
                shown = known[:10]
                suffix = (
                    f" (+{len(known) - len(shown)} ещё)"
                    if len(known) > len(shown) else ""
                )
                hint = f"известные типы: {', '.join(shown)}{suffix}"
            else:
                hint = "component_types пуст"
            raise ComponentLoadError(
                designator=designator,
                reason=f"тип {tname!r} не описан в component_types",
                type_name=tname,
                value=cdef.get("value"),
                hint=hint,
            )

        tinfo = types[tname]

        # --- 3. symbol обязателен ---
        lib_id = tinfo.get("symbol")
        if not lib_id:
            raise ComponentLoadError(
                designator=designator,
                reason=f"в типе {tname!r} не указан symbol",
                type_name=tname,
                value=tinfo.get("value"),
            )

        value = tinfo.get("value", tname)
        fields = dict(tinfo.get("fields", {}))

        # --- 4. symbol должен существовать в библиотеке ---
        try:
            pins_raw = source.get_pins(lib_id)
        except KeyError as e:
            raise ComponentLoadError(
                designator=designator,
                reason=f"символ {lib_id!r} не найден в библиотеке KiCad",
                type_name=tname,
                symbol=lib_id,
                value=value,
                hint=f"KeyError: {e}",
            ) from e

        # --- 5. Сырые границы bbox по пинам (система СИМВОЛА, Y↑) ---
        pin_coords = [(float(p.get("x_mm", 0.0)), float(p.get("y_mm", 0.0)))
                      for p in pins_raw]
        if pin_coords:
            min_x = min(x for x, y in pin_coords)
            max_x = max(x for x, y in pin_coords)
            min_y = min(y for x, y in pin_coords)
            max_y = max(y for x, y in pin_coords)
        else:
            min_x = max_x = min_y = max_y = 0.0

        # --- 6. СИММЕТРИЧНОЕ расширение, если ширина меньше клетки ---
        if max_x - min_x < grid_mm:
            min_x -= grid_mm
            max_x += grid_mm
        if max_y - min_y < grid_mm:
            min_y -= grid_mm
            max_y += grid_mm

        # --- 7. Снап границ bbox к клеткам сетки ---
        min_col_sym = math.floor(min_x / grid_mm + _SNAP_EPS)
        max_col_sym = math.ceil(max_x / grid_mm - _SNAP_EPS)
        min_row_sym = math.floor(min_y / grid_mm + _SNAP_EPS)
        max_row_sym = math.ceil(max_y / grid_mm - _SNAP_EPS)

        bbox_cols = max(1, max_col_sym - min_col_sym + 1)
        bbox_rows = max(1, max_row_sym - min_row_sym + 1)
        bbox_size = (bbox_cols, bbox_rows)

        # --- 8. anchor в системе символа ---
        anchor_x_sym = 0.0
        anchor_y_sym = 0.0

        # --- 9. anchor_offset_mm (от левого-верхнего угла bbox, Y↓) ---
        anchor_offset_x = anchor_x_sym - min_col_sym * grid_mm
        anchor_offset_y = max_row_sym * grid_mm - anchor_y_sym   # Y↓
        anchor_offset_mm = (anchor_offset_x, anchor_offset_y)

        # --- 10. пины (система СТРАНИЦЫ, Y↓, смещение от якоря) ---
        pins: List[Pin] = []
        for p in pins_raw:
            x_lib = float(p.get("x_mm", 0.0))
            y_lib = float(p.get("y_mm", 0.0))

            pin_key = f"{designator}:{p['number']}"
            pin_ctx = ctx(page=page, comp=designator, pin=pin_key)

            log.debug(
                "%s sym_mm=(%7.2f,%7.2f) name=%-8s orient=%s",
                pin_ctx, x_lib, y_lib, p["name"], p.get("orientation", 0),
            )

            pin_offset_x = x_lib - anchor_x_sym
            pin_offset_y = anchor_y_sym - y_lib

            outward = _compute_outward_angle(
                x_mm=x_lib, y_mm=y_lib,
                min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y,
            )
            expected_direction = opposite_direction(
                wire_angle_to_direction(outward)
            )

            lib_orientation = p.get("orientation", 0)
            try:
                lib_orientation_int = int(lib_orientation)
            except (TypeError, ValueError):
                lib_orientation_int = 0
            lib_direction = orientation_to_direction(lib_orientation_int)

            if lib_direction != expected_direction:
                log.warning(
                    "%s библиотечный orientation=%s (direction=%s), "
                    "по геометрии ожидается direction=%s (outward=%s). "
                    "Используем геометрию.",
                    pin_ctx, lib_orientation, lib_direction,
                    expected_direction, outward,
                )
            elif lib_direction == DEFAULT_DIRECTION and lib_orientation_int != 0:
                log.warning(
                    "%s неизвестная ориентация %s, принято %s",
                    pin_ctx, lib_orientation, DEFAULT_DIRECTION,
                )

            pins.append(Pin(
                owner=designator,
                number=p["number"],
                name=p["name"],
                offset_mm=(pin_offset_x, pin_offset_y),
                direction=expected_direction,
            ))

            log.debug(
                "%s offset_mm=(%7.2f,%7.2f) dir=%s",
                pin_ctx, pin_offset_x, pin_offset_y, expected_direction,
            )

        comp = cls(
            designator=designator,
            name=value,
            lib_id=lib_id,
            bbox_size=bbox_size,
            pins=pins,
            fields=fields,
            rotation=int(cdef.get("rotation", 0)) % 360,
            mirror=cdef.get("mirror"),
            anchor_offset_mm=anchor_offset_mm,
            grid_mm=grid_mm,
            simProperties=cls._build_sim_props(tname, tinfo, cdef, lib_id),
        )
        for pin in pins:
            pin.component = comp

        comp._warn_duplicate_pin_positions()

        return comp

    def __post_init__(self) -> None:
        """Валидация инвариантов компонента при создании.

        Reference компонента обязан быть KiCad-совместимым
        (<1..4 латинских буквы><номер>). Порты (PORT_*) — отдельный
        класс; сюда попадать не должны.
        """
        super().__post_init__()

        page = self.sheet_path or None

        if self.designator.startswith("PORT_"):
            raise DesignatorError(
                f"designator {self.designator!r} — это порт, "
                f"а не компонент. Порты создаются отдельным классом "
                f"и пишутся как иерархические метки."
            )

        validate_component_designator(self.designator, page=page)

    # ---------- диагностика дубликатов пинов ----------

    def _warn_duplicate_pin_positions(self) -> None:
        """Логирует группы пинов с одинаковыми координатами внутри компонента."""
        page = self.sheet_path or None
        for i, pi in enumerate(self.pins):
            for j in range(i + 1, len(self.pins)):
                pj = self.pins[j]
                if not self._same_pin_position(pi, pj):
                    continue
                if pi.name == pj.name:
                    log.info(
                        "%s пины %s и %s на одной позиции, имя '%s' "
                        "(кандидаты на alias — схлопнёт Netlist)",
                        ctx(page=page, comp=self.designator),
                        pi.local_key, pj.local_key, pi.name,
                    )
                else:
                    log.error(
                        "%s пины %s и %s на одной позиции, "
                        "но разные имена ('%s' vs '%s') — дефект библиотеки",
                        ctx(page=page, comp=self.designator),
                        pi.local_key, pj.local_key, pi.name, pj.name,
                    )

    def _same_pin_position(self, a: Pin, b: Pin) -> bool:
        """Совпадают ли смещения пинов от якоря."""
        return (abs(a.offset_mm[Axis.X] - b.offset_mm[Axis.X]) <= GRID_EPSILON_MM
                and abs(a.offset_mm[Axis.Y] - b.offset_mm[Axis.Y]) <= GRID_EPSILON_MM)

    # ---------- SPICE-привязка ----------

    @staticmethod
    def _build_sim_props(
        type_name: str,
        tdef: dict,
        cdef: dict,
        lib_id: str,
    ) -> Dict[str, str]:
        """Собрать Sim.* свойства компонента.

        Источники, в порядке приоритета (позже перекрывает раньше):
            tdef["spice"] — общее описание типа;
            cdef["spice"] — разовый override на конкретный инстанс.

        Возвращает готовые пары "Sim.Xxx" -> "value" ровно в том
        виде, в каком они пишутся в .kicad_sch (writer) и выгружаются
        в нетлист kicad-cli. Пустой словарь, если у компонента нет
        SPICE-модели.

        Ветки по структуре spice-секции:

            primitive + model_def   → Sim.Device из primitive,
                Sim.Model и Sim.Params — из model_def (или spice.model
                и spice.params). Пример: LED-тип с
                primitive: D,
                model_def: ".model LED_WHITE D(IS=1e-22 N=2.5 RS=6)"
                → Sim.Device=D, Sim.Model=LED_WHITE,
                  Sim.Params="IS=1e-22 N=2.5 RS=6".

            subckt+include          → Sim.Device=X, Sim.Name, Sim.Library,
                Sim.Pins, Sim.Params (spice.params + required_params),
                Sim.Enable=1.

            model (spice.model)     → Sim.Device, Sim.Model, Sim.Params.

            по lib_id (D/Q/M)       → Sim.Device из _infer_spice_device,
                Sim.Model из type_name без TYPE_, Sim.Params из
                spice.params. value НЕ используется: у диодов/
                транзисторов value — парт-номер или описание,
                не SPICE-идентификатор.

            по lib_id (R/C/L)       → Sim.Device, Sim.Params =
                "<dev>=<value>" (spice.value → value типа/инстанса).

            иначе                   → пусто, kicad_to_spice пропустит
                компонент или выведет «не моделируется».

        Спец-случай U1 (STM32G071RBT6): тип несёт subckt+auto_ports,
        но Sim.Library зависит от сценария (сгенерированный per-scenario
        .sub). Здесь пишется только Sim.Device/Sim.Name; Sim.Library
        подставляет kicad_to_spice.py на этапе сборки .cir.
        """
        spice = {**(tdef.get("spice") or {}), **(cdef.get("spice") or {})}
        out: Dict[str, str] = {}

        # ── 0. primitive + model_def — встроенный прибор с .model ──
        # Самый явный случай: в spice заданы primitive ("D"/"Q"/"M"/…)
        # и model_def (строка ".model NAME TYPE(params)"). Из model_def
        # извлекаем имя и параметры; сам .model соберёт
        # kicad_to_spice.collect_model_defs_from_comps как
        # ".model <Sim.Model> <type>(<Sim.Params>)".
        #
        # Пример LED-типа:
        #     primitive: D
        #     model_def: ".model LED_WHITE D(IS=1e-22 N=2.5 RS=6 BV=5 CJO=10p)"
        # → Sim.Device="D", Sim.Model="LED_WHITE",
        #   Sim.Params="IS=1e-22 N=2.5 RS=6 BV=5 CJO=10p".
        primitive = spice.get("primitive")
        if primitive in ("D", "Z", "Q", "M", "J"):
            out["Sim.Device"] = str(primitive)

            model_def = spice.get("model_def")
            mname, mtype, mparams = _parse_model_def(model_def or "")

            # Имя модели: spice.model > из model_def > type_name без TYPE_.
            if spice.get("model"):
                out["Sim.Model"] = str(spice["model"])
            elif mname:
                out["Sim.Model"] = mname
            else:
                fallback = type_name.removeprefix("TYPE_")
                if fallback:
                    out["Sim.Model"] = fallback

            # spice.params дополняет параметры из model_def.
            extra_parts: List[str] = []
            for k, v in (spice.get("params") or {}).items():
                extra_parts.append(f"{k}={v}")
            extra = " ".join(extra_parts)

            # Sim.Params = "TYPE(params)" — тип из model_def, а не
            # из _model_type_for. Иначе MMBT3906 (PNP) превратится
            # в NPN и вся логика перевернётся.
            if mtype:
                params_body = mparams
                if extra:
                    params_body = (params_body + " " + extra).strip()
                out["Sim.Params"] = f"{mtype}({params_body})"
            elif extra:
                default_type = {
                    "D": "D", "Z": "D",
                    "Q": "NPN",
                    "M": "NMOS",
                    "J": "NJF",
                }.get(primitive, "D")
                out["Sim.Params"] = f"{default_type}({extra})"

            return out

        subckt = spice.get("subckt")
        model = spice.get("model")
        device = spice.get("device")

        # ── 1. .subckt (X-инстанс) ──
        if subckt:
            out["Sim.Device"] = str(device) if device else "X"
            out["Sim.Name"] = str(subckt)

            if spice.get("include"):
                out["Sim.Library"] = (
                    "${KIPRJMOD}/spice/lib/" + str(spice["include"])
                )

            # Sim.Pins — строка целиком, в порядке портов из YAML.
            # dict сохраняет порядок вставки в Python 3.7+, поэтому
            # проходим по spice["nodes"].items() без сортировок.
            nodes = spice.get("nodes") or {}
            if isinstance(nodes, dict) and nodes:
                pairs = []
                for port, spec in nodes.items():
                    if not isinstance(spec, dict):
                        continue
                    pnum = spec.get("pin")
                    if pnum is None:
                        continue
                    pairs.append(f"{pnum}={port}")
                if pairs:
                    out["Sim.Pins"] = " ".join(pairs)

            # Sim.Params: сначала spice.params (k=v), затем
            # required_params (name=default, либо name без default).
            params_parts: List[str] = []
            for k, v in (spice.get("params") or {}).items():
                params_parts.append(f"{k}={v}")
            for p in spice.get("required_params", []) or []:
                pname = p.get("name")
                if not pname:
                    continue
                default = p.get("default")
                if default is None or default == "":
                    params_parts.append(str(pname))
                else:
                    params_parts.append(f"{pname}={default}")
            if params_parts:
                out["Sim.Params"] = " ".join(params_parts)

            out["Sim.Enable"] = "1"
            return out

        # ── 2. .model (явный spice.model) ──
        if model:
            out["Sim.Device"] = (
                str(device) if device
                else (Component._infer_spice_device(lib_id) or "D")
            )
            out["Sim.Model"] = str(model)

            if spice.get("include"):
                out["Sim.Library"] = (
                    "${KIPRJMOD}/spice/lib/" + str(spice["include"])
                )

            if spice.get("params"):
                out["Sim.Params"] = " ".join(
                    f"{k}={v}" for k, v in spice["params"].items()
                )
            return out

        # ── 3. D / Q / M / J / Z по lib_id — без spice.model ──
        # Имя модели: spice.model уже рассмотрен выше, значит либо
        # производное от имени типа (TYPE_SS54 → SS54), либо
        # ничего. value НЕ используется: у диодов/транзисторов value —
        # парт-номер или описание («Индикатор зелёный 1206»),
        # не SPICE-идентификатор.
        prim = Component._infer_spice_device(lib_id)
        if prim in ("D", "Z", "Q", "M", "J"):
            out["Sim.Device"] = prim
            model_name = type_name.removeprefix("TYPE_")
            if model_name:
                out["Sim.Model"] = str(model_name)
            if spice.get("params"):
                out["Sim.Params"] = " ".join(
                    f"{k}={v}" for k, v in spice["params"].items()
                )
            return out

        # ── 4. R / C / L — примитивы с номиналом ──
        # Значение берём из spice.value (уже в SPICE-нотации),
        # иначе из value типа/инстанса (KiCad-нотация = SPICE
        # для типовых номиналов: 10k, 100n, 1u).
        prim = Component._infer_spice_device(lib_id)
        if prim in ("R", "C", "L"):
            out["Sim.Device"] = prim
            sp_value = spice.get("value")
            value = sp_value or tdef.get("value") or cdef.get("value")
            if value:
                out["Sim.Params"] = f"{prim}={value}"
            return out

        return out

    @staticmethod
    def _infer_spice_device(lib_id: str) -> Optional[str]:
        """Вывести SPICE-префикс прибора из lib_id символа.

        Используется как fallback, когда в spice-секции не задан
        явно device. Возвращает:
            "R"/"C"/"L" — для Device:R / Device:C / Device:L;
            "D"          — для Device:D*, Device:LED;
            "Q"          — для Device:Q_*;
            "M"          — для Device:M_*;
            None         — если символ не опознан.
        """
        if not lib_id:
            return None

        exact = {
            "Device:R": "R",
            "Device:C": "C",
            "Device:L": "L",
            "Device:R_Small": "R",
            "Device:C_Small": "C",
            "Device:L_Small": "L",
        }
        if lib_id in exact:
            return exact[lib_id]

        part = lib_id.split(":", 1)[-1]
        if part == "D" or part == "LED" or part.startswith("D_"):
            return "D"
        if part.startswith("Q_"):
            return "Q"
        if part.startswith("M_"):
            return "M"
        return None

    # ---------- позиционирование ----------

    def set_position(
        self,
        bbox_origin: Cell,
        rotation: int = 0,
        mirror: Optional[str] = None,
    ) -> None:
        """Устанавливает позицию компонента на странице.

        Вызывается Placer'ом. Принимает bbox_origin (левый-верхний угол
        bbox в клетках), вычисляет anchor_page_mm и сохраняет только его.
        """
        self.rotation = rotation
        self.mirror = mirror
        self._apply_orientation()
        self.anchor_page_mm = self.anchor_page_mm_at(bbox_origin, self.grid_mm)

    def anchor_page_mm_at(
        self,
        bbox_origin: Cell,
        grid_mm: float = DEFAULT_GRID_MM,
    ) -> Tuple[float, float]:
        """Точка якоря на странице для данного bbox_origin.

        anchor_page_mm = bbox_origin_mm + anchor_offset_mm.
        """
        bx = bbox_origin.col * grid_mm
        by = bbox_origin.row * grid_mm
        return (bx + self.anchor_offset_mm[Axis.X],
                by + self.anchor_offset_mm[Axis.Y])

    def _apply_orientation(self) -> None:
        """Пересчитывает bbox, pin_offset и anchor_offset с учётом rotation/mirror.

        Пока rotation=0, mirror=None — ничего не делает.
        TODO: реализовать при появлении реальных поворотов.
        """
        if self.rotation == 0 and self.mirror is None:
            return
        log.warning(
            "%s rotation=%d mirror=%s — пересчёт геометрии не реализован",
            ctx(page=self.sheet_path or None, comp=self.designator),
            self.rotation, self.mirror,
        )

    # ---------- геометрия ----------

    def bbox_origin_cell(self) -> Cell:
        """Левый-верхний угол bbox на странице (клетки).

        Вычисляется из anchor_page_mm и anchor_offset_mm.
        """
        if self.anchor_page_mm is None:
            raise RuntimeError(
                f"Компонент {self.designator}: anchor_page_mm не установлен. "
                "Вызовите set_position() перед bbox_origin_cell()."
            )
        ax, ay = self.anchor_page_mm
        ox = ax - self.anchor_offset_mm[Axis.X]
        oy = ay - self.anchor_offset_mm[Axis.Y]
        return Cell(round(ox / self.grid_mm), round(oy / self.grid_mm))

    def bbox_page_cell(self) -> Tuple[int, int, int, int]:
        """(col0, row0, col1, row1) — прямоугольник на странице (клетки).

        col1, row1 — ИСКЛЮЧАЮЩИЕ границы.
        """
        origin = self.bbox_origin_cell()
        return (origin.col, origin.row,
                origin.col + self.bbox_cols,
                origin.row + self.bbox_rows)

    def abs_pin_mm(self, pin: Pin) -> Tuple[float, float]:
        """Реальная точка пина на странице (мм).

        abs_pin_mm = anchor_page_mm + pin.offset_mm.
        """
        if self.anchor_page_mm is None:
            raise RuntimeError(
                f"Компонент {self.designator}: anchor_page_mm не установлен. "
                "Вызовите set_position() перед abs_pin_mm()."
            )
        ax, ay = self.anchor_page_mm
        return (ax + pin.offset_mm[Axis.X],
                ay + pin.offset_mm[Axis.Y])

    def abs_pin_cell(self, pin: Pin) -> Cell:
        """Клетка пина на странице (округление от abs_pin_mm)."""
        x, y = self.abs_pin_mm(pin)
        return Cell(round(x / self.grid_mm), round(y / self.grid_mm))

    def iter_occupied_cells(self) -> Iterator[Tuple[int, int]]:
        """Генерирует клетки, занятые габаритом компонента."""
        origin = self.bbox_origin_cell()
        for c in range(origin.col, origin.col + self.bbox_cols):
            for r in range(origin.row, origin.row + self.bbox_rows):
                yield (c, r)

    def iter_pin_cells(self) -> Iterator[Tuple[int, int]]:
        """Генерирует абсолютные клетки пинов компонента."""
        for pin in self.pins:
            cell = self.abs_pin_cell(pin)
            yield (cell.col, cell.row)

    @property
    def frame_size(self) -> Tuple[int, int]:
        """Габарит фигуры, которую рисует Writer.

        Для обычного символа совпадает с bbox.
        Для SheetRef переопределяется: рамка внутри bbox (см. sheet_ref.py).
        """
        return self.bbox_size

    @property
    def frame_offset_mm(self) -> Tuple[float, float]:
        """Смещение ЛВ-угла frame относительно anchor (ЛВ-угла bbox).

        Обычный символ — (0, 0).
        SheetRef — (grid_mm, grid_mm): рамка на 1 клетку внутрь bbox.
        """
        return (0.0, 0.0)

    @property
    def kind(self) -> "ComponentKind":
        """Тип компонента. Переопределяется наследниками.

        У обычного символа — SYMBOL; PortComponent, SheetRefComponent,
        LabelComponent возвращают свой тип.
        """
        return ComponentKind.SYMBOL