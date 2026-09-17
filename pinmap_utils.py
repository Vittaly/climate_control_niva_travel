#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pinmap_utils.py — единая точка доступа к mcu_pin_map."""

import re


def _parse_old(s, pin=None, nets=None):
    """Разбор старой строки (см. migrate_pinmap.py)."""
    s = str(s).strip()
    signal = net = function = comment = None
    if "->" in s:
        left, right = s.split("->", 1)
        left = left.strip()
        if re.match(r"^(VSS|VDD)_\d+$", left):
            signal, function = left, None
        else:
            for sep in ("/", "-"):
                if sep in left:
                    a, b = left.split(sep, 1)
                    signal, function = a.strip(), b.strip()
                    break
            else:
                signal = left
        m = re.match(r"^([A-Za-z0-9_]+)\s*(?:\((.*)\))?\s*$", right.strip())
        if m:
            net, comment = m.group(1), m.group(2) or None
        else:
            net = right.strip()
    else:
        m = re.match(r"^([A-Za-z0-9_]+)\s*(?:\((.*)\))?\s*$", s)
        if m:
            signal, comment = m.group(1), m.group(2)
        else:
            signal = s
    if signal.startswith("VSS"):
        net = net or "GND"; function = function or "power_in"
    elif signal.startswith("VDD") or signal == "VBAT":
        net = net or "VCC_3V3"; function = function or "power_in"
    return {"signal": signal or "", "net": net,
            "function": function, "comment": comment}


def get_pin(mcu, pin, nets=None):
    """Вернуть dict {signal, net, function, comment} независимо от формата."""
    v = mcu.get(str(pin))
    if v is None:
        return None
    if isinstance(v, dict):
        return {
            "signal": v.get("signal", ""),
            "net": v.get("net"),
            "function": v.get("function"),
            "comment": v.get("comment"),
        }
    return _parse_old(v, pin=pin, nets=nets)


def get_signal(mcu, pin, nets=None):
    e = get_pin(mcu, pin, nets)
    return e["signal"] if e else ""


def get_net(mcu, pin, nets=None):
    e = get_pin(mcu, pin, nets)
    return e["net"] if e else None


def find_pins_by_net(mcu, net_name, nets=None):
    """Все номера пинов, у которых net == net_name."""
    out = []
    for pin in mcu:
        if get_net(mcu, pin, nets) == net_name:
            out.append(str(pin))
    return out
