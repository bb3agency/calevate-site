# Local S3 emulator for docker-compose.yml, built from MinIO's own source.
#
# MinIO publishes no anonymous image any more (quay.io answers "unauthorized";
# https://www.ibm.com/support/pages/node/7289585) and github.com/minio/minio was archived
# on 25 Apr 2026. This builds its last release tag, RELEASE.2025-10-15T17-29-55Z (commit
# 9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a, https://github.com/minio/minio/tags), the same
# tag CI builds in `.github/workflows/ci.yml`. That tag's go.mod says `go 1.24.0` and
# `toolchain go1.24.8`, hence Go 1.24.8 exactly and GOTOOLCHAIN=local. `go install`
# verifies the module against sum.golang.org.
#
# Both bases are pinned by index digest (hard rule 9), read from registry-1.docker.io's
# docker-content-digest header on 29 Sep 2026.

FROM golang:1.24.8-bookworm@sha256:4ed690d6649d63c312b99a6120025ec79ce3b542968a37da53d6236c7c61a848 AS build
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
RUN go install github.com/minio/minio@RELEASE.2025-10-15T17-29-55Z

FROM debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251
COPY --from=build /go/bin/minio /usr/local/bin/minio
# Runs as root so an existing `miniodata` volume is usable whatever owner wrote it. A
# developer-only emulator; nothing here reaches a deployed host.
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
