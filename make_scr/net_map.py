# make_scr/net_map.py
"""Плоская карта сетей — эквивалент нетлиста, который kicad-cli
выдаёт при экспорте корневой схемы с разворачиванием иерархии.

Используется внешней валидацией (run_e2e), не входит в Project.
Строит плоское множество сетей из уже загруженного графа и сверяет
его с нетлистом KiCad как РАЗБИЕНИЕ множества пинов — без имён
сетей, потому что KiCad переименовывает сети по приоритету метки
(VCC_12V → /X_FOO/VCC_12V), но классы эквивалентности пинов
сохраняет.

Ключевые правила:
    * X_* — маркер границы, а не пин. Не даёт PinRef; участвует
      только в union-find: склеивает родительскую сеть с одноимённой
      сетью-портом ребёнка. Сеть родителя, к которой подключён X_*,
      регистрируется в карте как сущность — даже если на этом листе
      у неё нет обычных пинов (только X_*-порты). Иначе union-find
      не найдёт parent_key и не склеит родителя с ребёнком.
    * Порт (is_hierarchical_port: true) — тоже маркер, а не пин.
      Он существует в карте как сущность, но без своих пинов.
    * Идентификатор пина — pin.identifier: number для обычных,
      name (имя порта) для sheet-пинов. Совпадает с (pin "…")
      нетлиста KiCad.
    * Проектные refdes получаются через refdes_maps[path[-1]].
      Для корня (пустой путь) — YAML-designator без изменений.

Использование:

    from project import Project
    from net_map import build_from_project, diff_against_kicad
    from net_map import parse_kicad_netlist_to_pinrefs

    proj = Project(MAIN_YAML).load()

    # Ожидаемое — по графу YAML. Project не мутируется.
    expected = build_from_project(proj)

    # Фактическое — из плоского нетлиста kicad-cli.
    actual = parse_kicad_netlist_to_pinrefs("out/root_flat.net")

    for line in diff_against_kicad(expected, actual):
        print(line)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from logging_setup import get_logger

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Публичные структуры
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PinRef:
    """Один вывод в плоской карте — проектный refdes + идентификатор.

    Для обычного пина identifier — номер ('42'), для sheet-пина —
    имя порта ('VCC_12V'). Оба совпадают с (pin "…") в нетлисте KiCad,
    который выдаёт kicad-cli при экспорте корня.
    """
    component: str
    pin: str

    def __repr__(self) -> str:
        return f"{self.component}.{self.pin}"


class FlatNetMap:
    """Плоское множество сетей.

    nets — словарь {имя_сети: {PinRef, ...}}. Имя вычисляется по
    приоритету KiCad-флаттенера, но в сверке не участвует: сравнение
    идёт через partition() — разбиение пинов на классы, инвариантное
    к именам и порядку.
    """

    def __init__(self) -> None:
        self.nets: Dict[str, Set[PinRef]] = {}

    def add(self, name: str, pin: PinRef) -> None:
        self.nets.setdefault(name, set()).add(pin)

    def partition(self) -> Set[frozenset]:
        """Классы эквивалентности пинов, без имён и без пустых групп."""
        return {frozenset(pins) for pins in self.nets.values() if pins}

    def as_dict(self) -> Dict[str, Set[PinRef]]:
        return {name: set(pins) for name, pins in self.nets.items()}

    def __repr__(self) -> str:
        lines = [f"FlatNetMap ({len(self.nets)} nets)"]
        for name in sorted(self.nets):
            pins = sorted(self.nets[name], key=repr)
            lines.append(f"  {name}: {pins}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Внутренняя сущность: одна сеть в одном инстансе
# ─────────────────────────────────────────────────────────────────────

@dataclass
class _Entity:
    path: Tuple[str, ...]           # путь X_*-designators; () для корня
    name: str                        # имя сети в этом инстансе
    pins: Set[Tuple[str, str]]      # (yaml_ref, pin_identifier), БЕЗ X_*
    is_port: bool = False


# ─────────────────────────────────────────────────────────────────────
# Построитель
# ─────────────────────────────────────────────────────────────────────

class NetMapBuilder:
    """Собирает FlatNetMap из уже загруженного Project.

    Принимает компоненты графа по отдельности, а не Project целиком:
    это позволяет вызывать построитель и в контексте валидации (где
    refdes_maps считаются отдельно), и в тестах без сборки Project.

    Требует непустой refdes_maps для мульти-инстансных X_*; иначе
    разные инстансы получат одинаковые refdes и разбиение «склеится».
    """

    def __init__(self, root_sheet, sheets, refdes_maps):
        """
        Args:
            root_sheet: Sheet с sheet_path == "" — корневая страница.
            sheets:     {sheet_path: Sheet} из Project.
            refdes_maps: {X_*: {yaml_ref: project_ref}}.
        """
        self.root_sheet = root_sheet
        self.sheets = sheets
        self.refdes_maps = refdes_maps

        self._entities: Dict[Tuple[Tuple[str, ...], str], _Entity] = {}
        self._parent: Dict[Tuple[Tuple[str, ...], str],
                           Tuple[Tuple[str, ...], str]] = {}

    def build(self) -> FlatNetMap:
        self._entities.clear()
        self._parent.clear()

        self._collect(self.root_sheet, ())
        self._join_ports(self.root_sheet, ())
        return self._resolve()

    # ─── шаг 1: сущности ───

    def _collect(self, sheet, path: Tuple[str, ...]) -> None:
        """Создать _Entity на каждую сеть листа (включая порты).

        Пины обычных компонентов собираются по pin.net_ref —
        это имя сети, к которой Project уже привязал пин.

        X_*-пины не дают PinRefs, но их pin.net_ref — это имя сети
        родителя, в которой участвует X_*. Такая сеть регистрируется
        как сущность с пустым набором пинов: нужна как якорь для
        union-find, чтобы _join_ports мог склеить её с сетью-портом
        ребёнка. Без этого сети, у которых на данном листе есть
        ТОЛЬКО X_*-порты (например, SOLAR_IN_RAW на корне), не
        появятся в карте и связь потеряется.
        """
        per_net: Dict[str, Set[Tuple[str, str]]] = {}
        port_nets: Set[str] = set()

        for des, comp in sheet.components.items():
            # Порт листа — метка, а не пин. Сеть-порт должна
            # существовать в карте, даже если у неё нет пинов
            # (pass-through порт без внутренних подключений).
            if getattr(comp, "is_port", False):
                net_name = getattr(comp, "net_name", None)
                if net_name:
                    port_nets.add(net_name)
                continue

            # X_* — маркер границы. Его пины не дают PinRefs, но
            # регистрируют сети родителя как пустые сущности — для
            # последующего union-find в _join_ports.
            if getattr(comp, "is_sheet_ref", False):
                for pin in comp.pins:
                    net_ref = _pin_net(pin)
                    if net_ref:
                        per_net.setdefault(net_ref, set())
                continue

            for pin in comp.pins:
                net_ref = _pin_net(pin)
                if net_ref is None:
                    continue
                ident = _pin_ident(pin)
                if not ident:
                    continue
                per_net.setdefault(net_ref, set()).add((des, ident))

        for net_name in set(per_net) | port_nets:
            key = (path, net_name)
            self._parent[key] = key
            self._entities[key] = _Entity(
                path=path,
                name=net_name,
                pins=per_net.get(net_name, set()),
                is_port=net_name in port_nets,
            )

        # Рекурсия в детей.
        for des, comp in sheet.components.items():
            if not getattr(comp, "is_sheet_ref", False):
                continue
            child_file = Path(comp.sheet_file).with_suffix(
                ".kicad_sch").name
            child_sheet = self.sheets.get(child_file)
            if child_sheet is None:
                log.warning(
                    "net_map: %s ссылается на %s — лист не загружен",
                    des, child_file,
                )
                continue
            self._collect(child_sheet, path + (des,))

    # ─── шаг 2: union-find ───

    def _find(self, key):
        p = self._parent[key]
        while p != key:
            self._parent[key] = self._parent[p]
            key, p = p, self._parent[p]
        return key

    def _union(self, a, b) -> None:
        ra, rb = self._find(a), self._find(b)
        if ra == rb:
            return
        # Детерминированное слияние: меньший корень побеждает.
        if ra > rb:
            ra, rb = rb, ra
        self._parent[rb] = ra

    def _join_ports(self, sheet, path: Tuple[str, ...]) -> None:
        """Склеить X_*.port на родителе с одноимённой сетью ребёнка.

        У sheet-пина номера нет — идентификатор это имя порта.
        Родительский pin.net_ref — имя корневой сети; имя порта
        (pin.identifier или pin.name) — имя сети-порта внутри
        дочернего YAML.
        """
        for des, comp in sheet.components.items():
            if not getattr(comp, "is_sheet_ref", False):
                continue

            child_file = Path(comp.sheet_file).with_suffix(
                ".kicad_sch").name
            child_sheet = self.sheets.get(child_file)
            if child_sheet is None:
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
                        "net_map: %s порт %r не найден в %s",
                        des, port_name, child_file,
                    )
                    continue
                if parent_key not in self._parent:
                    log.warning(
                        "net_map: %s порт %r не привязан к сети "
                        "родителя (path=%s)",
                        des, port_name, path,
                    )
                    continue

                self._union(parent_key, child_key)

            self._join_ports(child_sheet, child_path)

    # ─── шаг 3: сборка ───

    def _resolve(self) -> FlatNetMap:
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

        1. Есть корневая сеть (path=()) — её имя.
        2. Иначе — "/<path>/<name>" самого глубокого инстанса.
        """
        for ent in entities:
            if not ent.path:
                return ent.name
        deepest = max(entities, key=lambda e: (len(e.path), e.path, e.name))
        return "/" + "/".join(deepest.path) + "/" + deepest.name

    def _resolve_refs(
        self, path: Tuple[str, ...], pins: Set[Tuple[str, str]],
    ) -> Set[PinRef]:
        """YAML-designators → проектные refs через refdes_maps."""
        if not path:
            rm: Dict[str, str] = {}
        else:
            rm = self.refdes_maps.get(path[-1], {})
        return {PinRef(rm.get(ref, ref), pin) for ref, pin in pins}


# ─────────────────────────────────────────────────────────────────────
# Фабрика: собрать карту из Project, не мутируя его
# ─────────────────────────────────────────────────────────────────────

def build_from_project(project) -> FlatNetMap:
    """Построить плоскую карту, не изменяя состояние Project.

    Project отдаёт только свои структуры (root_sheet, sheets).
    Карта refdes считается локально — Project._refdes_maps не
    трогается, чтобы валидация не оставляла следов.
    """
    maps = project._compute_refdes()
    return NetMapBuilder(
        root_sheet=project.root_sheet,
        sheets=project.sheets,
        refdes_maps=maps,
    ).build()


# ─────────────────────────────────────────────────────────────────────
# Разбор плоского нетлиста KiCad
# ─────────────────────────────────────────────────────────────────────

def parse_kicad_netlist_to_pinrefs(netfile: str) -> Dict[str, Set[PinRef]]:
    """Читает плоский нетлист KiCad → {net_name: {PinRef, ...}}.

    Псевдо-сети с именем 'unconnected-*' отбрасываются: они не
    описываются в YAML, и включать их в сверку нельзя.
    """
    text = open(netfile, encoding="utf-8").read()
    out: Dict[str, Set[PinRef]] = {}

    for m in re.finditer(
        r'\(net\s+\(code "\d+"\)\s+\(name "([^"]+)"\)(.*?)\n\t\t\)',
        text, re.S,
    ):
        name = m.group(1).lstrip("/")
        if name.startswith("unconnected-"):
            continue
        pins: Set[PinRef] = set()
        for nm in re.finditer(
            r'\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)',
            m.group(2),
        ):
            pins.add(PinRef(nm.group(1), nm.group(2)))
        if pins:
            out[name] = pins
    return out


# ─────────────────────────────────────────────────────────────────────
# Сверка
# ─────────────────────────────────────────────────────────────────────

def diff_against_kicad(
    expected: FlatNetMap,
    actual: Dict[str, Set[PinRef]],
) -> List[str]:
    """Сравнивает разбиения. Пустой список — эквивалентны.

    Симметричная разность: любое расхождение — либо связь,
    которой нет в схеме, либо связь, которой нет в YAML.
    """
    exp = expected.partition()
    act = {frozenset(pins) for pins in actual.values() if pins}

    diffs: List[str] = []
    for part in sorted(exp - act, key=_sort_key):
        diffs.append("  В схеме нет сети из YAML: " + _fmt(part))
    for part in sorted(act - exp, key=_sort_key):
        diffs.append("  В YAML нет сети из схемы: " + _fmt(part))
    return diffs


def _part_reprs(part):
    """Отсортированный список repr() пинов группы.

    Возвращаем именно строки, чтобы sorted(...) не пытался
    сравнивать PinRef (у него нет __lt__).
    """
    return sorted(repr(p) for p in part)


def _sort_key(part):
    return tuple(_part_reprs(part))


def _fmt(part):
    return ", ".join(_part_reprs(part))


# ─────────────────────────────────────────────────────────────────────
# Помощники
# ─────────────────────────────────────────────────────────────────────

def _pin_net(pin) -> Optional[str]:
    """Имя сети, к которой привязан пин, или None."""
    return getattr(pin, "net_ref", None) or getattr(pin, "net_name", None)


def _pin_ident(pin) -> Optional[str]:
    """Идентификатор пина: number для обычных, name для sheet-пинов."""
    return getattr(pin, "identifier", None)


def _pin_port_name(pin) -> Optional[str]:
    """Имя порта sheet-пина = pin.name.

    Для sheet-пина identifier тоже возвращает name (потому что
    number=None), но семантически здесь нужен именно порт — читаем
    name напрямую, чтобы не зависеть от того, как resolver
    расставит приоритеты в будущем.
    """
    return getattr(pin, "name", None)