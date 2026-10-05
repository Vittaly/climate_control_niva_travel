# make_scr/writer.py
"""Запись .kicad_sch: одну страницу (для routes.txt) или всё дерево.

Публичные точки входа:
    Writer(sheet).write_text()
        — текстовая сводка по одной странице (routes.txt).

    Writer().write_project(...)
        — записать все .kicad_sch одного дерева от указанного корня.

Модель иерархии:
    Writer получает корневой Sheet и обходит дерево вниз через
    components: для каждого SheetRefComponent берёт его child_sheet
    и рекурсивно пишет. Каждый файл пишется ровно один раз (кэш по
    sheet.out_file).

    Все instance-данные уже посчитаны при загрузке:
      * Sheet.uuid                      — uuid файла;
      * SheetRefComponent.uuid          — uuid X_* в родителе;
      * SheetRefComponent.child_instance — SheetInstance ребёнка
                                           (page, path, uuid);
      * Component.instances             — List[SheetInstance], в которых
                                           компонент присутствует.

    Writer ничего не пересчитывает — читает готовое.

Корни:
    Writer используется Project.save для записи ВСЕХ корней проекта
    (главный + standalone) в один прогон. Метод write_project
    вызывается по одному разу на каждый корень, но состояние
    (в первую очередь _written) между вызовами НЕ сбрасывается:
    файл, попавший в два обхода, пишется один раз. Для нового
    прогона создаётся новый Writer() — тогда кеш пуст с самого
    начала.

    Для каждого вызова _root_sheet переустанавливается на текущий
    корень. Он нужен _out_name_for (имя файла корня) и
    _apply_instances (синтетический instance path для символов
    корня).

Мульти-инстанс:
    Один .kicad_sch может быть инстанцирован несколько раз
    (actuator_channel × 4). Файл пишется ОДИН раз. В каждом символе
    пишется N instance-блоков, по одному на SheetInstance листа.
    Writer берёт их из Component.instances.

Frame vs bbox:
    У каждого Component есть frame_size и frame_offset_mm.
    У обычного символа frame == bbox, frame_offset == (0, 0).
    У SheetRef frame = bbox - 2 клетки, frame_offset = (grid, grid).

Позиционирование:
    Component хранит anchor_page_mm (ЛВ-угол bbox).
    Writer:
      * для символа — sch.components.add(position=anchor_page_mm);
      * для sheet  — sch.add_sheet(position=anchor+frame_offset,
                                   size=(frame-1)*grid).

SPICE-привязка:
    Каждый обычный символ несёт Component.simProperties — пары
    "Sim.Xxx" → "value", собранные в Component.from_yaml из
    component_types[type].spice. Writer проецирует их в .kicad_sch
    как properties символа (set_property в цикле по парам). В этой
    версии kicad_sch_api метод add_properties отсутствует, а
    set_property пишет напрямую в _data.properties инстанса —
    именно то поле, которое сериализуется в (property "…").
    kicad-cli выгружает их в нетлист, откуда их читает
    kicad_to_spice.py.

Sheet-pin и имя сети на родителе:
    sheet-pin получает имя pin.identifier. Локальные метки имён
    КОРНЕВЫХ сетей у пинов X_* — теперь самостоятельные
    LabelComponent в sheet.labels (reason=SHEET_PIN_NAME), создаются
    в Sheet.create_sheet_pin_labels() после роутинга. Writer их
    просто читает в блоке 5, как любые другие метки, и НЕ создаёт
    их сам в _add_sheet_pins.

Логирование:
    Все лог-строки — одна строка, префикс ctx():
        [page] [net] [comp] [pin]
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

from cell import Cell
from constants import Axis, ComponentKind, Direction
from logging_setup import get_logger, ctx
from refdes import make_refdes

import re

if TYPE_CHECKING:
    from sheet import Sheet
    from sheet_instance import SheetInstance
    from sheet_ref import SheetRefComponent

log = get_logger(__name__)


class Writer:
    """Пишет .kicad_sch: одну страницу (text) или дерево (project)."""

    def __init__(self, sheet: Optional["Sheet"] = None):
        # Для write_text (routes.txt) — конструктор с одной страницей.
        # Для write_project — sheet приходит в _visit и переустанавливается.
        self.sheet = sheet
        if sheet is not None:
            self.cell_size_mm = sheet.grid_mm
            self.netlist = sheet.netlist
        else:
            self.cell_size_mm = 1.27
            self.netlist = None

        # Состояние обхода (актуально после write_project).
        # _written НЕ сбрасывается между вызовами write_project:
        # Project.save использует один Writer для всех корней,
        # чтобы файлы, попавшие в два обхода, писались один раз.
        self._written: Set[str] = set()
        self._out_dir: Optional[Path] = None
        self._root_sheet: Optional["Sheet"] = None
        self._root_file_name: str = ""
        self._project_name: str = "project"

    # =========================================================
    # Координаты
    # =========================================================

    def cell_to_mm(self, cell: Cell) -> tuple[float, float]:
        return (cell.col * self.cell_size_mm,
                cell.row * self.cell_size_mm)

    @staticmethod
    def _label_angle(direction: Direction) -> int:
        return {
            Direction.LEFT:    0,
            Direction.RIGHT: 180,
            Direction.DOWN:   90,
            Direction.UP:    270,
        }[direction]

    # =========================================================
    # Текстовая сводка (routes.txt)
    # =========================================================

    def write_text(self) -> str:
        if self.sheet is None:
            return ""
        lines = [
            f"# sheet={self.sheet.page}",
            f"# cell_size_mm={self.cell_size_mm}",
            f"# components={len(self.sheet.components)}",
            f"# labels={len(self.sheet.labels)}",
            f"# junctions={len(self.sheet.junctions)}",
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
    # Контекст логов
    # =========================================================

    @staticmethod
    def _designator(pin) -> str:
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
        return ctx(page=label, net=net_name,
                   comp=self._designator(pin),
                   pin=self._pin_num(pin))

    # =========================================================
    # Публичный вход
    # =========================================================

    def write_project(
        self,
        out_dir: Path,
        *,
        root_sheet: "Sheet",
        root_file_name: str,
        project_name: str,
    ) -> None:
        """Записать дерево .kicad_sch от указанного корня.

        Вызывается Project.save для каждого корня проекта (главного
        и standalone). Кеш _written НЕ сбрасывается между вызовами:
        если файл уже писался в предыдущем вызове (например, один
        Sheet в двух деревьях), второй раз не пишется.

        _root_sheet переустанавливается на текущий корень: он нужен
        _out_name_for (имя файла корня) и _apply_instances
        (синтетический instance path для символов корня). Для
        standalone-корня это сам standalone, а не главный корень.

        Для нового прогона создаётся новый Writer() — тогда кеш
        пуст с самого начала.

        Args:
            out_dir:         каталог для сохранения.
            root_sheet:      корень текущего обхода.
            root_file_name:  имя .kicad_sch корня.
            project_name:    имя проекта KiCad.

        Instance-данные уже готовы к моменту вызова: sheet.instances,
        comp.instances заполнены при загрузке через SheetRefComponent
        и Sheet.register_instance.
        """
        self._out_dir = Path(out_dir)
        self._out_dir.mkdir(parents=True, exist_ok=True)

        # Переустанавливаем корень и параметры текущего вызова.
        # _written СОХРАНЯЕТСЯ: см. докстринг выше.
        self._root_sheet = root_sheet
        self._root_file_name = root_file_name
        self._project_name = project_name

        self._visit(root_sheet)

    def reset(self) -> None:
        """Сбросить состояние обхода.

        Нужен, если Writer переиспользуется в новом прогоне.
        Project.save создаёт новый Writer() на каждый save(), так
        что явный reset обычно не требуется — метод оставлен для
        случаев прямого использования Writer вне Project.
        """
        self._written.clear()
        self._root_sheet = None
        self._root_file_name = ""
        self._project_name = "project"

    @property
    def written(self) -> Set[str]:
        """Множество уже записанных out_file — для повторных вызовов."""
        return self._written

    # =========================================================
    # Обход дерева
    # =========================================================

    def _visit(self, sheet: "Sheet") -> None:
        """Записать одну страницу и рекурсивно все её X_*."""
        file_key = sheet.out_file
        if file_key in self._written:
            return
        self._written.add(file_key)

        self.sheet = sheet
        self.cell_size_mm = sheet.grid_mm
        self.netlist = sheet.netlist

        self._write_one(sheet)

        # Рекурсия в дочерние Sheet через SheetRefComponent.child_sheet.
        for comp in sheet.components.values():
            if getattr(comp, "kind", None) != ComponentKind.SHEET_REF:
                continue
            child = comp.child_sheet
            if child is None:
                log.warning(
                    "%s child_sheet missing for %s — skip",
                    ctx(page=sheet.page, comp=comp.designator),
                    comp.designator,
                )
                continue
            self._visit(child)

    # =========================================================
    # Запись одной страницы
    # =========================================================

    def _write_one(self, sheet: "Sheet") -> None:
        """Сохранить .kicad_sch одной страницы."""
        label = sheet.page
        out_path = self._out_dir / self._out_name_for(sheet)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import kicad_sch_api as ksa
        except ImportError:
            log.warning("%s kicad_sch_api unavailable text_fallback",
                        ctx(page=label))
            self._write_text_fallback(out_path)
            return

        sch = ksa.create_schematic(self._project_name)

        # UUID файла должен совпадать с тем, что используется в instance
        # paths (Sheet.uuid). ksa.create_schematic генерирует свой случайный
        # UUID, потому что convenience-функция не пробрасывает параметр
        # uuid в Schematic.create. Перезаписываем его вручную — иначе
        # kicad-cli не находит instance paths по нашим (instances ...)-блокам
        # и подставляет top-level Reference всем инстансам сразу.
        sch._data["uuid"] = sheet.uuid

        placed = 0
        n_sheets = 0
        n_sheet_pins = 0

        # ---------- 1. Компоненты, порты, листы ----------
        sheet_refs_to_place = []
        for designator, comp in sheet.components.items():
            kind = getattr(comp, "kind", None)

            # Метки — не компоненты: они живут в sheet.labels и
            # пишутся в блоке 5. Если по какой-то причине метка
            # оказалась в components — пропускаем, чтобы не писать
            # её как обычный символ.
            if kind == ComponentKind.LABEL:
                log.warning(
                    "%s label_in_components des=%s — skip",
                    ctx(page=label, comp=designator), designator,
                )
                continue

            anchor_mm = comp.anchor_page_mm
            if anchor_mm is None:
                log.warning("%s no_anchor skip_write",
                            ctx(page=label, comp=designator))
                continue
            x_mm, y_mm = anchor_mm

            # --- Порт ---
            if kind == ComponentKind.PORT:
                if not comp.pins:
                    log.warning("%s port_no_pins",
                                ctx(page=label, net=comp.net_name,
                                    comp=comp.designator))
                    continue
                pin = comp.pins[0]
                px, py = comp.abs_pin_mm(pin)
                rotation = 180 if comp.side == "left" else 0
                try:
                    sch.add_hierarchical_label(
                        text=comp.net_name,
                        shape=comp.shape,
                        position=(px, py),
                        rotation=rotation,
                    )
                    log.info(
                        "%s write_hier_label net=%s pin_mm=(%.2f,%.2f) "
                        "anchor_mm=(%.2f,%.2f) rotation=%d shape=%s",
                        ctx(page=label, net=comp.net_name,
                            comp=comp.designator),
                        comp.net_name, px, py,
                        x_mm, y_mm, rotation, comp.shape,
                    )
                    placed += 1
                except Exception as e:
                    log.warning("%s port error=%s",
                                ctx(page=label, net=comp.net_name,
                                    comp=comp.designator), e)
                continue

            # --- Ссылка на лист ---
            if kind == ComponentKind.SHEET_REF:
                sheet_refs_to_place.append((designator, comp, anchor_mm))
                continue

            # --- Обычный компонент (kind == SYMBOL или None) ---
            lib_id = comp.lib_id or self._guess_lib_id(designator, comp)
            rotation = comp.rotation
            try:
                kicad_comp = sch.components.add(
                    lib_id,
                    reference=comp.designator,
                    value=comp.name,
                    position=(x_mm, y_mm),
                    rotation=rotation,
                    mirror=comp.mirror,
                )
                # SPICE-привязка: simProperties записываем как
                # properties символа. В этой версии kicad_sch_api
                # метода add_properties нет, а set_property пишет
                # напрямую в _data.properties инстанса — это то же
                # поле, куда сам kicad_sch_api кладёт Reference и
                # Value, и оно сериализуется в (property "…").
                # kicad-cli потом выгружает эти properties в нетлист.
                sim_props = getattr(comp, "simProperties", None) or {}
                if sim_props:
                    try:
                        for pname, pval in sim_props.items():
                            kicad_comp.set_property(pname, pval)
                    except Exception as e:
                        log.warning(
                            "%s sim_props des=%s error=%s",
                            ctx(page=label, comp=designator),
                            designator, e,
                        )
                log.info(
                    "%s write_symbol lib_id=%s anchor_mm=(%.2f,%.2f) "
                    "rotation=%d mirror=%s bbox_size=%dx%d cells "
                    "sim_props=%d",
                    ctx(page=label, comp=designator),
                    lib_id, x_mm, y_mm, rotation, comp.mirror,
                    comp.bbox_cols, comp.bbox_rows,
                    len(sim_props),
                )
                placed += 1
            except Exception as e:
                log.warning("%s add_component error=%s",
                            ctx(page=label, comp=designator), e)

        # ---------- 2. Вложенные листы ----------
        for designator, comp, anchor_mm in sheet_refs_to_place:
            fc, fr = comp.frame_size
            ox, oy = comp.frame_offset_mm

            x_mm = anchor_mm[Axis.X] + ox
            y_mm = anchor_mm[Axis.Y] + oy

            w_mm = (fc - 1) * self.cell_size_mm
            h_mm = (fr - 1) * self.cell_size_mm

            filename = Path(comp.sheet_file).with_suffix(".kicad_sch").name

            # page и uuid — из SheetInstance ребёнка (child_instance),
            # созданного конструктором SheetRefComponent.
            page_num = str(comp.child_page) if comp.child_page is not None else ""
            sheet_uuid = comp.uuid

            try:
                sobj = sch.add_sheet(
                    project_name=self._project_name,
                    name=comp.sheet_name or designator,
                    filename=filename,
                    position=(x_mm, y_mm),
                    size=(w_mm, h_mm),
                    page_number=page_num,
                    uuid=sheet_uuid,
                )
                log.info(
                    "%s write_sheet name=%s file=%s uuid=%s "
                    "page=%s frame_at_mm=(%.2f,%.2f) "
                    "frame_size_mm=(%.2f,%.2f) "
                    "frame=%dx%d bbox=%dx%d cells",
                    ctx(page=label, comp=designator),
                    comp.sheet_name, filename, sheet_uuid, page_num,
                    x_mm, y_mm, w_mm, h_mm,
                    fc, fr, comp.bbox_cols, comp.bbox_rows,
                )
                n_sheets += 1
            except Exception as e:
                log.error("%s add_sheet error=%s",
                          ctx(page=label, comp=designator), e)
                continue

            n_sheet_pins += self._add_sheet_pins(
                sch, sobj, comp, x_mm, y_mm, w_mm, h_mm, label)

        # ---------- 3. Провода ----------
        n_wires = self._emit_all_wires(sch, label)

        # ---------- 4. T-врезки ----------
        n_junctions = 0
        for j in getattr(sheet, "junctions", []) or []:
            try:
                sch.junctions.add(
                    position=j.anchor_mm,
                    diameter=j.diameter,
                    color=j.color,
                    uuid=j.uuid,
                )
                log.info(
                    "%s write_junction net=%s reason=%s mm=(%.2f,%.2f)",
                    ctx(page=label, net=j.net_name),
                    j.net_name, j.reason,
                    j.anchor_x, j.anchor_y,
                )
                n_junctions += 1
            except Exception as e:
                log.warning(
                    "%s junction net=%s mm=(%.2f,%.2f) error=%s",
                    ctx(page=label, net=j.net_name),
                    j.anchor_x, j.anchor_y, e,
                )

        # ---------- 5. Метки сети ----------
        # LabelComponent: имя = net.name, точка = anchor_page_mm,
        # направление = direction, происхождение = reason.
        # Сюда попадают все метки страницы: SHEET_PIN_NAME (созданы
        # в Sheet.create_sheet_pin_labels после роутинга),
        # INTERNAL_NET_NAME и FALLBACK (созданы роутером), USER
        # (если когда-нибудь появятся).
        n_labels = 0
        for lbl in getattr(sheet, "labels", []) or []:
            x_mm, y_mm = lbl.anchor_page_mm
            rotation = float(self._label_angle(lbl.direction))
            justify = "right" if rotation == 180.0 else "left"
            try:
                sch.add_label(
                    lbl.name, (x_mm, y_mm),
                    rotation=rotation,
                    effects={"justify": justify},
                )
                log.info(
                    "%s write_label net=%s reason=%s "
                    "anchor_mm=(%.2f,%.2f) dir=%s rotation=%.0f "
                    "justify=%s",
                    ctx(page=label, net=lbl.name),
                    lbl.name, lbl.reason.value,
                    x_mm, y_mm, lbl.direction, rotation, justify,
                )
                n_labels += 1
            except Exception as e:
                log.warning(
                    "%s label net=%s reason=%s error=%s",
                    ctx(page=label, net=lbl.name),
                    lbl.name, lbl.reason.value, e,
                )

        # ---------- 6. instances per symbol ----------
        # Читает готовое: comp.instances — список SheetInstance,
        # в которых компонент присутствует. Проектный refdes
        # вычисляется как make_refdes(designator, inst.page);
        # path берётся у SheetInstance.
        self._apply_instances(sch, sheet)

        # ---------- 7. Сохранить ----------
        try:
            sch.save(str(out_path))
            self._fix_hierarchical_label_shapes(out_path, sheet)
            log.info(
                "%s saved file=%s components=%d sheets=%d "
                "sheet_pins=%d wires=%d junctions=%d labels=%d",
                ctx(page=label),
                out_path.name, placed, n_sheets,
                n_sheet_pins, n_wires, n_junctions, n_labels,
            )
        except Exception as e:
            log.error("%s save_failed file=%s error=%s",
                      ctx(page=label), out_path.name, e)

    # =========================================================
    # instances per symbol
    # =========================================================

    def _apply_instances(self, sch, sheet: "Sheet") -> None:
        """Проставить каждому символу блок (instances ...).

        Для символов с instances (все дочерние листы) — по одному
        SymbolInstance на каждый SheetInstance в comp.instances.
        Refdes — make_refdes(designator, inst.page); path — inst.path.

        Для символов корня (instances пуст) — один синтетический блок
        с path=f"/{root.uuid}" и reference=designator.
        """
        try:
            from kicad_sch_api.core.types import SymbolInstance
        except Exception as e:
            log.error(
                "%s _apply_instances: SymbolInstance недоступен: %s",
                ctx(page=sheet.page), e,
            )
            return

        by_designator: Dict[str, Any] = {
            c.designator: c
            for c in sheet.components.values()
            if getattr(c, "kind", None) not in (
                ComponentKind.SHEET_REF,
                ComponentKind.PORT,
                ComponentKind.LABEL,
            )
        }

        # _root_sheet установлен в write_project на текущий корень:
        # для главного дерева это главный Sheet, для standalone —
        # сам standalone. Именно его uuid идёт в синтетический
        # instance path символов корня.
        root_uuid = self._root_sheet.uuid

        n_sym = 0
        for kicad_comp in sch.components:
            our = by_designator.get(kicad_comp.reference)
            if our is None:
                continue

            if our.instances:
                inst_list = [
                    SymbolInstance(
                        path=inst.path,
                        reference=make_refdes(our.designator, inst.page),
                        unit=1,
                        project=self._project_name,
                    )
                    for inst in our.instances
                ]
            elif sheet is self._root_sheet:
                inst_list = [SymbolInstance(
                    path=f"/{root_uuid}",
                    reference=our.designator,
                    unit=1,
                    project=self._project_name,
                )]
            else:
                log.warning(
                    "%s symbol %s: no instances and not root — "
                    "no (instances ...) block written",
                    ctx(page=sheet.page, comp=our.designator),
                    our.designator,
                )
                continue

            kicad_comp._data.instances = inst_list
            n_sym += 1

        log.info(
            "%s apply_instances symbols=%d",
            ctx(page=sheet.page), n_sym,
        )

    # =========================================================
    # Sheet pins для SheetRefComponent
    # =========================================================

    def _add_sheet_pins(self, sch, sobj, comp,
                        x_mm: float, y_mm: float,
                        w_mm: float, h_mm: float,
                        label: str) -> int:
        """Добавляет sheet_pin'ы X_*-компоненту.

        Пины сидят на кромке frame; их абсолютные координаты берём
        из comp.abs_pin_mm(pin).

        Локальные метки имён корневых сетей у этих пинов Writer
        здесь больше НЕ создаёт — они теперь самостоятельные
        LabelComponent в sheet.labels (reason=SHEET_PIN_NAME),
        создаются в Sheet.create_sheet_pin_labels() и пишутся
        общим блоком 5 в _write_one.
        """
        uid = comp.uuid
        if not uid:
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
            net_pin = pin.identifier
            if not net_pin:
                continue
            net_root = getattr(pin, "net_name", None) or net_pin

            pin_x_mm, pin_y_mm = comp.abs_pin_mm(pin)

            if abs(pin_x_mm - x_mm) < grid_mm / 2:
                side = "left"
            elif abs(pin_x_mm - (x_mm + w_mm)) < grid_mm / 2:
                side = "right"
            else:
                log.error(
                    "%s sheet_pin_off_frame pin=%s pin_x_mm=%.3f "
                    "frame_x=[%.3f..%.3f]",
                    ctx(page=label, comp=comp.designator,
                        pin=pin.local_key),
                    pin.local_key, pin_x_mm,
                    x_mm, x_mm + w_mm,
                )
                continue

            port = next(
                (p for p in getattr(comp, "ports", [])
                 if p.get("net_label") == net_pin),
                None,
            )
            if port is None:
                log.error(
                    "%s sheet_pin_port_missing sheet=%s pin=%s net_pin=%s",
                    ctx(page=label, comp=comp.designator,
                        pin=pin.local_key),
                    comp.sheet_name, comp.designator, net_pin,
                )
                continue
            shape = port["shape"]

            if pin_y_mm > y_mm + h_mm + grid_mm / 2:
                log.warning("%s sheet_pin pin=%s overflow_bottom",
                            ctx(page=label, comp=comp.designator,
                                pin=pin.local_key))
                continue
            if pin_y_mm < y_mm - grid_mm / 2:
                log.warning("%s sheet_pin pin=%s overflow_top",
                            ctx(page=label, comp=comp.designator,
                                pin=pin.local_key))
                continue

            if side == "left":
                offset = (y_mm + h_mm) - pin_y_mm
            else:
                offset = pin_y_mm - y_mm

            try:
                fn(uid, net_pin, shape, side, offset)
                log.info(
                    "%s write_sheet_pin pin=%s net_pin=%s net_root=%s "
                    "side=%s offset_mm=%.2f shape=%s pin_mm=(%.2f,%.2f)",
                    ctx(page=label, comp=comp.designator,
                        pin=pin.local_key),
                    pin.local_key, net_pin, net_root,
                    side, offset, shape,
                    pin_x_mm, pin_y_mm,
                )
                n_added += 1
            except Exception as e:
                log.warning("%s sheet_pin pin=%s error=%s",
                            ctx(page=label, comp=comp.designator,
                                pin=pin.local_key), e)
                continue

        return n_added

    # =========================================================
    # Провода
    # =========================================================

    def _emit_all_wires(self, sch, label: str) -> int:
        total = 0
        for net_name, net in self.netlist.nets.items():
            for wire in getattr(net, "wires", []) or []:
                if not self._wire_belongs_to(wire):
                    continue
                total += self._emit_wire(sch, wire, label, net_name)
        return total

    def _wire_belongs_to(self, wire) -> bool:
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
        n = 0
        is_t = bool(getattr(wire, "t_junction", False))
        has_end = wire.end is not None and not is_t

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

        path_segments = self._collect_path_segments(wire)

        for (a, b, _ca, _cb) in path_segments:
            try:
                sch.add_wire(a, b)
                n += 1
            except Exception as e:
                log.warning("%s add_wire a=%s b=%s error=%s",
                            self._ctx(label, net_name, wire.start),
                            a, b, e)

        if path_segments:
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
        out = []
        for seg in wire.segments():
            a = self.cell_to_mm(seg.start)
            b = self.cell_to_mm(seg.end)
            if abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9:
                continue
            out.append((a, b, seg.start, seg.end))
        return out

    # =========================================================
    # Вспомогательное
    # =========================================================

    def _out_name_for(self, sheet: "Sheet") -> str:
        """Имя выходного .kicad_sch для страницы.

        Для корня текущего вызова — root_file_name (может отличаться
        от <stem>.kicad_sch, если так задано в YAML для главного
        корня). Для остальных страниц — sheet.out_file.

        _root_sheet установлен в write_project на текущий корень:
        при обходе главного дерева это главный Sheet, при обходе
        standalone — сам standalone. Соответственно у standalone
        корневая страница получает root_file_name = sheet.out_file
        (то есть <stem>.kicad_sch), что совпадает с ожидаемым именем.
        """
        if sheet is self._root_sheet:
            return self._root_file_name
        return sheet.out_file

    @staticmethod
    def _sheet_uuid_of(sobj) -> Optional[str]:
        if sobj is None:
            return None
        if isinstance(sobj, str):
            return sobj
        for attr in ("uuid", "sheet_uuid", "id"):
            val = getattr(sobj, attr, None)
            if not val:
                continue
            s = str(val)
            if len(s) >= 32 and "-" in s:
                return s
        return None

    @staticmethod
    def _guess_lib_id(designator: str, comp) -> str:
        r = str(designator)
        if r.startswith("LED"): return "Device:LED"
        if r.startswith("R"):   return "Device:R"
        if r.startswith("C"):   return "Device:C"
        if r.startswith("L"):   return "Device:L"
        if r.startswith("D"):   return "Device:D"
        if r.startswith("Q"):   return "Device:Q_NMOS_GSD"
        if r.startswith(("J", "P")): return "Connector_Generic:Conn_01x02"
        return "Device:R"

    def _write_text_fallback(self, out_path: Path) -> None:
        txt = out_path.with_suffix(".txt")
        txt.write_text(self.write_text(), encoding="utf-8")
        log.info("%s text_fallback file=%s",
                 ctx(page=self.sheet.page), txt.name)

    def _fix_hierarchical_label_shapes(
        self, out_path: Path, sheet: "Sheet",
    ) -> None:
        """Обход бага kicad_sch_api: add_hierarchical_label игнорирует shape.

        После save читаем .kicad_sch и проставляем shape у тех
        hierarchical_label, чьи net_name совпадают с именами портов
        текущей страницы.
        """
        wanted: dict[str, str] = {}
        for comp in sheet.components.values():
            if getattr(comp, "kind", None) == ComponentKind.PORT:
                wanted[comp.net_name] = comp.shape

        if not wanted:
            return

        try:
            text = out_path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning(
                "%s hier_label_fix read_failed file=%s error=%s",
                ctx(page=sheet.page), out_path.name, e,
            )
            return

        original = text
        fixed = 0

        for name, shape in wanted.items():
            pattern = re.compile(
                r'(\(hierarchical_label\s+"'
                + re.escape(name)
                + r'"\s*\(shape\s+)\w+(\))'
            )

            def _repl(m: "re.Match", _shape=shape) -> str:
                return m.group(1) + _shape + m.group(2)

            text, n = pattern.subn(_repl, text)
            fixed += n

        if text == original:
            return

        try:
            out_path.write_text(text, encoding="utf-8")
        except OSError as e:
            log.error(
                "%s hier_label_fix write_failed file=%s error=%s",
                ctx(page=sheet.page), out_path.name, e,
            )
            return

        log.info(
            "%s hier_label_shapes_fixed file=%s count=%d",
            ctx(page=sheet.page), out_path.name, fixed,
        )