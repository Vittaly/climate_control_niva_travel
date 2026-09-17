# router_impl/logging_.py
"""Миксин логирования механики роутера.

Все лог-строки — одна строка, префикс ctx():
    [page] [net] [comp] [pin]
Пропущенное поле в середине — [-], хвостовые — опускаются.

Для провода, соединяющего два пина, пишутся ДВЕ серии лог-строк:
от лица start-пина и от лица end-пина. Геометрия (route, wire
segments/cells) в обеих сериях одинаковая; stub_in — только в
серии start, stub_out — только в серии end.
"""
from logging_setup import ctx, get_logger
from stub import ANGLE_NAME

log = get_logger(__name__)


class RouterLogMixin:
    """Методы логирования для Router. Требует self.page."""

    # =========================================================
    # Полный маршрут провода
    # =========================================================

    def _log_wire_full(self, net_name: str, wire) -> None:
        """Логирует полный маршрут провода.

        Если провод соединяет два пина — пишет ДВЕ серии лог-строк:
        от лица start-пина и от лица end-пина. Геометрия (route,
        wire segments/cells) в обеих сериях одинаковая; stub_in —
        только в серии start, stub_out — только в серии end.

        Для T-врезки (end is None) — одна серия от start-пина.
        """
        segs = wire.segments()
        total_cells = len(wire.all_cells())
        is_t = bool(getattr(wire, "t_junction", False))

        # --- серия от start: свой stub_in + общая геометрия ---
        self._log_wire_view(
            net_name, wire,
            pin=wire.start,
            stub=wire.start_stub,
            stub_label="stub_in",
            segs=segs,
            total_cells=total_cells,
        )

        # --- серия от end: свой stub_out + та же геометрия ---
        if wire.end is not None and not is_t:
            self._log_wire_view(
                net_name, wire,
                pin=wire.end,
                stub=wire.end_stub,
                stub_label="stub_out",
                segs=segs,
                total_cells=total_cells,
            )

    def _log_wire_view(self, net_name: str, wire,
                       pin, stub, stub_label: str,
                       segs, total_cells: int) -> None:
        """Одна серия лог-строк про провод от лица одного пина.

        stub — только свой (start_stub в серии start,
        end_stub в серии end). route и wire — общая геометрия,
        дублируется в каждой серии.
        """
        cctx = ctx(page=self.page, net=net_name,
                   comp=self._designator(pin),
                   pin=self._pin_num(pin))

        # 1. stub — только свой
        if stub is not None and not stub.on_grid:
            log.info(
                "%s %s page=(%.2f,%.2f) dir=%s steps=%d "
                "tip=%s tip_page=(%.2f,%.2f)",
                cctx, stub_label,
                stub.pin_mm[0], stub.pin_mm[1],
                ANGLE_NAME[stub.direction], len(stub.cells),
                stub.tip, stub.tip_mm[0], stub.tip_mm[1],
            )

        # 2. route — общая геометрия, дублируется
        if segs:
            parts = [f"{ANGLE_NAME[s.angle]} ×{s.length}" for s in segs]
            log.info("%s route %s", cctx, ", ".join(parts))

        # 3. wire summary — общая геометрия, дублируется
        log.info("%s wire %s segments=%d cells=%d",
                 cctx, wire.key, len(segs), total_cells)

    # =========================================================
    # Частичные маршруты (для отладки провалов)
    # =========================================================

    def _log_route(self, net_name: str, attempt, pin=None) -> None:
        """Route: right ×5, up ×4, left ×2."""
        if not attempt.segments:
            return
        parts = [f"{ANGLE_NAME[s.angle]} ×{s.length}"
                 for s in attempt.segments]
        log.info("%s route %s",
                 ctx(page=self.page, net=net_name,
                     comp=self._designator(pin),
                     pin=self._pin_num(pin)),
                 ", ".join(parts))

    def _log_planned_partial(self, net_name: str,
                             attempt, pin=None) -> None:
        """Что успел найти поиск до стены."""
        cctx = ctx(page=self.page, net=net_name,
                   comp=self._designator(pin),
                   pin=self._pin_num(pin))
        if attempt.path and len(attempt.path) > 1:
            from wire import WireSegment, segment_angle
            segs = _segments_of_path(attempt.path)
            parts = [f"{ANGLE_NAME[s.angle]} ×{s.length}" for s in segs]
            log.warning("%s planned_route_partial %s",
                        cctx, ", ".join(parts))
        log.warning("%s visited=%d", cctx, attempt.visited)

    def _log_frontier(self, net_name: str, attempt) -> None:
        """Blocking frontier: box R3, wire SIG_CLK."""
        if not attempt.frontier:
            return
        log.warning("%s frontier count=%d",
                    ctx(page=self.page, net=net_name),
                    len(attempt.frontier))
        for item in sorted(attempt.frontier):
            log.trace("%s frontier_item=%s",
                      ctx(page=self.page, net=net_name), item)

    # =========================================================
    # Достать (designator, pin_number) из Pin
    # =========================================================

    @staticmethod
    def _designator(pin) -> str:
        """Designator компонента из Pin.

        Пробует pin.component.designator, иначе — split local_key.
        """
        if pin is None:
            return "-"
        comp = getattr(pin, "component", None)
        if comp is not None:
            des = getattr(comp, "designator", None)
            if des:
                return des
        key = getattr(pin, "local_key", None)
        if key and ":" in key:
            return key.split(":", 1)[0]
        return "-"

    @staticmethod
    def _pin_num(pin) -> str:
        """Номер/имя пина из Pin.

        Пробует pin.number, иначе — split local_key.
        """
        if pin is None:
            return "-"
        num = getattr(pin, "number", None)
        if num:
            return str(num)
        key = getattr(pin, "local_key", None)
        if key and ":" in key:
            return key.split(":", 1)[1]
        return key or "-"


# =========================================================
# Локальный хелпер для _log_planned_partial
# =========================================================

def _segments_of_path(path):
    """Разбивает путь на ортогональные сегменты (локальная копия)."""
    from wire import WireSegment, segment_angle
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