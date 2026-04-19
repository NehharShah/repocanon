# go-app fixture

Minimal Go multi-binary fixture used by RepoCanon's analyzer tests:

- `cmd/api/main.go` and `cmd/worker/main.go` — two binaries to exercise multi_binary topology detection.
- `internal/store/` — exercises the Go internal/ visibility boundary.
- `pkg/api/` — exercises the public Go package directory role.
- `go.mod` uses block-form `require ( ... )` and lists deps that exercise multiple GO_RULES (gin, cobra, viper, gorm, sqlx, go-ethereum, testify, zap).
