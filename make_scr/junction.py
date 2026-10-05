# junction.py
"""Электрическая точка соединения на проводах — KiCad-элемент (junction ...).

В .kicad_sch junction — самостоятельный элемент верхнего уровня:

    (junction (at 255.27 7.62)
      (diameter 0)
      (color 0 0 0 0)
      (uuid "b5a91c45-3da9-42db-a473-02d6b23218ba")
    )

KiCad подключает label к проводу только если label.at совпадает
с endpoint сегмента ИЛИ с junction. Роутер ставит junction в трёх
случаях:
    * T-врезка (три сегмента в одной точке);
    * метка-имя внутренней сети в середине сегмента;
    * fallback-метка на проводе при провале трассировки.

В модели проекта Junction — не Component: у него нет designator,
lib_id, пинов и bbox. Он не участвует ни в раскладке (Placer его
не видит), ни в роутинге как endpoint. Его роль — точка, по
которой KiCad связывает сегменты и метки.

Поля net_name и reason в файл не пишутся: это метаданные для
отладки и для логов writer'а и роутера. Удаление junction при
повторном прогоне делается целиком (reset_routing_marks), потому
что все они создаются роутером — структурных среди них нет.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple, TYPE_CHECKING

from primitive import Primitive

if TYPE_CHECKING:
    from sheet import Sheet


# Значения по умолчанию совпадают с тем, что пишет KiCad, когда
# диаметр/цвет не заданы явно: (diameter 0) (color 0 0 0 0).
DEFAULT_DIAMETER = 0.0
DEFAULT_COLOR = (0, 0, 0, 0)


@dataclass(eq=False, kw_only=True)
class Junction(Primitive):
    """Точка соединения на странице.

    Attributes:
        anchor_mm:  координаты на странице в мм (система страницы, Y↓).
        diameter:   диаметр в мм; 0 — использовать дефолт KiCad.
        color:      RGBA, по умолчанию (0, 0, 0, 0) — не переопределён.
        sheet:      страница-владелец. Проставляется Sheet.add_junction;
                    используется writer'ом для контекста логов.
        net_name:   имя сети, к которой относится точка. В файл не
                    пишется, нужен для логов и для диагностики.
        reason:     почему junction появилась: "t_junction",
                    "internal_net_name", "fallback_on_wire".
    """

    anchor_mm: Tuple[float, float]
    diameter: float = DEFAULT_DIAMETER
    color: Tuple[int, int, int, float] = DEFAULT_COLOR
    sheet: Optional["Sheet"] = field(default=None, repr=False)
    net_name: str = ""
    reason: str = ""

    # ---------- создание ----------

    @classmethod
    def create(
        cls,
        anchor_mm: Tuple[float, float],
        *,
        diameter: float = DEFAULT_DIAMETER,
        color: Tuple[int, int, int, float] = DEFAULT_COLOR,
        net_name: str = "",
        reason: str = "",
        uuid: Optional[str] = None,
    ) -> "Junction":
        """Собрать Junction.

        uuid генерируется автоматически (Primitive.new_uuid), если
        не передан явно. Явный uuid нужен, если когда-нибудь
        понадобится загрузка из существующего .kicad_sch.
        """
        kwargs = dict(
            anchor_mm=(float(anchor_mm[0]), float(anchor_mm[1])),
            diameter=float(diameter),
            color=color,
            net_name=net_name,
            reason=reason,
        )
        if uuid is not None:
            kwargs["uuid"] = uuid
        return cls(**kwargs)

    def __post_init__(self) -> None:
        super().__post_init__()

        if self.diameter < 0:
            raise ValueError(
                f"Junction {self.uuid}: диаметр не может быть "
                f"отрицательным, получено {self.diameter}"
            )

        c = self.color
        if (not isinstance(c, (tuple, list)) or len(c) != 4):
            raise ValueError(
                f"Junction {self.uuid}: color должен быть кортежем "
                f"(r, g, b, a), получено {c!r}"
            )

    # ---------- идентичность ----------

    def __hash__(self) -> int:
        return hash(self.uuid)

    # ---------- геометрия ----------

    @property
    def anchor_x(self) -> float:
        return self.anchor_mm[0]

    @property
    def anchor_y(self) -> float:
        return self.anchor_mm[1]

    def anchor_cell(self, grid_mm: float):
        """Клетка сетки, в которой лежит junction.

        Возвращает Cell — импорт ленивый, чтобы не тянуть
        constants/cell в базовый модуль без нужды.
        """
        from cell import Cell
        return Cell(round(self.anchor_x / grid_mm),
                    round(self.anchor_y / grid_mm))

    # ---------- диагностика ----------

    def __repr__(self) -> str:
        return (
            f"<Junction {self.uuid[:8]} @ "
            f"({self.anchor_x:.2f}, {self.anchor_y:.2f})"
            + (f" net={self.net_name}" if self.net_name else "")
            + (f" reason={self.reason}" if self.reason else "")
            + ">"
        )