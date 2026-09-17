#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_u1_nets.py — сверка mcu_pin_map с nets, работает с обоими форматами."""
import yaml
from pinmap_utils import get_pin, get_signal, get_net

d = yaml.safe_load(open("main.yaml", encoding="utf-8"))["root_page"]
mcu = d.get("mcu_pin_map") or {}
nets = d.get("nets") or {}

# U1 в nets
used = {}
for net, info in nets.items():
    for n in info.get("nodes") or []:
        if isinstance(n, dict) and n.get("component") == "U1":
            used.setdefault(net, []).append(str(n["pin"]))

# U1 в карте
declared = {}
for pin in mcu:
    net = get_net(mcu, pin, nets)
    if net:
        declared.setdefault(net, []).append(str(pin))

print(f"{'цепь':<22} | U1 в nets          | U1 в mcu_map       | статус")
print("-" * 90)
for net in sorted(set(used) | set(declared)):
    a = used.get(net, [])
    b = declared.get(net, [])
    st = "OK" if sorted(a) == sorted(b) else (
        "НЕТ В NETS" if not a else (
        "НЕТ В КАРТЕ" if not b else "РАСХОЖДЕНИЕ"))
    if net in ("GND", "VCC_3V3", "VCC_5V", "VCC_12V", "VDDA_3V3"):
        if set(b) <= set(a):
            st = "OK (групповая)"
    print(f"{net:<22} | {a!s:<19} | {b!s:<19} | {st}")