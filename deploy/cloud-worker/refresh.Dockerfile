# Optional fast path for source-only updates on a previously qualified exact image.
# The normal Dockerfile remains the full dependency-build path.
ARG QUALIFIED_WORKER_IMAGE
FROM ${QUALIFIED_WORKER_IMAGE}
ARG QUALIFIED_WORKER_IMAGE
ARG STPD_SOURCE_REVISION
WORKDIR /opt/stpd
RUN printf '%s' "$QUALIFIED_WORKER_IMAGE" | grep -Eq '@sha256:[0-9a-f]{64}$' && \
    printf '%s' "$STPD_SOURCE_REVISION" | grep -Eq '^[0-9a-f]{40}$' && \
    test -z "$(git status --porcelain)" && \
    stpd_refresh_lock=$(sha256sum uv.lock | cut -d ' ' -f 1) && \
    git fetch origin "$STPD_SOURCE_REVISION" && \
    git checkout --detach "$STPD_SOURCE_REVISION" && \
    test "$stpd_refresh_lock" = "$(sha256sum uv.lock | cut -d ' ' -f 1)" && \
    uv sync --locked --all-extras --offline && \
    test -z "$(git status --porcelain)"
