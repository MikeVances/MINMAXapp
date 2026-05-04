"""
CIGR-based ventilation rate calculations for broilers.

Minimum ventilation (CO₂ method):
  Source: CIGR Report No. 2 "Climatization of Animal Houses", 1984 (revised 1999)

  H_total = 10.62 × W^0.75  [W/bird],  W = live weight in kg
  VCO₂    = H_total × 0.153  [L/h/bird]
             (RQ = 0.85, mixed broiler diet; heat equivalent ≈ 20 kJ/L O₂)
  q_min   = VCO₂ / 2.6 × safety_factor  [m³/h/bird]
             ΔCO₂ = 3 000 − 400 = 2 600 ppm = 2.6 L/m³

Maximum ventilation (tunnel airspeed method):
  q_max = v_tunnel × S_cross × 3 600 / N_birds  [m³/h/bird]
  S_cross = house width × effective height  [m²]

Note: the coefficient 6.90 used in calc_core / building_thermal is sensible heat only
(~65 % of total) and is NOT used here — CO₂ production requires total metabolic heat.
"""
from __future__ import annotations

# ── CIGR 1984 constants ──────────────────────────────────────────────────────
CIGR_HEAT_COEFF = 10.62   # W per (kg live weight)^0.75 — total metabolic heat
CO2_PER_WATT    = 0.153   # L CO₂ per W·h  (RQ = 0.85, ~20 kJ per L O₂)
DELTA_CO2       = 2.6     # L/m³  (3 000 ppm indoor target − 400 ppm ambient)


def calc_q_min_per_bird(weight_kg: float, safety_factor: float = 1.5) -> float:
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

    Returns:
        q_min in m³/h per bird
    """
    W       = max(weight_kg, 0.001)
    H_total = CIGR_HEAT_COEFF * (W ** 0.75)        # W/bird
    VCO2    = H_total * CO2_PER_WATT               # L CO₂/h/bird
    q_min   = (VCO2 / DELTA_CO2) * safety_factor   # m³/h/bird
    return round(q_min, 3)


def calc_q_max_per_bird(
    width_m: float,
    height_m: float,
    n_birds: float,
    v_tunnel_ms: float = 2.5,
) -> float:
    """
    Maximum ventilation per bird from tunnel airspeed target.

    Industry standard: 2.0–2.5 m/s at bird level for effective wind-chill.
    Above 3.0 m/s birds experience airstream stress (Aviagen 2019).

    Args:
        width_m:     House width, m
        height_m:    Effective cross-section height, m (≈ 70–85% of wall height)
        n_birds:     Number of birds alive on this day
        v_tunnel_ms: Target tunnel airspeed, m/s (default 2.5)

    Returns:
        q_max in m³/h per bird
    """
    S_cross = width_m * height_m
    q_max   = v_tunnel_ms * S_cross * 3600.0 / max(n_birds, 1.0)
    return round(q_max, 3)
