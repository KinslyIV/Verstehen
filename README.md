# Verstehen

Verstehen is a learning app: an AI tutor that probes what you know, plans a lesson, teaches with
questions, and builds a knowledge graph of what you've learned. It runs locally as a desktop app.

It is a port of [LearnHarness](https://github.com/amosblomqvist/learnharness) to Python, Pydantic
AI, PySide6, and Svelte. The goal is to keep the same learning flow and knowledge graph, rebuilt with
code that is easy to read, and to understand how LearnHarness works along the way: how the graph is
managed, how background work reports back to the tutor, how questions pause and resume a turn, and
how the side chat works.

- **Where the project is:** [status](docs/status.md) and [roadmap](docs/roadmap.md).
- **How it is built:** [architecture](docs/architecture.md).
- **How LearnHarness works:** [overview](docs/learnharness/overview.md) and the other docs in
  [`docs/learnharness/`](docs/learnharness/).
- **For coding agents:** [AGENTS.md](AGENTS.md), which also gives the reading order.

## Develop

Prerequisites: uv (>= 0.13.9), Node.js 24 with npm, make, and Docker (for packaging). Python 3.14 is pinned in
`backend/.python-version`.

```sh
make setup     # locked uv sync, npm ci, Playwright's Chromium
make check     # everything, before every commit
make verify    # the app with a scripted fake model in headless Chromium
make dev       # sidecar + Vite with a fresh temporary data dir; open http://localhost:5173
```

`VERSTEHEN_PORT` overrides the development sidecar port (default 8765). The verify skill
(`.claude/skills/verify/SKILL.md`) explains the flows, reruns, and evidence.

## Build and install

`make app` builds `dist/verstehen-<version>-1-x86_64.pkg.tar.zst` in a prepared Arch image
(`verstehen-build`, created on the first run; `make app-image` refreshes it). Copy the package to
the Arch laptop and install it with `sudo pacman -U <file>`, then open **Verstehen** from the
launcher. `verstehen --self-check` confirms the frozen dependencies.

The app uses the installed `claude` for Claude Code and signs in to ChatGPT in the browser.
Demos are checked in the app's own Chromium; no browser needs to be installed.

## Releases

Bump the version in `backend/pyproject.toml`, merge the PR with green CI, then on the merged commit run
`git tag vX.Y.Z && git push origin vX.Y.Z`. The release workflow checks the tag against the version, builds the
package, and publishes it to a GitHub Release. On the laptop:

```sh
gh release download vX.Y.Z -R KinslyIV/Verstehen -p '*.pkg.tar.zst'
sudo pacman -U ./verstehen-X.Y.Z-1-x86_64.pkg.tar.zst
```

## License

AGPL-3.0-only, matching LearnHarness. See [LICENSE](LICENSE).
