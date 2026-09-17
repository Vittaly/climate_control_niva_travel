# make_scr/connectivity.py
"""Граф связности компонентов страницы.

Строится из Netlist: для каждой сети с >= 2 пинами добавляются рёбра
между всеми парами компонентов этой сети. Вес ребра — сколько раз два
компонента встречаются в одной сети.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from logging_setup import get_logger
from netlist import Netlist
from sheet import Sheet

log = get_logger(__name__)

# designator -> {designator: weight}
Adjacency = Dict[str, Dict[str, int]]


def build_component_graph(netlist: Netlist, sheet: Sheet) -> Adjacency:
    """Строит граф связности компонентов одной страницы.

    Args:
        netlist: нетлист проекта (FQN-ключи пинов).
        sheet:   страница, для которой строим граф.

    Returns:
        Словарь смежности: adj[a][b] = вес (число общих сетей).
    """
    adj: Adjacency = defaultdict(lambda: defaultdict(int))

    for net_name, net in netlist.nets.items():
        # оставляем только пины этой страницы
        local_components: List[str] = []
        seen: set[str] = set()
        for fqn in net.pins:
            local = sheet.local_key(fqn)
            if local is None:
                continue
            designator, _ = local.split(":", 1)
            if designator in seen:
                continue
            seen.add(designator)
            local_components.append(designator)

        if len(local_components) < 2:
            continue

        # все пары внутри сети
        for i in range(len(local_components)):
            for j in range(i + 1, len(local_components)):
                a, b = local_components[i], local_components[j]
                adj[a][b] += 1
                adj[b][a] += 1

    result: Adjacency = {k: dict(v) for k, v in adj.items()}
    log.debug("[%s] граф связности: вершин %d, рёбер %d",
              sheet.sheet_path or "root", len(result),
              sum(len(v) for v in result.values()) // 2)
    return result


def graph_summary(adj: Adjacency) -> str:
    """Человекочитаемая сводка графа (для логов).

    Возвращает топ-5 компонентов по сумме весов рёбер.
    """
    if not adj:
        return "граф пуст"
    degrees = {k: sum(v.values()) for k, v in adj.items()}
    top = sorted(degrees.items(), key=lambda kv: -kv[1])[:5]
    return ", ".join(f"{k}({d})" for k, d in top)
