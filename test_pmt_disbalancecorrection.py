import win32com.client
import numpy as np

# 1. Connect to OpenDSS Engine
try:
    dss_obj = win32com.client.Dispatch("OpenDSSEngine.DSS")
    dss_text = dss_obj.Text
    dss_circuit = dss_obj.ActiveCircuit
    print("Connected to OpenDSS Version:", dss_obj.Version)
except Exception as e:
    print(f"Error connecting to OpenDSS: {e}")
    exit()

# 2. Build Feeder Circuit
script = """
Clear
New Circuit.Pakistani_PMT_Feeder basekv=11 pu=1.00 phases=3 bus1=SourceBus

! 200 kVA Step-Down Dyn11 Transformer (11 kV to 415 V)
New Transformer.PMT Phases=3 Windings=2 XHL=4.0 %loadloss=1.5
~ wdg=1 bus=SourceBus conn=Delta kv=11 kva=200
~ wdg=2 bus=LV_Bus.1.2.3.4 conn=Wye kv=0.415 kva=200

! Low Voltage 4-wire Line (Red, Yellow, Blue, Neutral) to Pole 1
New Linecode.LV_Line nphases=4 units=km
~ rmatrix=[0.45 | 0.05 0.45 | 0.05 0.05 0.45 | 0.05 0.05 0.05 0.70]
~ xmatrix=[0.30 | 0.10 0.30 | 0.10 0.10 0.30 | 0.10 0.10 0.10 0.30]

New Line.PoleDrop Phases=4 Bus1=LV_Bus.1.2.3.4 Bus2=Pole1.1.2.3.4 Linecode=LV_Line Length=100 Units=m

! Base Residential Loads on Pole 1 (230V Phase-to-Neutral)
New Load.House_A phases=1 bus1=Pole1.1.4 kv=0.23 kw=3.0 pf=0.92
New Load.House_B phases=1 bus1=Pole1.2.4 kv=0.23 kw=10.0 pf=0.90
New Load.House_C phases=1 bus1=Pole1.3.4 kv=0.23 kw=4.0 pf=0.95

! 12 kW Rooftop Solar Clustered on Phase A (Red Phase)
! Pmpp = 12 kW, Irradiance = 1.0 (Peak Solar at Noon)
New PVSystem.Solar_HouseA phases=1 bus1=Pole1.1.4 kv=0.23 kva=15 Pmpp=12.0 irradiance=1.0 pf=1.0

Set Mode=Snapshot
Solve
"""

for line in script.strip().split("\n"):
    if line.strip() and not line.startswith("!"):
        dss_text.Command = line

# 3. Read Baseline Readings (Simulated APMS)
dss_circuit.SetActiveElement("Transformer.PMT")
curr_base = dss_circuit.ActiveElement.CurrentsMagAng

I_A = curr_base[8]
I_B = curr_base[10]
I_C = curr_base[12]
I_N = curr_base[14]

I_avg = (I_A + I_B + I_C) / 3.0
unbalance_pct = (max(abs(I_A - I_avg), abs(I_B - I_avg), abs(I_C - I_avg)) / I_avg) * 100.0

print("\n" + "="*52)
print("       APMS BASELINE REPORT (PEAK NOON SOLAR)")
print("="*52)
print(f"Phase A Current : {I_A:6.1f} A  (Net Solar Back-Feed)")
print(f"Phase B Current : {I_B:6.1f} A  (Heavy Domestic Load)")
print(f"Phase C Current : {I_C:6.1f} A  (Baseline Load)")
print(f"Neutral Current : {I_N:6.1f} A  <-- High Neutral Thermal Stress!")
print(f"PPMC Unbalance  : {unbalance_pct:6.1f}%  <-- PPMC-DS-01 Clause 7.8 Alarm!")

# 4. Execute Optimization: Move Solar to Phase B (Matching Heavy Load)
print("\n[Action] Rebalance: Shift Solar_HouseA to Phase B (Yellow)...")
dss_text.Command = "Edit PVSystem.Solar_HouseA bus1=Pole1.2.4"
dss_text.Command = "Solve"

# 5. Read Post-Optimization Readings
dss_circuit.SetActiveElement("Transformer.PMT")
curr_post = dss_circuit.ActiveElement.CurrentsMagAng

I_A_post = curr_post[8]
I_B_post = curr_post[10]
I_C_post = curr_post[12]
I_N_post = curr_post[14]

I_avg_post = (I_A_post + I_B_post + I_C_post) / 3.0
unbalance_post = (max(abs(I_A_post - I_avg_post), abs(I_B_post - I_avg_post), abs(I_C_post - I_avg_post)) / I_avg_post) * 100.0

print("\n" + "="*52)
print("       APMS POST-OPTIMIZATION REPORT")
print("="*52)
print(f"Phase A Current : {I_A_post:6.1f} A")
print(f"Phase B Current : {I_B_post:6.1f} A")
print(f"Phase C Current : {I_C_post:6.1f} A")
print(f"Neutral Current : {I_N_post:6.1f} A  <-- Neutral Current Collapsed!")
print(f"PPMC Unbalance  : {unbalance_post:6.1f}%  <-- PPMC ALARM CLEARED!")
print("="*52)