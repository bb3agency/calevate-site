"""Guardrail: nothing in this repository may ship the voice worker for the wrong CPU.

**WHY THIS EXISTS, AND IT IS NOT A HYPOTHETICAL.** On 16 Sep 2026 the bring-up was one
command away from building the agent image on an amd64 VPS and pushing it to a platform
that runs `arm64` in every region. `pipecat cloud regions list`, read on the deploy host:

    ap-south (Mumbai) / eu-central / us-east / us-west  — architectures: arm64, default arm64

There is no amd64 region. The failure that was avoided is the expensive kind: `docker build`
succeeds, `deploy` succeeds, and the container never starts, with nothing in any output
naming the architecture as the cause.

⚠ **WHAT THIS FILE GUARDS CHANGED WITH D-622, AND THE OLD CLAUSES ARE GONE RATHER THAN
RELAXED.** It used to pin a LOCAL cross-build: `--platform` on every pull and on `buildx
build`, and an `.Architecture` check on the pulled image. That build no longer exists. The
deploy host cannot execute an arm64 binary at all (`/proc/sys/fs/binfmt_misc` holds only
`python3.12`; `docker run --platform linux/arm64 alpine uname -m` answers `exec format
error`, measured 16 Sep 2026), and the alternative to emulating an entire image build on a
production VPS — and then standing up a registry and an image-pull secret so the platform
could fetch the result — is to let Pipecat build it on the architecture they already run.

So the architecture is now decided in three places instead of one, and each is asserted
below: the Dockerfile's pinned base, the deploy manifest's declared region and
architecture, and the absence of any `image`/`build_id` key (which is what makes the CLI
build in the cloud at all). Guarding the old build would be guarding a path nobody runs.

**WHAT THIS DOES NOT PROVE.** That an arm64 image actually BUILDS. That happens on the
vendor's builder and is tracked as DEPLOYMENT §12.5 gate 3.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SETUP = _ROOT / "scripts" / "deploy" / "pipecat-worker-setup.sh"
_DEPLOYMENT = _ROOT / "docs" / "DEPLOYMENT.md"
_DOCKERFILE = _ROOT / "apps" / "voice-worker" / "Dockerfile"
_MANIFEST = _ROOT / "apps" / "voice-worker" / "pcc-deploy.toml"
_LOCK = _ROOT / "uv.lock"

#: The one architecture Pipecat Cloud offers. VENDOR FACT, read from `pipecat cloud regions
#: list` on the deploy host on 16 Sep 2026 and recorded in
#: `docs/evidence/pipecat-cloud-bringup-2026-09-16.md`. If this ever changes it changes in
#: the vendor's console first and here second — which is why the script reads it from a
#: variable and this test asserts the variable's default rather than a literal in ten places.
TARGET_ARCH = "arm64"

#: Mumbai. The caller, the carrier and the business are in India, and the in-call path is
#: the one place a hemisphere costs a conversational turn.
TARGET_REGION = "ap-south"


@pytest.fixture(scope="module")
def setup_script() -> str:
    assert _SETUP.is_file(), f"the bring-up script moved: {_SETUP}"
    return _SETUP.read_text()


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert _MANIFEST.is_file(), f"the deploy manifest moved: {_MANIFEST}"
    return tomllib.loads(_MANIFEST.read_text())


def test_the_target_architecture_is_declared_once(setup_script: str) -> None:
    """ONE declaration, so a vendor change is one edit rather than a search."""
    assert f"PIPECAT_TARGET_ARCH=${{PIPECAT_TARGET_ARCH:-{TARGET_ARCH}}}" in setup_script, (
        "the target architecture is not declared as an overridable variable with the "
        f"vendor's own value ({TARGET_ARCH}) as its default"
    )
    assert 'TARGET_PLATFORM="linux/${PIPECAT_TARGET_ARCH}"' in setup_script, (
        "the docker platform string is not derived from the declared architecture, so the "
        "two can disagree"
    )


def test_the_base_image_is_pinned_by_digest_because_a_cloud_build_takes_no_build_arg() -> None:
    """**THE DOCKERFILE'S DEFAULT IS THE BUILD INPUT, NOT A FALLBACK.**

    `pipecatcloud`'s build request carries exactly `uploadId`, `dockerfilePath` and `region`
    (`_utils/deploy_utils.py` -> `api.py::_build_create`, version 1.2.0, read 16 Sep 2026).
    There is nowhere to pass `--build-arg`, so whatever this line says is what the vendor's
    builder builds on — and a mutable tag there is hard rule 9's exact prohibition with the
    ARG making it look guarded.
    """
    bases = re.findall(r"^ARG PIPECAT_BASE=(.+)$", _DOCKERFILE.read_text(), re.MULTILINE)
    assert len(bases) == 1, f"expected exactly one ARG PIPECAT_BASE line, found {len(bases)}"
    assert "@sha256:" in bases[0], (
        f"the base image is pinned to '{bases[0]}', a mutable tag. A cloud build cannot be "
        "handed a different value, so this is the build input."
    )


def test_the_manifest_declares_the_architecture_and_the_region(manifest: dict) -> None:
    """Declared rather than inherited, and validated by the CLI before anything is built:
    `_utils/regions.py::validate_architecture_for_region` refuses an architecture the region
    does not list, which turns a container that never starts into an error at the edge."""
    assert manifest.get("architecture") == TARGET_ARCH, (
        f"the deploy manifest does not declare architecture = {TARGET_ARCH!r}"
    )
    assert manifest.get("region") == TARGET_REGION, (
        f"the deploy manifest does not declare region = {TARGET_REGION!r}"
    )


def test_the_manifest_names_no_image_because_that_is_what_triggers_the_cloud_build(
    manifest: dict,
) -> None:
    """An `image` or `build_id` key would send the deploy down the pre-built path, which
    needs a registry we do not have and an image-pull secret we would then have to own
    (`cli/commands/deploy.py:909-957`). Their absence is load-bearing, not an omission."""
    assert "image" not in manifest, (
        "the manifest names an image, so the deploy would try to PULL one instead of "
        "building it — and this repository publishes the worker image nowhere"
    )
    assert "build_id" not in manifest, (
        "the manifest pins a build_id, which reuses one past build forever instead of "
        "building the current context"
    )


def test_the_digest_command_selects_by_architecture_rather_than_by_what_the_host_pulled(
    setup_script: str,
) -> None:
    """**A MULTI-ARCH TAG RESOLVES TO THE HOST**, which is the whole trap, and `docker pull
    --platform` is not a reliable escape from it: on a host with no binfmt handlers it can
    return the host's image anyway. Reading the manifest LIST and picking the entry whose
    platform matches has no such failure mode — and transfers no layers."""
    assert "imagetools inspect" in setup_script, (
        "the digest is not read from the registry's manifest list, so it can still be "
        "whatever this host happened to pull"
    )
    assert "--raw" in setup_script, (
        "`--format` fetches each child's config blob and 403s wherever the blob CDN is "
        "proxied; `--raw` returns the index itself and is what works from a restricted host"
    )
    assert '"$PIPECAT_TARGET_ARCH"' in setup_script, (
        "the digest selection does not compare against the declared target architecture"
    )
    # The ONE pull left is the uv image, which is extracted and RUN ON THIS HOST by
    # `install-cli` — so it must stay the host's architecture and is not what this guards.
    # Any other pull would be fetching something we ship, and a pull inherits the host's
    # architecture: that is the instrument this command deliberately stopped using.
    pulls = re.findall(r"^\s*docker pull[^\n]*", setup_script, re.MULTILINE)
    shipped = [line for line in pulls if "$UV_IMAGE" not in line]
    assert not shipped, (
        "a pull of a shipped image is back; it inherits this host's architecture: "
        f"{[line.strip() for line in shipped]}"
    )


def test_the_doctor_reports_the_architecture_and_the_pin(setup_script: str) -> None:
    """An operator should be able to see, in one second and before anything is submitted,
    which architecture is targeted and what the build will actually be based on."""
    assert "ARCHITECTURE" in setup_script, "doctor does not report the architecture at all"
    assert "uname -m" in setup_script, "doctor does not read the host's own architecture"
    assert "BASE IMAGE" in setup_script, "doctor does not report the pinned base image"
    assert "dockerfile_base" in setup_script, (
        "doctor does not read the pin from the Dockerfile, so it could report something the "
        "build does not use"
    )


def test_the_deployment_contract_records_the_vendor_fact() -> None:
    """The guards above pin the CODE. This pins the REASON, so a future reader who wants to
    relax it finds the evidence rather than a bare constant."""
    text = _DEPLOYMENT.read_text()
    assert TARGET_ARCH in text, "DEPLOYMENT.md does not mention the target architecture"
    assert "regions list" in text, (
        "DEPLOYMENT.md does not name the command that establishes the architecture, so the "
        "claim cannot be re-checked when the vendor changes it"
    )


def test_the_lockfile_can_satisfy_the_target_architecture() -> None:
    """**THE BUILD CANNOT SUCCEED IF THE WHEELS DO NOT EXIST**, and that is a property of the
    lock rather than of the Dockerfile — and it is unchanged by the build moving to the
    vendor's machine, because they run `uv sync` against this same lock.

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
