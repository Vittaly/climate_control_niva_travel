# Архитектура проекта

Генератор KiCad-схем из YAML-описания: читает `main.yaml` с иерархическими
листами, строит компоненты и нетлист, раскладывает их по сетке, трассирует
соединения и сохраняет `.kicad_sch` + отладочные логи.

## Слои

    YAML ──► Project ──► Sheet ──► Placer ──► Router ──► Net.wires ──► Writer
              │           │         │          │           │
              │           │         │          │           └─ зарегистрированные провода
              │           │         │          └─ Dijkstra + T-врезки + stub
              │           │         └─ 3 стратегии раскладки + карта клеток
              │           └─ компоненты + FQN + двусторонние ссылки
              └─ чтение YAML, оркестрация, сохранение

## Файлы

### Данные

| Файл | Размер | Назначение |
|---|---|---|
| `cell.py` | ~0.3 КБ | Точка на сетке: (col, row), сложение, вычитание |
| `pin.py` | ~1.5 КБ | Пин компонента: номер, имя, клетка, x_mm/y_mm, направление |
| `net.py` | ~1.5 КБ | Сеть: пины (FQN), провода, `contains(cell)`, `is_fully_routed` |
| `netlist.py` | ~2 КБ | Реестр сетей, `assign_pin_to_net`, `register_wire` |
| `component.py` | ~4 КБ | Компонент: пины, габарит, `from_yaml`, FQN |
| `sheet.py` | ~3 КБ | Страница: свои компоненты, `fqn`, `add_component` |
| `wire.py` | ~3.5 КБ | Провод: путь, отростки, `WireSegment`, `segment_angle` |
| `stub.py` | ~4 КБ | Отросток пина: `plan_stub`, диагональ, `log_stub` |
| `occupant.py` | ~2 КБ | Что занимает клетку: `ComponentBody`, `PinCell`, `WireCell` |
| `router_map.py` | ~0.3 КБ | Тип карты: `Dict[(col,row), Occupant]` |

### Логика

| Файл | Размер | Назначение |
|---|---|---|
| `constants.py` | ~4 КБ | `Direction`, `Orientation`, `WireAngle`, `WireOrientation`, `OccupantKind`, `PlacementStrategy`, `NetType`, `Symbol`, `PLACER_*`, `MATRIX_*` |
| `kicad_source.py` | ~3 КБ | Мост к `kicad_sch_api`: `lib_id → пины / bbox` с кэшем |
| `connectivity.py` | ~1.5 КБ | Граф связности компонентов страницы |
| `placer.py` | ~14 КБ | 3 стратегии раскладки + `build_router_map` |
| `router.py` | ~14 КБ | Dijkstra, отростки, T-врезки, метки |
| `writer.py` | ~2 КБ | Вывод `.kicad_sch` + текстовый `routes.txt` |
| `report.py` | ~5 КБ | Сводки и ASCII-карта для отладки (опционально) |

### Инфраструктура

| Файл | Размер | Назначение |
|---|---|---|
| `logging_setup.py` | ~3 КБ | Логгер `eda`, консоль + `out/debug.log` + `out/router.log` |
| `project.py` | ~10 КБ | Точка входа: YAML → компоненты → размещение → роутинг → save |
| `main.py` | ~1 КБ | Запуск: поднять логи, собрать проект, сохранить |
| `README.md` | ~2.5 КБ | Документация |
| `main.yaml` | ~30 КБ | Корневое описание проекта |
| `sheets/*.yaml` | — | Иерархические листы |

## Зависимости между модулями

                            constants
                               │
              ┌────────────────┼─────────────────┐
              ▼                ▼                 ▼
            cell             pin              net
              │                │                │
              ▼                ▼                ▼
          component ◄──── sheet          netlist
              │                                │
              ▼                                │
          occupant                             │
              │                                │
              ▼                                ▼
         router_map ──────► router ──────► net.wires
                              ▲                │
                              │                ▼
                            stub            writer
                              ▲
                              │
                            placer

    project ──► читает YAML, строит Sheet/Component, зовёт Placer, Router, Writer

## Правила зависимостей

- `constants` — не зависит ни от кого.
- `cell`, `pin`, `net`, `netlist` — низкоуровневые структуры.
- `component` ↔ `sheet` — двусторонняя связь (Component.sheet, Sheet.components).
- `wire` ↔ `stub` — Wire ссылается на Stub, Stub на Wire не ссылается.
- `occupant` — знает про `component`, `pin`, `wire`.
- `router_map` — тип для `Dict[(col,row), Occupant]`.
- `placer` — знает про `component`, `connectivity`, `occupant`, `router_map`.
- `router` — знает про `placer` (только `grid_step` и `positions`), `stub`, `wire`, `occupant`.
- `writer` — знает про `component`, `sheet`, `netlist`.
- `project` — связывает всё.

## Модель компонента

    Component
    ├── designator  "U1"                    ← локальный, уникален на странице
    ├── name        "STM32F103"             ← человекочитаемое value
    ├── lib_id      "MCU_ST_STM32F1:..."    ← KiCad lib_id
    ├── width, height                       ← в клетках сетки
    ├── pins: List[Pin]
    ├── fields: Dict[str, str]              ← Voltage, Tolerance, ...
    └── sheet: Sheet                        ← двусторонняя связь

`Component.fqn` → `"X_ACT/U1"` или `"U1"` для корня.

## Модель пина

    Pin
    ├── owner       "U1"                    ← designator компонента
    ├── number      "5"
    ├── name        "PA0"
    ├── position    Cell(col,row)           ← внутри компонента
    ├── x_mm, y_mm  float                   ← реальные координаты KiCad
    ├── direction   Direction
    ├── net_ref     Optional[str]           ← имя сети
    └── component: Component                ← двусторонняя связь

`Pin.local_key` → `"U1:5"`, `Pin.fqn` → `"X_ACT/U1:5"`.

## Модель сети

    Net
    ├── name        "VCC_3V3"
    ├── net_type    NetType.POWER
    ├── flags       List[str]
    ├── pins: List[str]         ← FQN-ключи "X_ACT/U1:5"
    └── wires: List[Wire]       ← провода этой сети

`Net.contains(cell)` — проходит ли через клетку провод сети.
`Net.is_fully_routed` — все ли пины соединены.

## Модель провода

    Wire
    ├── net_name   "VCC_3V3"
    ├── start      Pin
    ├── end        Optional[Pin]        ← None для T-врезки
    ├── path       List[Cell]           ← клетки основного маршрута
    ├── start_stub Stub                 ← отросток от start-пина
    ├── end_stub   Stub                 ← отросток от end-пина
    └── t_junction bool

`Wire.segments()` — разбивка пути на прямолинейные сегменты.
`Wire.length` — суммарная длина в клетках.

## Модель отростка

    Stub
    ├── pin         Pin
    ├── cells       List[Cell]       ← клетки от пина к tip
    ├── tip         Cell             ← первая свободная клетка
    ├── direction   WireAngle
    ├── pin_mm      (x, y)           ← реальные координаты пина
    ├── tip_mm      (x, y)
    ├── on_grid     bool             ← пин уже на сетке
    └── diagonal    bool             ← отросток диагональный

Отросток — единственный элемент, где допускается диагональ.
Маршрут (Dijkstra) всегда ортогональный.

## Карта клеток

    RouterMap = Dict[(col, row), Occupant]

Клетка либо занята объектом, либо её нет в карте (свободна). Третьего нет.

    Occupant
    ├── ComponentBody(component)     allows(net) = False
    ├── PinCell(component, pin)      allows(net) = (pin.net_ref == net)
    └── WireCell(wire)               allows(net) = (wire.net_name == net)

## Алгоритм трассировки

    1. Первое соединение сети (два пина):
       a. Строим отростки от каждого пина — до первой свободной клетки
          за bbox, в направлении пина.
       b. Концы отростков соединяем Dijkstra по ортогональной сетке.
       c. Правила входа: тело — нельзя; пин — только своей сети;
          провод — только своей сети или перпендикулярно.

    2. Каждый следующий пин — T-врезка:
       a. Строим отросток.
       b. Ищем ближайшие точки на уже проложенных сегментах сети.
       c. Dijkstra от tip-отростка до точки врезки.
       d. При неудаче — пробуем следующие точки (до 5).

    3. При полном провале — метка на пине.

## Стратегии раскладки

`Placer.auto_place()` — выбирает автоматически по признакам:

    n = число компонентов
    density = плотность графа связности
    aspect = разброс площадей max/min
    has_hub = есть ли компонент со степенью >= n/2

    Правило:
        n <= 2            → ROWS          (упаковка рядами)
        n >= 8            → MATRIX        (RCM + улицы)
        density <= 0.10   → ROWS
        aspect >= 5       → CONNECTIVITY  (BFS + force-directed)
        has_hub           → CONNECTIVITY
        иначе             → MATRIX

## Иерархия страниц

    Project
    ├── root_sheet           (sheet_path="")
    └── sheets: Dict[str, Sheet]
        ├── X_ACT            (sheet_path="X_ACT")
        ├── X_PWR            (sheet_path="X_PWR")
        └── X_ACT/MOTOR_A    (sheet_path="X_ACT/MOTOR_A", вложенный)

Каждая Sheet хранит свои компоненты. FQN пина = `"X_ACT/U2:5"`.
`Netlist` хранит FQN-ключи, поэтому коллизии designator'ов между
страницами не возникают.

## Логирование

Все модули пишут через `log = get_logger(__name__)`. Иерархия `eda.<module>`.

    out/debug.log    все логи, DEBUG+
    out/router.log   только eda.router, DEBUG+
    консоль          INFO+

Механика прокладки маршрутов (отростки, Dijkstra, блокеры, метки)
видна в `out/router.log`.

## Что не реализовано

- Многослойная трассировка (сейчас один слой).
- Поворот компонентов (все ставятся без поворота).
- Межлистовые связи (порты листов как пины псевдокомпонента).
- Визуализация иерархии в `.kicad_sch` (вложенные sheet-символы).
- DRC (проверка правил проектирования).
- Оптимизация длины маршрутов после прокладки.

## Точки расширения

- `Occupant` — новые типы (ViaCell, KeepOutZone, PowerPlane).
- `WireAngle` / `WireOrientation` — диагональные сегменты маршрута.
- `Placer.auto_place` — новая стратегия через `PlacementStrategy`.
- `Router._can_enter` — правила проходимости.
- `constants.py` — все пороги и параметры в одном месте.