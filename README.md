# CKAD Flightdeck

Hands-on Kubernetes practice in your browser, backed by a real two-node K3s cluster.

- **36 exercises:** Core 20 and Focused 16 question sets.
- **Browser terminal:** Bash, kubectl, Helm, Kustomize, and an isolated Docker image builder.
- **Practice mode:** hints, walkthroughs, individual checks, notes, and progress tracking.
- **Timed mocks:** two-hour sessions with partial-credit grading and results by topic.

Runs locally with Docker. No API keys or cloud account required. This is an unofficial study tool, not an exam simulator endorsed by CNCF or the Linux Foundation.

## Quick start

Install and start **Docker Desktop** (Linux containers; WSL2 on Windows), or **Docker Engine with Compose v2** on Linux. A suggested starting allocation is 4 CPU cores, 8 GB RAM, and 10–15 GB free disk. First launch requires internet access to download images and tools.

Clone the repository, or download and extract its ZIP:

```bash
git clone https://github.com/olsonb97/ckad-flightdeck.git
cd ckad-flightdeck
```

**macOS / Linux**

```bash
bash start.sh
```

**Windows:** double-click `start.cmd`, or run `.\start.ps1` in PowerShell.

Wait for **Lab ready**, then open **http://127.0.0.1:8080**. Choose a question, solve it in the terminal, and select **Check work**. The **Help** tab has hints and worked solutions.

If port 8080 is taken, copy `.env.example` to `.env`, set `FLIGHTDECK_PORT=8081`, and restart the launcher.

## Question sets

| Set | Exercises | Focus |
|---|---:|---|
| Core | 20 | Application design, deployment, configuration, security, observability, and networking |
| Focused | 16 | Additional scenarios covering workloads, storage, RBAC, services, and troubleshooting |

Both sets support practice and timed mocks. Starting a mock resets that set’s lab resources and task files; saved notes and progress remain. Hints and practice checks are unavailable during a mock.

See the [question catalog](docs/QUESTION_CATALOG.md) and [sources and attribution](docs/SOURCES.md) for details. The lab targets Kubernetes 1.35; practice scores do not predict exam results.

## Manage the lab

Stop while preserving your work:

```bash
docker compose down
```

Resume with your platform’s launcher. To update a cloned installation:

```bash
git pull
```

Then rerun the launcher to rebuild. Saved data lives in Docker volumes. **`docker compose down --volumes` permanently deletes the lab and saved progress.**

The stack uses privileged containers and is intended for one trusted local user. Keep the web terminal bound to localhost; do not expose it publicly or connect it to a production cluster.

## Troubleshooting

- **Docker or startup failure:** confirm Docker is running Linux containers, then inspect `docker compose logs app cluster worker`.
- **Disconnected terminal after a restart:** reload the page.
- **Work not passing yet:** check Pod readiness and rollout status, then grade again.
- **Need more detail:** run `bash scripts/diagnostics.sh` for status and logs.

## Development

The Python backend and plain JavaScript frontend live in `app/`. Run the non-cluster tests in the running app container:

```bash
docker compose exec app python -m unittest discover -s /app/tests -v
```

## License

[MIT](LICENSE). Third-party notices are in [app/static/vendor](app/static/vendor/).
