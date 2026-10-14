FROM python:3.10.20-alpine3.22
LABEL authors="mbelchior"

WORKDIR /app
COPY main.py .
COPY requirements.txt .

RUN pip install -r requirements.txt
RUN adduser -D -u 1000 slicepoller

USER 1000
CMD ["python", "./main.py"]
