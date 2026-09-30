# make_scr/writer.py
"""Запись .kicad_sch: одну страницу (для routes.txt) или всё дерево.

Публичные точки входа:
    Writer(sheet).write_text()
        — текстовая сводка по одной странице (routes.txt).

    Writer().write_project(...)
        — записать все .kicad_sch проекта рекурсивно от root_sheet.

Модель иерархии:
    project.py отдаёт граф: {sheet_path: Sheet}, refdes_maps,
    project_name, out_dir, имя корневого файла. Writer сам:
      * обходит дерево от root_sheet;
      * генерирует uuid каждой страницы (через kicad-sch-api);
      * присваивает номера страниц (внутренний счётчик,
        корень = 1, дальше по DFS +1);
      * строит instance-пути (/<root_uuid>/<sheet_uuid>/...);
      * пишет каждый .kicad_sch ровно один раз.

    Всё, что относится к формату .kicad_sch — uuid, page,
    instance-пути — локальные переменные обхода. Project про них
    не знает.

Мульти-инстанс:
    Один .kicad_sch может быть инстанцирован несколько раз (пример —
    actuator_channel.kicad_sch × 4). Файл пишется ОДИН раз, но
    со всеми instance-описаниями в (instances ...) каждого символа.
    Порядок обхода гарантирует, что к моменту записи дочернего
    файла все его инстансы уже собраны: они приходят как список
    instances от родителя.

    Первый сегмент instance-пути — uuid корня, который
    kicad-sch-api присвоил корневому Schematic (sch.uuid). Он же
    записан в (uuid ...) корневого файла. Рассинхрон невозможен —
    источник один.

Frame vs bbox:
    У каждого Component есть frame_size и frame_offset_mm — это
    прямоугольник, который рисует Writer (символ / прямоугольник
    add_sheet). Пины сидят на кромке frame.

    У обычного символа frame == bbox, frame_offset == (0, 0):
    пины лежат на кромке bbox и «вылезают» за неё — это норма для
    символов KiCad.

    У SheetRef frame = bbox - 2 клетки, frame_offset = (grid, grid):
    рамка листа вписана в bbox с запасом в одну клетку со всех
    сторон, чтобы маршрутный забор (ComponentBody) закрывал
    пин-клетки и не давал чужим сетям проходить по кромке листа.

Позиционирование:
    Component хранит anchor_page_mm (ЛВ-угол bbox).
    Writer:
      * для символа — sch.components.add(position=anchor_page_mm);
      * для sheet  — sch.add_sheet(position=anchor+frame_offset,
                                   size=(frame-1)*grid).

Sheet-pin и имя сети на родителе:
    sheet-pin получает имя pin.name (имя hier-label внутри
    дочернего листа). Рядом КАЖДЫЙ РАЗ ставится локальная метка
    с именем pin.net_name — именем КОРНЕВОЙ сети на родителе.
    Без label'а сеть на родителе остаётся безымянной, и KiCad
    её либо разводит как локальную, либо вообще не показывает в
    нетлисте.

    Позиция sheet-pin берётся из comp.abs_pin_mm(pin) — абсолютная
    точка пина на странице, независимо от frame_offset.

Логирование:
    Все лог-строки — одна строка, префикс ctx():
        [page] [net] [comp] [pin]
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from cell import Cell
from constants import Axis, Direction
from logging_setup import get_logger, ctx

import re

if TYPE_CHECKING:
    from sheet import Sheet

log = get_logger(__name__)


class Writer:
    """Пишет .kicad_sch: одну страницу (text) или всё дерево (project)."""

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
        self._written: Set[str] = set()
        self._next_page: int = 1
        self._out_dir: Optional[Path] = None
        self._root_sheet: Optional["Sheet"] = None
        self._root_file_name: str = ""
        self._sheets: Dict[str, "Sheet"] = {}
        self._refdes_maps: Dict[str, Dict[str, str]] = {}
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
        """Текстовая сводка по self.sheet (для routes.txt)."""
        if self.sheet is None:
            return ""
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
    # Контекст логов: [page] [net] [comp] [pin]
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
    # Публичный вход: записать всё дерево проекта
    # =========================================================

    def write_project(
        self,
        out_dir: Path,
        *,
        root_sheet: "Sheet",
        root_file_name: str,
        sheets: Dict[str, "Sheet"],
        refdes_maps: Dict[str, Dict[str, str]],
        project_name: str,
    ) -> None:
        """Записать все .kicad_sch проекта рекурсивно от root_sheet.

        Args:
            out_dir:         каталог для сохранения.
            root_sheet:      корень обхода (главный корень проекта
                             или отдельный standalone-лист).
            root_file_name:  имя .kicad_sch корня (напр.
                             "climate_control_niva_travel.kicad_sch").
                             Для standalone — сам sheet_path.
            sheets:          {sheet_path: Sheet}, все листы проекта.
            refdes_maps:     {X_*: {base_ref: project_ref}} — карта
                             аннотированных refdes для мульти-инстанс
                             символов. Для одноуровневых файлов пустая.
            project_name:    имя проекта KiCad (для блока (instances ...)).
        """
        self._out_dir = Path(out_dir)
        self._out_dir.mkdir(parents=True, exist_ok=True)

        self._root_sheet = root_sheet
        self._root_file_name = root_file_name
        self._sheets = sheets
        self._refdes_maps = refdes_maps
        self._project_name = project_name

        # Нумерация страниц начинается заново на каждый root_sheet.
        # Кэш записанных файлов СОХРАНЯЕТСЯ между вызовами — второй
        # вызов (для standalone) не перезапишет уже записанное.
        self._next_page = 1

        self._visit(
            root_sheet,
            instances=[],
            parent_paths=None,     # корень сам себе родитель
        )

    @property
    def written(self) -> Set[str]:
        """Множество уже записанных sheet_path — для standalone-прохода."""
        return self._written

    # =========================================================
    # Обход дерева
    # =========================================================

    def _visit(
        self,
        sheet: "Sheet",
        instances: List[Dict[str, Any]],
        parent_paths: Optional[List[str]],
    ) -> None:
        """Пишет одну страницу и рекурсивно её детей.

        Args:
            sheet:         страница для записи.
            instances:     instance-описания ЭТОЙ страницы
                           (для корня []). Один элемент = одиночный
                           лист, много = мульти-инстанс.
            parent_paths:  пути, по которым ЭТА страница
                           инстанцирована (для корня None — Writer
                           сам подставит "/<self_uuid>").
        """
        file_key = sheet.sheet_path
        if file_key and file_key in self._written:
            return
        if file_key:
            self._written.add(file_key)

        # Устанавливаем контекст для вспомогательных методов.
        self.sheet = sheet
        self.cell_size_mm = sheet.grid_mm
        self.netlist = sheet.netlist

        info = self._write_one(sheet, instances)
        self_uuid = info.get("self_uuid")
        child_sheets: Dict[str, str] = info.get("child_sheets") or {}

        # Для корня parent_path ещё неизвестен — берём из self_uuid,
        # который ksa только что присвоил этому файлу. Так первый
        # сегмент instance-путей детей совпадает с (uuid ...) корня.
        if parent_paths is None:
            if self_uuid:
                parent_paths = [f"/{self_uuid}"]
            else:
                log.error(
                    "%s write_project: no self_uuid — "
                    "child instance paths will be broken",
                    ctx(page=sheet.page),
                )
                parent_paths = ["/"]

        # Собрать instance-пути для каждого ребёнка.
        # child_uid — uuid из (sheet (uuid ...)), который ksa
        # присвоил только что в родительском файле.
        next_file_instances: Dict[str, List[Dict[str, Any]]] = {}

        for designator, comp in sheet.components.items():
            if not getattr(comp, "is_sheet_ref", False):
                continue

            child_uid = child_sheets.get(designator)
            if not child_uid:
                log.warning(
                    "%s child %s uuid missing — skip "
                    "(writer returned: %r, sheet_ref designators: %r)",
                    ctx(page=sheet.page, comp=designator), designator,
                    child_sheets,
                    sorted(k for k, v in sheet.components.items()
                           if getattr(v, "is_sheet_ref", False)),
                )
                continue

            child_file = Path(comp.sheet_file).with_suffix(
                ".kicad_sch").name

            for parent_path in parent_paths:
                next_file_instances.setdefault(child_file, []).append({
                    "path":       f"{parent_path}/{child_uid}",
                    "sheet_uuid": child_uid,
                    "designator": designator,
                })

        # Рекурсия.
        for child_file, child_instances in next_file_instances.items():
            if child_file in self._written:
                continue
            child_sheet = self._sheets.get(child_file)
            if child_sheet is None:
                log.warning(
                    "%s child file %s not loaded",
                    ctx(page=sheet.page), child_file,
                )
                continue

            child_parent_paths = [inst["path"] for inst in child_instances]
            self._visit(
                child_sheet,
                instances=child_instances,
                parent_paths=child_parent_paths,
            )

    # =========================================================
    # Запись одной страницы
    # =========================================================

    def _write_one(
    self,
    sheet: "Sheet",
    instances: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Сохраняет .kicad_sch одной страницы.

        Returns:
            {
                "self_uuid":    str | None,
                "child_sheets": {designator: sheet_uuid},
            }
        """
        label = sheet.page
        out_path = self._out_dir / self._out_name_for(sheet)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import kicad_sch_api as ksa
        except ImportError:
            log.warning("%s kicad_sch_api unavailable text_fallback",
                        ctx(page=label))
            self._write_text_fallback(out_path)
            return {"self_uuid": None, "child_sheets": {}}

        sch = ksa.create_schematic(self._project_name)

        # ─── Контекст иерархии ──────────────────────────────────────
        # Для одиночного листа: ksa проставляет parent/sheet uuid,
        # чтобы дальше он мог корректно расставлять instance-пути
        # при авто-синхронизации. Refdes символов при этом ещё не
        # трогаем: символов в sch.components сейчас нет, они появятся
        # в цикле 1 ниже. Переназначение refdes — блок 6.
        #
        # Для мульти-инстанса set_hierarchy_context не вызывается:
        # instances проставим вручную в блоке 6.
        is_multi = len(instances) > 1
        if len(instances) == 1:
            inst = instances[0]
            sheet_uuid = inst.get("sheet_uuid") or ""
            path = inst.get("path") or ""
            parent_uuid = self._parent_uuid_from_path(path)
            if parent_uuid and sheet_uuid:
                try:
                    sch.set_hierarchy_context(parent_uuid, sheet_uuid)
                    log.info(
                        "%s set_hierarchy_context parent=%s sheet=%s",
                        ctx(page=label), parent_uuid, sheet_uuid,
                    )
                except Exception as e:
                    log.error(
                        "%s set_hierarchy_context failed parent=%s "
                        "sheet=%s err=%s",
                        ctx(page=label), parent_uuid, sheet_uuid, e,
                    )

        placed = 0
        n_sheets = 0
        n_sheet_pins = 0
        child_sheets: Dict[str, str] = {}

        # ---------- 1. Компоненты, порты, листы ----------
        sheet_refs_to_place = []
        for designator, comp in sheet.components.items():
            anchor_mm = comp.anchor_page_mm
            if anchor_mm is None:
                log.warning("%s no_anchor skip_write",
                            ctx(page=label, comp=designator))
                continue
            x_mm, y_mm = anchor_mm

            # --- Порт ---
            if getattr(comp, "is_port", False):
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

        # ---------- 2. Вложенные листы ----------
        # Рамка листа рисуется по frame_size + frame_offset_mm,
        # а не по bbox. У SheetRef frame = bbox - 2 клетки,
        # frame_offset = (grid, grid). Так пины листа оказываются
        # строго ВНУТРИ bbox, и Placer.build_router_map закрывает
        # их ComponentBody — чужая сеть по кромке листа не пройдёт.
        for designator, comp, anchor_mm in sheet_refs_to_place:
            fc, fr = comp.frame_size
            ox, oy = comp.frame_offset_mm

            # ЛВ-угол frame в мм = anchor (ЛВ bbox) + frame_offset.
            x_mm = anchor_mm[Axis.X] + ox
            y_mm = anchor_mm[Axis.Y] + oy

            # Если add_sheet рисует прямоугольник [pos, pos+size],
            # а кромки должны проходить через ЦЕНТРЫ крайних клеток
            # frame, ширина = (fc - 1) * grid.
            # Если окажется, что add_sheet считает size как «сколько
            # клеток» — вернуть fc * grid (см. комментарий выше).
            w_mm = (fc - 1) * self.cell_size_mm
            h_mm = (fr - 1) * self.cell_size_mm

            filename = Path(comp.sheet_file).with_suffix(".kicad_sch").name

            self._next_page += 1
            page_num = str(self._next_page)

            try:
                sobj = sch.add_sheet(
                    project_name=self._project_name,
                    name=comp.sheet_name or designator,
                    filename=filename,
                    position=(x_mm, y_mm),
                    size=(w_mm, h_mm),
                    page_number=page_num,
                )
                child_uid = self._sheet_uuid_of(sobj)
                if child_uid:
                    child_sheets[designator] = child_uid
                log.info(
                    "%s write_sheet name=%s file=%s uuid=%s "
                    "page=%s frame_at_mm=(%.2f,%.2f) "
                    "frame_size_mm=(%.2f,%.2f) "
                    "frame=%dx%d bbox=%dx%d cells",
                    ctx(page=label, comp=designator),
                    comp.sheet_name, filename, child_uid, page_num,
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

        # ---------- 5. Метки сети ----------
        n_labels = 0
        for lbl in getattr(sheet, "labels", []) or []:
            x_mm, y_mm = lbl.contact_mm
            rotation = float(self._label_angle(lbl.direction))
            justify = "right" if rotation == 180.0 else "left"
            try:
                sch.add_label(lbl.net_name, (x_mm, y_mm),
                            rotation=rotation,
                            effects={"justify": justify})
                log.info(
                    "%s write_label net=%s pin=%s on_wire=%s "
                    "contact_mm=(%.2f,%.2f) dir=%s rotation=%.0f "
                    "justify=%s",
                    ctx(page=label, net=lbl.net_name,
                        pin=lbl.local_key),
                    lbl.net_name, lbl.local_key, lbl.on_wire,
                    x_mm, y_mm, lbl.direction, rotation, justify,
                )
                n_labels += 1
            except Exception as e:
                log.warning("%s label error=%s",
                            ctx(page=label, net=lbl.net_name,
                                pin=lbl.local_key), e)

        # ---------- 6. instances per symbol ----------
        # Идут строго ПОСЛЕ добавления символов (блоки 1-2).
        #
        # _apply_instances пишет comp._data.instances — блок
        # (instances ...) в .kicad_sch. Именно его читает kicad-cli
        # при flat-export иерархии, предпочитая top-level Reference.
        # Поэтому вызываем для ЛЮБОГО числа instances — и single,
        # и multi. Для single запись одна, для multi — по одной
        # на каждый instance-путь.
        #
        # _apply_refdes_map синхронизирует top-level Reference: он
        # виден, если .kicad_sch открыть в GUI без родителя. Вызов
        # только для single: при multi top-level неоднозначен,
        # и KiCad ориентируется на instances.
        #
        # Порядок критичен: _apply_instances читает comp.reference
        # как base_ref и через refdes_maps достаёт проектный refdes.
        # Если _apply_refdes_map уже отработал, comp.reference
        # станет проектным, и lookup потеряет исходный base_ref.
        if instances:
            self._apply_instances(sch, instances)

        #if len(instances) == 1:
         #   self._apply_refdes_map(sch, instances[0].get("designator") or "")

        # ---------- 7. Сохранить ----------
        try:
            sch.save(str(out_path))
            # Обход бага kicad_sch_api: add_hierarchical_label игнорирует
            # параметр shape (принимает, но нигде не использует). После
            # save — проставляем shape у hierarchical_label по месту.
            self._fix_hierarchical_label_shapes(out_path, sheet)
            log.info(
                "%s saved file=%s components=%d sheets=%d "
                "sheet_pins=%d wires=%d junctions=%d labels=%d "
                "multi_instance=%s instances=%d",
                ctx(page=label),
                out_path.name, placed, n_sheets,
                n_sheet_pins, n_wires, n_junctions, n_labels,
                is_multi, len(instances),
            )
        except Exception as e:
            log.error("%s save_failed file=%s error=%s",
                    ctx(page=label), out_path.name, e)

        return {
            "self_uuid": self._schematic_uuid(sch),
            "child_sheets": child_sheets,
        }

    # =========================================================
    # Multi-instance: instances per symbol
    # =========================================================

    def _apply_refdes_map(self, sch, designator: str) -> None:
        """Переписывает reference символов одиночного листа по маппингу.

        Для одиночного листа project._compute_refdes всё равно считает
        новый refdes: оригинальные designators могут пересекаться с
        designators других листов проекта (C1 в power_supply и C1 в
        actuator_channel). Маппинг применяется один раз, для единственного
        instance этого листа.

        Для мульти-инстанса этот метод не вызывается — там refdes
        различаются по instance path и раскидываются через
        _apply_instances.
        """
        rm = self._refdes_maps.get(designator, {}) or {}
        if not rm:
            return

        n_renamed = 0
        for comp in sch.components:
            old = comp.reference
            new = rm.get(old)
            if new and new != old:
                comp._data.reference = new
                n_renamed += 1

        log.info(
            "%s apply_refdes_map sheet=%s renamed=%d total=%d",
            ctx(page=self.sheet.page), designator, n_renamed, len(rm),
        )

    def _apply_instances(
        self,
        sch,
        instances: List[Dict[str, Any]],
    ) -> None:
        """Проставляет comp._data.instances каждому символу.

        kicad-sch-api в Schematic._sync_components_to_data проверяет
        comp._data.instances и, если он непуст, пишет блок
        (instances ...) с этими записями вместо автоматической
        генерации одного path.
        """
        try:
            from kicad_sch_api.core.types import SymbolInstance
        except Exception as e:
            log.error(
                "%s _apply_instances: SymbolInstance недоступен: %s",
                ctx(page=self.sheet.page), e,
            )
            return

        if not instances:
            return

        n_sym = 0
        for comp in sch.components:
            base_ref = comp.reference
            inst_list = []
            for inst in instances:
                sheet_uuid = inst.get("sheet_uuid") or ""
                path = inst.get("path") or f"/{sheet_uuid}"
                sheet_des = inst.get("designator") or ""
                rm = self._refdes_maps.get(sheet_des, {}) or {}
                ref = rm.get(base_ref, base_ref)
                inst_list.append(SymbolInstance(
                    path=path,
                    reference=ref,
                    unit=1,
                    project=self._project_name,
                ))
            comp._data.instances = inst_list
            n_sym += 1

        log.info(
            "%s apply_instances symbols=%d instances=%d",
            ctx(page=self.sheet.page), n_sym, len(instances),
        )

    # =========================================================
    # Sheet pins для SheetRefComponent
    # =========================================================

    def _add_sheet_pins(self, sch, sobj, comp,
                        x_mm: float, y_mm: float,
                        w_mm: float, h_mm: float,
                        label: str) -> int:
        """Добавляет sheet_pin'ы и локальные метки имён корневых сетей.

        Args:
            sch:    Schematic-объект kicad-sch-api.
            sobj:   sheet-объект, к которому цепляются пины.
            comp:   SheetRefComponent.
            x_mm, y_mm:  ЛВ-угол FRAME (не bbox).
            w_mm, h_mm:  размер FRAME (не bbox).
            label:  имя страницы для логов.

        Пины сидят на кромке frame, их абсолютные координаты берём
        из comp.abs_pin_mm(pin) — они отсчитываются от anchor_page_mm
        (ЛВ bbox), а не от frame. Проверка «левый/правый» — по
        близости к x_mm или x_mm + w_mm.
        """
        uid = self._sheet_uuid_of(sobj)
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
            net_pin = pin.identifier
            if not net_pin:
                continue
            net_root = getattr(pin, "net_name", None) or net_pin

            # Абсолютная точка пина на странице — она не зависит
            # от того, где мы нарисовали frame.
            pin_x_mm, pin_y_mm = comp.abs_pin_mm(pin)

            # Сторона — по положению пина относительно кромок frame.
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
                    ctx(page=label, comp=comp.designator, pin=pin.local_key),
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

            # Локальная метка с именем КОРНЕВОЙ сети. Пишется ВСЕГДА,
            # даже если net_root == net_pin.
            rotation = 180.0 if side == "left" else 0.0
            justify = "right" if rotation == 180.0 else "left"

            try:
                sch.add_label(
                    net_root,
                    (pin_x_mm, pin_y_mm),
                    rotation=rotation,
                    effects={"justify": justify},
                )
                log.info(
                    "%s write_root_label pin=%s net_root=%s net_pin=%s "
                    "pin_mm=(%.2f,%.2f) rotation=%.0f justify=%s",
                    ctx(page=label, net=net_root,
                        comp=comp.designator, pin=pin.local_key),
                    pin.local_key, net_root, net_pin,
                    pin_x_mm, pin_y_mm, rotation, justify,
                )
            except Exception as e:
                log.warning("%s root_label pin=%s net_root=%s error=%s",
                            ctx(page=label, comp=comp.designator,
                                pin=pin.local_key),
                            pin.local_key, net_root, e)

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
        """Имя выходного .kicad_sch для страницы."""
        if sheet is self._root_sheet or not sheet.sheet_path:
            return self._root_file_name
        return sheet.sheet_path

    @staticmethod
    def _parent_uuid_from_path(path: str) -> Optional[str]:
        """Предпоследний сегмент instance-пути.

        Путь: "/<root_uuid>/<sheet_uuid>/.../<this_sheet_uuid>".
        """
        if not path:
            return None
        parts = [p for p in path.strip("/").split("/") if p]
        if len(parts) >= 2:
            return parts[-2]
        return None

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
            # uuid должен быть длинным и содержать дефисы — отсекаем
            # случайный int из "id".
            if len(s) >= 32 and "-" in s:
                return s
        return None

    @staticmethod
    def _schematic_uuid(sch) -> Optional[str]:
        for attr in ("uuid", "schematic_uuid"):
            val = getattr(sch, attr, None)
            if val:
                return str(val)
        data = getattr(sch, "_data", None)
        if isinstance(data, dict):
            val = data.get("uuid")
            if val:
                return str(val)
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

        Библиотека принимает параметр shape в Schematic.add_hierarchical_label,
        но не передаёт его ни в LabelCollection.add, ни в
        _sync_hierarchical_labels_to_data — поле теряется, в файл
        попадает дефолт (shape input). Правка по месту: после save
        читаем .kicad_sch и проставляем shape у тех hierarchical_label,
        чьи net_name совпадают с именами портов текущей страницы.

        Работает построчно-регулярно: ищет конкретный блок
        (hierarchical_label "<name>" (shape <текущий>)) и заменяет
        <текущий> на comp.shape. Не трогает labels других сетей,
        не зависит от отступов и порядка полей.

        Если kicad_sch_api когда-нибудь починят — метод можно удалить,
        он безвреден: если shape уже правильный, ни одна замена
        не сработает.
        """
        wanted: dict[str, str] = {}
        for comp in sheet.components.values():
            if getattr(comp, "is_port", False):
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