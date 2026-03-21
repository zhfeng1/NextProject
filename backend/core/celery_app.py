from celery import Celery

from backend.core.config import get_settings


settings = get_settings()

celery_app = Celery(
    "nextproject",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "backend.tasks.develop_code",
        "backend.tasks.deploy",
        "backend.tasks.test",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    task_soft_time_limit=settings.default_task_timeout_seconds,
    task_time_limit=settings.default_task_timeout_seconds + 300,
    task_routes={
        "backend.tasks.develop_code.develop_code_task": {"queue": "ai-tasks"},
        "backend.tasks.deploy.deploy_task": {"queue": "deploy-tasks"},
        "backend.tasks.test.playwright_smoke_task": {"queue": "test-tasks"},
    },
)

