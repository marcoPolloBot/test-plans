# AGENTS.md

## Cursor Cloud specific instructions

This repository (`libp2p/test-plans`) is a monorepo of interoperability and
performance test harnesses. It is not a single application; each top-level
folder is an independent "product". The dependency-refresh `update_script`
(npm installs + `uv sync`) runs automatically on startup. The notes below cover
non-obvious startup/run caveats that the update script intentionally does not handle.

### Docker must be started manually
Docker and the `uv` binary are pre-installed in the VM snapshot, but there is no
running init system, so **the Docker daemon is not auto-started**. Before running
anything that uses containers (transport-interop, hole-punch-interop), start it:

```bash
sudo dockerd            # run in the background (e.g. a tmux session)
sudo chmod 666 /var/run/docker.sock   # so docker works without sudo this session
```

The daemon is configured (`/etc/docker/daemon.json`) to use the `fuse-overlayfs`
storage driver with the containerd snapshotter disabled — required for Docker to
work inside this Firecracker VM. Do not change that.

### transport-interop (flagship, fully runnable here)
- Run from `transport-interop/`. Canonical command is `npm test` (see
  `package.json`); it generates docker-compose specs and runs them.
- Every entry in `versionsInput.json` points at a **prebuilt public GHCR image**
  (`ghcr.io/libp2p/test-plans/transport-interop/...`), so a single test pulls
  images instead of building locally. You do NOT need to run `make` to build
  implementation images for published versions.
- Filter to a single cheap test to validate end-to-end, e.g.:
  ```bash
  WORKER_COUNT=1 npm test -- --name-filter "go-v0.48 x go-v0.48 (tcp, noise, yamux)"
  ```
  A `redis:7-alpine` container is started automatically as the orchestrator.
- `npm run renderResults` turns `results.csv` into a markdown dashboard.
- There is no separate lint script; the `impl/<lang>/*` folders are independent
  projects built inside Docker, so root `tsc` over them reports missing-module
  errors — that is expected and not a real failure of the runner.

### hole-punch-interop (heavier; not run by default)
- `npm install` deps are refreshed automatically, but `versions.ts` reads local
  `impl/.../image.json` files, so you must `make` (compiles Rust relay/client +
  router images) before `npm test` works. Tests also need privileged Docker
  networking (routers, multiple networks). See `hole-punch-interop/README.md`.

### perf (needs external cloud infra)
- `perf/runner` npm deps are refreshed for dev readiness, but actually running a
  benchmark requires AWS credentials + Terraform (not installed) to provision
  EC2 instances. See `perf/README.md`.

### gossipsub-interop (Python via uv + Shadow simulator)
- Managed with `uv` (`uv sync` runs automatically). `uv` lives in `~/.local/bin`
  (already on PATH via `~/.bashrc`).
- Lint: `uv run ruff check .`
- The actual interop tests run real go/rust/nim/jvm gossipsub binaries inside the
  [Shadow](https://shadow.github.io/) network simulator. The required toolchains
  are pre-installed in the VM snapshot (not by the update script):
  - **Shadow 3.3.0** → `~/.local/bin/shadow`
  - **Go** → `/usr/local/go/bin` (go1.26.4; the repo `go.mod` only needs
    >=1.24.1). This is the durable default `go` via `~/.bashrc`, overriding the
    apt-installed Go 1.22 at `/usr/bin/go`. (The apt 1.22 build of go-libp2p
    **fails**, so the newer Go must stay first on PATH.)
  - **Nim** → `~/.nimble/bin`; **Rust** (rustup `stable`, currently 1.96, needed
    for `edition2024`); **JDK 21** (system)
- **Gotcha:** `run.py` (real, non-`--dry-run`) calls `make binaries` on every
  invocation, so *all four* toolchains must be on PATH for any test run. `go`,
  `nim`, and `cargo` are already on PATH via `~/.bashrc`; only Shadow/uv
  (`~/.local/bin`) needs the env file. A login shell already has everything; a
  minimal env can use:
  ```bash
  export PATH=/usr/local/go/bin:$HOME/.local/bin:$HOME/.nimble/bin:/usr/local/cargo/bin:$PATH
  ```
  `make binaries` is incremental: the nim binary (a file target with no
  prerequisites) is only built once, but go/rust/jvm are relinked each run.
- Run the full suite (~10 min, iterates partial-message + subnet-blob scenarios
  across go/rust/nim/jvm): `make test`. Single-stack subsets: `make test-go`,
  `make test-rust-only`. CI (`.github/workflows/gossipsub-interop-pr.yml`) runs
  `make test` with `continue-on-error`.
- Config-only dry run (no Shadow/binaries needed):
  ```bash
  uv run run.py --dry-run true --node_count 5 --composition go --scenario subnet-blob-msg
  ```
- Generated outputs (`shadow-outputs/`, `*/gossipsub-bin`, `nim-libp2p-src/`,
  `latest`, `params.json`, `plots/`) are all gitignored.
