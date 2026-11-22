# Image of the showcase mock systems (standard library only). Build with the context
# examples/showcase and --build-arg SERVICE=engineering|logistics.
FROM python:3.13-slim
ARG SERVICE
ENV PYTHONUNBUFFERED=1 \
    SERVICE=${SERVICE}
WORKDIR /app
COPY shared shared
COPY engineering engineering
COPY logistics logistics
USER nobody
CMD ["sh", "-c", "exec python -m ${SERVICE}"]
