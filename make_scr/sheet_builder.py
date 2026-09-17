from port_component import PortComponent

# где-то в построении страницы, после обычных компонентов:

def _add_ports(sheet, data, netlist):
    """Создаёт PortComponent для каждого порта из YAML
    и регистрирует их пины в соответствующих сетях."""
    for p in data.get("ports", []) or []:
        net_label = p.get("net_label", "")
        if not net_label:
            continue
        ptype = str(p.get("type", "INPUT")).upper()
        shape = p.get("shape") or _default_shape(ptype)
        side = "left" if ptype in ("INPUT", "POWER") else "right"

        port = PortComponent.create(
            designator=f"PORT_{net_label}",
            net_name=net_label,
            shape=shape,
            side=side,
        )
        sheet.add_component(port)

        # регистрация пина порта в сети — чтобы роутер его увидел
        net = netlist.nets.get(net_label)
        if net is None:
            log.warning("[%s] порт %s: сети %r нет в нетлисте",
                        sheet.sheet_path or "root", net_label, net_label)
            continue

        port_pin_fqn = sheet.fqn_pin(
            f"{port.designator}:{port.pins[0].number}")
        net.pins.add(port_pin_fqn)   # или .append — см. вопрос 1 ниже


def _default_shape(ptype: str) -> str:
    return {
        "POWER": "passive",
        "GND": "passive",
        "INPUT": "input",
        "OUTPUT": "output",
        "BIDIR": "bidirectional",
        "ANALOG": "passive",
        "DIGITAL_SIGNAL": "input",
    }.get(ptype, "input")
