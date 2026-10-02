# make_scr/constants.py
"""Единые константы проекта.

Использовать везде вместо литералов:
    Direction.RIGHT, Orientation.DEG_90, WireOrientation.VERTICAL,
    WireAngle.EAST, OccupantKind.PIN, PlacementStrategy.MATRIX,
    NetType.POWER, Symbol.HIERARCHICAL_SHEET, PLACER_MATRIX_MIN, ...

Здесь же — единственные места, где живут маппинги:
    угол вывода → направление;
    угол сегмента → ориентация сегмента;
    WireAngle ↔ Direction (для расчёта отростков);
    противоположное направление (для outward = opposite(direction)).
"""
from enum import IntEnum, StrEnum


# =========================================================
# Направления выводов компонента
# =========================================================

class Direction(StrEnum):
    """Направление вывода компонента в системе KiCad."""
    RIGHT = "right"
    LEFT = "left"
    UP = "up"
    DOWN = "down"


DEFAULT_DIRECTION = Direction.RIGHT


# =========================================================
# Углы ориентации выводов компонента
# =========================================================

class Orientation(IntEnum):
    """Угол ориентации вывода из библиотеки KiCad, в градусах.

    KiCad-семантика: orientation — направление «в тело» (от точки
    подключения пина к корпусу компонента).
    """
    DEG_0 = 0
    DEG_90 = 90
    DEG_180 = 180
    DEG_270 = 270


ORIENTATION_TO_DIRECTION: dict[Orientation, Direction] = {
    Orientation.DEG_0:   Direction.RIGHT,
    Orientation.DEG_90:  Direction.UP,
    Orientation.DEG_180: Direction.LEFT,
    Orientation.DEG_270: Direction.DOWN,
}


def orientation_to_direction(orientation: int) -> Direction:
    """Безопасно переводит угол KiCad в Direction."""
    try:
        return ORIENTATION_TO_DIRECTION[Orientation(orientation)]
    except ValueError:
        return DEFAULT_DIRECTION


# =========================================================
# Ориентация сегментов провода
# =========================================================

class WireOrientation(StrEnum):
    """Ориентация сегмента провода."""
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    DIAGONAL = "diagonal"


class WireAngle(IntEnum):
    """Угол ортогонального сегмента провода, в градусах.

    Семантика (экранная система, Y вниз):
        EAST  = вправо (col + 1)
        WEST  = влево  (col - 1)
        NORTH = вверх  (row - 1)
        SOUTH = вниз   (row + 1)
    """
    EAST = 0
    NORTH = 90
    WEST = 180
    SOUTH = 270


WIRE_ANGLE_TO_ORIENTATION: dict[WireAngle, WireOrientation] = {
    WireAngle.EAST:  WireOrientation.HORIZONTAL,
    WireAngle.WEST:  WireOrientation.HORIZONTAL,
    WireAngle.NORTH: WireOrientation.VERTICAL,
    WireAngle.SOUTH: WireOrientation.VERTICAL,
}


def wire_angle_to_orientation(angle: int) -> WireOrientation:
    """Безопасно переводит угол сегмента в ориентацию."""
    try:
        return WIRE_ANGLE_TO_ORIENTATION[WireAngle(angle)]
    except ValueError:
        return WireOrientation.HORIZONTAL


# =========================================================
# Direction ↔ WireAngle и opposite
# =========================================================

# Direction (KiCad-семантика) → WireAngle (экранная семантика).
# UP = вверх (NORTH), DOWN = вниз (SOUTH),
# LEFT = влево (WEST), RIGHT = вправо (EAST).
DIRECTION_TO_WIRE_ANGLE: dict[Direction, WireAngle] = {
    Direction.UP:    WireAngle.NORTH,
    Direction.DOWN:  WireAngle.SOUTH,
    Direction.LEFT:  WireAngle.WEST,
    Direction.RIGHT: WireAngle.EAST,
}


def direction_to_wire_angle(d: Direction) -> WireAngle:
    """Direction → WireAngle (семантическое соответствие)."""
    return DIRECTION_TO_WIRE_ANGLE.get(d, WireAngle.EAST)


def wire_angle_to_direction(angle: WireAngle) -> Direction:
    """WireAngle → Direction (семантическое соответствие)."""
    if angle == WireAngle.NORTH: return Direction.UP
    if angle == WireAngle.SOUTH: return Direction.DOWN
    if angle == WireAngle.EAST:  return Direction.RIGHT
    if angle == WireAngle.WEST:  return Direction.LEFT
    return Direction.RIGHT


def opposite_direction(d: Direction) -> Direction:
    """Противоположное направление (UP↔DOWN, LEFT↔RIGHT).

    Используется для перехода direction («в тело», KiCad-семантика)
    к outward («наружу», для отростка).
    """
    if d == Direction.UP:    return Direction.DOWN
    if d == Direction.DOWN:  return Direction.UP
    if d == Direction.LEFT:  return Direction.RIGHT
    if d == Direction.RIGHT: return Direction.LEFT
    return d


# =========================================================
# Занятость клеток карты
# =========================================================

class OccupantKind(StrEnum):
    """Тип объекта, занимающего клетку карты."""
    COMPONENT_BODY = "component_body"
    PIN = "pin"
    WIRE = "wire"


# =========================================================
# Стратегии раскладки
# =========================================================

class PlacementStrategy(StrEnum):
    """Стратегия раскладки компонентов на странице."""
    AUTO = "auto"
    ROWS = "rows"
    CONNECTIVITY = "connectivity"
    MATRIX = "matrix"


PLACER_ROWS_MAX = 2
PLACER_MATRIX_MIN = 8
PLACER_DENSITY_LOW = 0.10
PLACER_ASPECT_WIDE = 5.0
PLACER_HUB_FRACTION = 0.5

MATRIX_MARGIN = 3
MATRIX_BASE_STREET = 2
MATRIX_MAX_STREET = 8
MATRIX_STREET_SCALE = 0.5
MATRIX_TARGET_ASPECT = 1.4


# =========================================================
# Служебные строки KiCad
# =========================================================

class Symbol(StrEnum):
    """Специальные lib_id, которые нужно распознавать в YAML."""
    HIERARCHICAL_SHEET = "Core:Hierarchical_Sheet"


# =========================================================
# Типы сетей
# =========================================================

class NetType(StrEnum):
    """Категории сетей из YAML (attributes.type)."""
    POWER = "POWER"
    GND = "GND"
    DIGITAL_SIGNAL = "DIGITAL_SIGNAL"
    ANALOG_SIGNAL = "ANALOG_SIGNAL"
    PWM_POWER = "PWM_POWER"
    SIGNAL = "signal"


DEFAULT_NET_TYPE = NetType.SIGNAL


# =========================================================
# Сетка и умолчания
# =========================================================

DEFAULT_GRID_MM = 1.27
GRID_EPSILON_MM = 1e-6


# =========================================================
# Алгоритм поиска пути
# =========================================================

class PathSearch(StrEnum):
    """Алгоритм поиска пути между клетками.

    DIJKSTRA — с весами (heapq); при весах = 1 даёт тот же результат,
               что BFS, но медленнее.
    BFS      — поиск в ширину, все рёбра весят 1; самый дешёвый.
    ASTAR    — BFS + манхэттенская эвристика; быстрее на больших картах.
    """
    DIJKSTRA = "dijkstra"
    BFS = "bfs"
    ASTAR = "astar"

class Axis(IntEnum):
    """Индексы осей в кортежах (x, y)."""
    X = 0
    Y = 1

# =========================================================
# Библиотеки KiCad: таблицы проекта (sym-lib-table / fp-lib-table)
# =========================================================

class LibTableKind(StrEnum):
    """Тип таблицы библиотек проекта KiCad."""
    SYMBOL = "sym"          # sym-lib-table — библиотеки символов
    FOOTPRINT = "fp"        # fp-lib-table  — библиотеки посадочных мест


# Имя файла таблицы в корне проекта KiCad.
LIB_TABLE_FILES: dict[LibTableKind, str] = {
    LibTableKind.SYMBOL:    "sym-lib-table",
    LibTableKind.FOOTPRINT: "fp-lib-table",
}


# Корневой токен S-expression внутри файла таблицы.
LIB_TABLE_ROOT_TOKENS: dict[LibTableKind, str] = {
    LibTableKind.SYMBOL:    "sym_lib_table",
    LibTableKind.FOOTPRINT: "fp_lib_table",
}


# Тип плагина библиотеки в таблице (KiCad native).
LIB_TABLE_TYPE_KICAD = "KiCad"

# Версия формата таблицы (KiCad 6+).
LIB_TABLE_VERSION = 7

# Переменная KiCad, которая разворачивается в каталог .kicad_pro.
KIPRJMOD_VAR = "${KIPRJMOD}"


# Секции root_page в main.yaml, откуда берутся библиотеки проекта.
class ProjectLibSection(StrEnum):
    """Ключи root_page, описывающие библиотеки для регистрации."""
    SYMBOL_LIBS = "symbol_libs"
    FOOTPRINT_LIBS = "footprint_libs"


# Соответствие секции root_page → типу таблицы.
SECTION_TO_LIB_KIND: dict[ProjectLibSection, LibTableKind] = {
    ProjectLibSection.SYMBOL_LIBS:    LibTableKind.SYMBOL,
    ProjectLibSection.FOOTPRINT_LIBS: LibTableKind.FOOTPRINT,
}

PORT_DIRECTION_TO_SHAPE: dict[str, str] = {
    "INPUT":         "input",
    "OUTPUT":        "output",
    "BIDIR":         "bidirectional",
    "BIDIRECTIONAL": "bidirectional",
    "TRISTATE":      "tri_state",
    "TRI_STATE":     "tri_state",
    "PASSIVE":       "passive",
}

def port_shape(direction: str | None) -> str:
    """port_direction из YAML → shape для KiCad hierarchical_label / sheet-pin.

    Единственное место в проекте, где этот маппинг определён.
    Дефолт — INPUT, как и в YAML-конвенции.
    """
    return PORT_DIRECTION_TO_SHAPE.get(
        (direction or "INPUT").upper(), "input"
    )

def port_side(direction: str | None) -> str:
    """OUTPUT ставится на правый край листа, всё остальное — на левый."""
    return "right" if (direction or "INPUT").upper() == "OUTPUT" else "left"


class NetNameSourcePriority(IntEnum):
    """Приоритет источника имени сети — KiCad SCH_CONNECTION::PRIORITY.

    Значения упорядочены по важности: чем больше, тем весомее
    голос при выборе имени группы, объединённой union-find.
    Порядок повторяет KiCad 7/8/10:

        PIN         — обычный пин компонента;
        SHEET_PIN   — вывод на символе листа (X_*);
        HIER_LABEL  — иерархическая метка внутри листа;
        LOCAL_LABEL — локальная метка на проводе.

    Глобальных меток и power-символов (GLOBAL в KiCad) в этом
    проекте нет — соответствующего яруса не заводим.
    """
    PIN         = 0
    SHEET_PIN   = 1
    HIER_LABEL  = 2
    LOCAL_LABEL = 3