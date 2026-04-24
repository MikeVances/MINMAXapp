from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.profile_loader import get_profile
from ..core.calc_core import compute, CalcInput


router = APIRouter()


class CalcIn(BaseModel):
    house: str = Field(..., min_length=1, max_length=64)
    birds: int = Field(..., ge=1, le=60000)
    age_days: int = Field(..., ge=1, le=42)
    mode_id: str = Field(..., pattern=r"^(winter|summer|spring_autumn|tropical)$")
    display_unit: str = Field("per_bird", pattern=r"^(per_bird|per_kg)$")
    outside_t: float = Field(..., ge=-40, le=50, description="Outside air temperature, °C")
    heater_on: bool = Field(False, description="Heater correction enabled")
    user_max_m3h: float | None = Field(None, ge=0, description="System maximum capacity (m3/hour). Optional")


class CalcOut(BaseModel):
    q_min_m3h: float
    q_max_m3h: float  # final (capped if capacity provided)
    q_max_nominal_m3h: float  # before capacity capping
    basis_used: str
    weight_used_g: float
    profile_day_resolved: int
    rates: dict
    day_setpoints: dict | None = None  # {min_temp_c, rv_percent}
    heater_air_m3h: float | None = None  # Additional air for gas heaters
    heater_duty_cycle: float | None = None  # Heater duty cycle (0..1)
    ref_version: str = "seed-demo-1.0"


@router.post("/minmax", response_model=CalcOut)
def minmax(payload: CalcIn):
    try:
        profile = get_profile(seed_path="data/vent_profile_seed.json")
    except Exception:
        # Фоллбэк на демо-профиль, если seed не найден
        profile = get_profile(seed_path=None)

    ci = CalcInput(
        birds=payload.birds,
        age_days=payload.age_days,
        mode=payload.mode_id,  # type: ignore
        display_unit=payload.display_unit,  # type: ignore
        outside_t=payload.outside_t,
        heater_on=payload.heater_on,
    )

    try:
        cr = compute(profile, ci)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))

    q_min = round(cr.q_min_m3h, 3)
    q_max_nominal = round(cr.q_max_m3h, 3)
    q_max_final = q_max_nominal
    if payload.user_max_m3h is not None:
        q_max_final = min(q_max_nominal, float(payload.user_max_m3h))
        # гарантируем, что min не превышает допустимый max
        q_min = min(q_min, q_max_final)

    return CalcOut(
        q_min_m3h=q_min,
        q_max_m3h=q_max_final,
        q_max_nominal_m3h=q_max_nominal,
        basis_used=cr.basis_used,
        weight_used_g=cr.weight_used_g,
        profile_day_resolved=cr.profile_day_resolved,
        rates={
            "per_bird": {
                "min": round(cr.rates_per_bird_min, 4),
                "max": round(cr.rates_per_bird_max, 4),
            },
            "per_kg": {
                "min": round(cr.rates_per_kg_min, 4),
                "max": round(cr.rates_per_kg_max, 4),
            },
        },
        day_setpoints=(
            {
                "min_temp_c": cr.min_temp_c,
                "rv_percent": cr.rv_percent,
                "basis_used": cr.basis_used,
            }
            if (cr.min_temp_c is not None or cr.rv_percent is not None)
            else None
        ),
        heater_air_m3h=cr.heater_air_m3h,
        heater_duty_cycle=cr.heater_duty_cycle,
    )


# ---- Summary for 7 points by season ----
class SummaryIn(BaseModel):
    house: str = Field(..., min_length=1, max_length=64)
    birds: int = Field(..., ge=1, le=60000)
    mode_id: str = Field("summer", pattern=r"^(winter|summer|spring_autumn|tropical)$")  # Deprecated, kept for compatibility
    outside_t: float = Field(15.0, ge=-40, le=50, description="Outside air temperature, °C")
    user_max_m3h: float | None = Field(None, ge=0)
    heater_on: bool = Field(False)
    display_unit: str = Field("per_bird", pattern=r"^(per_bird|per_kg)$")


class SummaryRow(BaseModel):
    day: int
    min_temp_c: float | None
    weight_g: float | None
    birds_eff: float | None = None
    q_min_m3h: float
    q_min_pct: float | None = None
    q_max_nominal_m3h: float
    q_max_m3h: float
    q_max_pct: float | None = None
    min_floor_bird: float | None = None
    basis_used: str | None = None


class SummaryOut(BaseModel):
    house: str
    birds: int
    mode_id: str
    user_max_m3h: float | None
    ref_version: str = "seed-demo-1.0"
    rows: list[SummaryRow]


@router.post("/summary7", response_model=SummaryOut)
def summary7(payload: SummaryIn):
    try:
        profile = get_profile(seed_path="data/vent_profile_seed.json")
    except Exception:
        profile = get_profile(seed_path=None)

    # Use outside_t from payload (new way), fallback to mode_id mapping (old way)
    outside_t = payload.outside_t
    days = [1, 7, 14, 21, 28, 35, 42]
    # рассчитываем эффективное количество птиц с учётом смертности и берём пороги min
    try:
        from ..core.app_config import load_app_config
        cfg = load_app_config()
        total_m = max(cfg.total_mortality_pct, 0.0) / 100.0
        daily_m = 1.0 - (1.0 - total_m) ** (1.0 / max(41, 1))
        min0_7 = cfg.min_floor_0_7
        min7_14 = cfg.min_floor_7_14
    except Exception:
        daily_m = 0.0
        min0_7, min7_14 = 0.15, 0.25
    rows: list[SummaryRow] = []

    for d in days:
        ci = CalcInput(
            birds=payload.birds,
            age_days=d,
            mode=payload.mode_id,  # type: ignore
            display_unit=payload.display_unit,  # type: ignore
            outside_t=outside_t,
            heater_on=payload.heater_on,
        )
        cr = compute(profile, ci)
        q_min = round(cr.q_min_m3h, 3)
        q_max_nominal = round(cr.q_max_m3h, 3)
        q_max_final = q_max_nominal
        q_min_pct = None
        q_max_pct = None
        # Эффективное число птиц на этот день (для последующих представлений на голову/кг)
        survival = (1.0 - daily_m) ** max(d - 1, 0)
        birds_eff = payload.birds * survival
        if payload.user_max_m3h is not None:
            q_max_final = min(q_max_nominal, float(payload.user_max_m3h))
            q_min = min(q_min, q_max_final)
            if payload.user_max_m3h > 0:
                q_min_pct = round(100.0 * q_min / payload.user_max_m3h, 3)
                q_max_pct = round(100.0 * q_max_final / payload.user_max_m3h, 3)
        min_floor = min0_7 if d <= 7 else (min7_14 if d <= 14 else None)
        rows.append(
            SummaryRow(
                day=d,
                min_temp_c=cr.min_temp_c,
                weight_g=cr.weight_used_g,
                birds_eff=birds_eff,
                q_min_m3h=q_min,
                q_min_pct=q_min_pct,
                q_max_nominal_m3h=q_max_nominal,
                q_max_m3h=q_max_final,
                q_max_pct=q_max_pct,
                min_floor_bird=min_floor,
                basis_used=cr.basis_used,
            )
        )

    return SummaryOut(
        house=payload.house,
        birds=payload.birds,
        mode_id=payload.mode_id,
        user_max_m3h=payload.user_max_m3h,
        rows=rows,
    )


from ..core.app_config import load_app_config

@router.get("/config")
def get_config():
    cfg = load_app_config()
    return {
        "use_temp_blend": cfg.use_temp_blend,
        "max_per_kg": {
            "winter": cfg.max_per_kg_winter,
            "spring_autumn": cfg.max_per_kg_spring_autumn,
            "summer": cfg.max_per_kg_summer,
            "tropical": cfg.max_per_kg_tropical,
        },
        "min_floor": {
            "d0_7": cfg.min_floor_0_7,
            "d7_14": cfg.min_floor_7_14,
        },
        "total_mortality_pct": cfg.total_mortality_pct,
    }
