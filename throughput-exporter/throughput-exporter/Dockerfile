# Stage 1: Build
FROM golang:1.26.0-alpine3.23 AS builder
LABEL authors="mbelchior"

RUN apk add --no-cache libpcap-dev gcc musl-dev

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN go build -o throughput-monitor .

# Stage 2: Run
FROM alpine:3.23
LABEL authors="mbelchior"

RUN apk add --no-cache libpcap

COPY --from=builder /app/throughput-monitor .

EXPOSE 9200
ENTRYPOINT ["./throughput-monitor"]
CMD []