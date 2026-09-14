FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv/ponke
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN pip install --no-deps . && useradd --create-home ponke
USER ponke
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
