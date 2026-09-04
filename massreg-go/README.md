# MassReg Go - High-Performance Account Registration System

[![Go Version](https://img.shields.io/badge/go-1.19+-blue.svg)](https://golang.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Build Status](https://github.com/massreg/massreg-go/actions/workflows/build.yml/badge.svg)](https://github.com/massreg/massreg-go/actions)

## Overview

MassReg Go is a complete rewrite of the Python MassReg system in Go, designed for high-performance bulk account registration with strict traffic optimization and scalability requirements.

### Key Features

- **No Browser Automation**: Direct HTTP API calls instead of Playwright (5-10s → 0.5-2s per registration)
- **Traffic Optimization**: Gzip/Zstd compression, HTTP/2, keep-alive, caching (95% bandwidth reduction)
- **High Performance**: Target 1M+ registrations/day (17 hours vs 81 days in Python)
- **Microservices Architecture**: Scalable API gateway, workers, scheduler
- **Security**: No hardcoded secrets, JWT auth, AES-256 encryption
- **Monitoring**: Prometheus metrics, Grafana dashboards, structured logging

## Architecture

```
massreg-go/
├── cmd/
│   ├── api/           # API Gateway (port 8000)
│   ├── worker/        # Registration Workers (scalable)
│   ├── scheduler/     # Task Scheduler
│   └── migrator/      # Database Migrations
├── internal/
│   ├── core/          # Shared components
│   │   ├── config/    # Configuration
│   │   ├── logger/    # Structured JSON logging
│   │   ├── metrics/   # Prometheus metrics
│   │   └── errors/    # Error handling
│   ├── services/      # Business logic
│   │   ├── registration/  # Account registration (NO BROWSER!)
│   │   ├── sms/       # SMS providers (SMS-Activate)
│   │   ├── proxy/     # Proxy pools with health checks
│   │   └── ml/        # ML optimization
│   ├── repository/    # Database layer
│   ├── cache/         # Redis cluster
│   └── queue/         # Kafka message queue
├── pkg/
│   ├── client/        # Optimized HTTP clients
│   └── utils/         # Utilities
├── configs/           # YAML configurations
├── deployments/       # Kubernetes manifests
└── Dockerfile
```

## Performance Targets

| Metric | Python | Go | Improvement |
|--------|--------|-----|-------------|
| Registration time | 5-10 sec | 0.5-2 sec | 80% |
| Memory usage | 200 MB | 20 MB | 90% |
| CPU usage | 100% | 30% | 70% |
| Network traffic | 10 TB/day | 500 GB/day | 95% |
| RPS | 50 | 1000 | 20x |
| Deployment size | 50 MB | 15 MB | 70% |

## Quick Start

### Prerequisites

- Go 1.19+
- Docker & Docker Compose
- PostgreSQL 15+
- Redis 7+
- Kafka 2.8+

### Local Development

```bash
# Clone repository
git clone https://github.com/massreg/massreg-go.git
cd massreg-go

# Download dependencies
go mod download

# Run with Docker Compose
docker-compose up -d

# Or run locally
make build
./bin/api
./bin/worker
```

### Environment Variables

```bash
# Required
export JWT_SECRET=your-jwt-secret-min-32-chars
export API_KEY=your-api-key
export POSTGRES_URL=postgres://user:pass@localhost:5432/massreg?sslmode=disable
export REDIS_NODES=localhost:6379
export REDIS_PASSWORD=redis-password
export KAFKA_BROKERS=localhost:9092
export SMS_API_KEY_1=your-sms-activate-api-key
export AES_ENCRYPTION_KEY=32-character-encryption-key!

# Optional
export PROXY_LIST=http://proxy1:port,http://proxy2:port
export CONFIG_PATH=configs/config.yaml
```

## API Endpoints

### Health Check
```bash
GET /health
```

### Metrics (Prometheus)
```bash
GET /metrics
```

### Register Account
```bash
POST /api/v1/register
Content-Type: application/json

{
  "service": "Microsoft",
  "email": "",  // Empty to auto-generate
  "password": "",  // Empty to auto-generate
  "country": "US",
  "need_phone": true,
  "proxy_required": true
}
```

### Get Statistics
```bash
GET /api/v1/stats
```

## Configuration

See `configs/config.yaml` for full configuration options.

```yaml
server:
  host: "0.0.0.0"
  port: 8000
  jwt_secret: ${JWT_SECRET}
  
database:
  driver: "postgres"
  dsn: ${POSTGRES_URL}
  max_open_conns: 50
  
redis:
  addrs: ${REDIS_NODES}
  password: ${REDIS_PASSWORD}
  
sms:
  providers:
    - name: "primary"
      api_key: ${SMS_API_KEY_1}
      api_url: "https://46.21.159.86/stubs/handler_api.php"
      
proxy:
  enabled: true
  strategy: "least_used"
  health_check:
    enabled: true
    interval: "30s"
```

## Supported Services

- Microsoft Outlook
- Google Gmail
- Apple ID
- Snapchat
- Instagram
- Facebook
- Discord

## Traffic Optimization

### Implemented Optimizations

1. **Compression**: Gzip/Zstd for all HTTP requests/responses (60-80% savings)
2. **Connection Pooling**: HTTP keep-alive with configurable pool (30-50% savings)
3. **HTTP/2**: Multiplexing for concurrent requests (20-30% savings)
4. **Caching**: Redis distributed cache (40-60% savings)
5. **Batching**: Batch API requests (50-70% savings)
6. **Minimal Payloads**: Only required fields in JSON

## Security

- ✅ No hardcoded secrets (environment variables only)
- ✅ AES-256 encryption for data at rest
- ✅ HTTPS for all external connections
- ✅ JWT authentication with refresh tokens
- ✅ Audit logs for all actions
- ✅ Rate limiting (1000 req/sec per IP)
- ✅ SQL injection prevention (parameterized queries)

## Monitoring

### Prometheus Metrics

- `registration_attempts_total`: Total registration attempts
- `registration_success_total`: Successful registrations
- `registration_duration_seconds`: Registration latency histogram
- `proxy_pool_size`: Available proxies
- `sms_requests_total`: SMS API requests
- `http_requests_total`: HTTP client requests

### Grafana Dashboards

Access at `http://localhost:3000` (admin/admin)

Pre-configured dashboards:
- Registration Overview
- Worker Performance
- Proxy Health
- SMS Provider Stats

## Kubernetes Deployment

```bash
# Deploy to Kubernetes
kubectl apply -f deployments/

# Scale workers
kubectl scale deployment massreg-worker --replicas=10

# Check status
kubectl get pods -l app=massreg
```

## Make Commands

```bash
make build          # Build all binaries
make test           # Run tests with coverage
make fmt            # Format code
make vet            # Run go vet
make lint           # Run linter
make docker-build   # Build Docker image
make docker-run     # Run with docker-compose
make migrate-up     # Run database migrations
make clean          # Remove build artifacts
```

## Testing

```bash
# Unit tests
go test ./internal/... ./pkg/...

# Integration tests
go test -tags=integration ./tests/...

# With coverage
go test -v -race -coverprofile=coverage.out ./...
go tool cover -html=coverage.out
```

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For issues and questions:
- GitHub Issues: https://github.com/massreg/massreg-go/issues
- Documentation: https://github.com/massreg/massreg-go/wiki

---

**Note**: This software is intended for educational purposes and legitimate testing. Ensure compliance with terms of service for any platforms you interact with.
