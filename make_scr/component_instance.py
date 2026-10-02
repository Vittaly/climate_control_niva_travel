from dataclasses import dataclass

from make_scr.component import Component
from make_scr.refdes import make_refdes
from make_scr.sheet_instance import SheetInstance


@dataclass(eq=False)
class ComponentInstance:
    component:      "Component"        # локальное описание (U1, R1, …)
    sheet_instance: "SheetInstance"    # контекст присутствия (M1, M2, …)

    @property
    def refdes(self) -> str:
        """Проектное имя: f(designator, page). Не хранится."""
        return make_refdes(self.component.designator,
                           self.sheet_instance.page)

    @property
    def path(self) -> str:
        """Instance-путь листа. Делегация к SheetInstance."""
        return self.sheet_instance.path