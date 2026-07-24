FROM alpine:3.20
LABEL org.opencontainers.image.title="AetherStack" \
      org.opencontainers.image.description="Multi-model LLM control plane for Docker Desktop" \
      org.opencontainers.image.vendor="piksliviksi" \
      com.docker.desktop.extension.api.version=">= 0.2.3" \
      com.docker.desktop.extension.icon="https://raw.githubusercontent.com/piksliviksi/aetherstack/main/aetherstack.jpg" \
      com.docker.extension.screenshots="" \
      com.docker.extension.detailed-description="Start Open WebUI, LiteLLM, and Redis. Connect host Ollama for local GPU inference (NVIDIA, AMD, Intel)." \
      com.docker.extension.publisher-url="https://github.com/piksliviksi/aetherstack" \
      com.docker.extension.additional-urls='[{"title":"Documentation","url":"https://github.com/piksliviksi/aetherstack"}]' \
      com.docker.extension.categories="ai-ml,utility-tools" \
      com.docker.extension.changelog="Initial AetherStack Docker Extension scaffold"

COPY metadata.json .
COPY docker-compose.yaml .
COPY litellm_config.yaml .
COPY ui /ui
COPY aetherstack.svg .

WORKDIR /
