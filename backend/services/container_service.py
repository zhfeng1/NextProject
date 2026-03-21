from __future__ import annotations

from pathlib import Path

from backend.services.site_service import site_service
from backend.utils.docker import build_image, docker_available, inspect_container_health, run_container


class ContainerService:
    def _generate_dockerfile(self, site_root: Path) -> Path:
        dockerfile = site_root / "Dockerfile"
        if not dockerfile.exists():
            dockerfile.write_text(
                """FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn[standard]
COPY backend /app/backend
COPY frontend /app/frontend
EXPOSE 8080
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8080"]
""",
                encoding="utf-8",
            )
        return dockerfile

    async def create_site_container(self, site) -> str:
        if not docker_available():
            raise RuntimeError("Docker is not available")
        root = site_service.ensure_site_structure(site.site_id)
        dockerfile = self._generate_dockerfile(root)
        image_tag = f"nextproject/site-{site.site_id}:latest"
        build_image(root, dockerfile, image_tag)
        container_id = run_container(
            image_tag=image_tag,
            name=f"site-{site.site_id}",
            port_mapping=f"{site.port}:8080",
            network="nextproject-network",
            labels={"site_id": site.site_id, "org_id": str(site.org_id)},
            volumes=[f"{root / 'data'}:/app/data"],
            extra_args=["--memory", "512m", "--cpus", "0.5"],
        )
        inspect_container_health(container_id)
        return container_id


container_service = ContainerService()
