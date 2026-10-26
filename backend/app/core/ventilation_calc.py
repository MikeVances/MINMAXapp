"""
CIGR-based ventilation rate calculations for broilers.

Minimum ventilation (CO₂ method):
  Source: CIGR Report No. 2 "Climatization of Animal Houses", 1984 (revised 1999)

  H_total = 10.62 × W^0.75  [W/bird],  W = live weight in kg
  VCO₂    = H_total × 0.153  [L/h/bird]
             (RQ = 0.85, mixed broiler diet; heat equivalent ≈ 20 kJ/L O₂)
  q_min   = VCO₂ / 2.6 × safety_factor  [m³/h/bird]
             ΔCO₂ = 3 000 − 400 = 2 600 ppm = 2.6 L/m³

Maximum ventilation is NOT a per-bird norm: the tunnel airflow is a property of
the house (v_tunnel × S_cross × 3 600, see calc_core.compute) and does not scale
with the number of birds placed.

Note: the coefficient 6.90 used in calc_core / building_thermal is sensible heat only
(~65 % of total) and is NOT used here — CO₂ production requires total metabolic heat.
"""
from __future__ import annotations

from .bird_heat import BROILER, total_heat_20c_w

# ── CIGR 1984 constants ──────────────────────────────────────────────────────
CIGR_HEAT_COEFF = 10.62   # W per (kg live weight)^0.75 — total metabolic heat
CO2_PER_WATT    = 0.153   # L CO₂ per W·h  (RQ = 0.85, ~20 kJ per L O₂)
DELTA_CO2       = 2.6     # L/m³  (3 000 ppm indoor target − 400 ppm ambient)


def calc_q_min_per_bird(weight_kg: float, safety_factor: float = 1.5, species: str = BROILER) -> float:
    """
    Minimum ventilation per bird from CO₂ production (CIGR 1984).

    safety_factor covers:
      - moisture from litter (typically 2–3× bird respiratory moisture)
      - air distribution inefficiency (~10–15%)
      - operational margin
    Typical value: 1.5 (conservative), 1.2 (tight houses with good air mixing).

    Args:
        weight_kg:     Live body weight, kg
        safety_factor: Multiplier applied to CO₂-derived minimum (≥ 1.0)
        species:       bird_heat.BROILER | TURKEY — закон полного тепла по виду птицы
                       (CO₂ на ватт — обмен веществ вообще, он от вида не зависит)

    Returns:
        q_min in m³/h per bird
    """
    W       = max(weight_kg, 0.001)
    H_total = total_heat_20c_w(W, species)         # W/bird
    VCO2    = H_total * CO2_PER_WATT               # L CO₂/h/bird
    q_min   = (VCO2 / DELTA_CO2) * safety_factor   # m³/h/bird
    return round(q_min, 3)
