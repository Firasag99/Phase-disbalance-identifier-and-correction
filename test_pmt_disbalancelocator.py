import numpy as np
import pandas as pd
from scipy.stats import pearsonr

# ==============================================================================
# 1. SYNTHETIC DISTRIBUTION NETWORK CONFIGURATION (PMT + LV FEEDER)
# ==============================================================================
np.random.seed(42)
time_steps = 24
hours = np.arange(time_steps)

# Grid nominal voltage: 230 V (Line-to-Neutral)
V_nom = 230.0

# Upstream 11 kV grid background drift (affects all phases simultaneously)
upstream_drift = 2.5 * np.sin(2 * np.pi * (hours - 6) / 24)

# Line & Transformer Impedances (Ohms)
# PMT internal equivalent impedance
R_pmt, X_pmt = 0.035, 0.060
# Feeder conductor impedance (0.4 km aluminium run)
R_line, X_line = 0.180, 0.040

# ==============================================================================
# 2. GENERATE REALISTIC CONSUMER LOAD PROFILES (kW & kVAR)
# ==============================================================================
# Diurnal domestic load shape (morning ramp + evening peak)
base_curve = np.array([
    0.3, 0.2, 0.2, 0.3, 0.5, 0.8, 1.2, 1.4, 1.0, 0.7, 0.6, 0.7,
    0.8, 1.1, 1.3, 1.6, 1.8, 1.5, 1.2, 1.0, 1.3, 1.1, 0.6, 0.3
])

home_true_phases = {
    "Home_1": 1,  # Phase A (Red)
    "Home_2": 2,  # Phase B (Yellow)
    "Home_3": 3   # Phase C (Blue)
}

# Base sanctioned load: 25 kW per home with distinct local random variations
profiles_P = {}
profiles_Q = {}

for home in home_true_phases.keys():
    noise = np.random.normal(0, 0.25, time_steps)
    p_kw = np.clip(base_curve + noise, 0.1, 2.5) * 25.0  # Active power (kW)
    q_kvar = p_kw * np.tan(np.arccos(0.90))               # 0.90 PF lagging
    
    profiles_P[home] = p_kw
    profiles_Q[home] = q_kvar

# Calculate total load aggregated at the PMT bus per phase
P_phase_pmt = {1: np.zeros(time_steps), 2: np.zeros(time_steps), 3: np.zeros(time_steps)}
Q_phase_pmt = {1: np.zeros(time_steps), 2: np.zeros(time_steps), 3: np.zeros(time_steps)}

for home, phase in home_true_phases.items():
    P_phase_pmt[phase] += profiles_P[home]
    Q_phase_pmt[phase] += profiles_Q[home]

# Add background passive neighborhood base-load on each phase
for p in [1, 2, 3]:
    P_phase_pmt[p] += np.random.normal(15.0, 1.0, time_steps)
    Q_phase_pmt[p] += 5.0

# ==============================================================================
# 3. COMPUTE PHYSICAL VOLTAGE DYNAMICS (PHYSICS ENGINE)
# ==============================================================================
# APMS Voltages at the Transformer Bushing
# V_apms = V_nom + upstream_drift - (P_tot * R_pmt + Q_tot * X_pmt) / V_nom
apms_data = {}
for p in [1, 2, 3]:
    dv_pmt = (P_phase_pmt[p] * 1000.0 * R_pmt + Q_phase_pmt[p] * 1000.0 * X_pmt) / V_nom
    sensor_noise = np.random.normal(0, 0.05, time_steps)
    apms_data[f"Phase_{p}"] = V_nom + upstream_drift - dv_pmt + sensor_noise

df_apms = pd.DataFrame(apms_data)

# Consumer Smart Meter Voltages at House Service Drop
# V_home = V_apms - (P_home * R_line + Q_home * X_line) / V_nom
meter_data = {}
for home, phase in home_true_phases.items():
    dv_line = (profiles_P[home] * 1000.0 * R_line + profiles_Q[home] * 1000.0 * X_line) / V_nom
    meter_noise = np.random.normal(0, 0.05, time_steps)
    meter_data[f"{home}_V"] = df_apms[f"Phase_{phase}"] - dv_line + meter_noise
    meter_data[f"{home}_P"] = profiles_P[home]

df_meters = pd.DataFrame(meter_data)

# Print explicit variance check to prove dynamic time series
print("--- TIME SERIES VARIANCE VERIFICATION ---")
print(f"Variance APMS Phase 1: {df_apms['Phase_1'].var():.4f} (must be > 0)")
print(f"Variance APMS Phase 2: {df_apms['Phase_2'].var():.4f} (must be > 0)")
print(f"Variance APMS Phase 3: {df_apms['Phase_3'].var():.4f} (must be > 0)")
print(f"Variance Home 1:        {df_meters['Home_1_V'].var():.4f} (must be > 0)")

# ==============================================================================
# 4. PHASE IDENTIFICATION VIA DELTA-V CROSS CORRELATION
# ==============================================================================
# First-order differences remove the common 11 kV upstream diurnal baseline
df_apms_diff = df_apms.diff().dropna()
df_meters_diff = df_meters[[f"{h}_V" for h in home_true_phases.keys()]].diff().dropna()

print("\n--- RUNNING PHASE IDENTIFICATION ALGORITHM ---")
phase_mapping_results = {}

for home in home_true_phases.keys():
    home_dv = df_meters_diff[f"{home}_V"]
    
    best_phase = None
    highest_correlation = -2.0 
    
    print(f"\nEvaluating Profiles for {home}:")
    for phase_num in range(1, 4):  
        apms_dv = df_apms_diff[f"Phase_{phase_num}"]
        
        # Pearson cross-correlation of Delta V
        r_val, _ = pearsonr(home_dv, apms_dv)
            
        print(f"  -> Testing vs APMS Phase {phase_num} | Voltage Delta Correlation (r): {r_val:7.4f}")
        
        if r_val > highest_correlation:
            highest_correlation = r_val
            best_phase = phase_num
            
    phase_mapping_results[home] = best_phase
    print(f"  Decision Verdict: Connected to Phase {best_phase}")

# ==============================================================================
# 5. SIMULATION VALIDATION RESULTS
# ==============================================================================
print("\n==============================================")
print("--- SIMULATION VALIDATION RESULTS ---")
print("==============================================")
phase_names = {1: "A", 2: "B", 3: "C"}

for home, assigned_phase in phase_mapping_results.items():
    true_p = phase_names[home_true_phases[home]]
    calc_p = phase_names[assigned_phase] if assigned_phase else "None"
    status = "SUCCESS ✅" if true_p == calc_p else "FAILED ❌"
    print(f"{home:7s} -> True Phase: {true_p} | Calculated Phase: {calc_p} | Status Check: {status}")
print("==============================================\n")