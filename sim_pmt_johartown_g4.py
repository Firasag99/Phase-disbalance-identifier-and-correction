import numpy as np
import pandas as pd
from scipy.stats import pearsonr
import itertools

# ==============================================================================
# 1. PHYSICAL GRID SETUP: LESCO JOHAR TOWN G4 (200 kVA PMT, 42 CONSUMERS)
# ==============================================================================
np.random.seed(42)
time_steps = 24
hours = np.arange(time_steps)

FEEDER_NAME = "11 kV Khokhar Chowk Feeder (LESCO Johar Town Sub-Division)"
PMT_ID = "PMT-JT-G4-014 (200 kVA Dyn11, Streets 6 & 7, Block G4, Johar Town)"
V_nom = 230.0  # Nominal Line-to-Neutral Voltage (V)
PPMC_UNBALANCE_ALARM_LIMIT = 20.0  # PPMC-DS-01 Clause 7.9 Threshold (%)

# 11 kV upstream grid diurnal drift (V)
upstream_drift = 2.8 * np.sin(2 * np.pi * (hours - 6) / 24)

# Impedance parameters (Ohms)
R_pmt, X_pmt = 0.035, 0.060     # 200 kVA Dyn11 transformer internal impedance
R_line_base, X_line_base = 0.120, 0.035  # Distribution line impedance base

phase_labels = {1: "Phase A (Red)", 2: "Phase B (Yellow)", 3: "Phase C (Blue)"}

# ==============================================================================
# 2. GENERATE 42 REALISTIC CONSUMERS (1-KANAL, 10-MARLA, COMMERCIAL, & SOLAR)
# ==============================================================================
# Base summer residential load curve (Lahore diurnal shape)
base_curve = np.array([
    0.35, 0.25, 0.20, 0.20, 0.30, 0.55, 0.85, 1.10, 1.25, 1.30, 1.35, 1.45,
    1.50, 1.45, 1.40, 1.55, 1.75, 1.85, 1.60, 1.40, 1.35, 1.20, 0.80, 0.50
])

# Create 40 residential plots + 2 corner commercial shops
consumers = {}
true_phase_mapping = {}

# Distribution: Linemen historically hooked up homes arbitrarily
# Phase A: 14 homes (heavily saturated with net-metered solar)
# Phase B: 14 homes (heavy domestic AC loads, low solar)
# Phase C: 14 homes (moderate mixed loads)

# 1. Generate Phase A Consumers (High Solar Cluster: Houses 1 to 14)
for i in range(1, 15):
    cid = f"House_{i:02d}_G4"
    true_phase_mapping[cid] = 1
    # 7 of these 14 homes have 10-15 kW rooftop solar
    has_solar = i in [2, 4, 6, 8, 10, 12, 14]
    solar_size = np.random.choice([10.0, 12.0, 15.0]) if has_solar else 0.0
    base_load = np.random.uniform(3.5, 6.0) # kW baseline
    consumers[cid] = {"phase": 1, "solar_kw": solar_size, "base_kw": base_load, "distance_m": 50 + i * 20}

# 2. Generate Phase B Consumers (Heavy AC / Non-Solar Cluster: Houses 15 to 28)
for i in range(15, 29):
    cid = f"House_{i:02d}_G4"
    true_phase_mapping[cid] = 2
    # Only 2 homes have small solar
    has_solar = i in [16, 22]
    solar_size = 5.0 if has_solar else 0.0
    base_load = np.random.uniform(5.5, 9.5) # Heavy AC consumption
    consumers[cid] = {"phase": 2, "solar_kw": solar_size, "base_kw": base_load, "distance_m": 50 + (i-14) * 20}

# 3. Generate Phase C Consumers (Mixed Residential + 2 Shops: Houses 29 to 42)
for i in range(29, 41):
    cid = f"House_{i:02d}_G4"
    true_phase_mapping[cid] = 3
    has_solar = i in [31, 35, 39]
    solar_size = np.random.choice([7.0, 10.0]) if has_solar else 0.0
    base_load = np.random.uniform(4.0, 7.0)
    consumers[cid] = {"phase": 3, "solar_kw": solar_size, "base_kw": base_load, "distance_m": 50 + (i-28) * 20}

# Add 2 Commercial Shops on Phase C (Corner Grocery & Bakery running chillers)
consumers["Shop_01_G4"] = {"phase": 3, "solar_kw": 0.0, "base_kw": 8.5, "distance_m": 30}
consumers["Shop_02_G4"] = {"phase": 3, "solar_kw": 0.0, "base_kw": 6.5, "distance_m": 40}
true_phase_mapping["Shop_01_G4"] = 3
true_phase_mapping["Shop_02_G4"] = 3

# Compute diurnal 24-hr Active (P) and Reactive (Q) profiles
profiles_P = {}
profiles_Q = {}
solar_bell = np.zeros(time_steps)
solar_bell[7:18] = np.sin(np.pi * (np.arange(7, 18) - 7) / 10.0)

for cid, info in consumers.items():
    noise = np.random.normal(0, 0.08, time_steps)
    load_p = np.clip(base_curve * info["base_kw"] + noise, 0.5, 25.0)
    solar_gen = solar_bell * info["solar_kw"]
    
    net_p = load_p - solar_gen  # Negative = Exporting back to PMT
    net_q = np.maximum(load_p, 0.0) * np.tan(np.arccos(0.90)) # Inverters export at unity PF
    
    profiles_P[cid] = net_p
    profiles_Q[cid] = net_q

# ==============================================================================
# 3. TRANSFORMER BUS & CONSUMER METER SENSOR SYNTHESIS
# ==============================================================================
P_phase_pmt = {1: np.zeros(time_steps), 2: np.zeros(time_steps), 3: np.zeros(time_steps)}
Q_phase_pmt = {1: np.zeros(time_steps), 2: np.zeros(time_steps), 3: np.zeros(time_steps)}

for cid, phase in true_phase_mapping.items():
    P_phase_pmt[phase] += profiles_P[cid]
    Q_phase_pmt[phase] += profiles_Q[cid]

# Transformer secondary bus voltage (APMS Node)
apms_voltages = {}
for p in [1, 2, 3]:
    dv_pmt = (P_phase_pmt[p] * 1000.0 * R_pmt + Q_phase_pmt[p] * 1000.0 * X_pmt) / V_nom
    sensor_noise = np.random.normal(0, 0.03, time_steps)
    apms_voltages[f"Phase_{p}"] = V_nom + upstream_drift - dv_pmt + sensor_noise

df_apms = pd.DataFrame(apms_voltages)

# Consumer Smart Meter measurements at the house wall
meter_data = {}
for cid, phase in true_phase_mapping.items():
    dist_factor = consumers[cid]["distance_m"] / 300.0
    r_wire = R_line_base * dist_factor
    x_wire = X_line_base * dist_factor
    dv_line = (profiles_P[cid] * 1000.0 * r_wire + profiles_Q[cid] * 1000.0 * x_wire) / V_nom
    meter_noise = np.random.normal(0, 0.03, time_steps)
    meter_data[f"{cid}_V"] = df_apms[f"Phase_{phase}"] - dv_line + meter_noise

df_meters = pd.DataFrame(meter_data)

# ==============================================================================
# 4. MODULE 1: PHASE IDENTIFICATION ENGINE (PEARSON CORRELATION)
# ==============================================================================
print("=" * 80)
print(f"MODULE 1: RECONSTRUCTING PHASE TOPOLOGY (AMI + APMS CORRELATION)")
print(f"ASSET: {PMT_ID} | TOTAL CONSUMERS: {len(true_phase_mapping)}")
print("=" * 80)

df_apms_diff = df_apms.diff().dropna()
df_meters_diff = df_meters.diff().dropna()

identified_phases = {}
correct_count = 0

for cid in true_phase_mapping.keys():
    home_dv = df_meters_diff[f"{cid}_V"]
    correlations = {}

    for p in range(1, 4):
        apms_dv = df_apms_diff[f"Phase_{p}"]
        r_val, _ = pearsonr(home_dv, apms_dv)
        correlations[p] = r_val

    ranked = sorted(correlations.items(), key=lambda item: item[1], reverse=True)
    best_p, best_r = ranked[0]
    second_p, second_r = ranked[1]
    margin = best_r - second_r

    identified_phases[cid] = best_p
    if best_p == true_phase_mapping[cid]:
        correct_count += 1

print(f"Phase Mapping Completed: {correct_count}/{len(true_phase_mapping)} consumers mapped correctly ({(correct_count/len(true_phase_mapping))*100:.1f}% Accuracy)")
print("Sample Mappings:")
for cid in ["House_02_G4", "House_18_G4", "House_34_G4", "Shop_01_G4"]:
    print(f"  -> {cid:12s}: Mapped to {phase_labels[identified_phases[cid]]}")

# ==============================================================================
# 5. MODULE 2: PPMC-DS-01 CLAUSE 7.8 CURRENT UNBALANCE AUDIT (1:00 PM NOON)
# ==============================================================================
print("\n" + "=" * 80)
print("MODULE 2: PPMC-DS-01 CLAUSE 7.8 CURRENT UNBALANCE & PMT THERMAL AUDIT")
print("=" * 80)

noon = 13  # 1:00 PM Summer Peak

def calculate_grid_state(phase_assignment):
    P_agg = {1: 0.0, 2: 0.0, 3: 0.0}
    Q_agg = {1: 0.0, 2: 0.0, 3: 0.0}

    for c, p in phase_assignment.items():
        P_agg[p] += profiles_P[c][noon]
        Q_agg[p] += profiles_Q[c][noon]

    angles = {1: 0.0, 2: -2.0 * np.pi / 3.0, 3: 2.0 * np.pi / 3.0}
    I_phasors = {}
    I_mag = {}

    for p in [1, 2, 3]:
        S_complex = (P_agg[p] * 1000.0) + 1j * (Q_agg[p] * 1000.0)
        V_phasor = V_nom * np.exp(1j * angles[p])
        I_phasor = np.conj(S_complex / V_phasor)
        I_phasors[p] = I_phasor
        I_mag[p] = np.abs(I_phasor)

    # Neutral return current vector sum
    I_neutral = np.abs(I_phasors[1] + I_phasors[2] + I_phasors[3])

    # Current Unbalance %
    I_avg = (I_mag[1] + I_mag[2] + I_mag[3]) / 3.0
    unbalance_pct = (max(abs(I_mag[1] - I_avg), abs(I_mag[2] - I_avg), abs(I_mag[3] - I_avg)) / I_avg) * 100.0

    return I_mag, I_neutral, unbalance_pct, P_agg

I_mag_base, I_N_base, unbalance_base, P_agg_base = calculate_grid_state(identified_phases)

print(f"Operational Readings at PMT Secondary (1:00 PM Peak Heat & Solar):")
print(f"  * Total Active Feeder Load: {P_agg_base[1] + P_agg_base[2] + P_agg_base[3]:5.1f} kW ({(P_agg_base[1] + P_agg_base[2] + P_agg_base[3])/200.0*100:.1f}% PMT Capacity)")
print(f"  * Phase A (Red) Current   : {I_mag_base[1]:6.1f} A  (Net P: {P_agg_base[1]:5.1f} kW - Solar Back-Feed suppression)")
print(f"  * Phase B (Yellow) Current: {I_mag_base[2]:6.1f} A  (Net P: {P_agg_base[2]:5.1f} kW - Heavy Cooling Load)")
print(f"  * Phase C (Blue) Current  : {I_mag_base[3]:6.1f} A  (Net P: {P_agg_base[3]:5.1f} kW - Mixed Domestic/Shops)")
print(f"  * Neutral Return Current  : {I_N_base:6.1f} A  <-- High Continuous Neutral Lug Heating")
print(f"  * Current Unbalance       : {unbalance_base:6.1f}%")

if unbalance_base > PPMC_UNBALANCE_ALARM_LIMIT:
    print(f"  * PPMC-DS-01 Status       : ALARM TRIGGERED 🚨 (Limit: {PPMC_UNBALANCE_ALARM_LIMIT}% breached)")
    print(f"  * Clause 7.9/13.6 Action  : SMCD Logs Alarm Event; MCCB remains closed")

# ==============================================================================
# 6. MODULE 3 & 4: TARGETED SPARSE REBALANCING OPTIMIZER
# ==============================================================================
print("\n" + "=" * 80)
print("MODULE 3 & 4: TARGETED REBALANCING (MINIMAL LINEMAN INTERVENTIONS)")
print("=" * 80)

# Evaluate moving heavy exporters from Phase A into heavily loaded Phase B
candidates = []
exporters_on_A = [cid for cid, p in identified_phases.items() if p == 1 and profiles_P[cid][noon] < -3.0]

for c1 in exporters_on_A:
    test_cfg = identified_phases.copy()
    test_cfg[c1] = 2  # Shift to Phase B
    i_m, i_n, unbal, _ = calculate_grid_state(test_cfg)
    candidates.append((unbal, i_n, [(c1, 1, 2)], test_cfg))

# Also test shifting two high-export houses to Phase B & Phase C
for c1, c2 in itertools.combinations(exporters_on_A, 2):
    test_cfg = identified_phases.copy()
    test_cfg[c1] = 2  # Shift to Phase B
    test_cfg[c2] = 3  # Shift to Phase C
    i_m, i_n, unbal, _ = calculate_grid_state(test_cfg)
    candidates.append((unbal, i_n, [(c1, 1, 2), (c2, 1, 3)], test_cfg))

candidates.sort(key=lambda x: (x[1] + x[0])) # Minimize Neutral Current + Unbalance
best_unbal, best_in, best_steps, best_config = candidates[0]

i_mag_opt, in_opt, unbal_opt, P_agg_opt = calculate_grid_state(best_config)

print("\n" + "#" * 80)
print("            LESCO SUB-DIVISION FIELD CREW WORK TICKET")
print("#" * 80)
print(f"SUB-DIVISION       : LESCO Johar Town Sub-Division (Feeder: Khokhar Chowk)")
print(f"TARGET ASSET       : {PMT_ID}")
print(f"TOTAL ACTIONS      : {len(best_steps)} Drop Cable Shift(s) across {len(true_phase_mapping)} consumers")

for idx, step in enumerate(best_steps, 1):
    cid, from_p, to_p = step
    exp_val = abs(profiles_P[cid][noon])
    print(f"  Step {idx}: Shift drop clamp of {cid} ({exp_val:.1f} kW solar export) on Pole drop")
    print(f"          from {phase_labels[from_p]}  -->  {phase_labels[to_p]}")

print("-" * 80)
print("PROJECTED POST-CORRECTION AUDIT (AT PMT BUSHING):")
print(f"  * Phase A Current : {i_mag_opt[1]:5.1f} A")
print(f"  * Phase B Current : {i_mag_opt[2]:5.1f} A  (Solar export directly absorbs neighbor ACs!)")
print(f"  * Phase C Current : {i_mag_opt[3]:5.1f} A")
print(f"  * Neutral Current : {in_opt:5.1f} A (Baseline: {I_N_base:.1f} A | Drop: {I_N_base - in_opt:.1f} A!)")
print(f"  * Current Unbalance: {unbal_opt:5.1f}%")

if unbal_opt <= PPMC_UNBALANCE_ALARM_LIMIT:
    print(f"  * PPMC-DS-01 Status: ALARM CLEARED ✅ (Within statutory 20% limit)")
else:
    print(f"  * PPMC-DS-01 Status: Significantly Reduced ({unbal_opt:.1f}%)")
print("#" * 80)