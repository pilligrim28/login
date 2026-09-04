.PHONY: build test run clean docker k8s lint vet fmt

# Build variables
VERSION ?= 1.0.0
BUILD_TIME := $(shell date -u '+%Y-%m-%d_%H:%M:%S')
GIT_COMMIT := $(shell git rev-parse --short HEAD)

LDFLAGS := -ldflags "-X main.Version=$(VERSION) -X main.BuildTime=$(BUILD_TIME) -X main.GitCommit=$(GIT_COMMIT)"

# Go commands
GO := go
GOFMT := gofmt
GOLINT := golangci-lint

# Binary names
API_BINARY := api
WORKER_BINARY := worker
SCHEDULER_BINARY := scheduler
MIGRATOR_BINARY := migrator

# Default target
all: fmt vet lint build test

## Build targets
build: build-api build-worker build-scheduler build-migrator

build-api:
	@echo "Building API Gateway..."
	$(GO) build $(LDFLAGS) -o bin/$(API_BINARY) ./cmd/api

build-worker:
	@echo "Building Worker..."
	$(GO) build $(LDFLAGS) -o bin/$(WORKER_BINARY) ./cmd/worker

build-scheduler:
	@echo "Building Scheduler..."
	$(GO) build $(LDFLAGS) -o bin/$(SCHEDULER_BINARY) ./cmd/scheduler

build-migrator:
	@echo "Building Migrator..."
	$(GO) build $(LDFLAGS) -o bin/$(MIGRATOR_BINARY) ./cmd/migrator

## Run targets
run-api:
	$(GO) run ./cmd/api

run-worker:
	$(GO) run ./cmd/worker

run-scheduler:
	$(GO) run ./cmd/scheduler

run-all: build
	@echo "Starting all services..."
	./bin/$(API_BINARY) &
	./bin/$(WORKER_BINARY) &
	./bin/$(SCHEDULER_BINARY) &

## Test targets
test:
	$(GO) test -v -race -coverprofile=coverage.out ./...

test-coverage: test
	$(GO) tool cover -html=coverage.out -o coverage.html

test-unit:
	$(GO) test -v ./internal/... ./pkg/...

test-integration:
	$(GO) test -v -tags=integration ./tests/...

## Code quality
fmt:
	@echo "Formatting code..."
	$(GO) fmt ./...

vet:
	@echo "Running go vet..."
	$(GO) vet ./...

lint:
	@echo "Running linter..."
	$(GOLINT) run ./...

## Docker targets
docker-build:
	docker build -t massreg-go:$(VERSION) .

docker-run:
	docker-compose up -d

docker-stop:
	docker-compose down

## Kubernetes targets
k8s-deploy:
	kubectl apply -f deployments/

k8s-scale:
	kubectl scale deployment massreg-worker --replicas=10

k8s-status:
	kubectl get pods -l app=massreg

## Database migrations
migrate-up: build-migrator
	./bin/$(MIGRATOR_BINARY) up

migrate-down: build-migrator
	./bin/$(MIGRATOR_BINARY) down

migrate-status: build-migrator
	./bin/$(MIGRATOR_BINARY) status

## Clean
clean:
	rm -rf bin/
	rm -f coverage.out coverage.html
	$(GO) clean

## Help
help:
	@echo "MassReg Go - Makefile Commands"
	@echo ""
	@echo "Build:"
	@echo "  make build          - Build all binaries"
	@echo "  make build-api      - Build API gateway"
	@echo "  make build-worker   - Build worker service"
	@echo ""
	@echo "Run:"
	@echo "  make run-api        - Run API gateway"
	@echo "  make run-worker     - Run worker"
	@echo "  make run-all        - Run all services"
	@echo ""
	@echo "Test:"
	@echo "  make test           - Run all tests with coverage"
	@echo "  make test-unit      - Run unit tests"
	@echo "  make test-coverage  - Generate coverage report"
	@echo ""
	@echo "Code Quality:"
	@echo "  make fmt            - Format code"
	@echo "  make vet            - Run go vet"
	@echo "  make lint           - Run linter"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build   - Build Docker image"
	@echo "  make docker-run     - Run with docker-compose"
	@echo ""
	@echo "Kubernetes:"
	@echo "  make k8s-deploy     - Deploy to Kubernetes"
	@echo "  make k8s-scale      - Scale workers"
	@echo ""
	@echo "Database:"
	@echo "  make migrate-up     - Run database migrations"
	@echo "  make migrate-down   - Rollback migrations"
	@echo ""
	@echo "Clean:"
	@echo "  make clean          - Remove build artifacts"
