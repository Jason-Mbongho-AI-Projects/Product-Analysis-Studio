"""Read-mostly HTTP API over the intelligence layer (spec 57).

Runs as a **separate process** from the Streamlit UI:

    python -m pas.api

Disabled unless ``PAS_API_ENABLED=true``, so it can never start by accident.

Design notes:

* Authentication is by ``Authorization: Bearer pas_...``. Keys are scoped to one
  workspace, so a key cannot read another tenant's data even if the path is
  guessed.
* Writes require the ``write`` scope; a read key can never start an analysis or
  spend against the model provider.
* Every response is JSON, and errors never echo internal detail.
* The service layer does the actual work, so the API and the UI cannot drift
  apart — there is exactly one implementation of every capability.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..auth.models import Identity, Permission, PermissionDenied, Role
from ..config import load_config
from ..service import StudioService
from ..storage.db import get_connection, migrate
from . import keys as key_store
from .ratelimit import limiter

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024


def _error(status: int, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


def _service_for(record: dict[str, Any]) -> StudioService:
    """Build a service bound to the key's workspace and scope.

    The scope maps onto the same role model the UI uses, so API authorisation is
    the identical code path rather than a parallel implementation that could
    drift.
    """
    config = load_config()
    role = Role.ANALYST if "write" in record["scope_set"] else Role.EXECUTIVE
    identity = Identity(
        user_id=f"api:{record['id']}",
        email="",
        name=f"API key {record['key_prefix']}",
        workspace_id=record["workspace_id"],
        role=role,
        permissions=__import__(
            "pas.auth.models", fromlist=["ROLE_PERMISSIONS"]
        ).ROLE_PERMISSIONS[role],
    )
    return StudioService(config=config, identity=identity)


async def _authenticate(request: Request) -> tuple[dict[str, Any] | None, Response | None]:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None, _error(401, "Provide an API key as 'Authorization: Bearer <key>'.")

    secret = header[7:].strip()
    conn = get_connection()
    record = key_store.resolve_key(conn, secret)
    if record is None:
        # Unknown, revoked and expired are indistinguishable by design.
        return None, _error(401, "Invalid or expired API key.")

    allowed, retry_after = limiter.check(record["id"], record["rate_per_minute"])
    if not allowed:
        return None, JSONResponse(
            {
                "error": "Rate limit exceeded.",
                "retry_after_seconds": round(retry_after, 2),
            },
            status_code=429,
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )

    key_store.touch_key(conn, record["id"])
    return record, None


def endpoint(write: bool = False) -> Callable:
    """Wrap a handler with auth, scope check, timing and request logging."""

    def decorator(handler: Callable) -> Callable:
        async def wrapper(request: Request) -> Response:
            started = time.monotonic()
            record, failure = await _authenticate(request)
            if failure is not None:
                return failure
            assert record is not None

            if write and "write" not in record["scope_set"]:
                response: Response = _error(
                    403, "This key is read-only. A 'write' scope is required."
                )
            else:
                try:
                    service = _service_for(record)
                    response = await handler(request, service)
                except PermissionDenied as exc:
                    response = _error(403, str(exc))
                except ValueError as exc:
                    response = _error(400, str(exc))
                except Exception:  # never leak internals to a caller
                    logger.exception("Unhandled API error on %s", request.url.path)
                    response = _error(500, "Internal error.")

            key_store.record_request(
                get_connection(),
                workspace_id=record["workspace_id"],
                api_key_id=record["id"],
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return response

        return wrapper

    return decorator


async def _json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError("Request body is too large.")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    return payload


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def health(request: Request) -> Response:
    """Unauthenticated liveness check. Reveals nothing about the workspace."""
    return JSONResponse({"status": "ok", "service": "product-analysis-studio"})


@endpoint()
async def list_products(request: Request, service: StudioService) -> Response:
    return JSONResponse(
        {
            "products": [
                {
                    key: product.get(key)
                    for key in (
                        "id", "name", "one_liner", "category", "industry",
                        "business_model", "maturity", "analysis_count", "created_at",
                    )
                }
                for product in service.list_products()
            ]
        }
    )


@endpoint()
async def get_analysis(request: Request, service: StudioService) -> Response:
    product_id = request.path_params["product_id"]
    if service.get_product(product_id) is None:
        return _error(404, "Product not found.")

    analysis = service.latest_analysis(product_id)
    if analysis is None:
        return _error(404, "No analysis has been run for this product.")

    data = service.dashboard(analysis["id"])
    return JSONResponse(
        {
            "analysis_id": analysis["id"],
            "version": analysis["version"],
            "status": analysis["status"],
            "score": data["composite"],
            "evidence_quality": data["quality"],
        }
    )


@endpoint()
async def get_score(request: Request, service: StudioService) -> Response:
    analysis = service.latest_analysis(request.path_params["product_id"])
    if analysis is None:
        return _error(404, "No analysis found.")
    data = service.dashboard(analysis["id"])
    return JSONResponse(
        {
            "composite": data["composite"],
            "dimensions": [
                {
                    "dimension": score["dimension"],
                    "score": score["score"],
                    "inverted": bool(score["inverted"]),
                    "weight": score["weight"],
                    "confidence": score["confidence"],
                    "explanation": score["explanation"],
                }
                for score in data["scores"]
            ],
        }
    )


@endpoint()
async def get_competitors(request: Request, service: StudioService) -> Response:
    analysis = service.latest_analysis(request.path_params["product_id"])
    if analysis is None:
        return _error(404, "No analysis found.")
    return JSONResponse({"competitors": service.dashboard(analysis["id"])["competitors"]})


@endpoint()
async def get_recommendations(request: Request, service: StudioService) -> Response:
    analysis = service.latest_analysis(request.path_params["product_id"])
    if analysis is None:
        return _error(404, "No analysis found.")
    return JSONResponse(
        {"recommendations": service.dashboard(analysis["id"])["recommendations"]}
    )


@endpoint()
async def get_market(request: Request, service: StudioService) -> Response:
    analysis = service.latest_analysis(request.path_params["product_id"])
    if analysis is None:
        return _error(404, "No analysis found.")
    return JSONResponse({"market": service.dashboard(analysis["id"])["market"]})


@endpoint()
async def get_radar(request: Request, service: StudioService) -> Response:
    analysis = service.latest_analysis(request.path_params["product_id"])
    if analysis is None:
        return _error(404, "No analysis found.")
    return JSONResponse(service.radar(analysis["id"]))


@endpoint()
async def get_evidence(request: Request, service: StudioService) -> Response:
    analysis = service.latest_analysis(request.path_params["product_id"])
    if analysis is None:
        return _error(404, "No analysis found.")
    limit = min(int(request.query_params.get("limit", 200)), 1000)
    return JSONResponse({"evidence": service.evidence(analysis["id"], limit=limit)})


@endpoint()
async def export_analysis(request: Request, service: StudioService) -> Response:
    analysis = service.latest_analysis(request.path_params["product_id"])
    if analysis is None:
        return _error(404, "No analysis found.")
    return Response(
        service.export_json(analysis["id"]), media_type="application/json"
    )


@endpoint(write=True)
async def simulate(request: Request, service: StudioService) -> Response:
    """Run the deterministic pricing simulation. No model call, so no LLM cost."""
    body = await _json_body(request)
    from ..analysis.finance import Economics

    economics = Economics(
        arpu_monthly=float(body.get("arpu_monthly", 100)),
        gross_margin_pct=float(body.get("gross_margin_pct", 75)),
        cac=float(body.get("cac", 500)),
        monthly_churn_pct=float(body.get("monthly_churn_pct", 4)),
        monthly_expansion_pct=float(body.get("monthly_expansion_pct", 0)),
        customers=int(body.get("customers", 100)),
    )
    result = service.simulate(
        economics,
        elasticity=float(body.get("elasticity", -1.0)),
        fixed_costs=float(body.get("fixed_costs", 0)),
        new_customers_per_month=float(body.get("new_customers_per_month", 0)),
        months=min(int(body.get("months", 24)), 120),
    )
    unit = result["unit_economics"]
    return JSONResponse(
        {
            "unit_economics": {
                "ltv": unit.ltv,
                "ltv_cac_ratio": unit.ltv_cac_ratio,
                "cac_payback_months": unit.cac_payback_months,
                "mrr": unit.mrr,
                "arr": unit.arr,
                "is_healthy": unit.is_healthy,
                "warnings": unit.warnings,
            },
            "price_sensitivity": [
                {
                    "price_change_pct": scenario.price_change_pct,
                    "new_arpu": scenario.new_arpu,
                    "new_customers": scenario.new_customers,
                    "new_mrr": scenario.new_mrr,
                    "mrr_change_pct": scenario.mrr_change_pct,
                }
                for scenario in result["curve"]
            ],
            "disclaimer": (
                "Projections under the supplied assumptions, not predictions."
            ),
        }
    )


@endpoint(write=True)
async def create_analysis(request: Request, service: StudioService) -> Response:
    """Create a product and start an analysis. Spends against the API key's workspace."""
    body = await _json_body(request)

    product_id = body.get("product_id")
    if not product_id:
        product_id = service.create_product(
            name=str(body.get("name", "")),
            intake_kind=str(body.get("intake_kind", "idea")),
            intake_input=str(body.get("description", "")),
            source_url=body.get("url"),
        )
    elif service.get_product(product_id) is None:
        return _error(404, "Product not found.")

    analysis_id, _job = service.start_analysis(
        product_id,
        mode=str(body.get("mode", "founder")),
        research_enabled=bool(body.get("research", True)),
        deep_research=bool(body.get("deep_research", False)),
        extra_urls=list(body.get("extra_urls", []) or []),
    )
    return JSONResponse(
        {
            "product_id": product_id,
            "analysis_id": analysis_id,
            "status": "running",
            "poll": f"/v1/products/{product_id}/analysis",
        },
        status_code=202,
    )


@endpoint()
async def ask(request: Request, service: StudioService) -> Response:
    """Answering costs a model call, so it needs the write scope."""
    return _error(
        403, "Use POST /v1/products/{product_id}/ask with a write-scoped key."
    )


@endpoint(write=True)
async def post_ask(request: Request, service: StudioService) -> Response:
    body = await _json_body(request)
    product_id = request.path_params["product_id"]
    analysis = service.latest_analysis(product_id)
    if analysis is None:
        return _error(404, "No analysis found.")

    answer = service.ask(product_id, analysis["id"], str(body.get("question", "")))
    return JSONResponse(
        {
            "answer": answer.text,
            "confidence": answer.confidence,
            "caveats": answer.caveats,
            "citations": answer.citations,
            "dropped_citations": answer.dropped_citations,
            "retrieval": answer.retrieval,
        }
    )


async def not_found(request: Request, exc: Exception) -> Response:
    return _error(404, "Not found.")


ROUTES = [
    Route("/health", health),
    Route("/v1/products", list_products),
    Route("/v1/products", create_analysis, methods=["POST"]),
    Route("/v1/products/{product_id}/analysis", get_analysis),
    Route("/v1/products/{product_id}/score", get_score),
    Route("/v1/products/{product_id}/competitors", get_competitors),
    Route("/v1/products/{product_id}/recommendations", get_recommendations),
    Route("/v1/products/{product_id}/market", get_market),
    Route("/v1/products/{product_id}/radar", get_radar),
    Route("/v1/products/{product_id}/evidence", get_evidence),
    Route("/v1/products/{product_id}/export", export_analysis),
    Route("/v1/products/{product_id}/ask", ask),
    Route("/v1/products/{product_id}/ask", post_ask, methods=["POST"]),
    Route("/v1/simulate", simulate, methods=["POST"]),
]


def create_app() -> Starlette:
    """Build the ASGI application."""
    migrate(get_connection())
    return Starlette(
        routes=ROUTES,
        exception_handlers={404: not_found},
    )


app = create_app()
