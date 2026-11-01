# 5. Thermal, workload, scheduling, forecasting, cost, and carbon mathematics

## 5.1 Thermal curves

The presets in `thermal/facility.py` share base PUE 1.20 and threshold 22°C. Low uses slope 0.01 and max 1.45; medium 0.02 and max 1.70; high 0.03 and max 2.00. In B2 the 100 kW nominal facility derives a base cap of 120 kW. The 500/600 kW teaching example is the same ratio.

At 32°C on medium, PUE 1.40 and 500 kW nominal becomes 428.57 kW effective under a 600 kW cap. A request of 450 kW needs 630 kW facility power. Static scheduling may request it because it plans against nominal constraints; realized scoring records the 30 kW excess. A capacity-aware scheduler limits forecast allocations, but forecast error can still cause realized violations.

Energy-only is an accounting model: effective compute remains nominal while the effective facility cap tracks PUE, so it cannot show cap violations by construction. It is not a physical “unlimited cooling” observation.

## 5.2 Jobs and service

A job \(i\) has release \(a_i\), exclusive deadline \(d_i\), processing slots \(r_i\), total IT energy \(e_i\), and parallelism. An allocation \(x_{i,t}\) is legal only for \(a_i\le t<d_i\). Completion requires \(\sum_t x_{i,t}=r_i\). Demanded slots equal completed plus unfinished. Two policies receive identical jobs but may complete different work because one throttles to forecast capacity or makes choices that leave insufficient future slots. Therefore identical input is not equal service; comparisons of cost/carbon require equal completed work.

## 5.3 Greedy allocation and rolling execution

At an origin, the generic carbon-first policy sorts deadline-feasible hours by forecast carbon; cost-first sorts by forecast price. It greedily allocates required units while respecting nominal job/cluster constraints. Capacity-aware variants then keep and repair allocations against hourly effective capacity. B2 repeats this with a 24-hour look-ahead and commits the current hour only, then advances one hour. Jobs with deadlines beyond the horizon are represented through the runner’s reservation rules. This is receding-horizon greedy scheduling, not global optimal control.

Four-hour example: one two-slot job arrives at 0, deadline 4. Forecast carbon is `[400,100,150,300]`, price `[20,80,30,25]`, capacities `[1,1,1,1]`. Carbon-first chooses hours 1 and 2; cost-first chooses 0 and 3. If hour 1 heat reduces capacity to zero, static still plans 1+2 and violates/loses service; capacity-aware repairs to 2+3 if forecast knows it; full thermal-aware also multiplies signals by forecast PUE, potentially changing the order. Oracle uses realized data and represents hindsight, not deployability.

## 5.4 TinyLSTM

An LSTM is a recurrent neural network with gated memory that can retain temporal patterns. HeatTrace supplies 72 historical hours, each with five features: standardized temperature, sine/cosine hour-of-day, and sine/cosine day-of-year. `TinyTemperatureLSTM` is one unidirectional layer, input size 5, hidden size 32, final hidden state, dropout 0.1, and a linear 32→24 head.

The scaler mean/std is fitted only on training observations. The frozen contract uses AdamW, learning rate 0.001, SmoothL1 loss, batch 64, maximum 50 epochs, and early stopping patience 5. Checkpoints include architecture, scaler, split/config hashes, and weights. `evaluation_metrics.csv` reports RMSE/MAE; the v1 development report records heatwave TinyLSTM RMSE 5.81°C versus 3.69°C for the relevant baseline. Accuracy alone does not establish scheduling regret: one needs the same scheduler with forecast source substituted and hourly allocations retained.

Previous-day persistence returns the last 24 historical hours: target \(t+h\) uses observation \(t+h-24\), so all values are known at origin. This was B2’s declared fallback if leakage-safe station-specific models were unavailable.

## 5.5 HeatGuard calibration

For calibration origin \(o\), horizon \(h\), forecast and realized PUE give residual

\[
r_{o,h}=\max(0,\mathrm{PUE}^{real}_{o,h}-\mathrm{PUE}^{forecast}_{o,h}).
\]

The calibrated margin is a past-only 90th percentile using the frozen `higher` method. Guarded PUE is forecast PUE plus margin (subject to model bounds), so safe capacity is cap divided by guarded PUE. Fixed HeatGuard uses margin 0.10. A larger margin reduces scheduled IT capacity; it can reduce violations but also strand capacity and miss work. It is a heuristic quantile buffer, not formal distributionally robust optimization or a probabilistic guarantee.

## 5.6 Realized scoring

Scheduling objectives use forecasts, but final scores use realized temperature/PUE, price, and carbon proxy. IT energy is derived from committed job allocations. Cooling energy is facility minus IT energy. A cap violation hour has realized facility power above cap (tolerance 1e-6); maximum exceedance measures its worst magnitude.

Supported interpretation: modeled energy, wholesale-price proxy cost, and average production/consumption-based carbon accounting under the synthetic workload/facility. Unsupported: retail cost, marginal emissions, avoided emissions, grid causal response, real data-center performance, or a causal effect of forecasting.

