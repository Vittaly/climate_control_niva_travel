# make_scr/netlist.py
"""Реестр сетей и привязка FQN-пинов к ним.

Ключи пинов — полностью квалифицированные (FQN):
    "U1:42"          — компонент на корне
    "X_ACT/U2:5"     — компонент на листе X_ACT
    "X_ACT/M1/U3:1"  — вложенный лист

Alias-пины:
    Alias — это ВНУТРИКОМПОНЕНТНЫЙ механизм: один физический пад,
    несколько номеров выводов одного и того же компонента
    (например, U2:1, U2:7, U2:9 — три GND на одной позиции).

    Если при добавлении пина в сеть обнаруживается пин ТОГО ЖЕ
    КОМПОНЕНТА с теми же координатами и именем (в пределах
    GRID_EPSILON_MM) в той же сети, новый пин НЕ добавляется
    в net.pins и pin_to_net, а получает ссылку alias_of на
    канонический пин-оригинал.

    Пины РАЗНЫХ компонентов никогда не схлопываются, даже если
    их абсолютные координаты на странице совпали (наложение при
    placement — это отдельная проблема, которую ловит
    check_short_circuits, а не alias-механизм).

    КЗ (один пад, разные сети) проверяется отдельно методом
    check_short_circuits() после построения всех сетей.
"""
from typing import Dict, Iterable, List, Optional

from constants import Axis, GRID_EPSILON_MM
from logging_setup import get_logger
from net import Net
from pin import Pin
from wire import Wire

log = get_logger(__name__)


# =========================================================
# Вспомогательные функции
# =========================================================

def _same_position(a: Pin, b: Pin) -> bool:
    """Совпадают ли смещения пинов от якоря (мм).

    Вызывается только для пинов одного компонента — значит,
    достаточно сравнить offset_mm (абсолютные координаты совпадут).
    """
    return (abs(a.offset_mm[Axis.X] - b.offset_mm[Axis.X]) <= GRID_EPSILON_MM
            and abs(a.offset_mm[Axis.Y] - b.offset_mm[Axis.Y]) <= GRID_EPSILON_MM)


def _abs_pin_mm(pin: Pin) -> tuple[float, float]:
    """Абсолютные координаты пина на странице (мм).

    Component сам знает anchor_page_mm и pin.offset_mm.
    """
    comp = pin.component
    if comp is not None and comp.anchor_page_mm is not None:
        return comp.abs_pin_mm(pin)
    # fallback: смещение от якоря
    return pin.offset_mm




def _position_key(pin: Pin) -> tuple[float, float]:
    """Ключ позиции для группировки с учётом GRID_EPSILON_MM.

    Округляет координаты до точности, достаточной для сравнения,
    чтобы пины, отличающиеся на <= GRID_EPSILON_MM, попали в одну группу.
    """
    x, y = _abs_pin_mm(pin)
    # шаг округления — 10 * epsilon, чтобы граница не «дробила» группу
    scale = 1.0 / (GRID_EPSILON_MM * 10.0)
    return (round(x * scale), round(y * scale))


def _assert_alias_invariants(pin: Pin, canonical: Pin) -> None:
    """Проверяет инварианты alias-пина перед простановкой ссылки."""
    assert pin is not canonical, "alias не может ссылаться на себя"
    assert canonical.alias_of is None, "оригинал не может быть alias'ом"
    assert pin.component is canonical.component, (
        "alias допустим только внутри одного компонента"
    )


# =========================================================
# Netlist
# =========================================================

class Netlist:
    """Хранит сети и обратный индекс FQN-пина -> сеть.

    Дополнительно хранит канонические пины (net_pins) — по одному
    на каждый физический пад. Alias-пины в net_pins не попадают,
    но имеют alias_of на канонический пин.
    """

    def __init__(self):
        """Создаёт пустой нетлист."""
        self.nets: Dict[str, Net] = {}
        self.pin_to_net: Dict[str, str] = {}    # FQN pin key -> net_name
        self.net_pins: Dict[str, Pin] = {}      # FQN -> канонический Pin

    # ---------- сети ----------

    def add_net(self, name: str, net_type: str, flags: List[str]) -> None:
        """Регистрирует сеть. Повторный вызов с тем же именем — no-op."""
        if name in self.nets:
            return
        self.nets[name] = Net(name=name, net_type=net_type, flags=flags)
        log.debug("Сеть зарегистрирована: %s (%s)", name, net_type)

    # ---------- пины ----------

    def assign_pin_to_net(
        self,
        fqn_key: str,
        net_name: str,
        pin: Pin,
    ) -> None:
        """Привязывает FQN-пин к сети.

        Если в этой же сети уже есть пин ТОГО ЖЕ КОМПОНЕНТА с теми же
        координатами и именем (в пределах GRID_EPSILON_MM), новый пин
        не добавляется в net.pins и pin_to_net, а получает alias_of
        на канонический пин.

        Пины разных компонентов не схлопываются, даже если их
        абсолютные координаты на странице совпали.

        Args:
            fqn_key:  FQN-ключ пина ("X_ACT/U2:5").
            net_name: имя сети.
            pin:      объект пина (обязателен).

        Raises:
            ValueError: если сеть не зарегистрирована.
        """
        if net_name not in self.nets:
            raise ValueError(f"Нет сети: {net_name}")

        pin.net_ref = net_name

        duplicate = self._find_duplicate_in_net(pin, net_name)
        if duplicate is not None:
            _assert_alias_invariants(pin, duplicate)
            pin.alias_of = duplicate
            log.info(
                "alias: %s → %s (net=%s, comp=%s)",
                fqn_key, duplicate.local_key, net_name,
                _designator(pin),
            )
            return

        self.net_pins[fqn_key] = pin
        self.pin_to_net[fqn_key] = net_name
        self.nets[net_name].pins.append(fqn_key)

    def _find_duplicate_in_net(self, pin: Pin, net_name: str) -> Optional[Pin]:
        """Ищет в сети канонический пин-дубликат ВНУТРИ ТОГО ЖЕ КОМПОНЕНТА.

        Alias — это внутрикомпонентный механизм: один физический пад,
        несколько номеров выводов одного чипа. Поэтому сначала сужаем
        область поиска до пинов того же компонента, и только потом
        сравниваем имена и координаты.

        Пины других компонентов не рассматриваются, даже если их
        абсолютные координаты на странице совпали.
        """
        same_comp = self._pins_of_same_component_in_net(pin, net_name)

        for existing in same_comp:
            if existing.name != pin.name:
                continue
            if not _same_position(existing, pin):
                continue
            return existing
        return None

    def _pins_of_same_component_in_net(
        self, pin: Pin, net_name: str,
    ) -> List[Pin]:
        """Канонические пины сети, принадлежащие тому же компоненту, что и pin."""
        result: List[Pin] = []
        for fqn in self.nets[net_name].pins:
            existing = self.net_pins.get(fqn)
            if existing is None:
                continue
            if existing.component is not pin.component:
                continue
            result.append(existing)
        return result

    # ---------- провода ----------

    def register_wire(self, wire: Wire) -> None:
        """Регистрирует провод в соответствующей сети.

        Raises:
            ValueError: если сеть не зарегистрирована.
        """
        net = self.nets.get(wire.net_name)
        if net is None:
            raise ValueError(f"Нет сети: {wire.net_name}")
        net.add_wire(wire)

    # ---------- доступ ----------

    def get_net(self, net_name: str) -> Optional[Net]:
        """Возвращает Net по имени или None."""
        return self.nets.get(net_name)

    def pins_in_net(self, net_name: str) -> List[str]:
        """Список FQN-ключей канонических пинов в сети.

        Alias-пины сюда не входят — они покрыты каноническими.
        """
        net = self.get_net(net_name)
        return net.pins if net else []

    def pin_by_fqn(self, fqn_key: str) -> Optional[Pin]:
        """Возвращает канонический Pin по FQN или None."""
        return self.net_pins.get(fqn_key)

    # ---------- проверки ----------

    def check_short_circuits(self) -> None:
        """Логирует КЗ: пины в одной точке, но в разных сетях.

        Вызывать один раз после построения всех сетей.
        Использует net_pins (только канонические пины).

        Здесь сравнение по абсолютным координатам намеренно НЕ
        ограничено компонентом: два разных компонента, оказавшихся
        в одной точке страницы, — это либо наложение при placement,
        либо реальное КЗ. Оба случая стоит залогировать.
        """
        by_pos: Dict[tuple, List[Pin]] = {}
        for pin in self.net_pins.values():
            key = _position_key(pin)
            by_pos.setdefault(key, []).append(pin)

        for key, pins in by_pos.items():
            nets = {p.net_ref for p in pins if p.net_ref is not None}
            if len(nets) > 1:
                log.error(
                    "КЗ: пины %s в одной точке, но в разных сетях: %s",
                    [p.local_key for p in pins], nets,
                )

    def check_alias_invariants(self, all_pins: Iterable[Pin]) -> None:
        """Проверяет инварианты alias-пинов.

        Args:
            all_pins: все пины проекта (включая alias-пины, которые
                      не попали в net_pins). Передаёт вызывающий код,
                      т.к. сам Netlist хранит только канонические пины.
        """
        for pin in self.net_pins.values():
            # у канонического alias_of должен быть None
            if pin.alias_of is not None:
                log.error(
                    "Инвариант нарушен: канонический пин %s имеет alias_of=%s",
                    pin.local_key, pin.alias_of.local_key,
                )

        for pin in all_pins:
            canonical = getattr(pin, "alias_of", None)
            if canonical is None:
                continue
            # alias допустим только внутри одного компонента
            if pin.component is not canonical.component:
                log.error(
                    "Межкомпонентный alias: %s → %s (компоненты %s и %s)",
                    pin.local_key, canonical.local_key,
                    _designator(pin), _designator(canonical),
                )


# =========================================================
# Утилиты
# =========================================================

def _designator(pin: Pin) -> str:
    """Обозначение компонента пина для логов ('C7', 'U2', '?')."""
    comp = getattr(pin, "component", None)
    if comp is None:
        return "?"
    return getattr(comp, "designator", "?")