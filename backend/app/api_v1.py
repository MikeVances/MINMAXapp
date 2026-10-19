"""
Публичный API v1 — инженерный калькулятор (контракт: docs/api/v1/openapi.yaml).

Отдельное FastAPI-подприложение, смонтированное в /api/v1, а не набор роутеров
основного: у v1 свой формат ошибок (RFC 7807, application/problem+json), и его
обработчики не должны менять ответы, которые уже разбирает интерфейс.

Без состояния: ни один маршрут не читает настройки хозяйства и калибровки —
всё, что влияет на расчёт, приходит в запросе (docs/api/v1/README.md).
"""
from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .core import construction
from .core import ventilation_design as vd
from .core.build_info import APP_VERSION, build_info
from .core.building_thermal import HeaterConfig
from .core.errors import CalcError
from .core.growth_profiles import PROFILE_ID_PATTERN, ProfileNotFound, list_profiles

API_VERSION = "1.0.0"
ERRORS_DOC = "https://github.com/MikeVances/MINMAXapp/blob/main/docs/api/v1/errors.md"

api = FastAPI(title="MINMAX Ventilation Engineering API", version=API_VERSION,
              docs_url="/docs", openapi_url="/openapi.json", redoc_url=None)


# ─── Ошибки: RFC 7807 ─────────────────────────────────────────────────────────

# HTTP-статус по коду ошибки ядра. Ссылка на несуществующий справочный объект — 404,
# всё остальное, что ядро отвергло по смыслу, — 422 (данные разобраны, но считать по
# ним нельзя)
_STATUS_BY_CODE = {"profile_not_found": 404, "material_not_found": 404}


def _problem(status: int, code: str, title: str, params: Optional[dict] = None,
             errors: Optional[list] = None) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{ERRORS_DOC}#{code}", "title": title, "status": status,
        "code": code, "instance": f"req-{uuid.uuid4().hex[:8]}",
    }
    if params:
        body["params"] = params
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type="application/problem+json",
                        headers={"X-Request-Id": body["instance"]})


@api.exception_handler(CalcError)
def _calc_error(_: Request, exc: CalcError) -> JSONResponse:
    return _problem(_STATUS_BY_CODE.get(exc.code, 422), exc.code, exc.code.replace("_", " "), exc.params)


@api.exception_handler(ProfileNotFound)
def _profile_not_found(_: Request, exc: ProfileNotFound) -> JSONResponse:
    return _problem(404, "profile_not_found", "growth profile not found", {"id": str(exc.args[0])})


@api.exception_handler(RequestValidationError)
def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
    errs = exc.errors()
    # Тело — не JSON: это не ошибка полей, а неразобранный запрос
    if any(e.get("type") == "json_invalid" for e in errs):
        return _problem(400, "bad_request", "request body is not valid JSON")
    fields = [{
        # loc начинается с "body" — клиенту нужен путь внутри своего JSON
        "field": ".".join(str(p) for p in e["loc"] if p != "body"),
        "code": e["type"],
        "message": e["msg"],
    } for e in errs]
    return _problem(422, "validation_failed", "request fields are invalid", errors=fields)


# ─── Модели запроса ───────────────────────────────────────────────────────────
# Повторяют компоненты openapi.yaml. extra="forbid": опечатка в имени поля
# (wall_heigth_m) — 422, а не молча подставленное значение по умолчанию.

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LayerIn(_Strict):
    thickness_mm: float = Field(..., gt=0, le=1000)
    material_id: Optional[str] = Field(None, max_length=64)
    lambda_w_mk: Optional[float] = Field(None, ge=0.01, le=200)

    @model_validator(mode="after")
    def _one_lambda_source(self):
        if (self.material_id is None) == (self.lambda_w_mk is None):
            raise ValueError("exactly one of material_id or lambda_w_mk is required")
        return self


class SurfaceIn(_Strict):
    layers: Optional[list[LayerIn]] = Field(None, min_length=1, max_length=6)
    u_w_m2k: Optional[float] = Field(None, ge=0.05, le=10)

    @model_validator(mode="after")
    def _one_of(self):
        if (self.layers is None) == (self.u_w_m2k is None):
            raise ValueError("exactly one of layers or u_w_m2k is required")
        return self

    def to_core(self) -> construction.Surface:
        if self.u_w_m2k is not None:
            return construction.Surface(u_w_m2k=self.u_w_m2k)
        return construction.Surface(layers=tuple(
            construction.Layer(l.thickness_mm, l.material_id, l.lambda_w_mk) for l in self.layers))


class EnvelopeIn(_Strict):
    ua_w_per_k: Optional[float] = Field(None, gt=0, le=200_000)
    walls: Optional[SurfaceIn] = None
    roof: Optional[SurfaceIn] = None
    end_walls: Optional[SurfaceIn] = None

    @model_validator(mode="after")
    def _one_of(self):
        by_construction = self.walls is not None or self.roof is not None or self.end_walls is not None
        if self.ua_w_per_k is not None and by_construction:
            raise ValueError("either ua_w_per_k or construction (walls, roof), not both")
        if self.ua_w_per_k is None and (self.walls is None or self.roof is None):
            raise ValueError("ua_w_per_k or both walls and roof are required")
        return self


class AirtightnessIn(_Strict):
    # «class» — ключевое слово Python: поле называется иначе, в JSON — class
    tightness_class: Optional[Literal["tight", "moderate", "leaky", "very_leaky"]] = Field(None, alias="class")
    relative_leakage: Optional[float] = Field(None, gt=0, le=5)
    leak_at_4pa_m3h: Optional[float] = Field(None, gt=0)

    @model_validator(mode="after")
    def _one_of(self):
        given = [v for v in (self.tightness_class, self.relative_leakage, self.leak_at_4pa_m3h) if v is not None]
        if len(given) != 1:
            raise ValueError("exactly one of class, relative_leakage, leak_at_4pa_m3h is required")
        return self


class CageRowIn(_Strict):
    count: int = Field(1, ge=1, le=20)
    width_m: float = Field(..., gt=0, le=5)
    height_m: float = Field(..., gt=0, le=10)


class HouseIn(_Strict):
    length_m: float = Field(..., gt=0, le=400)
    width_m: float = Field(..., gt=0, le=60)
    wall_height_m: float = Field(..., gt=0, le=10)
    ridge_height_m: Optional[float] = Field(None, gt=0, le=15)
    altitude_m: float = Field(0.0, ge=0, le=4000)
    airtightness: Optional[AirtightnessIn] = None
    cage_rows: Optional[list[CageRowIn]] = Field(None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def _ridge_not_below_wall(self):
        if self.ridge_height_m is not None and self.ridge_height_m < self.wall_height_m:
            raise ValueError("ridge_height_m must not be below wall_height_m")
        return self


class FlockIn(_Strict):
    birds: int = Field(..., ge=1, le=200_000)
    growth_profile_id: str = Field(..., pattern=PROFILE_ID_PATTERN)
    housing: Literal["floor_litter", "cages"]
    mortality_pct: float = Field(4.0, ge=0, le=100)
    target_rh_pct: Optional[float] = Field(None, ge=40, le=70)
    cycle_days: int = Field(..., ge=21, le=63)


class ClimateIn(_Strict):
    winter_design_c: float = Field(..., ge=-60, le=30)
    summer_design_db_c: float = Field(..., ge=0, le=55)
    summer_design_rh_pct: float = Field(..., ge=1, le=100)


class HeatersIn(_Strict):
    type: Literal["gas_open", "gas_indirect", "electric"]
    power_kw: float = Field(..., gt=0, le=5000)


class DesignRequest(_Strict):
    house: HouseIn
    envelope: EnvelopeIn
    flock: FlockIn
    climate: ClimateIn
    heaters: Optional[HeatersIn] = None
    heating_margin_pct: float = Field(vd.DEFAULT_HEATING_MARGIN_PCT, ge=0, le=50)
    # Давление туннеля и характеристика вентилятора — этап 3b; поля уже в контракте,
    # и принять их сейчас лучше, чем отвергать запрос, собранный по контракту
    tunnel_fan: Optional[dict] = None
    tunnel_static_pressure_pa: Optional[float] = Field(None, gt=0, le=150)


# ─── Маршруты ─────────────────────────────────────────────────────────────────

def _note(n: vd.Note) -> dict:
    out: dict[str, Any] = {"code": n.code}
    if n.params:
        out["params"] = n.params
    if n.severity:
        out["severity"] = n.severity
    if n.source_id:
        out["source_id"] = n.source_id
    return out


def _sources(ids: list[str], profile_citation: Optional[str]) -> list[dict]:
    catalog = {**construction.SOURCES, **vd.SOURCES}
    out = [{"id": i, "citation": catalog[i]} for i in ids if i in catalog]
    if profile_citation:
        out.append({"id": "growth_profile", "citation": profile_citation})
    return out


def _app_version() -> str:
    info = build_info()
    return f"{APP_VERSION} · {info.get('commit', 'unknown')}"


@api.post("/ventilation-designs", status_code=201)
def create_ventilation_design(req: DesignRequest) -> JSONResponse:
    h, env, flock, clim = req.house, req.envelope, req.flock, req.climate
    if flock.housing == "cages" and not h.cage_rows:
        raise CalcError("cage_section_missing")
    air = h.airtightness
    result = vd.design(vd.DesignInput(
        geometry=construction.HouseGeometry(h.length_m, h.width_m, h.wall_height_m, h.ridge_height_m),
        altitude_m=h.altitude_m,
        airtightness=vd.Airtightness(air.tightness_class, air.relative_leakage, air.leak_at_4pa_m3h)
        if air else None,
        cage_rows=tuple(vd.CageRow(r.width_m, r.height_m, r.count) for r in h.cage_rows or ()),
        ua_w_per_k=env.ua_w_per_k,
        walls=env.walls.to_core() if env.walls else None,
        roof=env.roof.to_core() if env.roof else None,
        end_walls=env.end_walls.to_core() if env.end_walls else None,
        birds=flock.birds, growth_profile_id=flock.growth_profile_id, housing=flock.housing,
        mortality_pct=flock.mortality_pct, target_rh_pct=flock.target_rh_pct, cycle_days=flock.cycle_days,
        winter_design_c=clim.winter_design_c, summer_design_db_c=clim.summer_design_db_c,
        summer_design_rh_pct=clim.summer_design_rh_pct,
        # gas_indirect воздух корпуса не загрязняет — для модели это как электрический
        heater=HeaterConfig("gas_open" if req.heaters.type == "gas_open" else "electric", req.heaters.power_kw)
        if req.heaters else None,
        heating_margin_pct=req.heating_margin_pct,
    ))
    body: dict[str, Any] = {
        "envelope_ua_w_per_k": result.envelope_ua_w_per_k,
        "days": [vars(d) for d in result.days],
        "peak": result.peak,
        "equipment": result.equipment,
        "warnings": [_note(n) for n in result.warnings],
        "assumptions": [_note(n) for n in result.assumptions],
        "sources": _sources(result.source_ids, result.profile_source),
        "api_version": API_VERSION,
        "app_version": _app_version(),
    }
    if result.heaters_sufficient is not None:
        body["heaters_sufficient"] = result.heaters_sufficient
    return JSONResponse(body, status_code=201, headers={"Cache-Control": "no-store"})


# Справочники меняются только с версией приложения — клиенту можно кэшировать
_CATALOG_CACHE = {"Cache-Control": "public, max-age=3600"}


@api.get("/construction-materials")
def list_construction_materials() -> JSONResponse:
    data = []
    for m in construction.MATERIALS.values():
        item: dict[str, Any] = {"id": m.id, "name": m.name, "lambda_w_mk": m.lambda_w_mk,
                                "source_id": m.source_id}
        if m.density_kg_m3 is not None:
            item["density_kg_m3"] = m.density_kg_m3
        if m.typical_thickness_mm:
            item["typical_thickness_mm"] = list(m.typical_thickness_mm)
        data.append(item)
    return JSONResponse({"data": data}, headers=_CATALOG_CACHE)


@api.get("/growth-profiles")
def list_growth_profiles() -> JSONResponse:
    data = []
    for p in list_profiles():
        days = [pt.day for pt in p.points]
        item: dict[str, Any] = {"id": p.id, "name": p.name, "builtin": p.builtin,
                                "first_day": min(days), "last_day": max(days)}
        if p.breed:
            item["breed"] = p.breed
        data.append(item)
    # Пользовательские профили меняются без новой версии — не кэшировать надолго
    return JSONResponse({"data": data}, headers={"Cache-Control": "no-cache"})


@api.get("/housing-systems")
def list_housing_systems() -> JSONResponse:
    return JSONResponse({"data": [
        {"id": "floor_litter", "supported": True, "source_id": "cigr_2002"},
        {"id": "cages", "supported": True, "source_id": "aarnink_2018"},
    ]}, headers=_CATALOG_CACHE)
