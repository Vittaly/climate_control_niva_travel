#!/usr/bin/env python3
"""
manhattan_router.py — автотрассировщик A* по сетке с обходом корпусов и пинов.

Модель:
  - bbox компонентов НЕПРОЗРАЧНЫ для A*. Выход из своего bbox — через
    _make_stub, который выталкивает стартовую/финишную точку за его
    пределы (с учётом clearance).
  - пины всех компонентов (и stub_end портов) регистрируются через
    add_pin(ref=...) и блокируются, кроме конкретных выводов
    start/goal (own_pins — набор клеток, не ref'ов компонентов).
  - уже проложенные провода (_wire_cells) блокируют ТОЛЬКО параллельные
    наложения и только ЧУЖОЙ сети. Своя сеть может ходить по своим
    проводам (подключение к дереву).
  - fallback-путей НЕТ. Если A* не находит чистый путь — route()
    возвращает None, вызывающий код пропускает ребро и пишет [FAIL].
Лог: пишется в общий (страничный) logger через logger=....
"""

import heapq
import logging
import os
import sys
import time


class ManhattanRouter:
    def __init__(self, grid=1.27, clearance=0.5, turn_penalty=2.0,
                 max_iter=1_000_000, verbose=False,
                 log_prefix="", log_file=None, logger=None,
                 h_weight=1.3):
        self.grid = float(grid)
        self.clearance = float(clearance)
        self.turn_penalty = float(turn_penalty)
        self.max_iter = int(max_iter)
        self.verbose = bool(verbose)
        self.log_prefix = log_prefix
        # Weighted A*: h умножается на h_weight. При 1.0 — обычный A*
        # (оптимальный путь, но медленный). При 1.3 — до 30% длиннее
        # оптимального, но исследует в разы меньше состояний. Для PCB
        # auto-routing это стандартная практика.
        self.h_weight = float(h_weight)

        if logger is not None:
            # используем переданный (страничный) логгер, своих хендлеров не заводим
            self.log = logger
            self._file_handler = None
        else:
            self.log = logging.getLogger(f"router.{id(self)}")
            self.log.setLevel(logging.DEBUG)
            self.log.propagate = True   # -> root (gen.log + stdout)
            self._file_handler = None
            if log_file:
                try:
                    fmt = logging.Formatter(
                        "%(asctime)s [%(levelname)-7s] %(message)s",
                        datefmt="%H:%M:%S")
                    fh = logging.FileHandler(
                        os.path.abspath(log_file), mode="w",
                        encoding="utf-8", delay=False)
                    fh.setLevel(logging.DEBUG); fh.setFormatter(fmt)
                    self.log.addHandler(fh)
                    self._file_handler = fh
                except Exception as e:
                    print(f"[ROUTER] не могу открыть {log_file}: {e}",
                          file=sys.stderr, flush=True)

        self.log.info("=" * 70)
        self.log.info("%s[ROUTER-INIT] grid=%.3f clearance=%.3f "
                      "turn_penalty=%.1f max_iter=%d h_weight=%.2f",
                      self.log_prefix, self.grid, self.clearance,
                      self.turn_penalty, self.max_iter, self.h_weight)

        self._obstacles = []   # [(x0,y0,x1,y1,owner)]
        self._pins = set()     # {(gx, gy)}
        self._pin_refs = {}    # {(gx, gy): ref}
        # {(gx,gy): set('H'|'V')} — какие направления уже заняты проводом.
        # Блокируем только параллельные наложения; перпендикулярные
        # пересечения разрешены (кроме точек — они в _pins).
        self._wire_cells = {}
        self._bbox = None
        self._stats = {"ok": 0, "failed": 0, "maxiter": 0,
                       "cells_visited": 0, "time_total": 0.0}
        self._last_fail_blame = set()

    # ---------- логирование ----------
    def _flush(self):
        if self._file_handler:
            try:
                self._file_handler.flush()
                os.fsync(self._file_handler.stream.fileno())
            except Exception:
                pass

    def close(self):
        try:
            self._flush()
        except Exception:
            pass
        if self._file_handler:
            try:
                self._file_handler.close()
                self.log.removeHandler(self._file_handler)
            except Exception:
                pass
            self._file_handler = None

    # ---------- сбор ----------
    def add_obstacle(self, x0, y0, x1, y1, owner=None):
        self._obstacles.append((min(x0, x1), min(y0, y1),
                                max(x0, x1), max(y0, y1), owner))
        if self._bbox is None:
            self._bbox = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        else:
            b = self._bbox
            b[0] = min(b[0], x0, x1); b[1] = min(b[1], y0, y1)
            b[2] = max(b[2], x0, x1); b[3] = max(b[3], y0, y1)

    def add_pin(self, x, y, ref=None):
        g = (round(x / self.grid), round(y / self.grid))
        self._pins.add(g)
        if ref is not None:
            self._pin_refs[g] = ref
        # Расширяем bbox и по пинам тоже: порты могут стоять далеко за
        # пределами компонентов (в этом проекте — на 300+ мм правее),
        # и _inside_bbox(margin_cells=...) не должен их отсекать.
        # Без этого A* не может ни стартовать из их stub_end (iter=1),
        # ни финишировать в них (maxiter, h=50 у границы поля).
        if self._bbox is None:
            self._bbox = [x, y, x, y]
        else:
            b = self._bbox
            b[0] = min(b[0], x); b[1] = min(b[1], y)
            b[2] = max(b[2], x); b[3] = max(b[3], y)

    def block_path(self, path, net_name=None):
        """Регистрирует клетки маршрута с направлением и именем сети:
        {(gx,gy): {'H': net_name, 'V': net_name}}.

        Блокируем только параллельные наложения и только чужой сети:
        своя сеть может ходить по своим проводам (подключение к дереву).
        Если net_name=None — старое поведение (блокировать всем)."""
        if not path or len(path) < 2:
            return 0
        if not hasattr(self, "_wire_cells"):
            self._wire_cells = {}
        added = 0
        for i in range(len(path) - 1):
            x1, y1 = path[i]
            x2, y2 = path[i + 1]
            if abs(x1 - x2) < 1e-6:
                orient = "V"
            elif abs(y1 - y2) < 1e-6:
                orient = "H"
            else:
                # диагональ — не ортогональный Manhattan, не регистрируем
                continue
            gx1 = int(round(x1 / self.grid))
            gy1 = int(round(y1 / self.grid))
            gx2 = int(round(x2 / self.grid))
            gy2 = int(round(y2 / self.grid))
            steps = max(abs(gx2 - gx1), abs(gy2 - gy1))
            if steps == 0:
                continue
            for s in range(steps + 1):
                gx = round(gx1 + (gx2 - gx1) * s / steps)
                gy = round(gy1 + (gy2 - gy1) * s / steps)
                cell = self._wire_cells.setdefault((gx, gy), {})
                if cell.get(orient) != net_name:
                    cell[orient] = net_name
                    added += 1
        return added

    def reset_stats(self):
        self._stats = {"ok": 0, "failed": 0, "maxiter": 0,
                       "cells_visited": 0, "time_total": 0.0}

    def report(self):
        s = self._stats
        total = s["ok"] + s["failed"] or 1
        self.log.info(
            "%s[ROUTER-STATS] ok=%d failed=%d (maxiter=%d) | "
            "obstacles=%d pins=%d grid=%.3f cells=%d avg=%.3fs",
            self.log_prefix, s["ok"], s["failed"], s["maxiter"],
            len(self._obstacles), len(self._pins), self.grid,
            s["cells_visited"], s["time_total"] / total)
        self._flush()

    # ---------- сетка ----------
    def _g(self, v):
        return int(round(v / self.grid))

    def _w(self, g):
        return g * self.grid

    def _cell_blocked(self, gx, gy, own_pins=None,
                      cur_dir=None, _cur_net=None):
        """cur_dir: 'H' | 'V' — направление движения, которым A* пришёл
        в клетку. _cur_net — имя текущей сети.

        Отдельного allow-бокса нет. Старт/финиш A* гарантированно вне
        bbox — это обеспечивает _make_stub, выталкивающий пины за
        пределы корпусов с учётом clearance. Поэтому bbox-проверка
        стартовую/финишную клетку не задевает и никаких исключений
        для неё не требуется.

        Блокируются:
          * чужие пины (stub_end, пины компонентов) при любом направлении;
          * параллельные наложения проложенных проводов чужой сети
            (своя сеть может ходить по своим проводам);
          * bbox любого компонента (все непрозрачны).
        """
        # 1. Чужие пины — препятствие. «Своими» считаются ТОЛЬКО
        #    конкретные ВЫВОДЫ (клетки) старта и цели этого маршрута,
        #    а не все выводы компонента-владельца. Компонент/лист —
        #    контейнер, к сети относится только вывод. Иначе маршрут
        #    одной цепи проходит сквозь stub_end другой цепи того же
        #    листа (X_ACT/X_PWR/X_UI), занимает чужие целевые клетки
        #    и следующая цепь падает в h=1.
        if (gx, gy) in self._pins:
            if not (own_pins and (gx, gy) in own_pins):
                return True
        # 2. Проложенные провода: блокируем только параллельные наложения
        #    и только чужой сети.
        cell = getattr(self, "_wire_cells", {}).get((gx, gy))
        if cell and cur_dir is not None:
            owner_net = cell.get(cur_dir)
            if owner_net is not None and owner_net != _cur_net:
                return True
        # 3. bbox: непрозрачны все.
        x, y = self._w(gx), self._w(gy)
        c = self.clearance
        for obs in self._obstacles:
            x0, y0, x1, y1 = obs[0], obs[1], obs[2], obs[3]
            if (x0 - c) <= x <= (x1 + c) and (y0 - c) <= y <= (y1 + c):
                return True
        return False

    def _inside_bbox(self, gx, gy, margin_cells=500):
        """Ограничить поле поиска разумным радиусом. Теперь bbox включает
        и пины (см. add_pin), поэтому 500 клеток ≈ 635 мм в каждую сторону
        — с запасом хватает на любой локальный обход и на подход к портам,
        но не даёт A* разбредаться в пустое поле."""
        if self._bbox is None:
            return True
        x, y = self._w(gx), self._w(gy)
        x0, y0, x1, y1 = self._bbox
        m = self.grid * margin_cells
        return (x0 - m) <= x <= (x1 + m) and (y0 - m) <= y <= (y1 + m)

    def _make_stub(self, g_pt, sdir, own_ref,
                   own_pins=None, net_name=None):
        """Идёт от пина по направлению sdir, пока не выйдет из ВСЕХ bbox
        И не окажется на клетке, свободной от ЧУЖОГО провода в этом
        направлении. Свой bbox — тоже препятствие."""
        gx, gy = g_pt
        dx, dy = sdir if sdir else (1, 0)
        _hv = "H" if dx != 0 else "V"

        def _blocked(nx, ny):
            # bbox хранится в мм, g_pt — в индексах сетки: сравниваем в мм.
            # Учитываем clearance — как _cell_blocked. Иначе стаб остановится
            # в клетке, которую A* всё ещё считает "внутри" bbox+clearance,
            # и все её соседи окажутся заблокированы (iter=1).
            wx, wy = self._w(nx), self._w(ny)
            c = self.clearance
            for obs in self._obstacles:
                x0, y0, x1, y1 = obs[0], obs[1], obs[2], obs[3]
                if (x0 - c) <= wx <= (x1 + c) and (y0 - c) <= wy <= (y1 + c):
                    return True
            return False

        def _foreign_wire(nx, ny):
            # Не садиться концом отростка на чужой провод, идущий
            # в нашем направлении (H/V). Свой провод — можно.
            if net_name is None:
                return False
            cell = getattr(self, "_wire_cells", {}).get((nx, ny))
            if not cell:
                return False
            owner = cell.get(_hv)
            return owner is not None and owner != net_name

        if not _blocked(gx, gy) and not _foreign_wire(gx, gy):
            return (gx, gy)
        for step in range(1, 80):
            nx, ny = gx + dx * step, gy + dy * step
            if _blocked(nx, ny):
                continue
            if _foreign_wire(nx, ny):
                continue
            return (nx, ny)
        return (gx + dx * 80, gy + dy * 80)


    # ---------- A* ----------
    def route(self, p1, p2, own_pins=None,
              p1_dir=None, p2_dir=None,
              p1_owner=None, p2_owner=None,
              net_name=None, net_cells=None):
        """Возвращает polyline от p1 до p2 (включая сами пины) или None.
        Fallback-путей нет: строим правильно либо никак.

        Если net_cells задан (клетки уже проложенного дерева этой же
        цепи), цель ПОДМЕНЯЕТСЯ на ближайшую к старту клетку сети:
        маршрут идёт "пин → сеть", а не "пин → исходная цель".
        """
        t0 = time.time()
        g1 = (self._g(p1[0]), self._g(p1[1]))
        g2 = (self._g(p2[0]), self._g(p2[1]))
        g1_before = g1; g2_before = g2

        if p1_dir is not None:
            g1 = self._make_stub(g1, p1_dir, p1_owner,
                                 own_pins=own_pins, net_name=net_name)
        # v48: запоминаем стартовый стаб для вызывающего кода.
        self._last_stub_g1_mm = (self._w(g1[0]), self._w(g1[1]))

        # Подмена цели: ищем ближайшую клетку проложенной сети этой
        # цепи к старту. Если такая есть — финишируем именно там.
        _substituted = False
        if net_cells:
            bx, by = g1
            best = None
            for (cx, cy) in net_cells:
                d = abs(cx - bx) + abs(cy - by)
                if best is None or d < best[0]:
                    best = (d, (cx, cy))
            if best is not None and best[1] != g1:
                g2 = best[1]
                p2 = (self._w(g2[0]), self._w(g2[1]))
                _substituted = True

        # Стаб цели — только если цель НЕ подменена (иначе g2 уже на
        # дереве, выталкивать нечего).
        if (not _substituted) and p2_dir is not None:
            g2 = self._make_stub(g2, p2_dir, p2_owner,
                                 own_pins=own_pins, net_name=net_name)

        # v48: запоминаем финишный стаб.
        self._last_stub_g2_mm = (self._w(g2[0]), self._w(g2[1]))
        if self.verbose:
            self.log.debug(
                "%s[STUB] p1=%s dir=%s -> g1=%s  |  p2=%s dir=%s -> g2=%s "
                "(subst=%s)",
                self.log_prefix, g1_before, p1_dir, g1,
                g2_before, p2_dir, g2, _substituted)

        if g1 == g2:
            self._stats["ok"] += 1
            self._stats["time_total"] += time.time() - t0
            return self._pts_from_grid(p1, [g1], p2)

        # Старт/финиш — вне bbox благодаря _make_stub, отдельного
        # allow-бокса не требуется. Костыль allow_cells убран: он
        # отключал проверки чужих пинов и проводов внутри 3x3 вокруг
        # старта/цели, что приводило к T-контактам чужой сети
        # (пример: GND на угол FB_M3 в ACT, короткое C30).

        # Клетки дерева этой же сети — альтернативные цели. Если A* по
        # пути случайно попадёт в другую точку дерева, тоже финиш.
        _net_goal_cells = set(net_cells) if net_cells else set()

        DIRS = [(1, 0, 0), (-1, 0, 0), (0, 1, 1), (0, -1, 1)]
        start = (g1[0], g1[1], -1)
        came = {}; g_best = {start: 0.0}; heap = [(0.0, 0.0, start)]
        iter_count = 0
        best_h = float("inf"); best_cell = None

        while heap:
            iter_count += 1
            if iter_count > self.max_iter:
                self._stats["maxiter"] += 1
                self._stats["failed"] += 1
                self._stats["time_total"] += time.time() - t0
                self.log.error("%s[ROUTER-FAIL] maxiter %s -> %s",
                               self.log_prefix, p1, p2)
                self._log_failure_diag(p1, p2, g1, g2, best_cell, best_h,
                                       own_pins, p1_owner, p2_owner,
                                       subst=_substituted)
                return None

            f, g_in_heap, cur = heapq.heappop(heap)
            if g_in_heap > g_best.get(cur, float("inf")):
                continue
            x, y, dprev = cur
            h_here = abs(x - g2[0]) + abs(y - g2[1])
            if h_here < best_h:
                best_h = h_here
                best_cell = (x, y)

            hit_goal = (x, y) == g2
            hit_tree = (x, y) in _net_goal_cells and (x, y) != g1

            # own_terminal_v54: свой провод своей сети — терминал
            # ТОЛЬКО при продольном касании (H в H, V в V). Это даёт
            # T-стык, который KiCad считает соединением.
            # hit_own_pin УБРАН: через неподключённый пин своей сети
            # маршрут идёт насквозь (в _cell_blocked own_pins его
            # пропускает). Терминал — только провод своей сети
            # при совпадении направления.
            hit_own_wire = False
            if net_name is not None and (x, y) != g1:
                _wc54 = getattr(self, "_wire_cells", {}).get((x, y))
                if _wc54:
                    if dprev == 0:
                        _cur_hv = "H"
                    elif dprev == 1:
                        _cur_hv = "V"
                    else:
                        _cur_hv = None
                    if (_cur_hv is not None and
                            _wc54.get(_cur_hv) == net_name):
                        hit_own_wire = True

            if hit_goal or hit_tree or hit_own_wire:
                self._stats["ok"] += 1
                self._stats["time_total"] += time.time() - t0
                self._stats["cells_visited"] += iter_count
                path_g = [(x, y)]; node = cur
                while node in came:
                    node = came[node]
                    path_g.append((node[0], node[1]))
                path_g.reverse()
                pts = [p1]
                for gx_, gy_ in path_g:
                    q = (self._w(gx_), self._w(gy_))
                    if (abs(pts[-1][0] - q[0]) > 1e-6 or
                            abs(pts[-1][1] - q[1]) > 1e-6):
                        pts.append(q)
                if hit_goal and not hit_tree:
                    if (abs(pts[-1][0] - p2[0]) > 1e-6 or
                            abs(pts[-1][1] - p2[1]) > 1e-6):
                        pts.append(p2)
                return self._simplify(pts)

            for dx, dy, dcur in DIRS:
                nx, ny = x + dx, y + dy
                if not self._inside_bbox(nx, ny):
                    continue
                hv = "H" if dx != 0 else "V"
                if self._cell_blocked(nx, ny, own_pins,
                                      cur_dir=hv, _cur_net=net_name):
                    continue
                turn = 0.0 if (dprev == dcur or dprev == -1) else self.turn_penalty
                ng = g_best[cur] + 1.0 + turn
                nst = (nx, ny, dcur)
                if ng < g_best.get(nst, float("inf")):
                    g_best[nst] = ng
                    # Weighted A*: h с коэффициентом. Внутренняя стоимость
                    # по-прежнему ng (без веса), т.к. при завершении нам
                    # нужен g именно реальной длины пути.
                    h = (abs(nx - g2[0]) + abs(ny - g2[1])) * self.h_weight
                    heapq.heappush(heap, (ng + h, ng, nst))
                    came[nst] = cur

        self._stats["failed"] += 1
        self._stats["time_total"] += time.time() - t0
        self.log.error("%s[ROUTER-FAIL] no path %s -> %s iter=%d",
                       self.log_prefix, p1, p2, iter_count)
        self._log_failure_diag(p1, p2, g1, g2, best_cell, best_h,
                               own_pins, p1_owner, p2_owner,
                               subst=_substituted)
        return None

    def _pts_from_grid(self, p1, grid_path, p2):
        """Склеивает p1 + grid_path (в мировых координатах) + p2,
        выкидывая дубли по координатам."""
        pts = [p1]
        for gx, gy in grid_path:
            q = (self._w(gx), self._w(gy))
            if abs(pts[-1][0] - q[0]) > 1e-6 or abs(pts[-1][1] - q[1]) > 1e-6:
                pts.append(q)
        if abs(pts[-1][0] - p2[0]) > 1e-6 or abs(pts[-1][1] - p2[1]) > 1e-6:
            pts.append(p2)
        return self._simplify(pts)

    # ---------- диагностика неудач ----------
    def _log_failure_diag(self, p1, p2, g1, g2, best_cell, best_h,
                          own_pins, p1_owner, p2_owner, subst=False):
        """Печатает причину неудачи и заполняет self._last_fail_blame.
        subst=True, если цель была подменена на ближайшую клетку дерева
        (g2 в этом случае — не исходный p2, а точка сети)."""
        lg = self.log
        c = self.clearance
        blame = set()
        if p1_owner: blame.add(p1_owner)
        if p2_owner: blame.add(p2_owner)

        if subst:
            lg.error("%s[FAIL-DIAG]   цель подменена: p2=%s → g2=%s "
                     "(route-to-net)",
                     self.log_prefix, p2, g2)

        if best_cell is None:
            lg.error("%s[FAIL-DIAG] %s -> %s : A* не сделал ни шага "
                     "(старт/цель блокированы)",
                     self.log_prefix, p1, p2)
        else:
            bwx, bwy = self._w(best_cell[0]), self._w(best_cell[1])
            lg.error("%s[FAIL-DIAG] %s -> %s : ближайший к цели узел "
                     "(h=%d) в world(%.2f,%.2f)",
                     self.log_prefix, p1, p2, best_h, bwx, bwy)

        for label, gpt in (("g1", g1), ("g2", g2)):
            wx, wy = self._w(gpt[0]), self._w(gpt[1])
            hit = []
            for obs in self._obstacles:
                x0, y0, x1, y1 = obs[0], obs[1], obs[2], obs[3]
                owner = obs[4] if len(obs) > 4 else None
                if owner in (p1_owner, p2_owner):
                    continue
                if (x0 - c) <= wx <= (x1 + c) and (y0 - c) <= wy <= (y1 + c):
                    hit.append(owner or "?")
            if hit:
                for o in hit:
                    if o != "?":
                        blame.add(o)
                lg.error("%s[FAIL-DIAG]   %s world(%.2f,%.2f) внутри bbox: %s",
                         self.log_prefix, label, wx, wy, sorted(set(hit)))
            else:
                lg.error("%s[FAIL-DIAG]   %s world(%.2f,%.2f): свободен",
                         self.log_prefix, label, wx, wy)

        x1w, y1w = self._w(g1[0]), self._w(g1[1])
        x2w, y2w = self._w(g2[0]), self._w(g2[1])
        xmin, xmax = sorted((x1w, x2w))
        ymin, ymax = sorted((y1w, y2w))

        pins_in = []
        for (pgx, pgy) in self._pins:
            wx, wy = self._w(pgx), self._w(pgy)
            if (xmin - self.grid <= wx <= xmax + self.grid and
                    ymin - self.grid <= wy <= ymax + self.grid):
                if own_pins and (pgx, pgy) in own_pins:
                    continue
                pref = self._pin_refs.get((pgx, pgy))
                pins_in.append((pref or "?", round(wx, 2), round(wy, 2)))
        if pins_in:
            lg.error("%s[FAIL-DIAG]   %d чужих пинов в коридоре: %s",
                     self.log_prefix, len(pins_in), pins_in[:10])

        obs_in = []
        for obs in self._obstacles:
            x0, y0, x1, y1 = obs[0], obs[1], obs[2], obs[3]
            owner = obs[4] if len(obs) > 4 else None
            if owner in (p1_owner, p2_owner):
                continue
            if not (x1 < xmin - c or x0 > xmax + c or
                    y1 < ymin - c or y0 > ymax + c):
                obs_in.append((owner or "?",
                               round(x0, 1), round(y0, 1),
                               round(x1, 1), round(y1, 1)))
                if owner:
                    blame.add(owner)
        if obs_in:
            lg.error("%s[FAIL-DIAG]   %d bbox в коридоре: %s",
                     self.log_prefix, len(obs_in), obs_in[:10])

        self._last_fail_blame = blame
        self._flush()
        return blame

    def _simplify(self, path):
        if len(path) <= 2:
            return path
        out = [path[0]]
        for i in range(1, len(path) - 1):
            x1, y1 = out[-1]; x2, y2 = path[i]; x3, y3 = path[i+1]
            if (abs(x1-x2) < 1e-6 and abs(x2-x3) < 1e-6) or \
               (abs(y1-y2) < 1e-6 and abs(y2-y3) < 1e-6):
                continue
            out.append(path[i])
        out.append(path[-1])
        return out

# --- PATCHED-BY patch_router_final.py ---

# --- own_terminal_v54 ---
