# make_scr/net_map.py
"""Разбор плоского нетлиста KiCad и сверка с ожидаемой картой сетей.

Модуль решает две узкие задачи внешней валидации (run_e2e):

    1. Прочитать нетлист kicad-cli как плоское множество сетей.
    2. Сравнить его с ожидаемой плоской картой.

Сверка идёт в два шага:

    a. Топология — по РАЗБИЕНИЮ множества пинов на классы
       эквивалентности (FlatNetMap.partition()). Ловит обрывы,
       лишние связи, приклеенные к чужой сети пины.

    b. Имена — по нормализованному имени каждой группы
       (FlatNetMap.names_by_partition() vs net-имена). Ловит
       случай «топология совпала, а имена перепутаны».

Нормализация имён (_norm_net_name):
    KiCad префиксует неглобальные сети путём листа
    (VCC_12V → /X_FOO/VCC_12V). Сравнение отрезает ведущий '/'
    и префикс пути до последнего '/'. Глобальные метки и
    power-символы идут без пути — их имена сравниваются как есть.

Откуда берётся ожидаемая карта:
    Из графа YAML — Sheet.flatten() / Project.flatten() /
    Project.flatten_roots(). Само схлопывание и выбор имени группы
    живут в flat.Flattener (см. flat.py) и вызываются через
    Sheet.flatten(). Этот модуль в схлопывании не участвует.

Почему PinRef и FlatNetMap переехали в flat.py:
    Обход дерева Sheet'ов — операция над графом, её место в
    Sheet/Project. Здесь остаются только «внешний формат» (net)
    и операция сравнения двух уже готовых карт. Типы PinRef и
    FlatNetMap — общий дом с Flattener'ом, поэтому живут в flat.py.

Использование:

    from project import Project
    from net_map import parse_kicad_netlist_to_pinrefs, diff_against_kicad

    proj = Project(MAIN_YAML).load()

    # Ожидаемое — по графу YAML.
    expected = proj.flatten()

    # Фактическое — из плоского нетлиста kicad-cli.
    actual = parse_kicad_netlist_to_pinrefs("out/root_flat.net")

    for line in diff_against_kicad(expected, actual):
        print(line)

Для нескольких корней проекта:

    for sheet_path, expected in proj.flatten_roots().items():
        netfile = f"out/{Path(sheet_path).stem}_flat.net"
        actual = parse_kicad_netlist_to_pinrefs(netfile)
        for line in diff_against_kicad(expected, actual):
            print(line)
"""
from __future__ import annotations

import re
from typing import Dict, List, Set

from flat import FlatNetMap, PinRef
from logging_setup import get_logger

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Разбор плоского нетлиста KiCad
# ─────────────────────────────────────────────────────────────────────

def parse_kicad_netlist_to_pinrefs(netfile: str) -> Dict[str, Set[PinRef]]:
    """Читает плоский нетлист KiCad → {net_name: {PinRef, ...}}.

    Псевдо-сети с именем 'unconnected-*' отбрасываются: они не
    описываются в YAML, и включать их в сверку нельзя.

    Формат kicad-cli: каждый блок net содержит (name "...") и
    последовательность (node (ref "...") (pin "...") ...). Имена
    сетей приводятся к виду без ведущего '/' — kicad-cli добавляет
    его для сетей под-листов.
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
    """Сравнивает разбиения и имена. Пустой список — эквивалентны.

    Шаги:
        1. Топология: симметричная разность partition() vs partition
           фактического нетлиста. Любое расхождение — либо связь,
           которой нет в схеме, либо связь, которой нет в YAML.
        2. Имена: только для групп, у которых партиция совпала.
           Имя в YAML (из names_by_partition) сравнивается с именем
           в net после нормализации _norm_net_name. Ловит случай
           «топология та же, имена перепутаны» (VCC_12V ↔ GND).

    Имена нормализуются, потому что KiCad добавляет префикс пути
    (/X_FOO/VCC_12V) для неглобальных сетей.
    """
    exp = expected.partition()
    act = {frozenset(pins) for pins in actual.values() if pins}

    diffs: List[str] = []

    # ── 1. Топология ──
    for part in sorted(exp - act, key=_sort_key):
        diffs.append("  В схеме нет сети из YAML: " + _fmt(part))
    for part in sorted(act - exp, key=_sort_key):
        diffs.append("  В YAML нет сети из схемы: " + _fmt(part))

    # ── 2. Имена для совпавших групп ──
    exp_names = expected.names_by_partition()
    act_names: Dict[frozenset, str] = {
        frozenset(pins): name
        for name, pins in actual.items() if pins
    }

    for part in sorted(exp & act, key=_sort_key):
        yml_name = exp_names.get(part, "")
        net_name = act_names.get(part, "")
        if _norm_net_name(yml_name) != _norm_net_name(net_name):
            diffs.append(
                f"  Сеть {_fmt(part)}: имя в YAML={yml_name!r}, "
                f"в схеме={net_name!r}"
            )

    return diffs


# ─────────────────────────────────────────────────────────────────────
# Помощники сверки
# ─────────────────────────────────────────────────────────────────────

def _norm_net_name(name: str) -> str:
    """Нормализовать имя сети для сравнения.

    Отрезает ведущий '/' и префикс пути до последнего '/'.
    Примеры:
        'VCC_12V'           → 'VCC_12V'
        '/X_FOO/VCC_12V'    → 'VCC_12V'
        '/X_A/GND'          → 'GND'

    Слабость: две несвязанные сети с одинаковым хвостом на разных
    подлистах (/X_A/GND и /X_B/GND) при таком сравнении считаются
    «совпавшими по имени». Топология их всё равно различит —
    партиции не пересекутся, и до сравнения имён такие группы
    просто не дойдут. Ложных срабатываний в сторону «имя не
    совпало» нормализация не даёт.
    """
    return name.lstrip("/").rsplit("/", 1)[-1]


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