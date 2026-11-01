# 1. HeatTrace research foundations

## 1.1 What HeatTrace asks

HeatTrace is a historical-event benchmark for a simulated data-center scheduler. It asks whether evaluations built from ordinary or event-blind time windows miss operational stress that appears during complete heatwaves. The historical part supplies temperature, wholesale price, demand/generation, and a production-average carbon-intensity proxy. The data center, workloads, deadlines, PUE, power cap, and scheduler actions are simulated.

A data center consumes electricity because processors, memory, storage, and networking perform computation, while cooling and electrical infrastructure remove heat and deliver power. Wholesale prices vary because demand, generator availability, fuel cost, congestion, and renewable output change hourly. The grid carbon proxy varies as the generation/consumption mix changes. Heat matters in the model because warmer ambient air makes cooling less efficient, raising PUE. With a fixed facility-power cap, more cooling overhead leaves less power for IT.

Carbon-aware scheduling moves flexible work toward forecast hours with lower `gCO2/kWh`, subject to arrival times, deadlines, and capacity. A deadline prevents the trivial answer “wait forever for the cleanest hour.” HeatTrace is interesting because a policy that looks equal to another during an ordinary window may separate when heat simultaneously increases overhead and reduces effective IT capacity.

## 1.2 Core equations and symbols

For hour \(t\), the implemented thermal model is

\[
e_t=\max(T_t-T_0,0),\qquad
\mathrm{PUE}_t=\min(p_0+s e_t,p_{\max}).
\]

- \(T_t\): observed or forecast ambient temperature in °C.
- \(T_0\): temperature threshold below which PUE stays at its base.
- \(e_t\): degrees above the threshold.
- \(p_0\): base PUE.
- \(s\): PUE increase per °C.
- \(p_{\max}\): cap on modeled PUE.

Power Usage Effectiveness is facility power divided by IT power. Thus

\[
P^{facility}_t=P^{IT}_t\mathrm{PUE}_t,qquad
E^{facility}_t=E^{IT}_t\mathrm{PUE}_t.
\]

Under a facility cap \(P^{cap}\), usable IT capacity is

\[
C^{eff}_t=\min(C^{nom}, P^{cap}/\mathrm{PUE}_t),
\]

where \(C^{nom}\) is nominal IT capacity. Cost and modeled carbon accounting are

\[
Cost=\sum_t E^{facility}_t L_t/1000,qquad
Carbon=\sum_t E^{facility}_t I_t/1000.
\]

Here \(L_t\) is CAISO day-ahead LMP in USD/MWh, \(I_t\) is EIA CISO production/consumption-average intensity in g/kWh, and the factors of 1,000 convert MWh pricing to kWh and grams to kilograms. This is accounting against proxies—not a retail bill, marginal emissions estimate, avoided-emissions claim, or causal grid response.

The source equations are in `src/heattrace/thermal/model.py`; realized scoring is in `src/heattrace/thermal/metrics.py` and `src/heattrace/evaluation/metrics.py`.

## 1.3 One numerical story

Take nominal IT capacity 500 kW, facility cap 600 kW, base PUE 1.20, threshold 22°C, slope 0.02/°C, temperature 32°C. Then excess temperature is 10°C and PUE is \(1.20+0.02(10)=1.40\). Effective IT capacity is \(\min(500,600/1.40)=428.57\) kW.

If a temperature-unaware scheduler requests 450 kW for one hour, modeled facility power is \(450(1.40)=630\) kW: 30 kW above the cap. If it instead executes 400 kWh of IT work in an hour priced at $50/MWh with intensity 300 g/kWh, facility energy is 560 kWh, proxy cost is \(560(50)/1000=$28\), and modeled carbon is \(560(300)/1000=168\) kg. At a cool hour with PUE 1.20, the same IT work uses 480 kWh, costs $24 at the same price, and accounts for 144 kg at the same intensity. If the cooler hour has a later deadline-compatible slot and a cleaner grid, shifting is even more attractive.

Observed inputs in that example would be temperature, price, and intensity. The 500/600 kW facility, PUE curve, 450 kW request, workload deadline, and scheduler decision are simulated.

## 1.4 Original and updated research questions

The v1 frozen primary question (`docs/p6_frozen_protocol.md`) was: under the power-capped model, does static scheduling have a lower tested maximum feasible workload in complete heatwaves than matched controls? Secondary questions asked whether awareness recovered feasibility and whether event-blind windows understated failures or ranking changes. The intended evidence was paired heatwave-minus-control effects across three frozen event triplets, with seeds aggregated inside events—not 756 independent observations.

Track B2 asks whether those benchmark effects replicate temporally and geographically across five California stations and 2022–2026 warm seasons, using station events nested inside regional episodes. Evidence for the broad claim would require repeated directionally consistent episode effects, valid station-specific forecasts, common workload support, equal completed service, and executed sensitivities. Evidence against it includes null boundary shifts, ordinary windows as discriminating as heatwaves, confidence intervals spanning zero, or failures to retain common support.

HeatTrace is therefore not merely “a temperature-aware scheduler.” Its main contribution is the evaluation lens: complete events, matched controls, ordinary/event-blind baselines, explicit thermal feasibility, provenance freezes, equal-service gates, and negative-result reporting. It does not currently validate a superior new scheduling algorithm.

## 1.5 Heatwave definition

For station \(j\), daily maximum \(M_{j,d}=\max_{t\in d}T_{j,t}\). The B2 threshold \(q_j\) is the empirical P90 of valid June–September daily maxima from 2022–2025, using linear interpolation. A qualifying day satisfies strict \(M_{j,d}>q_j\). Three or more consecutive qualifying local dates form one event; missing days break a run. The full scheduler window adds one local onset day before and one recovery day after. Regional episodes are connected components after expanding every event interval by 24 hours on both sides and linking overlaps. These rules are implemented in `src/heattrace/process/p12_b2_events.py`.

Example: threshold 35°C and daily maxima `[34, 36, 38, 37, 33]`. Days 2–4 strictly exceed the threshold, so they form a three-day event. Day 1 becomes onset and day 5 recovery. A day exactly 35°C would not qualify.

## 1.6 What would support or refute the work

Supporting evidence is scoped: repeated extra static cap-violation hours in heatwaves, lower grid-tested feasibility boundaries, or policy separation above a frozen ordinary-window tail under equal service. Refuting or limiting evidence is equally scientific: a null event, no boundary recovery, an uncertainty interval crossing zero, a calibrated guard no better than a fixed margin, or an unexecuted ablation. An unsupported hypothesis does not make the whole experiment invalid; a protocol violation does invalidate the affected comparison.

