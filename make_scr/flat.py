# make_scr/flat.py
"""Плоская карта сетей поддерева — эквивалент нетлиста kicad-cli.

Модуль не знает про Project. Всё, что нужно для схлопывания,
лежит внутри самого поддерева:

    * сущности сетей — в sheet.components каждой страницы;
    * стыки X_* ↔ порт ребёнка — в X_*-компонентах этого поддерева;
    * refdes разрешаются через refdes_maps, которые построил
      вызывающий код (обычно Sheet._compute_refdes_maps).

Публичный вход — Sheet.flatten():

    from flat import Flattener
    flat_map = Flattener(
        root=sheet,
        refdes_maps=sheet._compute_refdes_maps(),
    ).build()

Схлопывание идёт от указанного листа (root) вниз до самых
глубоких потомков. Внешний контекст (анцесторы root'а) не
учитывается: это «плоский нетлист поддерева», а не «все связи
листа в проекте».

Ключевые правила:
    * X_* — маркер границы, не даёт PinRef. Его пины регистрируют
      родительские сети как якоря union-find, чтобы _join_ports
      мог склеить их с одноимёнными сетями-портами ребёнка.
    * Порт (is_hierarchical_port) — тоже маркер, не пин. Он
      существует в карте как сущность, но без своих пинов.
    * Идентификатор пина — pin.identifier: number для обычных,
      name (имя порта) для sheet-пинов. Совпадает с (pin "…")
      в нетлисте KiCad.
    * Проектные refdes получаются через refdes_maps[X_des].
      Для корня поддерева (path=()) — YAML-designator без
      изменений.

Выбор имени сети — повторяет логику KiCad (SCH_CONNECTION):
для каждой группы электрически соединённых пинов выбирается
ОДИН драйвер по правилу:
    1. максимальный приоритет драйвера;
    2. при равенстве — меньшая длина пути (ближе к корню);
    3. при равенстве — лексикографически меньшее имя.

Имя неглобальной сети в нетлисте получает префикс пути от
корня (/X_FOO/VCC_12V). Сравнение имён при сверке нормализуется
в net_map._norm_net_name (отрезание пути до последнего '/').

Сверка с kicad-cli идёт в два шага:
    1. по РАЗБИЕНИЮ множества пинов (FlatNetMap.partition()) —
       инвариантно к именам, ловит обрывы и лишние связи;
    2. по именам групп (FlatNetMap.names_by_partition()) — ловит
       случаи, когда топология совпала, а имена перепутаны.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from logging_setup import get_logger

if TYPE_CHECKING:
    from sheet import Sheet

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Публичные структуры
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PinRef:
    """Один вывод в плоской карте — проектный refdes + идентификатор.

    Для обычного пина identifier — номер ('42'); для sheet-пина —
    имя порта ('VCC_12V'). Оба совпадают с (pin "…") в нетлисте
    KiCad, который выдаёт kicad-cli при экспорте схемы.
    """
    component: str
    pin: str

    def __repr__(self) -> str:
        return f"{self.component}.{self.pin}"


class FlatNetMap:
    """Плоское множество сетей.

    nets — словарь {имя_сети: {PinRef, ...}}. Имя вычисляется по
    приоритету KiCad-флаттенера (см. Flattener._choose_name).
    Для сверки доступны две проекции:
        partition()          — только топология (без имён);
        names_by_partition() — топология + имя каждой группы.
    """

    def __init__(self) -> None:
        self.nets: Dict[str, Set[PinRef]] = {}

    def add(self, name: str, pin: PinRef) -> None:
        self.nets.setdefault(name, set()).add(pin)

    def partition(self) -> Set[frozenset]:
        """Классы эквивалентности пинов, без имён и без пустых групп."""
        return {frozenset(pins) for pins in self.nets.values() if pins}

    def names_by_partition(self) -> Dict[frozenset, str]:
        """{frozenset(pins): name} — имя каждой группы.

        Если в nets случайно оказались две записи с одним и тем же
        множеством пинов (этого не должно быть — group определяется
        корнем union-find однозначно), сохраняется первое имя; в
        лог пишется предупреждение.
        """
        out: Dict[frozenset, str] = {}
        for name, pins in self.nets.items():
            if not pins:
                continue
            key = frozenset(pins)
            if key in out and out[key] != name:
                log.warning(
                    "FlatNetMap: одному множеству пинов соответствуют "
                    "два имени: %r и %r — берётся первое",
                    out[key], name,
                )
                continue
            out[key] = name
        return out

    def as_dict(self) -> Dict[str, Set[PinRef]]:
        return {name: set(pins) for name, pins in self.nets.items()}

    def __repr__(self) -> str:
        lines = [f"FlatNetMap ({len(self.nets)} nets)"]
        for name in sorted(self.nets):
            pins = sorted(self.nets[name], key=repr)
            lines.append(f"  {name}: {pins}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Приоритеты драйверов имени сети — повторяют порядок KiCad.
#
# SCH_CONNECTION::PRIORITY (KiCad 7/8/10):
#     PIN_NAME    — обычный пин компонента;
#     SHEET_PIN   — вывод на символе листа (X_*);
#     HIER_LABEL  — иерархическая метка внутри листа (PortComponent);
#     LOCAL_LABEL — локальная метка на проводе.
#
# Глобальные метки и power-символы (GLOBAL) в этом проекте
# не используются — соответствующего яруса нет.
#
# Константы модульные: они нужны и в объявлении _Entity (дефолт
# driver_priority), и в _collect, и в _choose_name. Объявлены ДО
# _Entity, потому что дефолт вычисляется в момент создания
# dataclass'а.
# ─────────────────────────────────────────────────────────────────────

PRIORITY_PIN         = 0   # PIN_NAME
PRIORITY_SHEET_PIN   = 1   # SHEET_PIN
PRIORITY_HIER_LABEL  = 2   # HIER_LABEL
PRIORITY_LOCAL_LABEL = 3   # LOCAL_LABEL


# ─────────────────────────────────────────────────────────────────────
# Внутренняя сущность: одна сеть в одном инстансе
# ─────────────────────────────────────────────────────────────────────

@dataclass
class _Entity:
    """Сеть одного листа поддерева.

    Ключ сущности — (path, name):
        path: кортеж X_*-designator'ов от root'а Flattener'а; () — сам root.
        name: имя сети в YAML этого листа.
    pins: {(local_designator, pin_identifier), ...} — без X_*, без портов.
    driver_priority: ярус драйвера, дающего имя этой сети (см.
        PRIORITY_*). При union-find группы побеждает максимальный.
    """
    path: Tuple[str, ...]
    name: str
    pins: Set[Tuple[str, str]]
    is_port: bool = False
    driver_priority: int = PRIORITY_PIN


# ─────────────────────────────────────────────────────────────────────
# Схлопыватель
# ─────────────────────────────────────────────────────────────────────

class Flattener:
    """Схлопывает поддерево от root до низа в FlatNetMap.

    Экземпляр живёт один вызов build(). Состояние — две таблицы:
        _entities:  {(path, net_name): _Entity}
        _parent:    {(path, net_name): (path, net_name)} — union-find

    Создаётся в Sheet.flatten(); наружу не торчит.
    """

    def __init__(
        self,
        root: "Sheet",
        refdes_maps: Dict[str, Dict[str, str]],
    ) -> None:
        """
        Args:
            root:        лист, с которого начинается схлопывание.
                         Обычно корень проекта, но может быть любая
                         страница — тогда flat-карта описывает её
                         поддерево.
            refdes_maps: {X_des: {local_des: project_ref}} — карта
                         переименования локальных refdes в проектные
                         для мульти-инстансных X_*. Для одноинстансных
                         листов маппинг тождественен, но всё равно
                         передаётся, чтобы не разветвлять логику.
        """
        self.root = root
        self.refdes_maps = refdes_maps

        self._entities: Dict[Tuple[Tuple[str, ...], str], _Entity] = {}
        self._parent: Dict[Tuple[Tuple[str, ...], str],
                           Tuple[Tuple[str, ...], str]] = {}

    # ---------- публичная точка входа ----------

    def build(self) -> FlatNetMap:
        """Собрать плоскую карту.

        Порядок:
            1. Обойти поддерево и создать _Entity на каждую сеть
               каждого листа (включая сети-порты и «пустые» сети
               родителя, к которым подключены X_*-пины).
            2. Пройти по X_*-компонентам и склеить union-find'ом
               их сеть на родителе с одноимённой сетью-портом
               ребёнка.
            3. Сгруппировать сущности по корням union-find, выбрать
               имя группы, сконвертировать локальные refdes в
               проектные через refdes_maps.
        """
        self._entities.clear()
        self._parent.clear()

        self._collect(self.root, ())
        self._join_ports(self.root, ())
        return self._resolve()

    # ---------- шаг 1: сбор сущностей ----------

    def _collect(self, sheet: "Sheet", path: Tuple[str, ...]) -> None:
        """Создать _Entity на каждую сеть листа (включая порты).

        Обычные компоненты дают пины: для каждого пина берётся
        pin.net_ref (имя сети) и pin.identifier (номер или имя).
        Пины X_*-компонентов не дают PinRef'ов: их сеть на этом
        листе регистрируется как сущность с пустым набором пинов —
        нужна как якорь, чтобы _join_ports мог найти parent_key.
        Пины портов — тоже маркеры: сеть-порт существует, пинов
        не добавляет.

        driver_priority каждой сети выставляется по её источнику:
        порт листа → HIER_LABEL, X_*-пин → LOCAL_LABEL (writer
        ставит рядом с sheet-пином обычный label с тем же именем
        — см. writer._add_sheet_pins), метка на проводе
        (sheet.labels) → LOCAL_LABEL, остальное → PIN. Если у сети
        несколько источников — берётся максимальный приоритет:
        KiCad в этом случае выбирает имя по верхнему ярусу.
        """
        per_net: Dict[str, Set[Tuple[str, str]]] = {}
        port_nets: Set[str] = set()
        priorities: Dict[str, int] = {}

        def bump(net_name: str, prio: int) -> None:
            if priorities.get(net_name, -1) < prio:
                priorities[net_name] = prio

        # Метки на проводах (роутер пишет их в sheet.labels).
        for lbl in getattr(sheet, "labels", []) or []:
            net_name = getattr(lbl, "net_name", None)
            if net_name:
                bump(net_name, PRIORITY_LOCAL_LABEL)

        for des, comp in sheet.components.items():
            # ── порт листа: иерархический ──
            if getattr(comp, "is_port", False):
                net_name = getattr(comp, "net_name", None)
                if net_name:
                    port_nets.add(net_name)
                    bump(net_name, PRIORITY_HIER_LABEL)
                continue

            # ── X_* — маркер границы ──
            #
            # Родительская сеть имени M1_IN1 (net_ref у X_*-пина)
            # на самом деле представлена в .kicad_sch ДВУМЯ
            # элементами: sheet-pin'ом с именем порта (IN1) и
            # обычным локальным label с именем сети (M1_IN1).
            # Writer ставит label безусловно (writer._add_sheet_pins).
            # В терминах KiCad это LOCAL_LABEL, и по приоритету
            # он выше HIER_LABEL из подлиста. Регистрируем якорь
            # с этим приоритетом, чтобы _choose_name выбрал
            # читаемое имя M1_IN1, а не "/X_ACTUATOR_CHANNEL_M1/IN1".
            if getattr(comp, "is_sheet_ref", False):
                for pin in comp.pins:
                    net_ref = _pin_net(pin)
                    if net_ref:
                        per_net.setdefault(net_ref, set())
                        bump(net_ref, PRIORITY_LOCAL_LABEL)
                continue

            # ── обычный компонент ──
            for pin in comp.pins:
                net_ref = _pin_net(pin)
                if net_ref is None:
                    continue
                ident = _pin_ident(pin)
                if not ident:
                    continue
                per_net.setdefault(net_ref, set()).add((des, ident))
                # PIN — низший ярус; не перебиваем более высокий,
                # если он уже был выставлен портом/X_*/меткой.
                if net_ref not in priorities:
                    priorities[net_ref] = PRIORITY_PIN

        for net_name in set(per_net) | port_nets:
            key = (path, net_name)
            self._parent[key] = key
            self._entities[key] = _Entity(
                path=path,
                name=net_name,
                pins=per_net.get(net_name, set()),
                is_port=net_name in port_nets,
                driver_priority=priorities.get(net_name, PRIORITY_PIN),
            )

        # Рекурсия в детей — по прямым ссылкам comp.child_sheet.
        for des, comp in sheet.components.items():
            if not getattr(comp, "is_sheet_ref", False):
                continue
            child = getattr(comp, "child_sheet", None)
            if child is None:
                log.warning(
                    "flatten: %s не имеет child_sheet — потомок не обойдён",
                    des,
                )
                continue
            self._collect(child, path + (des,))

    # ---------- шаг 2: union-find ----------

    def _find(self, key):
        """Корень группы union-find с path-compression."""
        p = self._parent[key]
        while p != key:
            self._parent[key] = self._parent[p]
            key, p = p, self._parent[p]
        return key

    def _union(self, a, b) -> None:
        """Склеить две группы. Детерминированное слияние: меньший ключ побеждает."""
        ra, rb = self._find(a), self._find(b)
        if ra == rb:
            return
        if ra > rb:
            ra, rb = rb, ra
        self._parent[rb] = ra

    def _join_ports(self, sheet: "Sheet", path: Tuple[str, ...]) -> None:
        """Склеить X_*.port на родителе с одноимённой сетью ребёнка.

        У sheet-пина номера нет — identifier это имя порта. Правило:
            parent_key = (path, parent_net)         ← сеть родителя
            child_key  = (path + (X_des,), port_name) ← сеть-порт ребёнка
        Если child_key или parent_key не найдены — это структурная
        проблема YAML: пишем warning и пропускаем. Молча пропустить
        нельзя: неверная привязка даст искажённую карту.
        """
        for des, comp in sheet.components.items():
            if not getattr(comp, "is_sheet_ref", False):
                continue

            child = getattr(comp, "child_sheet", None)
            if child is None:
                continue

            child_path = path + (des,)

            for pin in comp.pins:
                parent_net = _pin_net(pin)
                port_name = _pin_port_name(pin)
                if not parent_net or not port_name:
                    continue

                parent_key = (path, parent_net)
                child_key = (child_path, port_name)

                if child_key not in self._parent:
                    log.warning(
                        "flatten: %s порт %r не найден в дочернем листе",
                        des, port_name,
                    )
                    continue
                if parent_key not in self._parent:
                    log.warning(
                        "flatten: %s порт %r не привязан к сети родителя "
                        "(path=%s)",
                        des, port_name, path,
                    )
                    continue

                self._union(parent_key, child_key)

            self._join_ports(child, child_path)

    # ---------- шаг 3: сборка ----------

    def _resolve(self) -> FlatNetMap:
        """Разложить сущности по корням union-find и построить карту."""
        groups: Dict[Tuple, List[_Entity]] = {}
        for key, ent in self._entities.items():
            root = self._find(key)
            groups.setdefault(root, []).append(ent)

        result = FlatNetMap()
        for entities in groups.values():
            name = self._choose_name(entities)
            for ent in entities:
                for pinref in self._resolve_refs(ent.path, ent.pins):
                    result.add(name, pinref)
        return result

    @staticmethod
    def _choose_name(entities: List[_Entity]) -> str:
        """Имя группы по приоритету KiCad-флаттенера.

        Алгоритм:
            1. Отбираем сущности с максимальным driver_priority.
            2. Среди них — с минимальной длиной пути (ближайшие к
               корню поддерева).
            3. Среди оставшихся — лексикографически меньшее имя.

        Возвращаем имя без префикса пути для корневых сущностей
        (path=()); с префиксом "/<path>/<name>" — для вложенных.

        Порядок шагов повторяет SCH_CONNECTION::ResolveDrivers:
        сначала ярус, затем близость к корню, затем алфавит.
        """
        if not entities:
            return ""

        # 1. Максимальный приоритет.
        top = max(e.driver_priority for e in entities)
        candidates = [e for e in entities if e.driver_priority == top]

        # 2. Минимальная длина пути.
        min_len = min(len(e.path) for e in candidates)
        candidates = [e for e in candidates if len(e.path) == min_len]

        # 3. Алфавитный tie-break: лексикографически меньшее имя.
        best = min(candidates, key=lambda e: e.name)

        if not best.path:
            return best.name
        return "/" + "/".join(best.path) + "/" + best.name

    def _resolve_refs(
        self,
        path: Tuple[str, ...],
        pins: Set[Tuple[str, str]],
    ) -> Set[PinRef]:
        """Преобразовать локальные (des, pin) в проектные PinRef.

        Для path=() — это root Flattener'а, refdes берутся как есть.
        Иначе — из refdes_maps по последнему X_* в пути: этот X_*
        породил текущий лист, и его карта знает, как локальные
        refdes листа превращаются в проектные.
        """
        if not path:
            rm: Dict[str, str] = {}
        else:
            rm = self.refdes_maps.get(path[-1], {})
        return {PinRef(rm.get(ref, ref), pin) for ref, pin in pins}


# ─────────────────────────────────────────────────────────────────────
# Помощники: унифицированный доступ к «сети пина» и «идентификатору»
# ─────────────────────────────────────────────────────────────────────

def _pin_net(pin) -> Optional[str]:
    """Имя сети, к которой привязан пин, или None.

    У обычных пинов после загрузки стоит net_ref (см.
    Netlist.assign_pin_to_net). У sheet-пинов может быть только
    net_name — читаем оба поля, чтобы не зависеть от того, как
    конкретный Sheet-класс их проставляет.
    """
    return getattr(pin, "net_ref", None) or getattr(pin, "net_name", None)


def _pin_ident(pin) -> Optional[str]:
    """Идентификатор пина: number для обычных, name для sheet-пинов.

    Соответствует Pin.identifier: number or name.
    """
    return getattr(pin, "identifier", None)


def _pin_port_name(pin) -> Optional[str]:
    """Имя порта sheet-пина = pin.name.

    Для sheet-пина identifier тоже возвращает name (потому что
    number=None), но семантически здесь нужен именно порт —
    читаем name напрямую, чтобы не зависеть от того, как resolver
    расставит приоритеты в будущем.
    """
    return getattr(pin, "name", None)