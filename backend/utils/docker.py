import subprocess
from pathlib import Path


def run_checked_command(command: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"command failed: {' '.join(command)}")
    return result.stdout.strip()


def docker_available() -> bool:
    result = subprocess.run(["docker", "version"], capture_output=True, text=True)
    return result.returncode == 0


def build_image(context_dir: Path, dockerfile: Path, image_tag: str) -> str:
    return run_checked_command(
        ["docker", "build", "-t", image_tag, "-f", str(dockerfile), str(context_dir)],
        cwd=context_dir,
    )


def push_image(image_tag: str) -> str:
    return run_checked_command(["docker", "push", image_tag])


def remove_image(image_tag: str) -> str:
    return run_checked_command(["docker", "rmi", image_tag])


def run_container(
    *,
    image_tag: str,
    name: str,
    port_mapping: str,
    network: str,
    labels: dict[str, str] | None = None,
    volumes: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> str:
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        network,
        "-p",
        port_mapping,
    ]
    for key, value in (labels or {}).items():
        command.extend(["--label", f"{key}={value}"])
    for volume in volumes or []:
        command.extend(["-v", volume])
    if extra_args:
        command.extend(extra_args)
    command.append(image_tag)
    return run_checked_command(command)


def inspect_container_health(container_id: str, timeout: int = 30) -> str:
    import time

    started = time.time()
    while time.time() - started < timeout:
        result = subprocess.run(
            ["docker", "inspect", "--format={{.State.Health.Status}}", container_id],
            capture_output=True,
            text=True,
        )
        status = result.stdout.strip()
        if status in {"healthy", ""}:
            return status or "running"
        time.sleep(1)
    raise TimeoutError(f"Container {container_id} health check timed out")
