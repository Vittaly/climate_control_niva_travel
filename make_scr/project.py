# make_scr/project.py
"""Корневая сущность: YAML -> компоненты/нетлист -> размещение -> трассы -> файлы."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import yaml

from component import Component
from constants import Axis, DEFAULT_GRID_MM, DEFAULT_NET_TYPE, Symbol
from kicad_source import KiCadSource
from logging_setup import get_logger
from netlist import Netlist
from placer import Placer
from router import Router
from sheet import Sheet
from sheet_ref import SheetRefComponent
from writer import Writer

log = get_logger(__name__)


class Project:
    """Точка входа: загрузка, размещение, роутинг, сохранение."""

    def __init__(self, root_yaml: str | Path,
                 grid_mm: float = DEFAULT_GRID_MM):
        """
        Args:
            root_yaml: путь к main.yaml.
            grid_mm:   шаг сетки в мм.
        """
        self.root_path = Path(root_yaml)
        self.base_dir = self.root_path.parent
        self.grid_mm = grid_mm

        self.source = KiCadSource()
        self.netlist = Netlist()

        self.root_sheet: Optional[Sheet] = None
        self.sheets: Dict[str, Sheet] = {}
        self.root_data: dict = {}

        log.info("Project создан: %s (grid=%.2f мм)",
                 self.root_path, grid_mm)

    # =========================================================
    # Загрузка
    # =========================================================

    def load(self) -> "Project":
        """Полный цикл загрузки: main.yaml + рекурсивно все листы."""
        log.info("Загрузка %s", self.root_path)
        self._read_root()

        self.root_sheet = Sheet(
            designator="",
            sheet_path="",
            yaml_path=self.root_path,
            data=self.root_data,
        )
        self.sheets[""] = self.root_sheet

        self._load_components(self.root_sheet, self.root_data)
        self._load_nets(self.root_sheet, self.root_data)
        self._log_components_with_nets(self.root_sheet)
        self._discover_sheets(self.root_sheet, self.root_data)

        log.info(
            "Загрузка завершена: листов %d, компонентов %d, сетей %d",
            len(self.sheets),
            sum(len(s.components) for s in self.sheets.values()),
            len(self.netlist.nets),
        )
        return self

    def _read_root(self) -> None:
        """Читает main.yaml и сохраняет секцию root_page."""
        with open(self.root_path, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        self.root_data = doc["root_page"]
        log.debug("root_page: project=%s, version=%s",
                  self.root_data.get("project"),
                  self.root_data.get("version"))

    # ---------- компоненты и сети ----------

    def _load_components(self, sheet: Sheet, data: dict) -> None:
        """Строит Component для всех записей data['components'].

        X_* (Core:Hierarchical_Sheet) не пропускаются — они создаются
        как SheetRefComponent: дают габарит, пины по портам дочернего
        YAML и место в placer.positions.

        После обычных компонентов добавляет PortComponent для каждой
        записи data['ports'] (порты страницы).
        """
        types = data.get("component_types", {})
        for designator, cdef in data.get("components", {}).items():
            if cdef.get("symbol") == Symbol.HIERARCHICAL_SHEET:
                # ссылка на вложенный лист — как компонент
                sheet_file = cdef.get("value", "")
                ref = SheetRefComponent.create(
                    designator=designator,
                    sheet_file=sheet_file,
                    parent_yaml_path=sheet.yaml_path,
                )
                sheet.add_component(ref)
                log.debug("[%s] добавлен SheetRef %s (%s, портов %d)",
                          sheet.sheet_path or "root",
                          designator, sheet_file, len(ref.pins))
                continue

            comp = Component.from_yaml(
                designator=designator,
                cdef=cdef,
                types=types,
                source=self.source,
                grid_mm=self.grid_mm,
            )
            if comp:
                sheet.add_component(comp)

        # --- Порты страницы (data['ports']) ---
        self._load_ports(sheet, data)

    def _load_ports(self, sheet: Sheet, data: dict) -> None:
        """Создаёт PortComponent для каждого порта из data['ports'].

        Сети ещё не зарегистрированы в netlist (это делает _load_nets
        сразу после), поэтому FQN пинов регистрируются отдельно —
        в _load_nets, где все сети уже есть.
        """
        from port_component import PortComponent

        ports = data.get("ports", []) or []
        if not ports:
            return

        for p in ports:
            net_label = p.get("net_label", "")
            if not net_label:
                continue
            ptype = str(p.get("type", "INPUT")).upper()
            shape = p.get("shape") or _default_port_shape(ptype)
            side = "left" if ptype in ("INPUT", "POWER") else "right"

            port = PortComponent.create(
                designator=f"PORT_{net_label}",
                net_name=net_label,
                shape=shape,
                side=side,
            )
            sheet.add_component(port)
            log.debug("[%s] добавлен порт %s (side=%s shape=%s)",
                      sheet.sheet_path or "root",
                      port.designator, side, shape)

    def _load_nets(self, sheet: Sheet, data: dict) -> None:
        """Регистрирует сети листа и привязывает их FQN-пины.

        Здесь же — регистрация пинов портов и пинов SheetRef
        (вложенных листов): к этому моменту все сети уже добавлены
        в netlist, и FQN можно безопасно привязать.
        """
        for net_name, ndef in data.get("nets", {}).items():
            attrs = ndef.get("attributes", {})
            self.netlist.add_net(
                net_name,
                attrs.get("type", DEFAULT_NET_TYPE),
                list(attrs.keys()),
            )
        for net_name, ndef in data.get("nets", {}).items():
            for node in ndef.get("nodes", []):
                self._bind_node(sheet, net_name, node)

        # --- Пины портов: регистрация в сетях ---
        self._bind_ports_to_nets(sheet, data)

        # --- Пины SheetRef: регистрация в сетях ---
        self._bind_sheet_refs_to_nets(sheet, data)

    def _bind_ports_to_nets(self, sheet: Sheet, data: dict) -> None:
        """Привязывает FQN пина каждого порта к его сети."""
        from port_component import PortComponent

        for comp in sheet.components.values():
            if not isinstance(comp, PortComponent):
                continue
            net = self.netlist.nets.get(comp.net_name)
            if net is None:
                log.warning("[%s] порт %s: сети %r нет в нетлисте",
                            sheet.sheet_path or "root",
                            comp.designator, comp.net_name)
                continue
            pin = comp.pins[0]
            fqn = f"{sheet.fqn(comp.designator)}:{pin.number}"
            self.netlist.assign_pin_to_net(fqn, comp.net_name, pin=pin)

            log.debug("[%s] порт %s: пин %s привязан к сети %s",
                      sheet.sheet_path or "root",
                      comp.designator, fqn, comp.net_name)

    def _bind_sheet_refs_to_nets(self, sheet: Sheet, data: dict) -> None:
        """Привязывает FQN пинов SheetRef-ов к их сетям."""
        for comp in sheet.components.values():
            if not getattr(comp, "is_sheet_ref", False):
                continue

            for pin in comp.pins:
                net_name = pin.number  # для SheetRef номер = имя порта
                net = self.netlist.nets.get(net_name)
                if net is None:
                    log.debug(
                        "[%s] SheetRef %s: сеть %r не найдена, пин %s "
                        "оставлен без привязки",
                        sheet.sheet_path or "root",
                        comp.designator, net_name, pin.number,
                    )
                    continue

                fqn = f"{sheet.fqn(comp.designator)}:{pin.number}"
                self.netlist.assign_pin_to_net(fqn, net_name, pin=pin)

                log.debug("[%s] SheetRef %s: пин %s привязан к сети %s",
                          sheet.sheet_path or "root",
                          comp.designator, fqn, net_name)

    def _bind_node(self, sheet: Sheet, net_name: str, node: dict) -> None:
        """Привязывает пин из YAML-узла к сети через FQN страницы."""
        designator = node["component"]
        pin_no = str(node["pin"])

        comp = sheet.get_component(designator)
        if comp is None:
            log.debug("[%s] Узел %s:%s — не компонент страницы, пропуск",
                      sheet.sheet_path or "root", designator, pin_no)
            return

        pin = comp.pin_by_number(pin_no)
        if pin is None:
            log.debug("[%s] Пин %s:%s не найден, пропуск",
                      sheet.sheet_path or "root", designator, pin_no)
            return

        fqn = pin.fqn
        try:
            self.netlist.assign_pin_to_net(fqn, net_name, pin=pin)
        except ValueError:
            log.warning("Сеть %s не зарегистрирована при привязке %s",
                        net_name, fqn)

    # ---------- сводка пинов с сетями ----------

    def _log_components_with_nets(self, sheet: Sheet) -> None:
        """Сводка: компоненты с пинами — смещение от якоря (мм) и сеть."""
        label = sheet.sheet_path or "root"
        for designator, comp in sheet.components.items():
            log.info("[%s] %s (%s) %dx%d, пинов %d",
                     label, designator, comp.name,
                     comp.bbox_cols, comp.bbox_rows, len(comp.pins))
            for pin in comp.pins:
                net = pin.net_ref if pin.net_ref else "-"
                log.info(
                    "    %s.%-3s %-8s offset_mm=(%7.2f,%7.2f)  net=%s",
                    designator, pin.number, pin.name,
                    pin.offset_mm[Axis.X], pin.offset_mm[Axis.Y],
                    net,
                )

    # ---------- иерархические страницы ----------

    def _discover_sheets(self, parent: Sheet, data: dict) -> None:
        """Находит ссылки Core:Hierarchical_Sheet и грузит их содержимое.

        ВАЖНО: SheetRefComponent для родителя создаётся отдельно —
        в _load_components. Здесь мы только читаем дочерние YAML
        и рекурсивно строим для них Sheet-объекты.

        На родителя SheetRef уже лежит в parent.components — оттуда
        Placer и Router его видят. Здесь — только содержимое дочки.
        """
        for designator, cdef in data.get("components", {}).items():
            if cdef.get("symbol") != Symbol.HIERARCHICAL_SHEET:
                continue

            sheet_path = (f"{parent.sheet_path}/{designator}"
                          if parent.sheet_path else designator)

            yaml_path = self.base_dir / cdef["value"]
            if not yaml_path.exists():
                log.warning("Лист %s: файл %s не найден, пропускаю",
                            sheet_path, yaml_path)
                continue

            with open(yaml_path, encoding="utf-8") as f:
                sub_data = yaml.safe_load(f)

            sub_sheet = Sheet(
                designator=designator,
                sheet_path=sheet_path,
                yaml_path=yaml_path,
                data=sub_data,
            )
            self.sheets[sheet_path] = sub_sheet

            self._load_components(sub_sheet, sub_data)
            self._load_nets(sub_sheet, sub_data)
            self._log_components_with_nets(sub_sheet)
            self._discover_sheets(sub_sheet, sub_data)

            log.debug("Лист %s: компонентов %d",
                      sheet_path, len(sub_sheet.components))

    # =========================================================
    # Размещение и роутинг
    # =========================================================

    def place_and_route(self) -> "Project":
        """Раскладывает и трассирует каждую страницу отдельно."""
        log.info("Старт размещения и роутинга: страниц %d", len(self.sheets))
        for sheet in self.sheets.values():
            self._place_and_route_sheet(sheet)
        return self

    def _place_and_route_sheet(self, sheet: Sheet) -> None:
        """Размещает и трассирует одну страницу.

        SheetRef-компоненты (X_*) попадают в placer как обычные
        компоненты: у них есть bbox_size и pins — Placer сам их
        разложит.
        """
        label = sheet.sheet_path or "root"
        log.info("[%s] размещение %d компонентов",
                 label, len(sheet.components))

        placer = Placer(self.netlist, grid_step=self.grid_mm)
        for comp in sheet.components.values():
            placer.register_component(comp)

        strategy_used = placer.auto_place(self.netlist, sheet)
        log.info("[%s] стратегия размещения: %s", label, strategy_used)

        placer.all_overlaps()

        router = Router.from_placer(placer, sheet.components)
        wires = router.route_all(self.netlist, sheet)

        sheet.placer = placer
        sheet.router = router
        log.info("[%s] готово: проводов %d, меток %d, T-врезок %d",
                 label, len(wires),
                 len(sheet.labels), len(sheet.t_junctions))

    # =========================================================
    # Сохранение
    # =========================================================

    def save(self, out_dir: str | Path = "out") -> Path:
        """Сохраняет .kicad_sch для каждой страницы + routes.txt."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        writer = Writer(cell_size_mm=self.grid_mm)

        for sheet_path, sheet in self.sheets.items():
            label = sheet_path or "root"
            out_name = (Path(self.root_data.get("file", "root.kicad_sch")).name
                        if sheet_path == "" else sheet.out_file)
            writer.write_sheet(
                out_dir / out_name,
                sheet,
                netlist=self.netlist,
            )
            log.info("[%s] сохранён %s", label, out_name)

        (out_dir / "routes.txt").write_text(
            writer.write_text([]), encoding="utf-8",
        )
        return out_dir


# =========================================================
# Порты страницы: вспомогательное
# =========================================================

def _default_port_shape(ptype: str) -> str:
    """Форма hierarchical_label по типу порта из YAML."""
    return {
        "POWER": "passive",
        "GND": "passive",
        "INPUT": "input",
        "OUTPUT": "output",
        "BIDIR": "bidirectional",
        "ANALOG": "passive",
        "DIGITAL_SIGNAL": "input",
    }.get(ptype, "input")