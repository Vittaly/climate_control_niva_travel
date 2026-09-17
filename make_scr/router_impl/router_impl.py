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

    def __init__(self, map_: RouterMap, placer,
                 components: Dict[str, Component],
                 search: PathSearch = PathSearch.BFS):
        self.map = map_
        self.placer = placer
        self.components = components
        self.grid_mm = placer.grid_step
        self.search = search

        # блокеры, встреченные за весь прогон (для отчёта)
        self.frontier = set()

        # страница, к которой привязан роутер (ставится в route_all)
        self.page = "root"

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
    def from_placer(cls, placer, components,
                    search: PathSearch = PathSearch.BFS) -> "Router":
        """Строит Router из карты, которую подготовил Placer."""
        m = placer.build_router_map()
        log.info("%s router created cells=%d search=%s",
                 ctx(page=getattr(placer, "page", "root")),
                 len(m), search)
        return cls(m, placer, components, search=search)

    # =========================================================
    # Публичная точка входа
    # =========================================================

    def route_all(self, netlist: Netlist, sheet) -> List[Wire]:
        """Трассирует все сети одной страницы.

        Метки и T-врезки пишутся в sheet и у роутера не сохраняются.
        В начале прогона накопители sheet сбрасываются — повторный
        прогон даёт чистый результат.
        """
        self.page = sheet.sheet_path or "root"
        log.info("%s routing nets=%d",
                 ctx(page=self.page), len(netlist.nets))

        sheet.reset_routing_marks()

        all_wires: List[Wire] = []

        for net_name, net in netlist.nets.items():
            endpoints = self._collect_endpoints(net, sheet)
            if len(endpoints) < 2:
                log.debug("%s net_pins_lt2 skip",
                          ctx(page=self.page, net=net_name))
                continue

            log.debug("%s pins=%s",
                      ctx(page=self.page, net=net_name),
                      ", ".join(p.local_key for _, p in endpoints))

            net_wires = self._route_net(net_name, endpoints, sheet)
            for w in net_wires:
                netlist.register_wire(w)
                all_wires.append(w)
            log.debug("%s rss=%.1f net_wires=%d total_wires=%d",
                      ctx(page=self.page, net=net_name),
                      _rss_mb(), len(net_wires), len(all_wires))

        log.info("%s routing_done wires=%d labels=%d t_junctions=%d",
                 ctx(page=self.page),
                 len(all_wires),
                 len(sheet.labels), len(sheet.t_junctions))
        return all_wires

    # =========================================================
    # Сбор пинов сети
    # =========================================================

    def _collect_endpoints(self, net, sheet
                           ) -> List[Tuple[Cell, "Pin"]]:
        """Собирает пины сети на этой странице с абсолютными клетками."""
        endpoints: List[Tuple[Cell, "Pin"]] = []
        for fqn in net.pins:
            local = sheet.local_key(fqn)
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
                   endpoints: List[Tuple[Cell, "Pin"]],
                   sheet) -> List[Wire]:
        """Трассирует одну сеть: первое соединение + T-врезки."""
        wires: List[Wire] = []

        cell_a, pin_a = endpoints[0]
        cell_b, pin_b = endpoints[1]

        wire = self._route_pair(net_name, cell_a, pin_a,
                                cell_b, pin_b, sheet)
        if wire is None:
            log.warning("%s fail %s → %s",
                        ctx(page=self.page, net=net_name,
                            comp=self._designator(pin_a),
                            pin=self._pin_num(pin_a)),
                        pin_a.local_key, pin_b.local_key)
            return wires

        wires.append(wire)
        log.info("%s ok segments=%d",
                 ctx(page=self.page, net=net_name,
                     comp=self._designator(pin_a),
                     pin=self._pin_num(pin_a)),
                 len(wire.segments()))

        for cell_c, pin_c in endpoints[2:]:
            wire = self._route_t_junction(net_name, cell_c, pin_c,
                                          wires, sheet)
            if wire:
                wires.append(wire)
                log.info("%s ok t_junction=%s",
                         ctx(page=self.page, net=net_name,
                             comp=self._designator(pin_c),
                             pin=self._pin_num(pin_c)),
                         wire.end.local_key if wire.end else "?")
            else:
                log.warning("%s fail %s → net",
                            ctx(page=self.page, net=net_name,
                                comp=self._designator(pin_c),
                                pin=self._pin_num(pin_c)),
                            pin_c.local_key)

        return wires

    # =========================================================
    # Соединение двух пинов
    # =========================================================

    def _route_pair(self, net_name: str,
                    cell_a: Cell, pin_a: "Pin",
                    cell_b: Cell, pin_b: "Pin",
                    sheet) -> Optional[Wire]:
        """Соединяет два пина: stub → Dijkstra → stub.

        При провале пишет FallbackLabel на оба пина в sheet.labels.
        """
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

            self._mark_fallback(sheet, net_name, pin_a, cell_a,
                                "route failed")
            self._mark_fallback(sheet, net_name, pin_b, cell_b,
                                "route failed")
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
                          existing_wires: List[Wire],
                          sheet) -> Optional[Wire]:
        """Присоединяет новый пин к существующей сети врезкой T.

        При удаче пишет TJunction в sheet.t_junctions.
        При провале пишет FallbackLabel в sheet.labels.
        """
        log.info("%s t_connect",
                 ctx(page=self.page, net=net_name,
                     comp=self._designator(pin_c),
                     pin=self._pin_num(pin_c)))

        stub_c = plan_stub(pin_c, self.placer, self.map)

        # кандидаты — все клетки всех сегментов уже проложенных проводов
        candidates: List[Cell] = []
        for w in existing_wires:
            for seg in w.segments():
                candidates.extend(seg.cells())

        candidates.sort(key=lambda c: abs(c.col - stub_c.tip.col) +
                                       abs(c.row - stub_c.tip.row))

        max_tries = 5
        log.debug("%s t_connect candidates=%d tries=%d",
                  ctx(page=self.page, net=net_name,
                      comp=self._designator(pin_c),
                      pin=self._pin_num(pin_c)),
                  len(candidates), min(len(candidates), max_tries))

        for i, target in enumerate(candidates[:max_tries]):
            log.trace("%s t_connect_try=%d target=%s",
                      ctx(page=self.page, net=net_name,
                          comp=self._designator(pin_c),
                          pin=self._pin_num(pin_c)),
                      i + 1, target)
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
            sheet.t_junctions.append(TJunction(
                net_name=net_name,
                target=target,
                source=stub_c.tip,
                wire_key=host.key if host else "",
            ))
            log.info("%s t_junction recorded net=%s target=%s host=%s",
                     ctx(page=self.page,
                         comp=self._designator(pin_c),
                         pin=self._pin_num(pin_c)),
                     net_name, target,
                     host.key if host else "?")
            return wire

        log.warning("%s fail %s → net tries=%d",
                    ctx(page=self.page, net=net_name,
                        comp=self._designator(pin_c),
                        pin=self._pin_num(pin_c)),
                    pin_c.local_key,
                    min(len(candidates), max_tries))
        self._mark_fallback(sheet, net_name, pin_c, cell_c,
                            "T-junction failed")
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

    def _mark_fallback(self, sheet, net_name: str, pin, cell: Cell,
                       reason: str) -> None:
        """Ставит метку на пин, если её ещё нет на странице.

        Идемпотентность — по local_key в пределах страницы.
        """
        key = pin.local_key
        for lbl in sheet.labels:
            if lbl.local_key == key:
                return
        sheet.labels.append(FallbackLabel(
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