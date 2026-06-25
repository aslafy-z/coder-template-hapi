# Coder HAPI Workspace Template

This template runs a per-workspace [HAPI](https://hapi.run) hub and runner inside a Kubernetes-based Coder workspace using a pre-built workspace image. HAPI listens only on `127.0.0.1:3006` and is exposed through an owner-only Coder app, not a public Kubernetes Service. It also starts an **Agent Auth Companion** on `127.0.0.1:43117` to help authenticate Codex, Claude Code, OpenCode, GitHub, and HAPI-oriented workflows from a browser or mobile device without storing provider tokens itself.

## Prerequisites

- An existing Kubernetes cluster and namespace for workspace resources.
- Kubernetes authentication from the Coder provisioner, either via in-cluster ServiceAccount credentials or by setting `use_kubeconfig` and providing `~/.kube/config` on the Coder host.
- A pre-built workspace image. The included release workflow publishes this image to GHCR.

## Workspace image

Workspace creation includes a **Workspace image** parameter named `workspace_image`. It defaults to the latest released GHCR image for this template and is used directly by the Kubernetes Deployment. Release automation updates this default before creating the release commit, tag, and image so new template imports point at the matching pre-built image tag.

## Tool installation with mise

The base image contains `mise` plus common archive and network utilities. HAPI and optional AI agent harnesses are installed at workspace startup by `scripts/start-hapi.sh` using the global mise config at:

```text
/home/coder/.config/mise/config.toml
```

The generated config is global to the workspace user and does not overwrite `/home/coder/project/.mise.toml`. Tool state and shims live in the user's home directory, so restarting a workspace can reuse already-installed tools.

## Agent harness parameter

Workspace creation shows an **Agent harness** selector named `agent_harness`:

| Value | Behavior |
| --- | --- |
| `none` | Do not install HAPI and do not install any agent harness. |
| `hapi-only` | Install GitHub CLI (`gh`), then install and start HAPI. |
| `code` | Install GitHub CLI (`gh`), HAPI, and Claude Code (`claude`), then start HAPI. |
| `agy` | Install GitHub CLI (`gh`), HAPI, and Antigravity CLI (`agy`), then start HAPI. |
| `codex` | Install GitHub CLI (`gh`), HAPI, and Codex (`codex`), then start HAPI. |
| `opencode` | Install GitHub CLI (`gh`), HAPI, and OpenCode (`opencode`), then start HAPI. |
| `all` | Install GitHub CLI (`gh`), HAPI, Claude Code, Antigravity CLI, Codex, and OpenCode, then start HAPI. |

Every mode except `none` includes Node 22, GitHub CLI (`gh`), and HAPI (`npm:@twsxtd/hapi`) in the managed global mise config.

## HAPI token parameter

Workspace creation includes a mutable **HAPI CLI API token** parameter named `hapi_cli_api_token`. It defaults to `token`, which matches the HAPI UI login token you can enter from a browser or mobile app. Change this parameter at runtime if you want a stronger per-workspace token.

The template passes the value to HAPI as `CLI_API_TOKEN`, so it overrides HAPI's first-run generated token behavior and is used by the hub and CLI/runner processes. The startup log prints the configured token line as:

```text
HAPI CLI_API_TOKEN: token
```

## Runtime layout

- Project root: `/home/coder/project`
- HAPI state: `/home/coder/.hapi`
- HAPI hub log: `/home/coder/.hapi/hub.log`
- HAPI runner log: `/home/coder/.hapi/runner.log`
- Global mise config: `/home/coder/.config/mise/config.toml`
- Agent Auth Companion log: `/home/coder/.hapi/authd.log`

The startup script starts:

```text
CLI_API_TOKEN=token hapi hub --no-relay
CLI_API_TOKEN=token hapi runner start --workspace-root /home/coder/project
```

It checks for existing matching processes before starting HAPI, so workspace restarts do not create duplicate hub or runner processes.


## Agent Auth Companion

Every mode except `none` exposes an **Agent Auth** Coder app at `http://localhost:43117`. The companion is a small Python web app bundled into the workspace image and started by `scripts/start-hapi.sh` before HAPI. It provides:

- A mobile-friendly dashboard for GitHub CLI (`gh`), Codex, Claude, OpenCode, HAPI, and repository status.
- An allowlisted PTY runner for login commands only, including `gh auth login --web`, `codex login --device-auth`, `codex login`, `claude`, and `opencode`.
- Detection of login URLs, device codes, and loopback callback listeners from CLI output.
- A stdin bridge for paste-code flows, so a code copied from a provider page can be sent back to the real CLI.
- Secure localhost callback replay for OAuth flows that redirect to `localhost` or `127.0.0.1` inside the workspace. The companion only replays URLs for an active session, only to loopback hosts, only to the port and path detected from the CLI output, requires `code` and `state` parameters, redacts sensitive query values from logs, and does not store the full callback URL.

The companion intentionally does not implement OAuth clients, embed provider login pages, redeem authorization codes, or store provider tokens. The official CLIs continue to handle PKCE/state validation, token exchange, and their normal auth caches such as `~/.codex/auth.json`, `~/.local/share/opencode/auth.json`, Claude configuration, GitHub CLI state, or cloud-provider credentials.

Typical mobile flows:

1. Prefer device-code login where available, such as **GitHub device login** or **Codex device-code**.
2. Use browser login with callback replay when a CLI prints a localhost callback URL: open the provider URL, copy the final failed `http://127.0.0.1:<port>/...?...` URL from the phone, paste it into the session, and press **Replay callback**.
3. Use the stdin bridge for CLIs that ask for a pasted code: paste the code in the session input and press **Send stdin**.

## Opening HAPI

After the workspace starts with any harness mode except `none`, open the **HAPI** app from the Coder dashboard. Open the **Agent Auth** app when you need to authenticate GitHub or an AI harness before launching sessions. The app points to `http://localhost:3006`, uses subdomains, and is shared with the workspace owner only.

## Credentials

No provider credentials are committed by this template. The HAPI shared secret defaults to `token` for convenience and can be changed with the mutable `hapi_cli_api_token` parameter. Users should authenticate through each tool's normal login flow or provide per-user/per-workspace environment variables or mounted secrets. HAPI state and any local auth material should remain under `/home/coder/.hapi` or in user-provided secret mounts.

## Known limitations

- Live HAPI sessions do not survive pod deletion.
- This iteration runs a per-workspace HAPI hub only.
- There is no shared HAPI control plane yet.
- Changing `agent_harness` does not necessarily uninstall tools from previous selections.
- Some harnesses may require user login after install; use the Agent Auth app for device-code, paste-code, or localhost callback replay flows.
- Tool installation depends strictly on the configured mise aliases; if a mise alias breaks, the selected harness fails until the alias or config is fixed.
- The generated mise config is installed as the workspace user's global mise config, separate from the project `.mise.toml`.

## Image release automation

GitHub Actions publishes the workspace image to GitHub Container Registry as `ghcr.io/<owner>/<repo>`. The release workflow does not rely on conventional commit messages. Instead, every push to `main` bumps the latest `vMAJOR.MINOR.PATCH` tag by one patch version, writes the resulting `VERSION` file, updates the Terraform `workspace_image` default to the next `ghcr.io/<owner>/<repo>:vMAJOR.MINOR.PATCH` image, commits those changes, creates and pushes an annotated release tag, creates the GitHub Release, and publishes Docker image tags for the semantic version, the `v`-prefixed tag, `latest`, and the short commit SHA.

To choose a non-patch bump, run the **Release image** workflow manually and select `major`, `minor`, or `patch`.
