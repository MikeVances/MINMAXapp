"""
Публичный API v1 — инженерный калькулятор (контракт: docs/api/v1/openapi.yaml).

Отдельное FastAPI-подприложение, смонтированное в /api/v1, а не набор роутеров
основного: у v1 свой формат ошибок (RFC 7807, application/problem+json), и его
обработчики не должны менять ответы, которые уже разбирает интерфейс.

Без состояния: ни один маршрут не читает настройки хозяйства и калибровки —
всё, что влияет на расчёт, приходит в запросе (docs/api/v1/README.md).
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from typing import Any, Literal, Optional

from fastapi import FastAPI, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import api_access
from .core import construction
from .core import design_climate
from .core import sources
from .core.tunnel_design import Pads
from .core import ventilation_design as vd
from .core import ventilation_requirement as vr
from .core.build_info import APP_VERSION, build_info
from .core.building_thermal import HeaterConfig
from .core.errors import CalcError
from .core.growth_profiles import PROFILE_ID_PATTERN, ProfileNotFound, list_profiles, load_profile
from .core.paths import PROJECT_ROOT, data_path

API_VERSION = "1.0.0"
ERRORS_DOC = "https://github.com/MikeVances/MINMAXapp/blob/main/docs/api/v1/errors.md"

api = FastAPI(title="MINMAX Ventilation Engineering API", version=API_VERSION,
              docs_url="/docs", openapi_url="/openapi.json", redoc_url=None)


# ─── Идентификатор запроса и журнал вызовов ───────────────────────────────────
# Агент может пересказать правдоподобный «результат расчёта», которого не было
# (инструмент не подключился, а описание API он знает из промта) — без журнала
# это неотличимо от настоящего вызова. Поэтому у каждого ответа есть request_id
# (в теле: платформы агентов отдают модели тело, а не заголовки), агент обязан
# его называть, а сервер пишет каждый расчёт в журнал — сверить можно всегда.

AUDIT_LOG_PATH = data_path("API_AUDIT_LOG", "data/api_audit.jsonl")
_audit_logger: Optional[logging.Logger] = None
_audit_lock = threading.Lock()


def _audit(entry: dict) -> None:
    """Строка JSON в журнал вызовов. Сбой журнала не должен ломать расчёт."""
    global _audit_logger
    try:
        with _audit_lock:
            if _audit_logger is None:
                AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                logger = logging.getLogger("minmax.api_v1.audit")
                logger.setLevel(logging.INFO)
                logger.propagate = False
                # 5 МБ × 3 файла: ~10 тыс. расчётов, диск площадки не забьётся
                handler = RotatingFileHandler(AUDIT_LOG_PATH, maxBytes=5_000_000, backupCount=3,
                                              encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(message)s"))
                logger.addHandler(handler)
                _audit_logger = logger
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **entry}
        # Чей ключ: владелец видит, какой клиент тратит лимит, — по отпечатку, не по ключу
        client = _client_var.get()
        if client:
            entry["client"] = client
        _audit_logger.info(json.dumps(entry, ensure_ascii=False, default=str))
    except Exception:
        logging.getLogger(__name__).warning("api audit log write failed", exc_info=True)


# Отпечаток ключа текущего запроса — для журнала. ContextVar, а не request.state:
# _audit вызывают и места, куда request не передаётся
_client_var: ContextVar[Optional[str]] = ContextVar("api_v1_client", default=None)


def _route_path(request: Request) -> str:
    """Путь внутри /api/v1: Starlette оставляет в scope полный путь и кладёт префикс в root_path."""
    path, root = request.scope["path"], request.scope.get("root_path", "")
    return path[len(root):] if root and path.startswith(root) else path


def _check_access(request: Request) -> Optional[Response]:
    """Отказ 401/429 или None — запрос идёт дальше (api_access: зачем и какие лимиты)."""
    group = api_access.route_group(_route_path(request))
    keys = api_access.configured_keys()
    if group is None or not keys:
        return None
    client = api_access.match_key(request.headers.get(api_access.API_KEY_HEADER), keys)
    if client is None:
        return _problem(request, 401, "api_key_required", "missing or invalid X-API-Key")
    _client_var.set(client)
    verdict = api_access.limiter.hit(client, group)
    if not verdict.allowed:
        return _problem(request, 429, "rate_limited", "rate limit exceeded",
                        {"limit": verdict.limit, "window_s": api_access.limiter.window_s},
                        headers={"Retry-After": str(verdict.retry_after_s)})
    return None


@api.middleware("http")
async def _request_id(request: Request, call_next):
    request.state.request_id = f"req-{uuid.uuid4().hex[:12]}"
    # Ключ проверяется здесь, а не зависимостью маршрута: зависимость FastAPI
    # срабатывает после разбора тела, и клиент без ключа получал бы 400/422 по
    # своим полям вместо 401. И у отказа уже есть request_id
    _client_var.set(None)
    denied = _check_access(request)
    response = denied if denied is not None else await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")


# ─── Ошибки: RFC 7807 ─────────────────────────────────────────────────────────

# HTTP-статус по коду ошибки ядра. Ссылка на несуществующий справочный объект — 404,
# всё остальное, что ядро отвергло по смыслу, — 422 (данные разобраны, но считать по
# ним нельзя)
_STATUS_BY_CODE = {"profile_not_found": 404, "material_not_found": 404, "source_not_found": 404,
                   "climate_unavailable": 502}


def _problem(request: Request, status: int, code: str, title: str, params: Optional[dict] = None,
             errors: Optional[list] = None, headers: Optional[dict] = None) -> JSONResponse:
    rid = _rid(request)
    body: dict[str, Any] = {
        "type": f"{ERRORS_DOC}#{code}", "title": title, "status": status,
        "code": code, "instance": rid,
    }
    if params:
        body["params"] = params
    if errors:
        body["errors"] = errors
    # Отказ — тоже факт для сверки: агент мог сказать «посчитал», а сервер ответил ошибкой
    _audit({"request_id": rid, "path": request.url.path, "status": status, "code": code,
            "params": params, "errors": errors})
    return JSONResponse(body, status_code=status, media_type="application/problem+json", headers=headers)


@api.exception_handler(CalcError)
def _calc_error(request: Request, exc: CalcError) -> JSONResponse:
    return _problem(request, _STATUS_BY_CODE.get(exc.code, 422), exc.code, exc.code.replace("_", " "), exc.params)


@api.exception_handler(ProfileNotFound)
def _profile_not_found(request: Request, exc: ProfileNotFound) -> JSONResponse:
    return _problem(request, 404, "profile_not_found", "growth profile not found", {"id": str(exc.args[0])})


@api.exception_handler(RequestValidationError)
def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    errs = exc.errors()
    # Тело — не JSON: это не ошибка полей, а неразобранный запрос
    if any(e.get("type") == "json_invalid" for e in errs):
        return _problem(request, 400, "bad_request", "request body is not valid JSON")
    fields = [{
        # loc начинается с "body" — клиенту нужен путь внутри своего JSON
        "field": ".".join(str(p) for p in e["loc"] if p != "body"),
        "code": e["type"],
        "message": e["msg"],
    } for e in errs]
    return _problem(request, 422, "validation_failed", "request fields are invalid", errors=fields)


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
    # Последний день в корпусе. Верх — цикл индюка (22 нед); бройлеру ядро не даст
    # больше 63 (broiler_day_out_of_range): предел зависит от вида птицы профиля
    cycle_days: int = Field(..., ge=21, le=154)
    # Индейка: день посадки в этот корпус (на доращивание — день пересадки) и тип корпуса
    first_day: int = Field(1, ge=1, le=153)
    stage: Optional[Literal["brooder", "grow_out"]] = None


class ClimateIn(_Strict):
    winter_design_c: float = Field(..., ge=-60, le=30)
    summer_design_db_c: float = Field(..., ge=0, le=55)
    summer_design_rh_pct: float = Field(..., ge=1, le=100)


class HeatersIn(_Strict):
    type: Literal["gas_open", "gas_indirect", "electric"]
    power_kw: float = Field(..., gt=0, le=5000)


class PadsIn(_Strict):
    type: Literal["7090", "7060", "5090"] = "7090"
    thickness_mm: Literal[50, 75, 100, 150, 200, 300] = 150


class FanPointIn(_Strict):
    static_pressure_pa: float = Field(..., ge=0, le=150)
    flow_m3h: float = Field(..., gt=0, le=100_000)


class FanCurveIn(_Strict):
    points: list[FanPointIn] = Field(..., min_length=2, max_length=12)


class TunnelRulesIn(_Strict):
    min_day: int = Field(..., ge=1, le=42)
    min_outdoor_c: float = Field(..., ge=0, le=35)

    def to_core(self) -> vd.TunnelRules:
        return vd.TunnelRules(self.min_day, self.min_outdoor_c)


class DesignRequest(_Strict):
    house: HouseIn
    envelope: EnvelopeIn
    flock: FlockIn
    climate: ClimateIn
    heaters: Optional[HeatersIn] = None
    heating_margin_pct: float = Field(vd.DEFAULT_HEATING_MARGIN_PCT, ge=0, le=50)
    tunnel_rules: Optional[TunnelRulesIn] = None
    pads: Optional[PadsIn] = None
    tunnel_fan: Optional[FanCurveIn] = None
    tunnel_static_pressure_pa: Optional[float] = Field(None, gt=0, le=150)


class FlockNowIn(_Strict):
    # birds — ТЕКУЩЕЕ поголовье: падежа (mortality_pct) здесь нет намеренно —
    # он уже сидит в числе, которое ввёл клиент, и был бы учтён дважды
    birds: int = Field(..., ge=1, le=200_000)
    growth_profile_id: str = Field(..., pattern=PROFILE_ID_PATTERN)
    housing: Literal["floor_litter", "cages"]
    # Верх — цикл индюка; бройлеру ядро не даст больше 70 (broiler_day_out_of_range)
    age_days: int = Field(..., ge=0, le=154)
    target_rh_pct: Optional[float] = Field(None, ge=40, le=70)
    stage: Optional[Literal["brooder", "grow_out"]] = None


class ConditionsIn(_Strict):
    outdoor_t_c: float = Field(..., ge=-60, le=55)
    outdoor_rh_pct: float = Field(..., ge=0, le=100)


class RequirementRequest(_Strict):
    house: HouseIn
    envelope: Optional[EnvelopeIn] = None
    flock: FlockNowIn
    conditions: ConditionsIn
    heaters: Optional[HeatersIn] = None
    tunnel_rules: Optional[TunnelRulesIn] = None


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
    # Тот же справочник, что отдаёт /sources: по id агент получит пересказ и ограничения
    out = [{"id": i, "citation": sources.citation(i)} for i in ids if sources.get_source(i)]
    if profile_citation:
        out.append({"id": "growth_profile", "citation": profile_citation})
    return out


def _app_version() -> str:
    info = build_info()
    return f"{APP_VERSION} · {info.get('commit', 'unknown')}"


@api.post("/ventilation-designs", status_code=201)
def create_ventilation_design(req: DesignRequest, request: Request) -> JSONResponse:
    flock, clim = req.flock, req.climate
    if flock.housing == "cages" and not req.house.cage_rows:
        raise CalcError("cage_section_missing")
    result = vd.design(vd.DesignInput(
        **_house_parts(req.house), **_envelope_parts(req.envelope),
        birds=flock.birds, growth_profile_id=flock.growth_profile_id, housing=flock.housing,
        mortality_pct=flock.mortality_pct, target_rh_pct=flock.target_rh_pct, cycle_days=flock.cycle_days,
        first_day=flock.first_day, stage=flock.stage,
        winter_design_c=clim.winter_design_c, summer_design_db_c=clim.summer_design_db_c,
        summer_design_rh_pct=clim.summer_design_rh_pct,
        heater=_heater(req.heaters),
        heating_margin_pct=req.heating_margin_pct,
        tunnel_rules=req.tunnel_rules.to_core() if req.tunnel_rules else None,
        pads=Pads(req.pads.type, req.pads.thickness_mm) if req.pads else None,
        fan_curve=tuple((p.static_pressure_pa, p.flow_m3h) for p in req.tunnel_fan.points)
        if req.tunnel_fan else (),
        tunnel_static_pressure_pa=req.tunnel_static_pressure_pa,
    ))
    rid = _rid(request)
    body: dict[str, Any] = {
        "request_id": rid,
        "envelope_ua_w_per_k": result.envelope_ua_w_per_k,
        # Необязательные поля дня (RH, плотность) — опускаются, а не null: как
        # остальные «только если» в контракте
        "days": [{k: v for k, v in vars(d).items() if v is not None} for d in result.days],
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
    _audit({"request_id": rid, "path": request.url.path, "status": 201,
            "request": req.model_dump(by_alias=True, exclude_none=True),
            "result": {"peak": body["peak"], "heating_kw": body["equipment"]["heating_kw"],
                       "tunnel_fans_m3h": body["equipment"]["tunnel_fans_m3h"],
                       "tunnel_fans": body["equipment"].get("tunnel_fans"),
                       "warnings": [n["code"] for n in body["warnings"]]}})
    return JSONResponse(body, status_code=201, headers={"Cache-Control": "no-store"})


def _heater(h: Optional[HeatersIn]) -> Optional[HeaterConfig]:
    # gas_indirect воздух корпуса не загрязняет — для модели это как электрический
    if h is None:
        return None
    return HeaterConfig("gas_open" if h.type == "gas_open" else "electric", h.power_kw)


def _house_parts(h: HouseIn) -> dict:
    air = h.airtightness
    return dict(
        geometry=construction.HouseGeometry(h.length_m, h.width_m, h.wall_height_m, h.ridge_height_m),
        altitude_m=h.altitude_m,
        airtightness=vd.Airtightness(air.tightness_class, air.relative_leakage, air.leak_at_4pa_m3h)
        if air else None,
        cage_rows=tuple(vd.CageRow(r.width_m, r.height_m, r.count) for r in h.cage_rows or ()),
    )


def _envelope_parts(env: Optional[EnvelopeIn]) -> dict:
    if env is None:
        return {}
    return dict(
        ua_w_per_k=env.ua_w_per_k,
        walls=env.walls.to_core() if env.walls else None,
        roof=env.roof.to_core() if env.roof else None,
        end_walls=env.end_walls.to_core() if env.end_walls else None,
    )


@api.post("/ventilation-requirements", status_code=201)
def create_ventilation_requirement(req: RequirementRequest, request: Request) -> JSONResponse:
    flock, cond = req.flock, req.conditions
    if flock.housing == "cages" and not req.house.cage_rows:
        raise CalcError("cage_section_missing")
    r = vr.requirement(vr.RequirementInput(
        **_house_parts(req.house), **_envelope_parts(req.envelope),
        birds=flock.birds, growth_profile_id=flock.growth_profile_id, housing=flock.housing,
        age_days=flock.age_days, target_rh_pct=flock.target_rh_pct,
        outdoor_t_c=cond.outdoor_t_c, outdoor_rh_pct=cond.outdoor_rh_pct,
        heater=_heater(req.heaters),
        tunnel_rules=req.tunnel_rules.to_core() if req.tunnel_rules else None,
        stage=flock.stage,
    ))
    rid = _rid(request)
    body: dict[str, Any] = {
        "request_id": rid,
        "qmin_m3h": r.qmin_m3h, "qmin_basis": r.qmin_basis, "qmax_m3h": r.qmax_m3h,
        "target_temp_c": r.target_temp_c, "weight_g": r.weight_g, "tunnel": r.tunnel,
        "findings": [_note(n) for n in r.findings],
        "assumptions": [_note(n) for n in r.assumptions],
        "sources": _sources(r.source_ids, r.profile_source),
        "api_version": API_VERSION, "app_version": _app_version(),
    }
    for key in ("heating_need_kw", "heater_duty_pct", "air_exchange_m3h", "target_rh_pct",
                "stocking_density_kg_m2", "stocking_density_head_m2"):
        if getattr(r, key) is not None:
            body[key] = getattr(r, key)
    _audit({"request_id": rid, "path": request.url.path, "status": 201,
            "request": req.model_dump(by_alias=True, exclude_none=True),
            "result": {k: body.get(k) for k in ("qmin_m3h", "qmax_m3h", "heating_need_kw", "heater_duty_pct")}
            | {"findings": [n["code"] for n in body["findings"]]}})
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


# Справочник источников: по `source_id` из ответа расчёта агент получает выверенный
# пересказ правила, как калькулятор его применяет и где модель от источника отличается.
# Поиск по ключу, а не по полному тексту гайдов: второго канала чисел, мимо журнала
# расчётов, у агента появиться не должно
SOURCE_ID_PATTERN = r"^[a-z0-9][a-z0-9_]{0,63}$"


@api.get("/sources")
def list_sources() -> JSONResponse:
    return JSONResponse({"data": [sources.as_dict(s) for s in sources.CATALOG.values()]},
                        headers=_CATALOG_CACHE)


@api.get("/sources/{source_id}")
def get_source(source_id: str = Path(..., pattern=SOURCE_ID_PATTERN)) -> JSONResponse:
    s = sources.get_source(source_id)
    if s is None:
        raise CalcError("source_not_found", id=source_id)
    return JSONResponse(sources.as_dict(s), headers=_CATALOG_CACHE)


@api.get("/growth-profiles")
def list_growth_profiles() -> JSONResponse:
    data = []
    for p in list_profiles():
        days = [pt.day for pt in p.points]
        item: dict[str, Any] = {"id": p.id, "name": p.name, "builtin": p.builtin,
                                "species": p.species, "first_day": min(days), "last_day": max(days)}
        if p.breed:
            item["breed"] = p.breed
        if p.sex:
            item["sex"] = p.sex
        data.append(item)
    # Пользовательские профили меняются без новой версии — не кэшировать надолго
    return JSONResponse({"data": data}, headers={"Cache-Control": "no-cache"})


# Расчётный климат по точке: первый запрос ~20 с (10 лет часов ERA5), повтор — из
# памяти процесса. Ключ — координаты с шагом 0.1° (~11 км): ближе ERA5 (сетка 0.25°)
# всё равно не различает. Кэш живёт до перезапуска — данные за 2015–2024 не меняются
_climate_cache: dict[tuple[float, float], dict] = {}
_climate_lock = threading.Lock()


@api.get("/climate-designs")
def get_climate_design(request: Request, latitude: float = Query(..., ge=-90, le=90),
                       longitude: float = Query(..., ge=-180, le=180)) -> JSONResponse:
    key = (round(latitude, 1), round(longitude, 1))
    with _climate_lock:
        cached = _climate_cache.get(key)
    if cached is None:
        # Вне блокировки: 20 с сети не должны держать другие точки
        temps, rhs, elevation = design_climate.fetch_hourly(*key)
        c = design_climate.design_conditions(temps, rhs, elevation)
        cached = {
            "winter_design_c": c.heating_996_c, "summer_design_db_c": c.cooling_04_db_c,
            "summer_design_rh_pct": c.cooling_04_rh_pct, "summer_mcwb_c": c.cooling_04_mcwb_c,
            "evap_wb_c": c.evap_04_wb_c, "elevation_m": c.elevation_m,
            "source_id": "era5_open_meteo", "citation": sources.citation("era5_open_meteo"),
            "latitude": key[0], "longitude": key[1],
        }
        with _climate_lock:
            _climate_cache[key] = cached
    rid = _rid(request)
    _audit({"request_id": rid, "path": request.url.path, "status": 200,
            "request": {"latitude": latitude, "longitude": longitude},
            "result": {k: cached[k] for k in ("winter_design_c", "summer_design_db_c", "summer_design_rh_pct")}})
    # Температуры из этого ответа агент переносит в проект — им тоже нужен номер для
    # сверки. В кэше request_id нет: у каждого запроса свой
    return JSONResponse({"request_id": rid, **cached}, headers=_CATALOG_CACHE)


# Выверенный контракт — для платформ агентов: описания инструментов они берут из
# OpenAPI, а живая /openapi.json сгенерирована FastAPI из моделей — без русских
# описаний, примеров и смысла полей. Отдаём файл как есть, без разбора
CONTRACT_PATH = PROJECT_ROOT / "docs" / "api" / "v1" / "openapi.yaml"


@api.get("/openapi.yaml", include_in_schema=False)
def contract(request: Request) -> Response:
    try:
        text = CONTRACT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Площадка выложена без docs/ (копия только backend/). Голый 500 агент
        # читает как «калькулятор сломан» — отдаём разбираемый отказ; он же
        # попадает в журнал, и владелец площадки видит, что контракт не выложен
        return _problem(request, 404, "contract_not_found", "API contract file is not deployed")
    return PlainTextResponse(text, media_type="application/yaml", headers={"Cache-Control": "no-cache"})


def _source_entry(value) -> Optional[dict]:
    """Источник колонки профиля: структура встроенного профиля или свободный текст."""
    if isinstance(value, dict):
        out = {k: v for k, v in value.items() if v is not None and k != "ref"}
        return {"citation": value.get("ref") or "", **out}
    if isinstance(value, str) and value:
        return {"citation": value}
    return None


@api.get("/growth-profiles/{profile_id}")
def get_growth_profile(profile_id: str = Path(..., pattern=PROFILE_ID_PATTERN)) -> JSONResponse:
    """
    Профиль по дням: масса, уставка температуры и влажности. Внешней системе и агенту
    уставка нужна и без расчёта корпуса («какая температура на 25-й день»).

    Источник у каждой колонки свой и называется отдельно: у встроенных профилей масса —
    таблица производителя кросса, а температура — одна методика для всех кроссов
    (Ross 2025 табл. 2.5, пересчёт по массе). Выдать их общей подписью «данные кросса»
    значило бы ввести в заблуждение.
    """
    p = load_profile(profile_id)
    given = {pt.day for pt in p.points}
    sources = {k: e for k, e in ((k, _source_entry(v)) for k, v in (p.source or {}).items()) if e}
    body: dict[str, Any] = {
        "id": p.id, "name": p.name, "builtin": p.builtin, "species": p.species, "sources": sources,
        "days": [{"day": d.day, "weight_g": d.body_weight_g, "temp_c": d.min_temp_c,
                  "rh_pct": d.rv_percent, "interpolated": d.day not in given}
                 for d in p.daily().values()],
    }
    if p.breed:
        body["breed"] = p.breed
    if p.sex:
        body["sex"] = p.sex
    if p.min_vent_norm:
        body["min_vent_norm"] = p.min_vent_norm
    # Встроенные меняются только с версией приложения, пользовательские — в любой момент
    return JSONResponse(body, headers=_CATALOG_CACHE if p.builtin else {"Cache-Control": "no-cache"})


@api.get("/housing-systems")
def list_housing_systems() -> JSONResponse:
    return JSONResponse({"data": [
        {"id": "floor_litter", "supported": True, "source_id": "cigr_2002"},
        {"id": "cages", "supported": True, "source_id": "aarnink_2018"},
    ]}, headers=_CATALOG_CACHE)
