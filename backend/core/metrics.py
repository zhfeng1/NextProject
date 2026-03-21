from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import Request, Response
from prometheus_client import Counter, Gauge, Histogram, generate_latest


http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
)
active_sites_total = Gauge("active_sites_total", "Number of active sites")
task_queue_length = Gauge("task_queue_length", "Number of tasks in queue", ["queue_name"])


async def prometheus_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    method = request.method
    endpoint = request.url.path
    start = perf_counter()
    response = await call_next(request)
    duration = perf_counter() - start
    http_requests_total.labels(method, endpoint, str(response.status_code)).inc()
    http_request_duration_seconds.labels(method, endpoint).observe(duration)
    return response


def render_metrics() -> Response:
    return Response(generate_latest(), media_type="text/plain; version=0.0.4")

