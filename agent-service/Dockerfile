FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /service
COPY app ./app

EXPOSE 8000
CMD ["python", "-m", "app.main"]

