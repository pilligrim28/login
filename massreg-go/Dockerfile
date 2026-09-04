# Build stage
FROM golang:1.19-alpine AS builder

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache git ca-certificates tzdata

# Copy go mod files
COPY go.mod go.sum* ./

# Download dependencies
RUN go mod download

# Copy source code
COPY . .

# Build arguments
ARG VERSION=dev
ARG BUILD_TIME=unknown
ARG GIT_COMMIT=unknown

# Build all binaries
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags "-X main.Version=${VERSION} -X main.BuildTime=${BUILD_TIME} -X main.GitCommit=${GIT_COMMIT}" -o bin/api ./cmd/api
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags "-X main.Version=${VERSION} -X main.BuildTime=${BUILD_TIME} -X main.GitCommit=${GIT_COMMIT}" -o bin/worker ./cmd/worker
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags "-X main.Version=${VERSION} -X main.BuildTime=${BUILD_TIME} -X main.GitCommit=${GIT_COMMIT}" -o bin/scheduler ./cmd/scheduler
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags "-X main.Version=${VERSION} -X main.BuildTime=${BUILD_TIME} -X main.GitCommit=${GIT_COMMIT}" -o bin/migrator ./cmd/migrator

# Runtime stage
FROM alpine:3.18

WORKDIR /app

# Install runtime dependencies
RUN apk add --no-cache ca-certificates tzdata

# Create non-root user
RUN addgroup -g 1000 massreg && \
    adduser -D -u 1000 -G massreg massreg

# Copy binaries from builder
COPY --from=builder /app/bin/* /app/

# Copy config template
COPY configs/config.yaml /app/configs/

# Set ownership
RUN chown -R massreg:massreg /app

# Switch to non-root user
USER massreg

# Expose ports
EXPOSE 8000 9090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8000/health || exit 1

# Default command
ENTRYPOINT ["/app/api"]
