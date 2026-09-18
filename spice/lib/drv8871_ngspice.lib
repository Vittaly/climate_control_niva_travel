* Поведенческая модель DRV8871 для ngspice
* Выводы: IN1 IN2 OUT1 OUT2 VM GND
.subckt DRV8871 IN1 IN2 OUT1 OUT2 VM GND

* Модели ключей (SW) для ngspice:
* Ron = 0.282 Ом (половина от суммарного RDS(on)=0.565 Ом из даташита)
* Vt = 1.4V (порог переключения логики), Vh = 0.4V (гистерезис)
.model SW_HS SW(Ron=0.282 Roff=1Meg Vt=1.4 Vh=0.4)
.model SW_LS SW(Ron=0.282 Roff=1Meg Vt=1.4 Vh=0.4)

* Синтаксис ключей ngspice: Sxxxx n+ n- nc+ nc- model
* Верхние ключи (High-Side) открываются, когда на входе HIGH
S_HS1 VM   OUT1 IN1 GND SW_HS
S_HS2 VM   OUT2 IN2 GND SW_HS

* Нижние ключи (Low-Side). В DRV8871 логика торможения/decay работает так:
* Если IN1=LOW, то OUT1 прижимается к GND. То есть нижний ключ инвертирован.
* Для ngspice инверсию делаем, меняя полярность управляющих узлов (GND и INx).
S_LS1 OUT1 GND  GND IN2 SW_LS
S_LS2 OUT2 GND  GND IN1 SW_LS

.ends DRV8871
