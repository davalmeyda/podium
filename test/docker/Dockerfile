# Clean-room Linux image used to verify that podium installs and works on a
# machine that has never seen it. Nothing from the host is baked in: the repo
# and credentials are mounted at run time by test/run.sh.
FROM debian:bookworm-slim

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git python3 python3-venv jq unzip xz-utils procps less \
 && rm -rf /var/lib/apt/lists/*

# Unprivileged user, like a real developer account.
RUN useradd --create-home --shell /bin/bash tester
USER tester
WORKDIR /home/tester
ENV PATH="/home/tester/.local/bin:/home/tester/.opencode/bin:${PATH}"

# Third-party CLIs podium integrates with, installed with their official installers.
# Always the latest releases: pass a fresh CACHE_BUST (test/run.sh uses a timestamp)
# so Docker never reuses a cached, outdated install.
ARG CACHE_BUST=0
RUN echo "cache-bust: ${CACHE_BUST}" && curl -fsSL https://claude.ai/install.sh | bash
# The installer ships OpenCode 1.x; podium targets OpenCode 2, so upgrade across the major.
RUN curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path \
 && /home/tester/.opencode/bin/opencode upgrade --major
RUN curl -fsSL https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.sh | bash || true

CMD ["bash"]
