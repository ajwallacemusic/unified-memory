# routekit

routekit is an open-source freight lane-pricing toolkit written in Go. It ingests carrier rate sheets, normalizes them into lanes, and produces quotes via a rating engine exposed as a library, a CLI, and a gRPC/HTTP service.

## Architecture Overview

routekit is a single Go module (`github.com/routekit/routekit`) organized as a monorepo with three layers:

1. **Ingest** – parses carrier rate sheets (CSV, XLSX, EDI 204/210) into canonical `RateRecord` values.
2. **Core** – lane normalization, geography resolution, rating, surcharge application, and quote assembly. Pure Go, no I/O except through interfaces.
3. **Delivery** – `routekitd` (service), `routekit` (CLI), and the generated client SDK.

Data flow: `ingest` -> `store` (Postgres) -> `lane` + `geo` -> `rating` -> `quote` -> `api`/`cli`.

Design principles:
- Core packages depend on interfaces, never on concrete database or HTTP types.
- Money is always integer minor units (`money.Amount`); never use floats for currency.
- Rating is deterministic: the same inputs and the same rate-table version must yield byte-identical quotes.
- All time handling is UTC internally; convert at the edges only.

## Package Map

| Path | Purpose |
|------|---------|
| `cmd/routekitd` | Service entrypoint (gRPC + HTTP gateway) |
| `cmd/routekit` | CLI entrypoint (cobra) |
| `cmd/migrate` | Migration runner wrapper |
| `internal/ingest` | Rate sheet parsers and validators |
| `internal/lane` | Lane model, normalization, lane keys |
| `internal/geo` | ZIP/postal, UN/LOCODE, and zone resolution |
| `internal/rating` | Rating engine, tiers, minimums, breakpoints |
| `internal/surcharge` | Fuel, accessorial, and seasonal surcharges |
| `internal/quote` | Quote assembly, expiry, and versioning |
| `internal/store` | Postgres repositories (pgx + sqlc) |
| `internal/api` | gRPC handlers and HTTP gateway wiring |
| `internal/config` | Env/file config loading and validation |
| `internal/obs` | Logging, metrics, tracing helpers |
| `pkg/money` | Integer currency type and arithmetic |
| `pkg/routekitclient` | Public Go client SDK |
| `proto/` | Protobuf definitions (buf-managed) |
| `db/migrations` | Versioned SQL migrations |
| `db/queries` | sqlc query files |
| `testdata/` | Golden files and sample rate sheets |
| `tools/` | Dev tooling pinned via `tools.go` |
| `docs/` | Design docs and ADRs |

Only `pkg/` is public API. Everything under `internal/` may change without notice.

## Build, Test, and Lint Commands

```
make build            # build all binaries into ./bin
make test             # unit tests with -race
make test-integration # requires Docker; spins up Postgres via testcontainers
make lint             # golangci-lint run ./...
make fmt              # gofumpt + goimports
make generate         # buf generate + sqlc generate + go generate ./...
make proto-lint       # buf lint && buf breaking --against .git#branch=main
make golden-update    # regenerate golden files (review the diff!)
make cover            # coverage report to ./coverage.html
```

Single package: `go test -race ./internal/rating/...`
Single test: `go test -race -run TestTierBreakpoints ./internal/rating`

Requires Go 1.23+, Docker (integration only), `buf`, and `sqlc` (versions pinned in `tools/`; use `make tools` to install).

## Coding Conventions

- Format with `gofumpt`; imports grouped as stdlib, third-party, then `github.com/routekit/routekit`.
- Keep packages small and cohesive; avoid `util`, `common`, or `helpers` packages.
- Accept interfaces, return concrete types. Define interfaces in the consuming package.
- Pass `context.Context` as the first parameter of any function that does I/O or may block.
- No package-level mutable state. No `init()` except for registering codecs/drivers.
- Use table-driven tests with `t.Run`; mark helpers with `t.Helper()`.
- Prefer golden-file tests for quote output; store under `testdata/golden/`.
- Use `testify/require` for assertions; avoid `assert` so tests stop at first failure.
- Exported identifiers need doc comments beginning with the identifier name.
- Logging uses `log/slog` through `internal/obs`; never `fmt.Println` or the stdlib `log` package.
- Metrics names follow `routekit_<subsystem>_<name>_<unit>`.
- Concurrency: every goroutine must have an owner and a cancellation path; use `errgroup`.

## Error Handling

- Wrap errors with context: `fmt.Errorf("resolve lane %s: %w", key, err)`.
- Define sentinel errors per package (`var ErrLaneNotFound = errors.New(...)`) and test with `errors.Is`/`errors.As`.
- Do not log and return the same error; log only at the boundary (handlers, CLI `main`).
- Map domain errors to API codes in `internal/api/errmap.go` only:
  - `ErrLaneNotFound` -> `NOT_FOUND`
  - `ErrInvalidRateSheet` -> `INVALID_ARGUMENT`
  - `ErrQuoteExpired` -> `FAILED_PRECONDITION`
- Never expose raw database or driver errors to clients.
- Panics are reserved for programmer errors at startup; recover only in the top-level server middleware.
- Ingest validation collects all row errors into a `ValidationReport` rather than failing on the first.

## Database Migrations

- Tool: `golang-migrate`, files in `db/migrations` named `NNNNNN_description.up.sql` / `.down.sql`.
- Create with `make migration name=add_lane_index`; this assigns the next sequence number.
- Every migration must have a working `down` file.
- Migrations are forward-compatible: the previous release must run against the new schema. Use expand/contract for breaking changes (add column -> backfill -> switch code -> drop in a later release).
- Never edit a migration that has been merged to `main`; add a new one.
- Large index builds use `CREATE INDEX CONCURRENTLY` in a migration with `-- migrate:no-transaction`.
- After changing schema or `db/queries`, run `make generate` and commit the sqlc output.
- Integration tests apply all migrations from scratch; CI also tests up/down/up.

## Release Process

1. Ensure `main` is green and `CHANGELOG.md` has an entry under `Unreleased`.
2. Run `make release-prep version=vX.Y.Z` to update the changelog and version constants.
3. Open a release PR; require one maintainer approval.
4. After merge, tag: `git tag -s vX.Y.Z && git push origin vX.Y.Z`.
5. The tag triggers the release workflow: goreleaser builds binaries, publishes container images to `ghcr.io/routekit/routekitd`, and creates the GitHub release.
6. Verify the published image with `make smoke-release version=vX.Y.Z`.

Versioning follows semver. Breaking changes to `pkg/` or to proto definitions require a major bump. Rate-table schema changes require a minor bump at minimum and a migration note in the changelog.

## CI

GitHub Actions, defined in `.github/workflows/`:

- `ci.yml` – on every PR: `make lint`, `make test`, `make generate` with a clean-diff check, `make proto-lint`.
- `integration.yml` – on PRs touching `db/`, `internal/store`, or `internal/api`, and nightly on `main`.
- `release.yml` – on `v*` tags.
- `codeql.yml` – weekly and on PRs to `main`.

PRs must pass all required checks and have at least one review. Generated-code drift fails CI; always run `make generate` before pushing.

## Things to Never Do

- Never use `float32`/`float64` for money, rates, or weights that feed pricing.
- Never edit generated files (`*.pb.go`, `internal/store/sqlcgen/*`) by hand.
- Never edit an already-merged migration.
- Never import `internal/` packages from `pkg/`.
- Never call the database from `rating`, `lane`, `geo`, or `surcharge`; go through interfaces.
- Never use `time.Now()` directly in core packages; inject a `Clock`.
- Never commit real carrier rate sheets or customer data; use anonymized fixtures in `testdata/`.
- Never commit secrets, tokens, or `.env` files.
- Never regenerate golden files without reviewing and explaining the diff in the PR.
- Never skip hooks or force-push to `main`.
- Never add a dependency without checking its license is Apache-2.0, MIT, or BSD compatible.

## Glossary

- **Lane** – an origin-destination pair (plus mode and equipment) for which a price is defined.
- **Lane key** – canonical string identifying a lane, e.g. `US-60601>US-30301|FTL|DRY53`.
- **Rate sheet** – a carrier-supplied document listing rates by lane.
- **Rate table** – the normalized, versioned set of rates the engine reads.
- **Breakpoint** – a weight or distance threshold where the rate tier changes.
- **Minimum charge** – the floor price for a shipment on a lane regardless of weight.
- **FTL / LTL** – full truckload / less-than-truckload.
- **Accessorial** – an add-on service charge (liftgate, residential delivery, detention).
- **Fuel surcharge (FSC)** – a variable charge indexed to a published diesel price.
- **Zone** – a grouping of postal areas treated as one origin or destination for rating.
- **Quote** – a priced, expiring offer for a shipment, tied to a rate-table version.
- **Golden file** – a checked-in expected output used for regression tests.
- **LOCODE** – UN/LOCODE, the standard code for trade and transport locations.
