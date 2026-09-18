# make_scr/writer.py
"""Сохранение проекта: .kicad_sch для каждой страницы.

Writer привязан к одной Sheet — как Placer и Router:
    - Writer(sheet)   — конструктор;
    - self.cell_size_mm = sheet.grid_mm;
    - self.netlist      = sheet.netlist;
    - write_sheet(out_path) — пишет .kicad_sch этой страницы.

Провода берутся из self.netlist (Net.wires), фильтруются по странице
через pin.component.sheet is self.sheet.

Порты страницы (PortComponent) рисуются как hierarchical_label.
Вложенные листы (SheetRefComponent) — через add_sheet + sheet_pin.
T-врезки пишутся через sch.junctions.add.
Метки-заглушки — через sch.add_label.

Позиционирование:
    Компонент хранит anchor_page_mm (точку якоря на странице, мм).
    Writer передаёт её в (at x y angle) для symbol и использует
    для листов/портов.
    Никаких placer.positions — они временные.

Логирование:
    Все лог-строки — одна строка, префикс ctx():
        [page] [net] [comp] [pin]
    Пропущенное поле в середине — [-], хвостовые — опускаются.
"""
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from cell import Cell
from constants import Axis
from logging_setup import get_logger, ctx

if TYPE_CHECKING:
    from sheet import Sheet

log = get_logger(__name__)


class Writer:
    """Пишет .kicad_sch и текстовый отчёт для одной страницы."""

    def __init__(self, sheet: "Sheet"):
        """Sheet — страница; сетка и нетлист берутся из неё."""
        self.sheet = sheet
        self.cell_size_mm = sheet.grid_mm
        self.netlist = sheet.netlist

    # =========================================================
    # Координаты
    # =========================================================

    def cell_to_mm(self, cell: Cell) -> tuple[float, float]:
        """Переводит координаты клетки в мм от начала листа.

        Используется для T-врезок и меток — там клетки.
        Для компонентов используется anchor_page_mm (уже в мм).
        """
        return (cell.col * self.cell_size_mm,
                cell.row * self.cell_size_mm)

    def write_text(self) -> str:
        """Текстовая сводка по странице (для routes.txt / отладки)."""
        lines = [
            f"# sheet={self.sheet.page}",
            f"# cell_size_mm={self.cell_size_mm}",
            f"# components={len(self.sheet.components)}",
            f"# labels={len(self.sheet.labels)}",
            f"# t_junctions={len(self.sheet.t_junctions)}",
        ]
        for designator, comp in self.sheet.components.items():
            anchor = comp.anchor_page_mm
            if anchor is None:
                lines.append(f"{designator}: {comp.name} no_anchor")
                continue
            lines.append(
                f"{designator}: {comp.name} "
                f"anchor_mm=({anchor[Axis.X]:.2f},{anchor[Axis.Y]:.2f}) "
                f"{comp.bbox_cols}x{comp.bbox_rows} cells "
                f"rot={comp.rotation} mirror={comp.mirror}"
            )
        return "\n".join(lines)

    # =========================================================
    # Контекст для логов: [page] [net] [comp] [pin]
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

    def _ctx(self, label: str, net_name: str, pin) -> str:
        """ctx(page, net, comp, pin) для логов writer'а."""
        return ctx(page=label, net=net_name,
                   comp=self._designator(pin),
                   pin=self._pin_num(pin))

    # =========================================================
    # Главная точка входа
    # =========================================================

    def write_sheet(self, out_path: Path) -> None:
        """Сохраняет .kicad_sch для этой страницы."""
        sheet = self.sheet
        label = sheet.page
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # пробуем KiCad API
        try:
            import kicad_sch_api as ksa
        except ImportError:
            log.warning("%s kicad_sch_api unavailable text_fallback",
                        ctx(page=label))
            self._write_text_fallback(out_path)
            return

        sch = ksa.create_schematic()
        placed = 0
        n_sheets = 0
        n_sheet_pins = 0

        # ---------- 1. Компоненты, порты, листы ----------
        sheet_refs_to_place = []
        for designator, comp in sheet.components.items():
            anchor_mm = comp.anchor_page_mm
            if anchor_mm is None:
                log.warning("%s no_anchor skip_write",
                            ctx(page=label, comp=designator))
                continue
            x_mm, y_mm = anchor_mm

            # --- Порт: hierarchical_label ---
            if getattr(comp, "is_port", False):
                rotation = 180 if comp.side == "left" else 0
                try:
                    sch.add_hierarchical_label(
                        text=comp.net_name,
                        shape=comp.shape,
                        position=(x_mm, y_mm),
                        rotation=rotation,
                    )
                    log.info(
                        "%s write_hier_label net=%s anchor_mm=(%.2f,%.2f) "
                        "rotation=%d shape=%s",
                        ctx(page=label, net=comp.net_name,
                            comp=comp.designator),
                        comp.net_name, x_mm, y_mm, rotation, comp.shape,
                    )
                    placed += 1
                except Exception as e:
                    log.warning("%s port error=%s",
                                ctx(page=label, net=comp.net_name,
                                    comp=comp.designator), e)
                continue

            # --- Ссылка на лист: отложим до отдельного прохода ---
            if getattr(comp, "is_sheet_ref", False):
                sheet_refs_to_place.append((designator, comp, anchor_mm))
                continue

            # --- Обычный компонент ---
            lib_id = comp.lib_id or self._guess_lib_id(designator, comp)
            rotation = comp.rotation
            try:
                sch.components.add(
                    lib_id,
                    reference=comp.designator,
                    value=comp.name,
                    position=(x_mm, y_mm),
                    rotation=rotation,
                    mirror=comp.mirror,
                )
                log.info(
                    "%s write_symbol lib_id=%s anchor_mm=(%.2f,%.2f) "
                    "rotation=%d mirror=%s bbox_size=%dx%d cells",
                    ctx(page=label, comp=designator),
                    lib_id, x_mm, y_mm, rotation, comp.mirror,
                    comp.bbox_cols, comp.bbox_rows,
                )
                placed += 1
            except Exception as e:
                log.warning("%s add_component error=%s",
                            ctx(page=label, comp=designator), e)

        # ---------- 2. Вложенные листы (SheetRefComponent) ----------
        for designator, comp, anchor_mm in sheet_refs_to_place:
            x_mm, y_mm = anchor_mm
            w_mm = comp.bbox_cols * self.cell_size_mm
            h_mm = comp.bbox_rows * self.cell_size_mm

            filename = Path(comp.sheet_file).with_suffix(".kicad_sch").name

            try:
                sobj = sch.add_sheet(
                    name=comp.sheet_name or designator,
                    filename=filename,
                    position=(x_mm, y_mm),
                    size=(w_mm, h_mm),
                )
                log.info(
                    "%s write_sheet name=%s file=%s anchor_mm=(%.2f,%.2f) "
                    "size_mm=(%.2f,%.2f) bbox_size=%dx%d cells",
                    ctx(page=label, comp=designator),
                    comp.sheet_name, filename,
                    x_mm, y_mm, w_mm, h_mm,
                    comp.bbox_cols, comp.bbox_rows,
                )
                n_sheets += 1
            except Exception as e:
                log.error("%s add_sheet error=%s",
                          ctx(page=label, comp=designator), e)
                continue

            # ---------- 3. Sheet pins для этого листа ----------
            n_sheet_pins += self._add_sheet_pins(
                sch, sobj, comp, x_mm, y_mm, w_mm, h_mm, label)

        # ---------- 4. Провода ----------
        n_wires = self._emit_all_wires(sch, label)

        # ---------- 5. T-врезки ----------
        n_junctions = 0
        for tj in getattr(sheet, "t_junctions", []) or []:
            x_mm, y_mm = self.cell_to_mm(tj.target)
            try:
                sch.junctions.add(position=(x_mm, y_mm))
                log.info(
                    "%s write_junction net=%s target_cell=(%d,%d) "
                    "target_mm=(%.2f,%.2f)",
                    ctx(page=label, net=tj.net_name),
                    tj.net_name, tj.target.col, tj.target.row,
                    x_mm, y_mm,
                )
                n_junctions += 1
            except Exception as e:
                log.warning("%s junction target=%s error=%s",
                            ctx(page=label, net=tj.net_name),
                            tj.target, e)

        # ---------- 6. Метки сети ----------
        n_labels = 0
        for lbl in getattr(sheet, "labels", []) or []:
            x_mm, y_mm = self.cell_to_mm(lbl.cell)
            try:
                sch.add_label(lbl.net_name, (x_mm, y_mm))
                log.info(
                    "%s write_label net=%s pin=%s cell=(%d,%d) mm=(%.2f,%.2f)",
                    ctx(page=label, net=lbl.net_name,
                        pin=lbl.local_key),
                    lbl.net_name, lbl.local_key,
                    lbl.cell.col, lbl.cell.row,
                    x_mm, y_mm,
                )
                n_labels += 1
            except Exception as e:
                log.warning("%s label pin=%s error=%s",
                            ctx(page=label, net=lbl.net_name,
                                pin=lbl.local_key), e)

        # ---------- 7. Сохранить ----------
        try:
            sch.save(str(out_path))
            log.info("%s saved file=%s components=%d sheets=%d "
                     "sheet_pins=%d wires=%d junctions=%d labels=%d",
                     ctx(page=label),
                     out_path.name, placed, n_sheets,
                     n_sheet_pins, n_wires, n_junctions, n_labels)
        except Exception as e:
            log.error("%s save_failed file=%s error=%s",
                      ctx(page=label), out_path.name, e)

    # =========================================================
    # Sheet pins для SheetRefComponent
    # =========================================================

    def _add_sheet_pins(self, sch, sobj, comp,
                        x_mm: float, y_mm: float,
                        w_mm: float, h_mm: float,
                        label: str) -> int:
        """Добавляет sheet_pin-ы по пинам SheetRefComponent.

        У SheetRefComponent по одному пину на каждый порт дочернего
        YAML. Пин задан offset_mm от anchor (= левый-верхний угол
        листа). Сторона определяется offset_x: 0 — left, иначе right.
        """
        uid = (getattr(sobj, "uuid", None)
               or getattr(sobj, "id", None))
        if uid is None and isinstance(sobj, str):
            uid = sobj
        if uid is None:
            log.warning("%s sheet_pin no_uuid",
                        ctx(page=label, comp=comp.designator))
            return 0

        grid_mm = self.cell_size_mm
        n_added = 0

        mgr = getattr(sch, "sheets", None)
        fn = None
        if mgr is not None and hasattr(mgr, "add_sheet_pin"):
            fn = mgr.add_sheet_pin
        elif hasattr(sch, "add_sheet_pin"):
            fn = sch.add_sheet_pin
        if fn is None:
            log.warning("%s sheet_pin no_api",
                        ctx(page=label, comp=comp.designator))
            return 0

        for pin in comp.pins:
            net = pin.name or pin.number
            if not net:
                continue

            # сторона: offset_x == 0 → left, иначе right
            side = "left" if pin.offset_mm[Axis.X] == 0.0 else "right"

            # тип: ищем по имени порта в comp.ports
            port = next(
                (p for p in getattr(comp, "ports", [])
                 if p.get("net_label") == net),
                {},
            )
            ptype = str(port.get("type", "INPUT")).upper()
            shape = ("passive" if ptype == "POWER"
                     else "output" if ptype == "OUTPUT"
                     else "input")

            # Y пина в мм от верхнего края листа
            pin_y_mm = y_mm + pin.offset_mm[Axis.Y]
            if pin_y_mm > y_mm + h_mm - grid_mm:
                log.warning("%s sheet_pin pin=%s overflow",
                            ctx(page=label, comp=comp.designator,
                                pin=pin.local_key))
                continue

            # offset: для left API считает от НИЖНЕГО угла,
            # для right — от ВЕРХНЕГО
            if side == "left":
                offset = (y_mm + h_mm) - pin_y_mm
            else:
                offset = pin_y_mm - y_mm

            try:
                fn(uid, net, shape, side, offset)
                log.info(
                    "%s write_sheet_pin pin=%s net=%s side=%s "
                    "offset_mm=%.2f shape=%s pin_mm=(%.2f,%.2f)",
                    ctx(page=label, comp=comp.designator,
                        pin=pin.local_key),
                    pin.local_key, net, side, offset, shape,
                    x_mm + pin.offset_mm[Axis.X], pin_y_mm,
                )
                n_added += 1
            except Exception as e:
                log.warning("%s sheet_pin pin=%s error=%s",
                            ctx(page=label, comp=comp.designator,
                                pin=pin.local_key), e)

        return n_added

    # =========================================================
    # Провода
    # =========================================================

    def _emit_all_wires(self, sch, label: str) -> int:
        """Пишет провода всех сетей, отфильтрованных по странице."""
        total = 0
        for net_name, net in self.netlist.nets.items():
            for wire in getattr(net, "wires", []) or []:
                if not self._wire_belongs_to(wire):
                    continue
                total += self._emit_wire(sch, wire, label, net_name)
        return total

    def _wire_belongs_to(self, wire) -> bool:
        """Провод относится к странице, если start/end пины — её."""
        for attr in ("start", "end"):
            pin = getattr(wire, attr, None)
            if pin is None:
                continue
            comp = getattr(pin, "component", None)
            if comp is None:
                continue
            if comp.sheet is self.sheet:
                return True
        return False

    def _emit_wire(self, sch, wire, label: str, net_name: str) -> int:
        """Разбивает Wire на ортогональные отрезки и пишет их.

        Пишет:
            1. start_stub: от pin_mm до tip_mm (в мм).
            2. path: клетки пути (в мм через cell_to_mm).
            3. end_stub: от tip_mm до pin_mm (в мм).

        Логирование:
            - start_stub — в контексте wire.start;
            - end_stub   — в контексте wire.end;
            - path       — дублируется в контексте обоих пинов
                           (если end есть и это не T-врезка).
            sch.add_wire для каждого сегмента вызывается ОДИН раз;
            дублируется только log.trace.

        Args:
            sch:      schematic API.
            wire:     Wire с path, start_stub, end_stub.
            label:    имя страницы для логов.
            net_name: имя сети для логов.
        """
        n = 0
        is_t = bool(getattr(wire, "t_junction", False))
        has_end = wire.end is not None and not is_t

        # --- 1. start_stub — контекст wire.start ---
        if wire.start_stub is not None:
            s = wire.start_stub
            if (abs(s.pin_mm[Axis.X] - s.tip_mm[Axis.X]) > 1e-9 or
                    abs(s.pin_mm[Axis.Y] - s.tip_mm[Axis.Y]) > 1e-9):
                try:
                    sch.add_wire(s.pin_mm, s.tip_mm)
                    log.trace(
                        "%s write_stub_in pin=%s "
                        "pin_mm=(%.2f,%.2f) tip_mm=(%.2f,%.2f)",
                        self._ctx(label, net_name, wire.start),
                        s.pin.local_key,
                        s.pin_mm[Axis.X], s.pin_mm[Axis.Y],
                        s.tip_mm[Axis.X], s.tip_mm[Axis.Y],
                    )
                    n += 1
                except Exception as e:
                    log.warning("%s add_stub_in error=%s",
                                self._ctx(label, net_name, wire.start), e)

        # --- 2. path — общая геометрия ---
        path_segments = self._collect_path_segments(wire)

        # 2a. добавляем в sch — один раз на сегмент
        for (a, b, _ca, _cb) in path_segments:
            try:
                sch.add_wire(a, b)
                n += 1
            except Exception as e:
                log.warning("%s add_wire a=%s b=%s error=%s",
                            self._ctx(label, net_name, wire.start),
                            a, b, e)

        # 2b. логируем — в контексте start и (если есть) end
        views = [wire.start]
        if has_end:
            views.append(wire.end)
        for view_pin in views:
            cctx = self._ctx(label, net_name, view_pin)
            for (a, b, ca, cb) in path_segments:
                log.trace(
                    "%s write_wire a_mm=(%.2f,%.2f) b_mm=(%.2f,%.2f) "
                    "a_cell=(%d,%d) b_cell=(%d,%d)",
                    cctx,
                    a[0], a[1], b[0], b[1],
                    ca.col, ca.row, cb.col, cb.row,
                )

        # --- 3. end_stub — контекст wire.end ---
        if wire.end_stub is not None and has_end:
            s = wire.end_stub
            if (abs(s.pin_mm[Axis.X] - s.tip_mm[Axis.X]) > 1e-9 or
                    abs(s.pin_mm[Axis.Y] - s.tip_mm[Axis.Y]) > 1e-9):
                try:
                    sch.add_wire(s.tip_mm, s.pin_mm)
                    log.trace(
                        "%s write_stub_out pin=%s "
                        "tip_mm=(%.2f,%.2f) pin_mm=(%.2f,%.2f)",
                        self._ctx(label, net_name, wire.end),
                        s.pin.local_key,
                        s.tip_mm[Axis.X], s.tip_mm[Axis.Y],
                        s.pin_mm[Axis.X], s.pin_mm[Axis.Y],
                    )
                    n += 1
                except Exception as e:
                    log.warning("%s add_stub_out error=%s",
                                self._ctx(label, net_name, wire.end), e)

        return n

    def _collect_path_segments(self, wire):
        """Возвращает список (a_mm, b_mm, a_cell, b_cell) для path.

        Пропускает нулевые отрезки (a == b). Используется и для
        sch.add_wire, и для log.trace — чтобы path считался один раз.
        """
        cells = list(wire.all_cells())
        out = []
        for i in range(len(cells) - 1):
            a = self.cell_to_mm(cells[i])
            b = self.cell_to_mm(cells[i + 1])
            if abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9:
                continue
            out.append((a, b, cells[i], cells[i + 1]))
        return out

    # =========================================================
    # Вспомогательное
    # =========================================================

    @staticmethod
    def _guess_lib_id(designator: str, comp) -> str:
        """Fallback lib_id, если у компонента пусто."""
        r = str(designator)
        if r.startswith("LED"): return "Device:LED"
        if r.startswith("R"):   return "Device:R"
        if r.startswith("C"):   return "Device:C"
        if r.startswith("L"):   return "Device:L"
        if r.startswith("D"):   return "Device:D"
        if r.startswith("Q"):   return "Device:Q_NMOS_GSD"
        if r.startswith(("J", "P")): return "Connector_Generic:Conn_01x02"
        return "Device:R"

    # =========================================================
    # Текстовый fallback
    # =========================================================

    def _write_text_fallback(self, out_path: Path) -> None:
        """Текстовый отчёт, если kicad_sch_api недоступен."""
        txt = out_path.with_suffix(".txt")
        txt.write_text(self.write_text(), encoding="utf-8")
        log.info("%s text_fallback file=%s",
                 ctx(page=self.sheet.page), txt.name)