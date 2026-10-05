# KYC Document Intelligence service.
# Build context is the repository root (COPY paths start with app/), which is what the
# pipeline's `docker build .` uses.

FROM python:3.12-slim AS build
WORKDIR /build
COPY app/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /srv
COPY --from=build /install /usr/local
COPY app/kyc ./kyc
USER 10001
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '5000'), timeout=3)"]
CMD ["sh", "-c", "exec uvicorn kyc.main:get_app --factory --host 0.0.0.0 --port ${PORT}"]
