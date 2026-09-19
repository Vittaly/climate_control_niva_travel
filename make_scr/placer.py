# placer.py
"""Размещение компонентов на странице.

Стратегия выбирается автоматически по числу компонентов, плотности
графа связности, разбросу габаритов и наличию хабов. Снаружи —
единственный метод auto_place(); наружу не выставляется ни enum, ни
конфиги.

Три алгоритма (внутренние):
    - _place_rows()          — упаковка рядами;
    - _place_connectivity()  — BFS от хаба + раздвигание + force-directed;
    - _place_matrix()        — матричная раскладка (RCM + улицы).

Плейсер работает ТОЛЬКО В КЛЕТКАХ:
    - запрашивает у Component размер (bbox_size: cols, rows);
    - ищет место на общей карте (bbox_origin = (col, row));
    - передаёт в Component bbox_origin + rotation + mirror;
    - Component сам считает anchor_page_mm и сохраняет его;
    - bbox_origin НЕ хранится в Component — он нужен только
      для вычисления anchor_page_mm.

Ширина улиц:
    Ширина улицы = local + ceil(transit / divisor) + 2, где:
        local   — пины ТОЛЬКО компонентов, стоящих вплотную к улице
                  (для вертикальной улицы j — компоненты в колонках
                  j и j+1, смотрящие в улицу);
        transit — провода между компонентами слева и справа от улицы
                  (для вертикальной) или сверху и снизу (для
                  горизонтальной);
        divisor — (число параллельных улиц в том же направлении) + 2,
                  где +2 — обход по краю схемы (сверху и снизу для
                  вертикального транзита, слева и справа для
                  горизонтального).

Плейсер НЕ знает про:
    - систему символа/страницы;
    - pin.offset_mm;
    - округление размера (это делает Component).

Всё это — в Component.

Граф связности строится в connectivity.py.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sheet import Sheet

import math
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Dict, Iterator, List, Optional, Tuple

from cell import Cell
from component import Component
from constants import Axis
from logging_setup import get_logger, ctx

log = get_logger(__name__)


# =========================================================
# Внутренние типы
# =========================================================

class _Strategy(StrEnum):
    """Внутренний ярлык выбранной стратегии (для логов и тестов)."""
    ROWS = "rows"
    CONNECTIVITY = "connectivity"
    MATRIX = "matrix"


@dataclass
class _MatrixConfig:
    """Внутренние параметры матричной раскладки."""
    margin: int = 3
    base_street: int = 8       # минимум ширины улицы
    max_street: int = 64       # максимум, чтобы не раздувать поле
    target_aspect: float = 1.4


# Пороги эвристики.
_N_ROWS_MAX = 2            # 1..2 → ROWS
_N_MATRIX_MIN = 8          # >=8  → MATRIX
_DENSITY_LOW = 0.10        # ниже — ROWS (связность бесполезна)
_ASPECT_WIDE = 5.0         # разброс габаритов max/min
_HUB_FRACTION = 0.5        # степень хаба >= n * HUB_FRACTION


class Placer:
    """Размещает компоненты страницы, сам выбирая стратегию.

    Работает ТОЛЬКО В КЛЕТКАХ. Не знает про мм, anchor, pin_mm.
    """

    def __init__(self, sheet: "Sheet"):
        self.sheet = sheet
        self.netlist = sheet.netlist           # транслируется через страницу
        self.grid_step = sheet.grid_mm         # ← единственный источник
        self.page_name = sheet.page            # "root" или имя файла
        self.components: Dict[str, Component] = {}
        self.positions: Dict[str, Cell] = {}
        self.last_strategy: Optional[_Strategy] = None

    # =========================================================
    # Регистрация
    # =========================================================

    def register_component(self, comp: Component) -> None:
        """Добавляет компонент в пул размещения (ещё без координат)."""
        self.components[comp.designator] = comp
        log.debug("%s size=%dx%d cells",
                  ctx(page=self.page_name, comp=comp.designator),
                  comp.bbox_cols, comp.bbox_rows)

    def place(self, designator: str, col: int, row: int) -> None:
        """Ставит компонент в конкретную клетку страницы."""
        if designator not in self.components:
            raise ValueError(f"Компонент не зарегистрирован: {designator}")

        comp = self.components[designator]
        bbox_origin = Cell(col, row)
        self.positions[designator] = bbox_origin

        comp.set_position(
            bbox_origin=bbox_origin,
            rotation=comp.rotation,
            mirror=comp.mirror,
        )

        anchor_mm = comp.anchor_page_mm
        log.debug(
            "%s place bbox_origin=(%d,%d) anchor_mm=(%.2f,%.2f) "
            "rotation=%d mirror=%s size=%dx%d cells",
            ctx(page=self.page_name, comp=designator),
            col, row,
            anchor_mm[Axis.X], anchor_mm[Axis.Y],
            comp.rotation, comp.mirror,
            comp.bbox_cols, comp.bbox_rows,
        )

        for pin in comp.pins:
            pm = comp.abs_pin_mm(pin)
            pc = comp.abs_pin_cell(pin)
            log.trace(
                "%s offset_mm=(%.2f,%.2f) abs_mm=(%.2f,%.2f) abs=(%d,%d)",
                ctx(page=self.page_name, comp=designator, pin=pin.local_key),
                pin.offset_mm[Axis.X], pin.offset_mm[Axis.Y],
                pm[Axis.X], pm[Axis.Y],
                pc.col, pc.row,
            )

    # =========================================================
    # Единственная публичная точка входа
    # =========================================================

    def auto_place(self) -> str:
        """Размещает компоненты, сам выбирая алгоритм.

        После connectivity — проверяет наложения. Если они есть
        (connectivity не учитывает размеры компонентов при
        расстановке соседей по кольцам), откатывается на matrix.
        Matrix раскладывает по сетке и наложений не даёт.
        """
        from connectivity import build_component_graph

        adj = build_component_graph(self.sheet)
        strategy = self._choose_strategy(adj)

        log.info("%s placement components=%d strategy=%s",
                 ctx(page=self.page_name),
                 len(self.components), strategy)

        if strategy == _Strategy.ROWS:
            self._place_rows()
        elif strategy == _Strategy.CONNECTIVITY:
            self._place_connectivity(adj)
            overlaps = self.all_overlaps()
            if overlaps:
                log.warning(
                    "%s connectivity produced %d overlaps, "
                    "fallback to matrix",
                    ctx(page=self.page_name), len(overlaps),
                )
                self._reset_positions()
                self._place_matrix(adj, _MatrixConfig())
                strategy = _Strategy.MATRIX
        elif strategy == _Strategy.MATRIX:
            self._place_matrix(adj, _MatrixConfig())
        else:
            raise ValueError(f"Неизвестная стратегия: {strategy}")

        self.last_strategy = strategy
        self._log_positions("placement_done")
        return strategy.value

    # =========================================================
    # Автовыбор стратегии
    # =========================================================

    def _choose_strategy(self, adj: Dict[str, Dict[str, int]]) -> _Strategy:
        n = len(self.components)
        if n == 0:
            return _Strategy.ROWS
        if n <= _N_ROWS_MAX:
            return _Strategy.ROWS
        if n >= _N_MATRIX_MIN:
            return _Strategy.MATRIX

        density = self._graph_density(adj, n)
        aspect = self._aspect_ratio()
        has_hub = self._has_hub(adj, n)

        log.debug("%s features n=%d density=%.2f aspect=%.2f has_hub=%s",
                  ctx(page=self.page_name),
                  n, density, aspect, has_hub)

        if density <= _DENSITY_LOW:
            return _Strategy.ROWS
        if aspect >= _ASPECT_WIDE:
            return _Strategy.CONNECTIVITY
        if has_hub:
            return _Strategy.CONNECTIVITY
        return _Strategy.MATRIX

    @staticmethod
    def _graph_density(adj: Dict[str, Dict[str, int]], n: int) -> float:
        if n < 2:
            return 0.0
        edges = sum(len(v) for v in adj.values()) // 2
        max_edges = n * (n - 1) / 2
        return edges / max_edges if max_edges else 0.0

    def _aspect_ratio(self) -> float:
        areas = [c.bbox_cols * c.bbox_rows for c in self.components.values()]
        if not areas:
            return 1.0
        lo = min(areas)
        hi = max(areas)
        return hi / lo if lo else float("inf")

    @staticmethod
    def _has_hub(adj: Dict[str, Dict[str, int]], n: int) -> bool:
        if n < 3:
            return False
        threshold = n * _HUB_FRACTION
        for neighbors in adj.values():
            degree = sum(neighbors.values())
            if degree >= threshold:
                return True
        return False

    # =========================================================
    # Стратегия 1: ROWS
    # =========================================================

    def _place_rows(self, margin: int = 2, max_cols: int = 6) -> None:
        log.debug("%s strategy=rows margin=%d max_cols=%d",
                  ctx(page=self.page_name), margin, max_cols)
        col, row = margin, margin
        row_height = 0
        placed = 0
        for designator, comp in self.components.items():
            if placed and placed % max_cols == 0:
                col = margin
                row += row_height + margin
                row_height = 0
            self.place(designator, col, row)
            col += comp.bbox_cols + margin
            row_height = max(row_height, comp.bbox_rows)
            placed += 1
        log.debug("%s strategy=rows done placed=%d",
                  ctx(page=self.page_name), placed)
        self._log_positions("rows_placed")

    # =========================================================
    # Стратегия 2: CONNECTIVITY
    # =========================================================

    def _place_connectivity(
        self,
        adj: Dict[str, Dict[str, int]],
        seed_margin: int = 3,
        refine_iters: int = 30,
    ) -> None:
        """BFS-раскладка от хаба + раздвигание + force-directed refine.

        Три шага:
            1. _seed_by_bfs      — быстро расставляет по кольцам;
            2. _resolve_overlaps — раздвигает наложившиеся, если
                                   кольца не учли размеры компонентов;
            3. _refine_by_force  — добивает по cost (HPWL).
        """
        from connectivity import graph_summary
        log.debug("%s strategy=connectivity top=%s",
                  ctx(page=self.page_name), graph_summary(adj))

        self._seed_by_bfs(adj, margin=seed_margin)
        self._resolve_overlaps(adj)
        self._refine_by_force(adj, iterations=refine_iters)
        self._log_positions("connectivity_placed")

    def _seed_by_bfs(self, adj: Dict[str, Dict[str, int]],
                     margin: int = 3) -> None:
        if not self.components:
            return

        hub = max(
            self.components.keys(),
            key=lambda d: sum(adj.get(d, {}).values()),
        )
        log.debug("%s connectivity hub=%s", ctx(page=self.page_name), hub)

        avg_w = sum(c.bbox_cols for c in self.components.values()) / len(self.components)
        avg_h = sum(c.bbox_rows for c in self.components.values()) / len(self.components)
        center_col = int(margin + avg_w * 2)
        center_row = int(margin + avg_h * 2)

        visited: set[str] = set()
        q: deque[tuple[str, int]] = deque([(hub, 0)])
        visited.add(hub)

        ring_offsets = self._ring_offsets()
        current_radius = 0
        ring_index = 0

        while q:
            designator, radius = q.popleft()
            if radius != current_radius:
                current_radius = radius
                ring_index = 0

            if designator == hub:
                col, row = center_col, center_row
            else:
                offsets = ring_offsets[min(radius, len(ring_offsets) - 1)]
                dc, dr = offsets[ring_index % len(offsets)]
                ring_index += 1
                col = center_col + dc
                row = center_row + dr

            self.place(designator, col, row)

            for neighbor in adj.get(designator, {}):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                q.append((neighbor, radius + 1))

        orphans = [d for d in self.components if d not in visited]
        if orphans:
            log.debug("%s connectivity orphans=%s",
                      ctx(page=self.page_name), orphans)
            self._pack_orphans(orphans, margin=margin)

    @staticmethod
    def _ring_offsets() -> List[List[Tuple[int, int]]]:
        rings: List[List[Tuple[int, int]]] = [[]]
        for r in range(1, 8):
            ring: List[Tuple[int, int]] = []
            for dc in range(-r, r + 1):
                ring.append((dc, -r))
                ring.append((dc, r))
            for dr in range(-r + 1, r):
                ring.append((-r, dr))
                ring.append((r, dr))
            rings.append(ring)
        return rings

    @staticmethod
    def _ring_cells(r: int) -> List[Tuple[int, int]]:
        """Клетки кольца радиуса r (r=0 — одна клетка (0,0))."""
        if r == 0:
            return [(0, 0)]
        out: List[Tuple[int, int]] = []
        for dc in range(-r, r + 1):
            out.append((dc, -r))
            out.append((dc, r))
        for dr in range(-r + 1, r):
            out.append((-r, dr))
            out.append((r, dr))
        return out

    def _resolve_overlaps(self, adj: Dict[str, Dict[str, int]]) -> None:
        """Раздвигает компоненты, у которых есть наложения после BFS.

        Идёт в BFS-порядке от хаба: хаб остаётся на месте, каждый
        следующий либо остаётся, если его текущая позиция свободна
        от уже расставленных, либо переезжает в ближайшую свободную
        клетку по спирали вокруг своей текущей позиции.

        Нужно, потому что _seed_by_bfs ставит соседей по одноклеточным
        кольцам — компонент размером 3x7 и больше сдвигается всего
        на 1 клетку от хаба и налезает на соседей.

        В отличие от _refine_by_force, работает с большими радиусами,
        поэтому может выбраться из плотного наложения.
        """
        if not self.components:
            return

        hub = max(
            self.components.keys(),
            key=lambda d: sum(adj.get(d, {}).values()),
        )
        order = self._bfs_order(adj, hub)

        placed: Dict[str, Cell] = {}
        moved = 0

        for d in order:
            comp = self.components[d]
            current = self.positions[d]

            if self._pos_free_from(current, comp, placed):
                placed[d] = current
                continue

            new_pos = self._find_free_spot(comp, current, placed)
            placed[d] = new_pos
            self.positions[d] = new_pos
            comp.set_position(
                bbox_origin=new_pos,
                rotation=comp.rotation,
                mirror=comp.mirror,
            )
            moved += 1

        log.debug("%s connectivity resolve_overlaps moved=%d",
                  ctx(page=self.page_name), moved)

    def _bfs_order(self, adj: Dict[str, Dict[str, int]],
                   start: str) -> List[str]:
        """BFS-порядок обхода от start, затем оставшиеся."""
        visited: set[str] = {start}
        q: deque[str] = deque([start])
        order: List[str] = [start]

        while q:
            v = q.popleft()
            for u in adj.get(v, {}):
                if u not in visited:
                    visited.add(u)
                    order.append(u)
                    q.append(u)

        for d in self.components:
            if d not in visited:
                order.append(d)
        return order

    def _pos_free_from(self, pos: Cell, comp: Component,
                       placed: Dict[str, Cell]) -> bool:
        """Свободна ли позиция от уже расставленных компонентов."""
        x1, y1 = pos.col, pos.row
        x2, y2 = x1 + comp.bbox_cols, y1 + comp.bbox_rows

        for d, p in placed.items():
            oc = self.components[d]
            ox1, oy1 = p.col, p.row
            ox2, oy2 = ox1 + oc.bbox_cols, oy1 + oc.bbox_rows
            if not (x2 <= ox1 or ox2 <= x1 or y2 <= oy1 or oy2 <= y1):
                return False
        return True

    def _find_free_spot(self, comp: Component, near: Cell,
                        placed: Dict[str, Cell],
                        max_radius: int = 40) -> Cell:
        """Ближайшая свободная позиция по спирали вокруг near.

        Спираль: сначала пробуем r=0 (текущая), потом кольца всё
        большего радиуса. Шаг — 1 клетка, но max_radius большой,
        чтобы компонент мог выехать из плотной зоны.
        """
        bc, br = near.col, near.row
        for r in range(max_radius + 1):
            for dc, dr in self._ring_cells(r):
                c, rw = bc + dc, br + dr
                if c < 0 or rw < 0:
                    continue
                pos = Cell(c, rw)
                if self._pos_free_from(pos, comp, placed):
                    return pos
        # ничего не нашли — уводим далеко вправо-вниз
        return Cell(bc + 100, br + 100)

    def _pack_orphans(self, orphans: List[str], margin: int = 2,
                      max_cols: int = 6) -> None:
        if not self.positions:
            start_row = margin
        else:
            start_row = max(p.row for p in self.positions.values()) + 5

        col = margin
        row = start_row
        row_height = 0
        placed = 0
        for designator in orphans:
            comp = self.components[designator]
            if placed and placed % max_cols == 0:
                col = margin
                row += row_height + margin
                row_height = 0
            self.place(designator, col, row)
            col += comp.bbox_cols + margin
            row_height = max(row_height, comp.bbox_rows)
            placed += 1

    def _refine_by_force(self, adj: Dict[str, Dict[str, int]],
                         iterations: int = 30) -> None:
        """Force-directed улучшение cost (HPWL).

        Двигает каждый компонент на один шаг в сторону уменьшения
        суммарной длины связей. Шаги разной длины (1, 3, 8) дают
        шанс «перепрыгнуть» соседа, если одноклеточный шаг заблокирован.
        """
        if not adj:
            log.debug("%s connectivity no_graph refine_skipped",
                      ctx(page=self.page_name))
            return

        cost = self._target_cost(adj)
        log.debug("%s connectivity cost_start=%.1f",
                  ctx(page=self.page_name), cost)

        # Шаги: близкие (тонкая подстройка) и дальние (перескок).
        steps = (
            (1, 0), (-1, 0), (0, 1), (0, -1),
            (3, 0), (-3, 0), (0, 3), (0, -3),
            (8, 0), (-8, 0), (0, 8), (0, -8),
        )

        improved_total = 0
        for it in range(iterations):
            improved_this_round = 0
            for designator in list(self.components.keys()):
                current = self.positions.get(designator)
                if current is None:
                    continue

                best_delta = 0.0
                best_pos: Optional[Cell] = None
                for dc, dr in steps:
                    new_pos = Cell(current.col + dc, current.row + dr)
                    if new_pos.col < 0 or new_pos.row < 0:
                        continue
                    if not self._position_valid(designator, new_pos):
                        continue
                    delta = self._cost_delta(designator, current, new_pos, adj)
                    if delta < best_delta:
                        best_delta = delta
                        best_pos = new_pos

                if best_pos is not None:
                    self.positions[designator] = best_pos
                    comp = self.components[designator]
                    comp.set_position(
                        bbox_origin=best_pos,
                        rotation=comp.rotation,
                        mirror=comp.mirror,
                    )
                    cost += best_delta
                    improved_this_round += 1

            improved_total += improved_this_round
            log.debug("%s connectivity iter=%d improved=%d cost=%.1f",
                      ctx(page=self.page_name),
                      it, improved_this_round, cost)
            if improved_this_round == 0:
                break

        log.debug("%s connectivity refine_done improved=%d cost=%.1f",
                  ctx(page=self.page_name), improved_total, cost)

    def _target_cost(self, adj: Dict[str, Dict[str, int]]) -> float:
        total = 0.0
        seen: set[tuple[str, str]] = set()
        for a, neighbors in adj.items():
            pa = self.positions.get(a)
            if pa is None:
                continue
            for b, w in neighbors.items():
                key = (a, b) if a < b else (b, a)
                if key in seen:
                    continue
                seen.add(key)
                pb = self.positions.get(b)
                if pb is None:
                    continue
                total += w * (abs(pa.col - pb.col) + abs(pa.row - pb.row))
        return total

    def _cost_delta(self, designator: str, old_pos: Cell, new_pos: Cell,
                    adj: Dict[str, Dict[str, int]]) -> float:
        neighbors = adj.get(designator, {})
        delta = 0.0
        for b, w in neighbors.items():
            pb = self.positions.get(b)
            if pb is None:
                continue
            old_d = abs(old_pos.col - pb.col) + abs(old_pos.row - pb.row)
            new_d = abs(new_pos.col - pb.col) + abs(new_pos.row - pb.row)
            delta += w * (new_d - old_d)
        return delta

    def _position_valid(self, designator: str, pos: Cell) -> bool:
        comp = self.components[designator]
        x1, y1 = pos.col, pos.row
        x2, y2 = x1 + comp.bbox_cols, y1 + comp.bbox_rows

        for other, opos in self.positions.items():
            if other == designator:
                continue
            ocomp = self.components[other]
            ox1, oy1 = opos.col, opos.row
            ox2, oy2 = ox1 + ocomp.bbox_cols, oy1 + ocomp.bbox_rows
            if not (x2 <= ox1 or ox2 <= x1 or y2 <= oy1 or oy2 <= y1):
                return False
        return True

    def _reset_positions(self) -> None:
        """Сбрасывает координаты всех компонентов.

        Нужен для отката со стратегии, которая уже расставила
        компоненты, но результат оказался невалиден (пересечения).
        """
        self.positions.clear()
        for comp in self.components.values():
            comp.anchor_page_mm = None

    # =========================================================
    # Стратегия 3: MATRIX
    # =========================================================

    def _place_matrix(
        self,
        adj: Dict[str, Dict[str, int]],
        cfg: _MatrixConfig,
    ) -> None:
        from connectivity import graph_summary
        log.debug("%s strategy=matrix top=%s",
                  ctx(page=self.page_name), graph_summary(adj))

        positions = self._matrix_layout(adj, cfg)

        self.positions.clear()
        for designator, bbox_origin in positions.items():
            self.place(designator, bbox_origin.col, bbox_origin.row)

        for d in sorted(self.positions):
            pos = self.positions[d]
            log.trace(
                "%s matrix_pos origin=(%d,%d)",
                ctx(page=self.page_name, comp=d),
                pos.col, pos.row,
            )
        self._log_positions("matrix_placed")

    def _matrix_layout(
        self,
        adjacency: Dict[str, Dict[str, int]],
        cfg: _MatrixConfig,
    ) -> Dict[str, Cell]:
        """Конвейер матричной раскладки."""
        order, matrix = self._build_adjacency_matrix(adjacency)
        if not order:
            return {}

        perm = self._reverse_cuthill_mckee(order, matrix)
        rows = self._split_into_rows(perm, order, cfg)
        street_rows, street_cols = self._compute_streets(
            rows, matrix, order, cfg)
        return self._positions_from_grid(
            rows, order, street_rows, street_cols, cfg)

    def _build_adjacency_matrix(
        self,
        adjacency: Dict[str, Dict[str, int]],
    ) -> Tuple[List[str], List[List[int]]]:
        order = list(self.components.keys())
        index = {d: i for i, d in enumerate(order)}
        n = len(order)
        m = [[0] * n for _ in range(n)]

        for a, neighbors in adjacency.items():
            ia = index.get(a)
            if ia is None:
                continue
            for b, w in neighbors.items():
                ib = index.get(b)
                if ib is None:
                    continue
                m[ia][ib] = w

        return order, m

    def _reverse_cuthill_mckee(
        self,
        order: List[str],
        matrix: List[List[int]],
    ) -> List[int]:
        n = len(matrix)
        if n == 0:
            return []

        degrees = [sum(1 for x in row if x > 0) for row in matrix]
        visited = [False] * n
        result: List[int] = []

        while len(result) < n:
            start = min(
                (i for i in range(n) if not visited[i]),
                key=lambda i: degrees[i],
            )
            q: deque[int] = deque([start])
            visited[start] = True
            component_order: List[int] = []

            while q:
                v = q.popleft()
                component_order.append(v)
                neighbors = sorted(
                    (u for u in range(n) if matrix[v][u] > 0 and not visited[u]),
                    key=lambda u: degrees[u],
                )
                for u in neighbors:
                    if not visited[u]:
                        visited[u] = True
                        q.append(u)

            result.extend(component_order)

        result.reverse()
        log.debug("%s matrix rcm_first8=%s",
                  ctx(page=self.page_name),
                  [order[i] for i in result[:8]])
        return result

    def _split_into_rows(
        self,
        perm: List[int],
        order: List[str],
        cfg: _MatrixConfig,
    ) -> List[List[int]]:
        n = len(perm)
        if n == 0:
            return []

        widths = [self.components[order[i]].bbox_cols for i in perm]
        heights = [self.components[order[i]].bbox_rows for i in perm]

        avg_w = sum(widths) / n
        avg_h = sum(heights) / n
        est_rows = max(1, int(math.sqrt(n * avg_w / (avg_h * cfg.target_aspect))))
        est_cols = max(1, math.ceil(n / est_rows))

        rows: List[List[int]] = []
        current: List[int] = []
        for idx in perm:
            current.append(idx)
            if len(current) >= est_cols:
                rows.append(current)
                current = []
        if current:
            rows.append(current)

        log.debug("%s matrix rows=%d cols=%d",
                  ctx(page=self.page_name), len(rows), est_cols)
        return rows

    # =========================================================
    # Расчёт ширины улиц
    # =========================================================

    def _compute_streets(
        self,
        rows: List[List[int]],
        matrix: List[List[int]],
        order: List[str],
        cfg: _MatrixConfig,
    ) -> Tuple[List[int], List[int]]:
        """Ширина улиц между строками/колонками матрицы."""
        n_rows = len(rows)
        n_cols = max((len(r) for r in rows), default=0)

        if n_rows == 0 or n_cols == 0:
            return [], []

        pos: Dict[str, Tuple[int, int]] = {}
        for i, row in enumerate(rows):
            for j, idx in enumerate(row):
                pos[order[idx]] = (i, j)

        pin_dir = self._pin_counts_by_direction()
        wires_between = self._wires_between_components()

        # =========================================================
        # Локальные пины — ТОЛЬКО пограничные компоненты улицы
        # =========================================================

        col_local = [0] * max(0, n_cols - 1)
        for j in range(n_cols - 1):
            left = 0
            for i in range(n_rows):
                if j < len(rows[i]):
                    d = order[rows[i][j]]
                    left += pin_dir[d]["right"]
            right = 0
            for i in range(n_rows):
                if j + 1 < len(rows[i]):
                    d = order[rows[i][j + 1]]
                    right += pin_dir[d]["left"]
            col_local[j] = left + right

        row_local = [0] * max(0, n_rows - 1)
        for i in range(n_rows - 1):
            top = 0
            for j in range(n_cols):
                if i < len(rows) and j < len(rows[i]):
                    d = order[rows[i][j]]
                    top += pin_dir[d]["down"]
            bottom = 0
            for j in range(n_cols):
                if i + 1 < len(rows) and j < len(rows[i + 1]):
                    d = order[rows[i + 1][j]]
                    bottom += pin_dir[d]["up"]
            row_local[i] = top + bottom

        # =========================================================
        # Транзит: cross_wires_col[j] и cross_wires_row[i]
        # =========================================================

        cross_col = [0] * max(0, n_cols - 1)
        cross_row = [0] * max(0, n_rows - 1)

        for (a, b), wires in wires_between.items():
            if a not in pos or b not in pos:
                continue
            ra, ca = pos[a]
            rb, cb = pos[b]

            if ca != cb:
                lo, hi = sorted((ca, cb))
                for k in range(lo, hi):
                    if k < len(cross_col):
                        cross_col[k] += wires

            if ra != rb:
                lo, hi = sorted((ra, rb))
                for k in range(lo, hi):
                    if k < len(cross_row):
                        cross_row[k] += wires

        # =========================================================
        # Деление на число альтернативных маршрутов
        # =========================================================

        n_vert = max(1, n_cols - 1)
        n_horiz = max(1, n_rows - 1)
        divisor_col = n_vert + 2
        divisor_row = n_horiz + 2

        # =========================================================
        # Ширина улиц
        # =========================================================

        def street_width(local: int, cross: int, divisor: int) -> int:
            per_street = cross / divisor
            w = max(cfg.base_street, local + int(math.ceil(per_street)) + 2)
            return min(w, cfg.max_street)

        street_cols = [
            street_width(col_local[j], cross_col[j], divisor_col)
            for j in range(max(0, n_cols - 1))
        ]
        street_rows = [
            street_width(row_local[i], cross_row[i], divisor_row)
            for i in range(max(0, n_rows - 1))
        ]

        log.debug("%s matrix cross_col=%s", ctx(page=self.page_name), cross_col)
        log.debug("%s matrix cross_row=%s", ctx(page=self.page_name), cross_row)
        log.debug("%s matrix col_local=%s", ctx(page=self.page_name), col_local)
        log.debug("%s matrix row_local=%s", ctx(page=self.page_name), row_local)
        log.debug("%s matrix divisor_col=%d divisor_row=%d",
                  ctx(page=self.page_name), divisor_col, divisor_row)
        log.debug("%s matrix street_cols=%s", ctx(page=self.page_name), street_cols)
        log.debug("%s matrix street_rows=%s", ctx(page=self.page_name), street_rows)
        return street_rows, street_cols

    # =========================================================
    # Вспомогательные расчёты для улиц
    # =========================================================

    def _pin_counts_by_direction(self) -> Dict[str, Dict[str, int]]:
        """Число пинов каждого компонента по направлениям."""
        result: Dict[str, Dict[str, int]] = {}
        for designator, comp in self.components.items():
            counts = {"left": 0, "right": 0, "up": 0, "down": 0}
            for pin in comp.pins:
                dx = pin.offset_mm[Axis.X]
                dy = pin.offset_mm[Axis.Y]
                if dx > 0:
                    counts["right"] += 1
                elif dx < 0:
                    counts["left"] += 1
                if dy > 0:
                    counts["down"] += 1
                elif dy < 0:
                    counts["up"] += 1
            result[designator] = counts
        return result

    def _wires_between_components(self) -> Dict[Tuple[str, str], int]:
        """Оценка числа проводов между парами компонентов."""
        result: Dict[Tuple[str, str], int] = {}

        if self.netlist is None or self.sheet is None:
            return result

        for net_name, net in self.netlist.nets.items():
            comp_pins: Dict[str, list] = {}
            for fqn in net.pins:
                local = self.sheet.local_key(fqn)
                if local is None:
                    continue
                designator, num = local.split(":", 1)
                comp = self.components.get(designator)
                if comp is None:
                    continue
                pin = comp.pin_by_number(num)
                if pin is None:
                    continue
                comp_pins.setdefault(designator, []).append(pin)

            if len(comp_pins) < 2:
                continue

            items = sorted(comp_pins.items(), key=lambda kv: -len(kv[1]))
            hub, hub_pins = items[0]

            for designator, pins in items[1:]:
                key = (hub, designator) if hub < designator else (designator, hub)
                result[key] = result.get(key, 0) + len(pins)

        return result

    def _positions_from_grid(
        self,
        rows: List[List[int]],
        order: List[str],
        street_rows: List[int],
        street_cols: List[int],
        cfg: _MatrixConfig,
    ) -> Dict[str, Cell]:
        """Раскладывает компоненты по вычисленной сетке (в клетках)."""
        n_cols = max((len(r) for r in rows), default=0)
        col_widths = [0] * n_cols
        row_heights = [0] * len(rows)

        for i, row in enumerate(rows):
            for j, idx in enumerate(row):
                d = order[idx]
                comp = self.components[d]
                col_widths[j] = max(col_widths[j], comp.bbox_cols)
                row_heights[i] = max(row_heights[i], comp.bbox_rows)

        col_x: List[int] = []
        x = cfg.margin
        for j in range(n_cols):
            col_x.append(x)
            x += col_widths[j]
            if j < len(street_cols):
                x += street_cols[j]

        row_y: List[int] = []
        y = cfg.margin
        for i in range(len(rows)):
            row_y.append(y)
            y += row_heights[i]
            if i < len(street_rows):
                y += street_rows[i]

        result: Dict[str, Cell] = {}
        for i, row in enumerate(rows):
            for j, idx in enumerate(row):
                d = order[idx]
                comp = self.components[d]
                offset_c = (col_widths[j] - comp.bbox_cols) // 2
                offset_r = (row_heights[i] - comp.bbox_rows) // 2
                result[d] = Cell(col_x[j] + offset_c, row_y[i] + offset_r)

        log.debug("%s matrix done components=%d rows=%d cols=%d size=%dx%d",
                  ctx(page=self.page_name),
                  len(result), len(rows), n_cols, x, y)
        return result

    # =========================================================
    # Логирование установленных координат
    # =========================================================

    def _log_positions(self, title: str = "placed") -> None:
        if not self.positions:
            log.warning("%s %s no_positions",
                        ctx(page=self.page_name), title)
            return

        log.info("%s %s components=%d",
                 ctx(page=self.page_name), title, len(self.positions))

        for d in sorted(self.positions):
            pos = self.positions[d]
            comp = self.components[d]
            anchor_mm = comp.anchor_page_mm

            log.info(
                "%s %s bbox_origin=(%d,%d) anchor_mm=(%.2f,%.2f) "
                "rotation=%d mirror=%s size=%dx%d cells",
                ctx(page=self.page_name, comp=d),
                title,
                pos.col, pos.row,
                anchor_mm[Axis.X] if anchor_mm else 0.0,
                anchor_mm[Axis.Y] if anchor_mm else 0.0,
                comp.rotation, comp.mirror,
                comp.bbox_cols, comp.bbox_rows,
            )

            for pin in comp.pins:
                pm = comp.abs_pin_mm(pin)
                pc = comp.abs_pin_cell(pin)
                log.info(
                    "%s %s offset_mm=(%.2f,%.2f) abs_mm=(%.2f,%.2f) abs=(%d,%d)",
                    ctx(page=self.page_name, comp=d, pin=pin.local_key),
                    title,
                    pin.offset_mm[Axis.X], pin.offset_mm[Axis.Y],
                    pm[Axis.X], pm[Axis.Y],
                    pc.col, pc.row,
                )

    # =========================================================
    # Геометрия
    # =========================================================

    def component_bbox(self, designator: str) -> Tuple[int, int, int, int]:
        comp = self.components[designator]
        pos = self.positions[designator]
        return pos.col, pos.row, pos.col + comp.bbox_cols, pos.row + comp.bbox_rows

    def iter_occupied_cells(self, designator: str) -> Iterator[Tuple[int, int]]:
        comp = self.components[designator]
        pos = self.positions[designator]
        for c in range(pos.col, pos.col + comp.bbox_cols):
            for r in range(pos.row, pos.row + comp.bbox_rows):
                yield (c, r)

    def overlaps(self, comp_a: str, comp_b: str) -> bool:
        x1, y1, x2, y2 = self.component_bbox(comp_a)
        x3, y3, x4, y4 = self.component_bbox(comp_b)
        return not (x2 <= x3 or x4 <= x1 or y2 <= y3 or y4 <= y1)

    def all_overlaps(self) -> List[Tuple[str, str]]:
        overlaps: List[Tuple[str, str]] = []
        keys = list(self.positions.keys())
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                if self.overlaps(keys[i], keys[j]):
                    overlaps.append((keys[i], keys[j]))
        if overlaps:
            log.warning("%s overlaps=%d pairs=%s",
                        ctx(page=self.page_name),
                        len(overlaps), overlaps)
        return overlaps

    def build_router_map(self) -> "RouterMap":
        """Строит карту занятости для роутера."""
        from occupant import ComponentBody, PinCell
        from router_map import RouterMap

        m: RouterMap = {}
        pin_count = 0

        for designator, comp in self.components.items():
            pos = self.positions.get(designator)
            if pos is None:
                continue
            for c in range(pos.col, pos.col + comp.bbox_cols):
                for r in range(pos.row, pos.row + comp.bbox_rows):
                    m[(c, r)] = ComponentBody(component=comp)

        log.info("%s router_map components=%d pin_cells=%d total=%d",
                 ctx(page=self.page_name),
                 len(self.positions), pin_count, len(m))
        return m