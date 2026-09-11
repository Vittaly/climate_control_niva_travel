#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_automate.py — создание иерархии страниц напрямую через MCP-сервер (JSON-RPC stdio).
Запуск:  python3 mcp_automate.py   (Eeschema должен быть закрыт)"""
import json, subprocess, sys

SERVER_CMD = ["bun", "/home/vitaly-pc/.local/share/kicad-mcp-server/dist/index.js"]
SCH = "/home/vitaly-pc/kicad/climate_control_niva_travel/climate_control_niva_travel.kicad_sch"
PAGES = [
    ("CAN","cc_02_can.kicad_sch",90,30), ("PWR","cc_03_pwr.kicad_sch",240,30),
    ("UI","cc_04_ui.kicad_sch",390,30), ("SEN_CABIN","cc_05_sen_cabin.kicad_sch",90,180),
    ("SEN_HEAT","cc_06_sen_heat.kicad_sch",240,180), ("SEN_SOLAR","cc_07_sen_solar.kicad_sch",390,180),
    ("SEN_COND","cc_08_sen_cond.kicad_sch",540,30), ("OUT","cc_09_out.kicad_sch",540,180),
    ("ACT","cc_10_act.kicad_sch",690,30),
]

class RawMCP:
    def __init__(self, cmd):
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, bufsize=1, encoding="utf-8", errors="replace")
        self.next_id = 1
    def _read_line(self):
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP-сервер завершился")
            if line.strip():
                return json.loads(line)
    def call(self, method, params):
        rid = self.next_id; self.next_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":rid,"method":method,"params":params})+ "\n")
        self.proc.stdin.flush()
        while True:
            msg = self._read_line()
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})
            # иначе уведомление — игнорируем
    def close(self):
        try: self.proc.stdin.close()
        except Exception: pass
        self.proc.terminate()

def main():
    srv = RawMCP(SERVER_CMD)
    try:
        srv.call("initialize", {"protocolVersion": "2025-06-18",
                                 "capabilities": {}, "clientInfo": {"name":"cc_automate","version":"1.0"}})
        tools = srv.call("tools/list", {})
        names = [t["name"] for t in tools.get("tools", [])]
        print("инструментов:", len(names))
        add = next((n for n in names if "add" in n and "sheet" in n), None)
        imp = next((n for n in names if "import" in n and "pin" in n), None)
        print("add:", add, "| import_pins:", imp)
        if not add:
            sys.exit("нет инструмента добавления листа")
        for name, file, x, y in PAGES:
            r = srv.call("tools/call", {"name": add, "arguments": {
                "schematic": SCH, "sheet_name": name, "sheet_file": file, "x": x, "y": y}})
            ok = r.get("content", [{}])[0].get("text", r)
            print("+", name, str(ok)[:80])
        if imp:
            for name, *_ in PAGES:
                r = srv.call("tools/call", {"name": imp, "arguments": {"schematic": SCH, "sheet_name": name}})
                print("pins", name, "OK")
    finally:
        srv.close()

if __name__ == "__main__":
    main()
