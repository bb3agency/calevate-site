"""Guardrail: nothing in this repository may build the voice worker for the wrong CPU.

**WHY THIS EXISTS, AND IT IS NOT A HYPOTHETICAL.** On 16 Sep 2026 the bring-up was one
command away from building the agent image on an amd64 VPS and pushing it to a platform
that runs `arm64` in every region. `pipecat cloud regions list`, read on the deploy host:

    ap-south (Mumbai) / eu-central / us-east / us-west  — architectures: arm64, default arm64

There is no amd64 region. The failure that was avoided is the expensive kind: `docker build`
succeeds, `deploy` succeeds, and the container never starts, with nothing in any output
naming the architecture as the cause.

**WHY A TEST AND NOT A COMMENT.** Every path here is one somebody types by hand on a host
whose own architecture is the default for every tool involved — `docker pull`, `docker
build` and `uv` all silently mean "this machine" unless told otherwise. A comment saying
"remember --platform" is exactly the instruction that gets dropped the day somebody adds a
second build path in a hurry. The repository's own history is the argument: this is the
same defect class as `hide_parameters`, the deploy account's name and the image tag prefix —
nothing errors, and the thing breaks somewhere else, later, silently.

**WHAT THIS DOES NOT PROVE.** That an arm64 image actually BUILDS. That needs
`dailyco/pipecat-base`, which cannot be pulled from this container (Docker Hub's blob CDN
answers 403 through the proxy), so it is a deploy-host fact and is tracked as DEPLOYMENT
§12.5 gate 3. What this proves is narrower and is the half that regresses: that every build
input in this tree NAMES the target platform rather than inheriting the host's.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SETUP = _ROOT / "scripts" / "deploy" / "pipecat-worker-setup.sh"
_DEPLOYMENT = _ROOT / "docs" / "DEPLOYMENT.md"
_LOCK = _ROOT / "uv.lock"

#: The one architecture Pipecat Cloud offers. VENDOR FACT, read from `pipecat cloud regions
#: list` on the deploy host on 16 Sep 2026 and recorded in
#: `docs/evidence/pipecat-cloud-bringup-2026-09-16.md`. If this ever changes it changes in
#: the vendor's console first and here second — which is why the script reads it from a
#: variable and this test asserts the variable's default rather than a literal in ten places.
TARGET_ARCH = "arm64"


@pytest.fixture(scope="module")
def setup_script() -> str:
    assert _SETUP.is_file(), f"the bring-up script moved: {_SETUP}"
    return _SETUP.read_text()


def test_the_target_architecture_is_declared_once_and_is_the_platforms(setup_script: str) -> None:
    """ONE declaration, so a vendor change is one edit rather than a search."""
    assert f"PIPECAT_TARGET_ARCH=${{PIPECAT_TARGET_ARCH:-{TARGET_ARCH}}}" in setup_script, (
        "the target architecture is not declared as an overridable variable with the "
        f"vendor's own value ({TARGET_ARCH}) as its default"
    )
    assert 'TARGET_PLATFORM="linux/${PIPECAT_TARGET_ARCH}"' in setup_script, (
        "the docker platform string is not derived from the declared architecture, so the "
        "two can disagree"
    )


def test_every_pull_of_the_base_image_names_the_platform(setup_script: str) -> None:
    """**A MULTI-ARCH TAG RESOLVES TO THE HOST**, which is the whole trap.

    `docker pull dailyco/pipecat-base:latest` on an amd64 machine fetches the amd64
    manifest, and `RepoDigests` then reports THAT digest — so the "pinned" base image is
    pinned to an architecture the platform cannot run, and the pin looks correct.
    """
    pulls = re.findall(r"^\s*docker pull[^\n]*", setup_script, re.MULTILINE)
    assert pulls, "no docker pull found; this guard is asserting nothing"

    # ⚠ **THE TWO PULLS TARGET DIFFERENT ARCHITECTURES, AND THAT IS CORRECT.** This test
    # first demanded `--platform` on BOTH and failed — rightly, because the distinction is
    # real and is easy to flatten. The uv image is EXTRACTED AND RUN ON THIS HOST
    # (`install-cli` copies the binary out of it), so forcing the target platform there
    # would install a uv that cannot execute. The base image is BUILT ON and shipped to a
    # platform that is arm64 everywhere, so it must never inherit the host's.
    #
    # Distinguished by what the pull is FOR rather than by counting: a future third pull
    # has to declare which side it is on.
    host_pulls = [p for p in pulls if "$UV_IMAGE" in p]
    image_pulls = [p for p in pulls if "$UV_IMAGE" not in p]
    assert host_pulls, "the uv extraction pull vanished; this guard's exemption now hides nothing"
    for line in host_pulls:
        assert "--platform" not in line, (
            "the uv image is extracted and RUN on this host, so pinning it to the deploy "
            f"target would install a binary that cannot execute here: {line.strip()}"
        )
    assert image_pulls, "no pull of a shipped image found; this guard is asserting nothing"
    for line in image_pulls:
        assert "--platform" in line, (
            f"a pull inherits the host's architecture instead of naming the target: {line.strip()}"
        )


def test_the_image_build_names_the_platform(setup_script: str) -> None:
    """`docker build` has no cross-platform ability at all; `buildx` is what does.

    Asserted together because `--platform` on a plain `docker build` is accepted and then
    largely ignored on a default builder — a command that looks right and is not.
    """
    assert "buildx build" in setup_script, (
        "the build does not use buildx, so it cannot produce an image for another platform"
    )
    build = re.search(r"buildx build[^\n]*(?:\n[^\n]*)?", setup_script)
    assert build is not None
    assert "--platform" in build.group(0), "the buildx build does not name a platform"
    assert '"$TARGET_PLATFORM"' in build.group(0), (
        "the build names a platform that is not the declared one, so they can drift"
    )


def test_a_digest_of_the_wrong_architecture_is_refused(setup_script: str) -> None:
    """Belt AND braces, because the pull's `--platform` is silently a no-op on a host with
    no binfmt handlers: it can return the host's image anyway. The only honest check is to
    ask the pulled image what it IS."""
    assert ".Architecture" in setup_script, (
        "nothing verifies the architecture of the image whose digest is about to be pinned"
    )
    assert '"$PIPECAT_TARGET_ARCH"' in setup_script, (
        "the architecture check does not compare against the declared target"
    )


def test_the_doctor_reports_the_mismatch_before_a_build_is_attempted(setup_script: str) -> None:
    """A cross-build of this image is long. Learning the host cannot do it should cost one
    second in `doctor`, not twenty minutes in `build`."""
    assert "ARCHITECTURE" in setup_script, "doctor does not report the architecture at all"
    assert "uname -m" in setup_script, "doctor does not read the host's own architecture"
    assert "buildx" in setup_script


def test_the_deployment_contract_records_the_vendor_fact() -> None:
    """The guard above pins the CODE. This pins the REASON, so a future reader who wants to
    relax it finds the evidence rather than a bare constant."""
    text = _DEPLOYMENT.read_text()
    assert TARGET_ARCH in text, "DEPLOYMENT.md does not mention the target architecture"
    assert "regions list" in text, (
        "DEPLOYMENT.md does not name the command that establishes the architecture, so the "
        "claim cannot be re-checked when the vendor changes it"
    )


def test_the_lockfile_can_satisfy_the_target_architecture() -> None:
    """**THE BUILD CANNOT SUCCEED IF THE WHEELS DO NOT EXIST**, and that is a property of the
    lock rather than of the Dockerfile.

    `uv.lock` here is a UNIVERSAL lock (one `requires-python`, no `resolution-markers`
    forking the graph by platform), so every locked distribution resolves for every platform
    the marker set allows. This asserts the observable consequence: the binary wheels the
    voice worker actually needs are present for aarch64, not only for the host's x86_64.

    Checked on the four that would break a cross-build first, each a compiled extension with
    no pure-Python fallback.
    """
    lock = _LOCK.read_text()
    assert "resolution-markers" not in lock, (
        "the lock has forked by platform; a universal resolution is what makes the arm64 "
        "build's dependency set predictable and this guard's reasoning no longer holds"
    )
    for package in ("onnxruntime", "numpy", "pydantic_core", "uuid_utils"):
        assert re.search(rf"{package}-[^\"\s]*aarch64[^\"\s]*\.whl", lock), (
            f"{package} has no aarch64 wheel in uv.lock, so an arm64 build would have to "
            "compile it from source inside the image — or fail"
        )
