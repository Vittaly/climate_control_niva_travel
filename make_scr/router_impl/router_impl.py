# router_impl/impl.py
"""Router: оркестрация, T-врезки, occupy, fallback.

Механика:
    1. Первое соединение сети — два пина:
       - от каждого пина отросток до первой свободной клетки за bbox;
       - концы отростков соединяются Dijkstra (строго ортогонально).
    2. Последующие пины — T-врезка:
       - от нового пина отросток;
       - ищется ближайшая точка на существующих сегментах сети;
       - маршрут от tip-отростка до точки врезки.
    3. При неудаче — метка на пине.

Правила маршрутизации — в router_impl/rules.py.
Поиск пути — в router_impl/pathfind.py.
Логирование — в router_impl/logging_.py.
"""
from typing import Dict, List, Optional, Tuple

from cell import Cell
from component import Component
from constants import PathSearch
from logging_setup import ctx, get_logger
from netlist import Netlist
from occupant import WireCell
from router_map import RouterMap
from routing_types import FallbackLabel, TJunction
from stub import plan_stub
from wire import Wire

from router_impl import router_pathfind
from router_impl.router_logging import RouterLogMixin
from router_impl.router_rules import in_bounds
from router_impl.router_types import RouteAttempt

log = get_logger(__name__)


def _rss_mb() -> float:
    """RSS текущего процесса в МБ (для мониторинга утечек)."""
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:
        return 0.0


class Router(RouterLogMixin):
    """Роутер с отростками, Dijkstra, T-врезками и метками.

    Роутер stateless относительно меток и T-врезок: он пишет их
    в Sheet и забывает. Состояние самого роутера — карта, placer,
    components и накопленный frontier.
    """
    MAX_VISITS = 200_000

    def __init__(self, map_: RouterMap, placer, search=PathSearch.BFS):
        self.map = map_
        self.placer = placer
        self.sheet = placer.sheet                # ← единственная страница
        self.components = self.sheet.components  # ← тот же набор, что у Sheet
        self.netlist = self.sheet.netlist        # ← нетлист страницы
        self.grid_mm = placer.grid_step          # = sheet.grid_mm
        self.search = search
        self.frontier = set()
        self.page = self.sheet.page              # "root" или имя файла
        self.bounds = self._compute_bounds(pad_div=3)

        # блокеры, встреченные за весь прогон (для отчёта)
        self.frontier = set()

        # страница, к которой привязан роутер (ставится в route_all)
        self.page = self.sheet.page               # сразу, не в route_all

        # границы поля: bbox компонентов + 1/3 размера с каждой стороны
        self.bounds = self._compute_bounds(pad_div=3)
        log.info("%s router field cols=[%d..%d] rows=[%d..%d]",
                 ctx(page=self.page),
                 self.bounds[0], self.bounds[1],
                 self.bounds[2], self.bounds[3])

    # =========================================================
    # Границы поля (1/3 от bbox компонентов с каждой стороны)
    # =========================================================

    def _compute_bounds(self, pad_div: int = 3
                        ) -> Tuple[int, int, int, int]:
        """(min_col, max_col, min_row, max_row) с паддингом 1/pad_div.

        Использует Component.bbox_page_cell() — Component сам знает
        anchor_page_mm и anchor_offset_page_mm.
        """
        if not self.components:
            return (0, 0, 0, 0)

        min_c = min_r = 10 ** 9
        max_c = max_r = -(10 ** 9)

        for comp in self.components.values():
            if comp.anchor_page_mm is None:
                continue
            bbox = comp.bbox_page_cell()   # (col0, row0, col1, row1)
            min_c = min(min_c, bbox[0])
            max_c = max(max_c, bbox[2])
            min_r = min(min_r, bbox[1])
            max_r = max(max_r, bbox[3])

        if min_c > max_c or min_r > max_r:
            return (0, 0, 0, 0)

        W = max_c - min_c
        H = max_r - min_r
        pad_c = max(1, W // pad_div)
        pad_r = max(1, H // pad_div)

        return (min_c - pad_c, max_c + pad_c,
                min_r - pad_r, max_r + pad_r)

    def _in_bounds(self, cell: Cell) -> bool:
        return in_bounds(self.bounds, cell)

    @classmethod
    def from_placer(cls, placer,
                    search: PathSearch = PathSearch.BFS) -> "Router":
        m = placer.build_router_map()
        log.info("%s router created cells=%d search=%s",
                ctx(page=placer.page_name), len(m), search)
        return cls(m, placer, search=search)

    # =========================================================
    # Публичная точка входа
    # =========================================================

    def route_all(self) -> List[Wire]:
        """Трассирует все сети одной страницы.

        Метки и T-врезки пишутся в sheet и у роутера не сохраняются.
        В начале прогона накопители sheet сбрасываются.
        """
        log.info("%s routing nets=%d",
                ctx(page=self.page), len(self.netlist.nets))

        self.sheet.reset_routing_marks()

        all_wires: List[Wire] = []

        for net_name, net in self.netlist.nets.items():
            endpoints = self._collect_endpoints(net)
            if len(endpoints) < 2:
                log.debug("%s net_pins_lt2 skip",
                        ctx(page=self.page, net=net_name))
                continue

            log.debug("%s pins=%s",
                    ctx(page=self.page, net=net_name),
                    ", ".join(p.local_key for _, p in endpoints))

            net_wires = self._route_net(net_name, endpoints)
            for w in net_wires:
                self.netlist.register_wire(w)
                all_wires.append(w)
            log.debug("%s rss=%.1f net_wires=%d total_wires=%d",
                    ctx(page=self.page, net=net_name),
                    _rss_mb(), len(net_wires), len(all_wires))

        log.info("%s routing_done wires=%d labels=%d t_junctions=%d",
                ctx(page=self.page),
                len(all_wires),
                len(self.sheet.labels), len(self.sheet.t_junctions))
        return all_wires

    # =========================================================
    # Сбор пинов сети
    # =========================================================

    def _collect_endpoints(self, net) -> List[Tuple[Cell, "Pin"]]:
        """Собирает пины сети на этой странице с абсолютными клетками."""
        endpoints: List[Tuple[Cell, "Pin"]] = []
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
            cell = comp.abs_pin_cell(pin)
            endpoints.append((cell, pin))
        return endpoints

    # =========================================================
    # Трассировка одной сети
    # =========================================================

    def _route_net(self, net_name: str,
                endpoints: List[Tuple[Cell, "Pin"]]) -> List[Wire]:
        wires: List[Wire] = []
        n = len(endpoints)
        used: set = set()

        pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                ci, _ = endpoints[i]
                cj, _ = endpoints[j]
                d = abs(ci.col - cj.col) + abs(ci.row - cj.row)
                pairs.append((d, i, j))
        pairs.sort()

        seed: Optional[Wire] = None
        for _, i, j in pairs:
            ca, pa = endpoints[i]
            cb, pb = endpoints[j]
            w = self._route_pair(net_name, ca, pa, cb, pb)
            if w is not None:
                wires.append(w)
                used.add(i)
                used.add(j)
                seed = w
                log.info("%s seed_pair %s → %s",
                        ctx(page=self.page, net=net_name),
                        pa.local_key, pb.local_key)
                break

        if seed is None:
            log.warning("%s no_seed_pair endpoints=%d",
                        ctx(page=self.page, net=net_name), n)
            for cell, pin in endpoints:
                self._mark_fallback(net_name, pin, cell, "route failed")
            return wires

        for k, (cell, pin) in enumerate(endpoints):
            if k in used:
                continue
            w = self._route_t_junction(net_name, cell, pin, wires)
            if w:
                wires.append(w)
                used.add(k)
                log.info("%s ok t_junction=%s",
                        ctx(page=self.page, net=net_name,
                            comp=self._designator(pin),
                            pin=self._pin_num(pin)),
                        w.end.local_key if w.end else "?")
            else:
                log.warning("%s fail %s → net",
                            ctx(page=self.page, net=net_name,
                                comp=self._designator(pin),
                                pin=self._pin_num(pin)),
                            pin.local_key)

        return wires

    # =========================================================
    # Соединение двух пинов
    # =========================================================

    def _route_pair(self, net_name: str,
                    cell_a: Cell, pin_a: "Pin",
                    cell_b: Cell, pin_b: "Pin") -> Optional[Wire]:
        log.info("%s connect %s → %s",
                ctx(page=self.page, net=net_name,
                    comp=self._designator(pin_a),
                    pin=self._pin_num(pin_a)),
                pin_a.local_key, pin_b.local_key)

        stub_a = plan_stub(pin_a, self.placer, self.map)
        stub_b = plan_stub(pin_b, self.placer, self.map)

        attempt = self._find_path(net_name, stub_a.tip, stub_b.tip)
        if not attempt.success:
            log.warning("%s fail %s → %s",
                        ctx(page=self.page, net=net_name,
                            comp=self._designator(pin_a),
                            pin=self._pin_num(pin_a)),
                        pin_a.local_key, pin_b.local_key)
            self._log_planned_partial(net_name, attempt, pin_a)
            self._log_frontier(net_name, attempt)
            self.frontier.update(attempt.frontier)

            self._mark_fallback(net_name, pin_a, cell_a, "route failed")
            self._mark_fallback(net_name, pin_b, cell_b, "route failed")
            log.warning("%s fallback labels_on=%s,%s",
                        ctx(page=self.page, net=net_name),
                        pin_a.local_key, pin_b.local_key)
            return None

        wire = Wire(
            net_name=net_name,
            start=pin_a,
            end=pin_b,
            path=attempt.path,
            start_stub=stub_a.stub,
            end_stub=stub_b.stub,
        )
        self._occupy(wire)
        self._log_wire_full(net_name, wire)
        return wire

    # =========================================================
    # T-врезка
    # =========================================================

    def _route_t_junction(self, net_name: str,
                      cell_c: Cell, pin_c: "Pin",
                      existing_wires: List[Wire]) -> Optional[Wire]:
        log.info("%s t_connect",
                ctx(page=self.page, net=net_name,
                    comp=self._designator(pin_c),
                    pin=self._pin_num(pin_c)))

        stub_c = plan_stub(pin_c, self.placer, self.map)

        candidates: List[Cell] = []
        for w in existing_wires:
            for seg in w.segments():
                candidates.extend(seg.cells())

        candidates.sort(key=lambda c: abs(c.col - stub_c.tip.col) +
                                    abs(c.row - stub_c.tip.row))

        max_tries = 5
        for i, target in enumerate(candidates[:max_tries]):
            attempt = self._find_path(net_name, stub_c.tip, target)
            if not attempt.success:
                continue

            log.info("%s t_junction target=%s try=%d",
                    ctx(page=self.page, net=net_name,
                        comp=self._designator(pin_c),
                        pin=self._pin_num(pin_c)),
                    target, i + 1)
            wire = Wire(
                net_name=net_name,
                start=pin_c,
                end=None,
                path=attempt.path,
                start_stub=stub_c.stub,
                end_stub=None,
                t_junction=True,
            )
            self._occupy(wire)
            self._log_wire_full(net_name, wire)

            host = self._find_host_wire(target, existing_wires)
            self.sheet.t_junctions.append(TJunction(
                net_name=net_name,
                target=target,
                source=stub_c.tip,
                wire_key=host.key if host else "",
            ))
            log.info("%s t_junction recorded net=%s target=%s host=%s",
                    ctx(page=self.page,
                        comp=self._designator(pin_c),
                        pin=self._pin_num(pin_c)),
                    net_name, target, host.key if host else "?")
            return wire

        log.warning("%s fail %s → net tries=%d",
                    ctx(page=self.page, net=net_name,
                        comp=self._designator(pin_c),
                        pin=self._pin_num(pin_c)),
                    pin_c.local_key, min(len(candidates), max_tries))
        self._mark_fallback(net_name, pin_c, cell_c, "T-junction failed")
        log.warning("%s fallback label_on=%s",
                    ctx(page=self.page, net=net_name),
                    pin_c.local_key)
        return None

    @staticmethod
    def _find_host_wire(target: Cell,
                        existing_wires: List[Wire]) -> Optional[Wire]:
        """Возвращает провод, на сегменте которого лежит target."""
        for w in existing_wires:
            for seg in w.segments():
                if target in seg.cells():
                    return w
        return None

    # =========================================================
    # Поиск пути (тонкая обёртка над pathfind)
    # =========================================================

    def _find_path(self, net: str, start: Cell,
                   goal: Cell) -> RouteAttempt:
        return router_pathfind.find_path(self, net, start, goal)

    # =========================================================
    # Заполнение карты
    # =========================================================

    def _occupy(self, wire: Wire) -> None:
        """Помечает все клетки провода как WireCell.

        Не перезаписывает чужой WireCell: если клетка уже занята
        проводом другой сети, это OVERLAP — короткое замыкание.
        Логируем и пропускаем, чтобы карта не теряла старый провод.
        """
        for cell in wire.all_cells():
            key = (cell.col, cell.row)
            existing = self.map.get(key)
            if (isinstance(existing, WireCell)
                    and existing.wire.net_name != wire.net_name):
                log.warning(
                    "%s OCCUPY_OVERLAP cell=%s existing_net=%s "
                    "new_net=%s existing_wire=%s new_wire=%s",
                    ctx(page=self.page, net=wire.net_name),
                    cell, existing.wire.net_name, wire.net_name,
                    existing.wire.key, wire.key,
                )
                continue
            self.map[key] = WireCell(wire=wire)

    # =========================================================
    # Метки fallback — пишутся в Sheet, не в Router
    # =========================================================

    def _mark_fallback(self, net_name: str, pin, cell: Cell,
                   reason: str) -> None:
        """Ставит метку на пин, если её ещё нет на странице.

        Идемпотентность — по local_key в пределах страницы.
        """
        key = pin.local_key
        for lbl in self.sheet.labels:
            if lbl.local_key == key:
                return
        self.sheet.labels.append(FallbackLabel(
            net_name=net_name,
            local_key=key,
            cell=cell,
            reason=reason,
        ))
        log.info("%s label net=%s reason=%s",
                ctx(page=self.page, net=net_name,
                    comp=self._designator(pin),
                    pin=self._pin_num(pin)),
                net_name, reason)