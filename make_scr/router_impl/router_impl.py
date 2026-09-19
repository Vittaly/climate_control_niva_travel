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
    3. При неудаче — метка на пине или на T-точке.

Правила маршрутизации — в router_impl/rules.py.
Поиск пути — в router_impl/pathfind.py.
Логирование — в router_impl/logging_.py.
"""
from typing import Dict, List, Optional, Tuple

from cell import Cell
from component import Component
from constants import PathSearch, WireOrientation
from logging_setup import ctx, get_logger
from netlist import Netlist
from occupant import WireCell
from router_map import RouterMap
from routing_types import FallbackLabel, TJunction
from stub import plan_stub
from wire import Wire

from router_impl import router_pathfind
from router_impl.router_logging import RouterLogMixin
from router_impl.router_rules import in_bounds,  _orientations_at, _is_endpoint_at, _check_entry
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

        # Имена внутренних сетей (нет порта и нет fallback-метки):
        # KiCad иначе сгенерирует Net-(U1-ILIM) вместо /ILIM.
        self._name_internal_nets()

        log.info("%s routing_done wires=%d labels=%d t_junctions=%d",
                ctx(page=self.page),
                len(all_wires),
                len(self.sheet.labels), len(self.sheet.t_junctions))
        return all_wires


    def _name_internal_nets(self) -> None:
        """Ставит метку-имя на провод внутренних сетей.

        Внутренняя сеть — та, у которой на этой странице нет
        PortComponent и нет ни одной FallbackLabel. Такие сети
        остаются без имени в .kicad_sch, и KiCad генерирует
        Net-(U1-ILIM). Метка на проводе фиксирует имя из YAML.

        Метка ставится одна на сеть, на «чистой» клетке её провода
        (без транзита чужой сети — иначе KiCad приклеит имя к обеим).
        """
        # 1. Сети, у которых уже есть имя на этой странице:
        #    порты и существующие метки.
        named: set[str] = set()
        for comp in self.components.values():
            if getattr(comp, "is_port", False):
                named.add(comp.net_name)
        for lbl in self.sheet.labels:
            named.add(lbl.net_name)

        # 2. Сети, которые надо назвать: есть провода, нет имени.
        for net_name, net in self.netlist.nets.items():
            if net_name in named:
                continue
            wires = getattr(net, "wires", []) or []
            if not wires:
                continue

            cell = self._pick_label_cell(net_name, wires)
            if cell is None:
                log.warning(
                    "%s net_name_label skipped net=%s reason=no_cell",
                    ctx(page=self.page, net=net_name), net_name,
                )
                continue

            # метка на проводе, геометрия — как у on_wire-fallback,
            # но reason другой: это не аварийная ситуация.
            x_mm = cell.col * self.grid_mm
            y_mm = cell.row * self.grid_mm
            pin = wires[0].start        # любой пин сети для контекста
            self.sheet.labels.append(FallbackLabel(
                net_name=net_name,
                local_key=pin.local_key,
                contact_mm=(x_mm, y_mm),
                direction=pin.direction,
                reason="internal_net_name",
                on_wire=True,
            ))
            log.info(
                "%s net_name_label net=%s cell=%s mm=(%.2f,%.2f)",
                ctx(page=self.page, net=net_name),
                net_name, cell, x_mm, y_mm,
            )

    def _pick_label_cell(
        self, net_name: str, wires: List[Wire],
    ) -> Optional[Cell]:
        """Выбирает клетку для метки-имени сети.

        Приоритет:
            1. Середина самого длинного сегмента самого длинного
               провода — там метка не помешает и не попадёт в угол.
            2. Любая клетка пути.
            3. None, если ничего не нашли.

        Клетка обязательно должна быть «чистой»: только провода
        этой сети, без транзита чужих. Иначе KiCad приклеит имя
        и к чужой сети тоже.
        """
        # Сортируем провода по убыванию длины — самая заметная
        # сеть даст самую длинную метку-носитель.
        sorted_wires = sorted(
            wires, key=lambda w: w.length, reverse=True,
        )

        for wire in sorted_wires:
            for seg in wire.segments():
                cells = seg.cells()
                if len(cells) < 2:
                    continue
                # Берём середину сегмента, а не углы.
                mid = cells[len(cells) // 2]
                if self._cell_is_exclusive(mid, net_name):
                    return mid

        # Резервный вариант — любая клетка пути, если середина
        # не подошла.
        for wire in sorted_wires:
            for cell in wire.path:
                if self._cell_is_exclusive(cell, net_name):
                    return cell

        return None    
    

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
            for _cell, pin in endpoints:
                self._mark_fallback(net_name, pin,
                                    self._pin_contact_mm(pin),
                                    "route failed")
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

            self._mark_fallback(net_name, pin_a,
                                self._pin_contact_mm(pin_a),
                                "route failed")
            self._mark_fallback(net_name, pin_b,
                                self._pin_contact_mm(pin_b),
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

        # Регистрация в карте. Если _occupy вернул причину — клетка
        # занята чужой сетью несовместимо, провод НЕ валиден.
        reason = self._occupy(wire)
        if reason is not None:
            log.warning(
                "%s wire_rejected key=%s %s",
                ctx(page=self.page, net=net_name),
                wire.key, reason,
            )
            # провод не возвращаем — вызывающий его не зарегистрирует
            # в netlist и не отдаст Writer'у
            self._mark_fallback(net_name, pin_a,
                                self._pin_contact_mm(pin_a),
                                "route rejected")
            self._mark_fallback(net_name, pin_b,
                                self._pin_contact_mm(pin_b),
                                "route rejected")
            return None

        self._log_wire_full(net_name, wire)
        return wire


    

    # =========================================================
    # T-врезка
    # =========================================================

    def _cell_is_exclusive(self, cell: Cell, net_name: str) -> bool:
        """True, если клетка занята проводами ТОЛЬКО сети net_name.

        Клетки-пересечения двух сетей НЕ подходят для fallback-меток
        и T-врезок: KiCad приклеит label/endpoint к обеим сетям и
        склеит их. Для чистых клеток такого риска нет.
        """
        occ = self.map.get((cell.col, cell.row))
        if occ is None or not isinstance(occ, WireCell):
            return False
        for w in occ.wires:
            if w.net_name != net_name:
                return False
        return True
    
    
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

        # Отбрасываем клетки-пересечения: там уже транзит чужого провода.
        # T-точка или label на такой клетке склеит нашу сеть с чужой.
        exclusive = [c for c in candidates
                    if self._cell_is_exclusive(c, net_name)]

        max_tries = 5
        for i, target in enumerate(exclusive[:max_tries]):
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
            reason = self._occupy(wire)
            if reason is not None:
                log.warning(
                    "%s wire_rejected key=%s target=%s %s",
                    ctx(page=self.page, net=net_name),
                    wire.key, target, reason,
                )
                continue

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
                    pin_c.local_key, min(len(exclusive), max_tries))

        # ── Fallback ─────────────────────────────────────────────
        # Pin-side метка ставится всегда: пин связывается с сетью
        # по имени. Wire-side метка — только если есть «чистая»
        # клетка (без пересечений с чужими сетями), иначе она склеит
        # сети в KiCad.
        self._mark_fallback(
            net_name, pin_c,
            self._pin_contact_mm(pin_c),
            "T-junction failed",
            on_wire=False,
        )
        log.warning("%s fallback label_on_pin=%s",
                    ctx(page=self.page, net=net_name),
                    pin_c.local_key)

        if exclusive:
            target = exclusive[0]
            t_mm = (target.col * self.grid_mm,
                    target.row * self.grid_mm)
            self._mark_fallback(
                net_name, pin_c, t_mm,
                "T-junction failed",
                on_wire=True,
            )
            log.warning(
                "%s fallback label_on_wire cell=%s mm=(%.2f,%.2f)",
                ctx(page=self.page, net=net_name),
                target, t_mm[0], t_mm[1],
            )

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

    def _occupy(self, wire: Wire) -> Optional[str]:
        """Помечает клетки провода. Возвращает причину конфликта или None.

        None — карта обновлена, провод валиден.
        str  — конфликт: чужая сеть занимает клетку несовместимо.
            В этом случае карта НЕ обновляется, а вызывающий код
            обязан не регистрировать провод.

        Порядок: сначала проверяем все клетки, потом применяем.
        Если применить частично и упасть — карта и нетлист разойдутся.
        """
        plan: list[tuple[Cell, WireCell]] = []

        for cell in wire.all_cells():
            key = (cell.col, cell.row)
            existing = self.map.get(key)

            if existing is None:
                plan.append((cell, WireCell(wires=[wire])))
                continue

            if isinstance(existing, WireCell):
                # своя сеть — просто добавляем
                if any(w.net_name == wire.net_name for w in existing.wires):
                    plan.append((cell, existing))
                    continue

                # чужая сеть: совместимость
                ok, reason = self._check_cross(cell, wire, existing)
                if not ok:
                    return f"cell={cell} net={wire.net_name} reason={reason}"
                plan.append((cell, existing))
                continue

            # ComponentBody / PinCell — стена
            return (f"cell={cell} net={wire.net_name} "
                    f"blocked by {type(existing).__name__}")

        # Применяем: все клетки прошли проверку
        for cell, wc in plan:
            key = (cell.col, cell.row)
            if self.map.get(key) is None:
                self.map[key] = wc
            else:
                wc.add_wire(wire)

        return None

    
    def _check_cross(self, cell, new_wire, existing_wc):
        """Проверяет совместимость двух проводов в клетке.

        Разрешено: обе сети транзитом, ориентации перпендикулярны.
        Запрещено: endpoint у любой из сетей; параллельные ориентации;
                диагональ.
        """
        #from constants import WireOrientation
        #from router_impl.router_rules import orientations_at, is_endpoint_at

        new_orients = _orientations_at(new_wire, cell)
        new_endpoint = _is_endpoint_at(new_wire, cell)

        for old in existing_wc.wires:
            old_orients = _orientations_at(old, cell)
            old_endpoint = _is_endpoint_at(old, cell)

            if new_endpoint or old_endpoint:
                return False, f"endpoint with {old.net_name}"
            if WireOrientation.DIAGONAL in new_orients \
                    or WireOrientation.DIAGONAL in old_orients:
                return False, f"diagonal with {old.net_name}"

            for no in new_orients:
                for oo in old_orients:
                    if no == oo:
                        return False, f"parallel {no.value} with {old.net_name}"

        return True, None

    def _compatible_cross(new_orients, new_endpoint,
                      old_orients, old_endpoint) -> Optional[str]:
        if new_endpoint or old_endpoint:
            return "endpoint in shared cell"
        if WireOrientation.DIAGONAL in new_orients \
                or WireOrientation.DIAGONAL in old_orients:
            return "diagonal in shared cell"
        for no in new_orients:
            for oo in old_orients:
                if no == oo:
                    return f"parallel orientations {no}"
        return None

    # =========================================================
    # Метки fallback — пишутся в Sheet, не в Router
    # =========================================================

    def _pin_contact_mm(self, pin) -> Tuple[float, float]:
        """Точка контакта пина в мм (Y↓) для anchor'а fallback-метки.

        anchor_page_mm компонента + offset_mm пина (см. Pin.contact_mm).
        Если пин ещё не привязан к странице (anchor нет) — падаем на
        anchor компонента, чтобы метка всё равно встала.
        """
        mm = pin.contact_mm
        if mm is None:
            return pin.component.anchor_page_mm
        return mm

    def _mark_fallback(self, net_name: str, pin,
                       contact_mm: Tuple[float, float],
                       reason: str, on_wire: bool = False) -> None:
        """Ставит метку fallback.

        on_wire=False — метка на пине. Пин не подключён к сети проводом
            и связывается с ней по имени. Дедуп по local_key: у каждого
            пина своя метка.
        on_wire=True — метка на проводе сети (T-точка). Дедуп по net_name:
            на сеть достаточно одной такой метки.

        direction = pin.direction (без инверсии): anchor = contact_mm,
        текст рисуется против вектора направления, то есть наружу.
        """
        if on_wire:
            for lbl in self.sheet.labels:
                if lbl.net_name == net_name and lbl.on_wire:
                    log.debug("%s label_skipped net=%s already_on_wire",
                            ctx(page=self.page, net=net_name), net_name)
                    return
        else:
            for lbl in self.sheet.labels:
                if lbl.local_key == pin.local_key:
                    return

        self.sheet.labels.append(FallbackLabel(
            net_name=net_name,
            local_key=pin.local_key,
            contact_mm=contact_mm,
            direction=pin.direction,
            reason=reason,
            on_wire=on_wire,
        ))
        log.info("%s label net=%s reason=%s on_wire=%s "
                 "contact_mm=%s dir=%s",
                ctx(page=self.page, net=net_name,
                    comp=self._designator(pin),
                    pin=self._pin_num(pin)),
                net_name, reason, on_wire, contact_mm, pin.direction)