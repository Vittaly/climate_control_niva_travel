# Сквозной тестовый прогон через эмулятор Ngspice — `run_e2e.py`

Единая точка входа для полного цикла тестирования аналоговой части схемы:
экспорт нетлистов → генерация `.cir` → прогон в эмуляторе → PASS/FAIL.

Скрипт — **оркестратор**: не дублирует логику, а по шагам вызывает уже
имеющиеся скрипты/утилиты с нужными параметрами.

## Что вызывает

| Шаг | Инструмент | Назначение |
|---|---|---|
| 1. Экспорт | `kicad-cli sch export netlist` | для каждого листа из `circuit_model.json` → `spice/<SHEET>.net` |
| 2. Генерация | `kicad_to_spice.py <net> <SHEET> <порты…>` | `spice/<SHEET>.sub` (субсхема) + `spice/<SCEN>.cir` (по сценарию) |
| 3. Эмулятор | `run_tests.py` | `ngspice -b <SCEN>.cir` для всех, разбор `v(node)=…`/`i(src)=…`/`let`-векторов, печать PASS/FAIL |

Порты субсхемы берутся прямо из экспортированного нетлиста (все цепи листа + `GND`),
чтобы любой узел сценария был доступен как внешний вывод тестовой обвязки.
Внутренние no-connect цепи KiCad (`unconnected-(…)`) отбрасываются — их имена невалидны для SPICE.

## Запуск (из корня проекта)

```bash
python3 run_e2e.py               # полный цикл: экспорт + генерация + прогон
python3 run_e2e.py --gen         # только экспорт + генерация .cir (без прогона)
python3 run_e2e.py --run         # только прогон уже сгенерированных .cir
python3 run_e2e.py --sheet PWR   # генерировать только лист PWR
```

Код возврата: `0` — все сценарии PASS, иначе число провалов.
Подходит для CI: `python3 run_e2e.py && echo "все зелёные"`.

## Сценарии (23/23)

Покрытие и допуски — в `CHECKS` (внутри `run_tests.py`) и `SCENARIOS`/`scenarios_pwr()`
(внутри `kicad_to_spice.py`), описание в `TEST_SCENARIOS_NGSPICE.md`.

| Лист | Сценарии |
|---|---|
| PWR | P1 переполюсовка, P2 load-dump/TVS, P3 наводка, P4 КЗ шины, P6 обратный +12В |
| UI | TEMP, FAN, ILLUM |
| SEN_HEAT | HOT, COLD |
| SEN_SOLAR / SEN_COND | MID (2,5В → 1,65В) |
| ACT | M1_FWD (H-мост) |
| OUT | FAN_ON, FAN_OFF (буфер ШИМ) |
| CAN | RECESSIVE, DOMINANT |
| SEN_CABIN | FAN (вентилятор продувки) |
| FAN_KEY | STEADY (15А), STARTUP (30А), PWM 4кГц (завал затвора / freewheel / ток затвора) |

## Пример вывода

```
== 1. Экспорт нетлистов (kicad-cli) ==
  PWR          rc=0 -> spice/PWR.net
...
== 2. Генерация .sub/.cir (kicad_to_spice.py) ==
  PWR          rc=0 (портов: 33)
  OK -> spice/PWR.sub + 5 сценариев
...
== 3. Эмулятор Ngspice + проверка (run_tests.py) ==
PWR_P1         PASS  v(v(vbat_prot))=-3.577e-01  [0..1] переполюсовка: VBAT_PROT≈0
ACT_M1_FWD     PASS  v(v(motor_1_a))=+1.440e+01  [11..15] H-мост: OUT1 под напряжением
FAN_KEY_PWM     PASS  v(vgsmax)=+1.050e+01  [8..11.5] 4кГц: завал фронтов затвора (Vgs<12В)
...
Итого PASS: 23/23
```

`run_tests.py` запускает только файлы из `CHECKS` (сценарии тестирования); остальные
`.cir` в `spice/` игнорируются, а отсутствующий сценарий помечается `MISSING`.
Лишние/старые `.cir` удалены из `spice/` — там остаются только сценарии.

## Расширение сценария

1. Добавить сценарий в `SCENARIOS`/`scenarios_pwr()` (`kicad_to_spice.py`) — возбуждение и `print`.
2. Добавить допуск в `CHECKS` (`run_tests.py`) — `<сценарий>: ("v(node)", min, max, "описание")`.
3. `python3 run_e2e.py --sheet <ЛИСТ>`.

## Зависимости

- `ngspice` в PATH;
- `kicad-cli` (KiCad ≥ 7);
- модели: `motor_model.lab`, `hyg012n03_ngspice.lib`, `drv8871_ngspice.lib`,
  `mcp2562_ngspice.lib`, `mc78m05_ngspice.lib`, `ams1117_33_ngspice.lib` (в корне проекта);
- актуальная иерархия листов (`circuit_model.json` → `sheets`); FAN_KEY — отдельная схема.