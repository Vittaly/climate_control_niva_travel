# router_impl/pathfind.py
"""BFS / A* / Dijkstra. Функции принимают router и работают с его
map/bounds/page.

Все три алгоритма хранят не только prev (родителя клетки), но
и entry (направление, по которому вошли в клетку). Это нужно
для проверки выхода из чужого WireCell: после перпендикулярного
входа выход параллельно чужому проводу запрещён.

Два условия остановки — независимые:

  * target — конкретная клетка-ориентир. Штатная цель,
    выбирается вызывающим кодом (`_route_t_junction`) заранее.
    Если нигде по пути не сработал goal — pathfind дойдёт
    до target и остановится.

  * goal — состояние клетки: «лежит на host-проводе И вход
    в неё перпендикулярен host-сегменту». Это «везение»:
    роутер уже пришёл в сеть, хотя до target ещё не дошёл.
    Проверяется на КАЖДОЙ вытащенной клетке, ДО `cur == target`.

Если сработало goal — останавливаемся раньше target, потому что
в этой клетке T-врезка будет корректной (перпендикулярный вход).
Если дошли до target без срабатывания goal — тоже успех,
но подход может быть параллельным; вызывающий код решает,
ставить junction или уходить в fallback.
"""
from collections import deque
import heapq
from typing import Dict, Optional, Set, Tuple

from cell import Cell
from constants import (
    PathSearch,
    WireAngle,
    WIRE_ANGLE_TO_ORIENTATION,
    WireOrientation,
)
from logging_setup import ctx, get_logger
from stub import ANGLE_DELTA, ANGLE_NAME
from wire import WireSegment, segment_angle

from router_impl.router_rules import can_enter, can_leave
from router_impl.router_types import RouteAttempt

log = get_logger(__name__)

MAX_VISITS = 200_000
PROGRESS_STEP = 10000


# =========================================================
# Точка входа
# =========================================================

def find_path(
    router,
    net: str,
    start: Cell,
    goal: Cell,
    *,
    host_cells: Optional[Dict[Cell, Tuple[WireOrientation, ...]]] = None,
) -> RouteAttempt:
    """Выбирает алгоритм по router.search.

    Args:
        router:     роутер (map/bounds/page/search).
        net:        имя сети (для can_enter/can_leave).
        start:      начальная клетка.
        goal:       штатная цель — конкретная клетка-ориентир.
        host_cells: необязательная карта «клетка → ориентации
                    host-сегментов, проходящих через неё».
                    Если задана, то на каждой вытащенной клетке
                    сначала проверяется goal-условие: «клетка в
                    host_cells И вход перпендикулярен хотя бы
                    одному host-сегменту». При срабатывании —
                    остановка раньше target.

    Возвращает RouteAttempt:
        success=True,  path=[...], goal_reached_by="target"|"goal"
        success=False, visited=..., frontier=...
    """
    if router.search == PathSearch.BFS:
        return bfs(router, net, start, goal, host_cells=host_cells)
    if router.search == PathSearch.ASTAR:
        return astar(router, net, start, goal, host_cells=host_cells)
    return dijkstra(router, net, start, goal, host_cells=host_cells)


# =========================================================
# Общие хелперы
# =========================================================

def _reconstruct(cur: Cell,
                 prev: Dict[Tuple[int, int], Optional[Cell]]) -> list:
    """Восстанавливает путь от start до cur."""
    path = []
    node = cur
    while node is not None:
        path.append(node)
        node = prev[(node.col, node.row)]
    path.reverse()
    return path


def _segments_of(path):
    """Разбивает путь на ортогональные сегменты."""
    if len(path) < 2:
        return []
    segments = []
    seg_start = path[0]
    current = segment_angle(path[0], path[1])
    for i in range(1, len(path) - 1):
        a, b = path[i], path[i + 1]
        ang = segment_angle(a, b)
        if ang != current:
            segments.append(WireSegment(seg_start, a, current))
            seg_start = a
            current = ang
    segments.append(WireSegment(seg_start, path[-1], current))
    return segments


def _heuristic(a: Cell, b: Cell) -> int:
    """Манхэттенское расстояние между клетками."""
    return abs(a.col - b.col) + abs(a.row - b.row)


def _is_goal_state(
    cell: Cell,
    entry_angle: Optional[WireAngle],
    host_cells: Optional[Dict[Cell, Tuple[WireOrientation, ...]]],
) -> bool:
    """Сработало ли goal-условие на клетке.

    Goal = клетка принадлежит host-проводу сети И вход в неё
    перпендикулярен хотя бы одному host-сегменту в этой клетке.

    Если host_cells не задан (случай _route_pair) — goal
    никогда не срабатывает, и остановка идёт только по target.

    Args:
        cell:        текущая клетка.
        entry_angle: направление входа в клетку (WireAngle) или None
                     для старта.
        host_cells:  карта «клетка → ориентации host-сегментов».

    Returns:
        True, если сработал goal.
    """
    if host_cells is None:
        return False
    if cell not in host_cells:
        return False
    if entry_angle is None:
        # стартовая клетка: входа не было, goal не считаем.
        return False

    entry_orient = WIRE_ANGLE_TO_ORIENTATION[entry_angle]
    host_orients = host_cells[cell]
    # Перпендикулярно — значит, ориентация входа отличается
    # от ориентации host-сегмента. H != V.
    for ho in host_orients:
        if ho != entry_orient:
            return True
    return False


# =========================================================
# BFS
# =========================================================

def bfs(router, net: str, start: Cell, goal: Cell, *,
        host_cells: Optional[Dict[Cell, Tuple[WireOrientation, ...]]] = None,
        ) -> RouteAttempt:
    """Поиск в ширину: кратчайший путь при единичных весах."""
    map_ = router.map
    bounds = router.bounds
    page = router.page

    log.debug("%s bfs %s → %s", ctx(page=page, net=net), start, goal)

    if start == goal:
        log.debug("%s bfs start_eq_goal", ctx(page=page, net=net))
        return RouteAttempt(success=True, path=[start],
                            goal_reached_by="target")

    q = deque([start])
    prev: Dict[Tuple[int, int], Optional[Cell]] = {
        (start.col, start.row): None
    }
    entry: Dict[Tuple[int, int], Optional[WireAngle]] = {
        (start.col, start.row): None
    }
    visited = 0
    frontier: Set[str] = set()

    while q:
        cur = q.popleft()
        if visited > MAX_VISITS:
            log.warning("%s bfs visit_limit=%d",
                        ctx(page=page, net=net), MAX_VISITS)
            break
        visited += 1
        if visited % PROGRESS_STEP == 0:
            log.trace("%s bfs progress visited=%d queue=%d cur=%s",
                      ctx(page=page, net=net), visited, len(q), cur)

        cur_key = (cur.col, cur.row)
        cur_entry = entry[cur_key]

        # 1. Goal — «везение»: пришли в host-провод перпендикулярно.
        if _is_goal_state(cur, cur_entry, host_cells):
            path = _reconstruct(cur, prev)
            log.debug("%s bfs done_by_goal steps=%d cells=%d",
                      ctx(page=page, net=net), visited, len(path))
            return RouteAttempt(success=True, path=path,
                                segments=_segments_of(path),
                                visited=visited,
                                goal_reached_by="goal")

        # 2. Target — штатная цель.
        if cur == goal:
            path = _reconstruct(cur, prev)
            log.debug("%s bfs done_by_target steps=%d cells=%d",
                      ctx(page=page, net=net), visited, len(path))
            return RouteAttempt(success=True, path=path,
                                segments=_segments_of(path),
                                visited=visited,
                                goal_reached_by="target")

        for angle, (dc, dr) in ANGLE_DELTA.items():
            nxt = Cell(cur.col + dc, cur.row + dr)
            key = (nxt.col, nxt.row)
            if key in prev:
                continue

            ok, blocker = can_enter(map_, bounds, nxt, net, angle)
            if not ok:
                if blocker:
                    frontier.add(blocker)
                continue

            ok_leave, blocker_leave = can_leave(
                map_, cur, net, cur_entry, angle)
            if not ok_leave:
                if blocker_leave:
                    frontier.add(blocker_leave)
                continue

            prev[key] = cur
            entry[key] = angle
            q.append(nxt)

    log.trace("%s bfs fail visited=%d frontier=%s",
              ctx(page=page, net=net), visited, sorted(frontier))

    if visited == 1:
        log.warning("%s bfs stuck_at_start %s → %s map_cells=%d",
                    ctx(page=page, net=net), start, goal, len(map_))
        for angle, (dc, dr) in ANGLE_DELTA.items():
            nxt = Cell(start.col + dc, start.row + dr)
            key = (nxt.col, nxt.row)
            occ = map_.get(key)
            ok, blocker = can_enter(map_, bounds, nxt, net, angle)
            log.warning(
                "%s bfs probe dir=%s next=%s occ=%s in_prev=%s "
                "can_enter=%s blocker=%r",
                ctx(page=page, net=net), ANGLE_NAME[angle], nxt,
                type(occ).__name__ if occ else "None",
                key in prev, ok, blocker,
            )

    return RouteAttempt(success=False, visited=visited, frontier=frontier)


# =========================================================
# A*
# =========================================================

def astar(router, net: str, start: Cell, goal: Cell, *,
          host_cells: Optional[Dict[Cell, Tuple[WireOrientation, ...]]] = None,
          ) -> RouteAttempt:
    """A* с манхэттенской эвристикой."""
    map_ = router.map
    bounds = router.bounds
    page = router.page

    log.debug("%s astar %s → %s", ctx(page=page, net=net), start, goal)

    if start == goal:
        log.debug("%s astar start_eq_goal", ctx(page=page, net=net))
        return RouteAttempt(success=True, path=[start],
                            goal_reached_by="target")

    counter = 0
    heap = [(_heuristic(start, goal), counter, start)]
    g: Dict[Tuple[int, int], int] = {(start.col, start.row): 0}
    prev: Dict[Tuple[int, int], Optional[Cell]] = {
        (start.col, start.row): None
    }
    entry: Dict[Tuple[int, int], Optional[WireAngle]] = {
        (start.col, start.row): None
    }
    closed: Set[Tuple[int, int]] = set()
    visited = 0
    frontier: Set[str] = set()

    while heap:
        _, _, cur = heapq.heappop(heap)
        key = (cur.col, cur.row)
        if key in closed:
            continue
        closed.add(key)
        if visited > MAX_VISITS:
            log.warning("%s astar visit_limit=%d",
                        ctx(page=page, net=net), MAX_VISITS)
            break
        visited += 1
        if visited % PROGRESS_STEP == 0:
            log.debug("%s astar progress visited=%d queue=%d cur=%s",
                      ctx(page=page, net=net), visited, len(heap), cur)

        cur_entry = entry[key]

        # 1. Goal — «везение».
        if _is_goal_state(cur, cur_entry, host_cells):
            path = _reconstruct(cur, prev)
            log.debug("%s astar done_by_goal steps=%d cells=%d",
                      ctx(page=page, net=net), visited, len(path))
            return RouteAttempt(success=True, path=path,
                                segments=_segments_of(path),
                                visited=visited,
                                goal_reached_by="goal")

        # 2. Target.
        if cur == goal:
            path = _reconstruct(cur, prev)
            log.debug("%s astar done_by_target steps=%d cells=%d",
                      ctx(page=page, net=net), visited, len(path))
            return RouteAttempt(success=True, path=path,
                                segments=_segments_of(path),
                                visited=visited,
                                goal_reached_by="target")

        for angle, (dc, dr) in ANGLE_DELTA.items():
            nxt = Cell(cur.col + dc, cur.row + dr)
            nkey = (nxt.col, nxt.row)
            if nkey in closed:
                continue

            ok, blocker = can_enter(map_, bounds, nxt, net, angle)
            if not ok:
                if blocker:
                    frontier.add(blocker)
                continue

            ok_leave, blocker_leave = can_leave(
                map_, cur, net, cur_entry, angle)
            if not ok_leave:
                if blocker_leave:
                    frontier.add(blocker_leave)
                continue

            tentative = g[key] + 1
            if tentative < g.get(nkey, 1 << 30):
                g[nkey] = tentative
                prev[nkey] = cur
                entry[nkey] = angle
                counter += 1
                f = tentative + _heuristic(nxt, goal)
                heapq.heappush(heap, (f, counter, nxt))

    log.trace("%s astar fail visited=%d frontier=%s",
              ctx(page=page, net=net), visited, sorted(frontier))
    return RouteAttempt(success=False, visited=visited, frontier=frontier)


# =========================================================
# Dijkstra
# =========================================================

def dijkstra(router, net: str, start: Cell, goal: Cell, *,
             host_cells: Optional[Dict[Cell, Tuple[WireOrientation, ...]]] = None,
             ) -> RouteAttempt:
    """Ищет путь между клетками.

    Стоимость: свободная клетка — 1; клетка своей сети — 1;
    вход в чужую клетку запрещён, если он параллелен чужому
    проводу в этой клетке.
    """
    map_ = router.map
    bounds = router.bounds
    page = router.page

    log.debug("%s dijkstra %s → %s", ctx(page=page, net=net), start, goal)

    if start == goal:
        log.debug("%s dijkstra start_eq_goal", ctx(page=page, net=net))
        return RouteAttempt(success=True, path=[start],
                            goal_reached_by="target")

    counter = 0
    heap = [(0, counter, start)]
    dist: Dict[Tuple[int, int], int] = {(start.col, start.row): 0}
    prev: Dict[Tuple[int, int], Optional[Cell]] = {
        (start.col, start.row): None
    }
    entry: Dict[Tuple[int, int], Optional[WireAngle]] = {
        (start.col, start.row): None
    }
    visited = 0
    frontier: Set[str] = set()

    while heap:
        cost, _, cur = heapq.heappop(heap)
        if visited > MAX_VISITS:
            log.warning("%s dijkstra visit_limit=%d",
                        ctx(page=page, net=net), MAX_VISITS)
            break
        visited += 1
        if visited % PROGRESS_STEP == 0:
            log.debug("%s dijkstra progress visited=%d queue=%d cur=%s",
                      ctx(page=page, net=net), visited, len(heap), cur)

        cur_key = (cur.col, cur.row)
        cur_entry = entry[cur_key]

        # 1. Goal — «везение».
        if _is_goal_state(cur, cur_entry, host_cells):
            path = _reconstruct(cur, prev)
            log.debug("%s dijkstra done_by_goal steps=%d cost=%d cells=%d",
                      ctx(page=page, net=net), visited, cost, len(path))
            return RouteAttempt(success=True, path=path,
                                segments=_segments_of(path),
                                visited=visited,
                                goal_reached_by="goal")

        # 2. Target.
        if cur == goal:
            path = _reconstruct(cur, prev)
            log.debug("%s dijkstra done_by_target steps=%d cost=%d cells=%d",
                      ctx(page=page, net=net), visited, cost, len(path))
            return RouteAttempt(success=True, path=path,
                                segments=_segments_of(path),
                                visited=visited,
                                goal_reached_by="target")

        for angle, (dc, dr) in ANGLE_DELTA.items():
            nxt = Cell(cur.col + dc, cur.row + dr)
            key = (nxt.col, nxt.row)

            ok, blocker = can_enter(map_, bounds, nxt, net, angle)
            if not ok:
                if blocker:
                    frontier.add(blocker)
                    log.trace("%s dijkstra blocked cell=%s by=%s",
                              ctx(page=page, net=net), nxt, blocker)
                continue

            ok_leave, blocker_leave = can_leave(
                map_, cur, net, cur_entry, angle)
            if not ok_leave:
                if blocker_leave:
                    frontier.add(blocker_leave)
                    log.trace("%s dijkstra blocked_leave cell=%s by=%s",
                              ctx(page=page, net=net), cur, blocker_leave)
                continue

            new_cost = cost + 1
            if key in dist and dist[key] <= new_cost:
                continue
            dist[key] = new_cost
            prev[key] = cur
            entry[key] = angle
            counter += 1
            heapq.heappush(heap, (new_cost, counter, nxt))

    log.trace("%s dijkstra fail visited=%d frontier=%s",
              ctx(page=page, net=net), visited, sorted(frontier))
    return RouteAttempt(success=False, visited=visited, frontier=frontier)