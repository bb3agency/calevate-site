"""Every image production pulls is pinned by digest, and CI tests against the same Redis.

FAILS IF: a service in `compose.prod.yml` names a registry image by tag alone (a tag can be
moved under us, D-188 / hard rule 9), or CI's Redis service drifts from production's.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_PROD = ROOT / "compose.prod.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def _prod_services() -> dict[str, dict[str, object]]:
    loaded = yaml.safe_load(COMPOSE_PROD.read_text(encoding="utf-8"))
    services: dict[str, dict[str, object]] = loaded["services"]
    return services


def test_every_pulled_image_is_pinned_by_digest() -> None:
    pulled = {
        name: str(service["image"])
        for name, service in _prod_services().items()
        # A service with `build:` runs the image this deploy built from the pinned
        # Dockerfile; only the ones fetched from a registry can be moved under us.
        if "build" not in service and "image" in service
    }
    assert pulled, "compose.prod.yml pulls no registry image; this test checks nothing"
    unpinned = {name: image for name, image in pulled.items() if not DIGEST.search(image)}
    assert not unpinned, f"pin these by digest: {unpinned}"


def test_ci_runs_the_redis_production_runs() -> None:
    prod = str(_prod_services()["redis"]["image"])
    ci_services = [
        job.get("services", {}).get("redis", {}).get("image")
        for job in yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"].values()
    ]
    ci_redis = {image for image in ci_services if image}
    assert ci_redis == {prod}
