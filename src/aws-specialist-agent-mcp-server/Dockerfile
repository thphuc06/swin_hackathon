FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

ARG INSTALL_OPTIONAL_FINANCE_EXTRAS=false

COPY requirements.txt /app/requirements.txt
COPY requirements.optional-finance.txt /app/requirements.optional-finance.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && if [ "$INSTALL_OPTIONAL_FINANCE_EXTRAS" = "true" ]; then \
        pip install --no-cache-dir -r /app/requirements.optional-finance.txt; \
    fi

COPY app /app/app
COPY schemas /app/schemas
COPY planner_agent /app/planner_agent
COPY service_agent /app/service_agent
COPY stock /app/stock

EXPOSE 8000
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
