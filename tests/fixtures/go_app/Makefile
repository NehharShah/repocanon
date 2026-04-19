.PHONY: build build-api build-worker test test-race lint fmt run-api run-worker

build: build-api build-worker

build-api:
	go build -o bin/api ./cmd/api

build-worker:
	go build -o bin/worker ./cmd/worker

run-api:
	go run ./cmd/api

run-worker:
	go run ./cmd/worker

test:
	go test ./...

test-race:
	go test -race ./...

lint:
	golangci-lint run ./...

fmt:
	gofmt -w .
