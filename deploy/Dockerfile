# Imagem do scopehound (API + worker). Ferramentas externas (nuclei/ffuf/
# sqlmap) não vêm instaladas: habilite-as e instale os binários conscientemente.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SCOPEHOUND_MODE=server \
    SCOPEHOUND_HOST=0.0.0.0

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --extra server --no-dev

EXPOSE 8787
# roda como usuário sem privilégios
RUN useradd -m hound && chown -R hound /app
USER hound

CMD ["uv", "run", "scopehound", "serve"]
