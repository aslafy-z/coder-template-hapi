# Coder HAPI Workspace Template

This template runs a per-workspace [HAPI](https://hapi.run) hub and runner inside a Kubernetes-based Coder workspace. HAPI listens only on `127.0.0.1:3006` and is exposed through an owner-only Coder app, not a public Kubernetes Service.

## Dev container workflow

This template follows Coder's Envbuilder dev container approach instead of publishing and pinning a bespoke workspace image. The Terraform template starts the Envbuilder image, points it at a Git repository, and Envbuilder builds the workspace from that repository's `.devcontainer/devcontainer.json`.

Workspace creation shows these dev-container parameters:

| Parameter | Behavior |
| --- | --- |
| `repo` | Git repository containing `.devcontainer/devcontainer.json`. |
| `devcontainer_builder` | Envbuilder image used to build and run the dev container. Pin this in production. |
| `fallback_image` | Image Envbuilder uses if the dev container build fails. |

Set `cache_repo` on the Coder template to enable Envbuilder image caching. When caching is enabled, Envbuilder can push and reuse previously built dev container images instead of rebuilding on every start.

## Dev container contents

The included `.devcontainer/devcontainer.json` uses `codercom/enterprise-base:ubuntu`, adds the Dev Containers `common-utils` feature, and runs `.devcontainer/install-mise.sh` during creation. That script installs `mise` into the coder user's local bin directory so startup can install HAPI and optional agent harnesses with the same flow regardless of where the dev container is built.

## Tool installation with mise

HAPI and optional AI agent harnesses are installed at workspace startup by `scripts/start-hapi.sh` using a generated mise config at:

```text
/home/coder/.config/coder-hapi/mise.toml
```

The generated config is separate from the user's project and does not overwrite a repository `.mise.toml`. Tool state and shims live in the user's home directory, so restarting a workspace can reuse already-installed tools.

## Agent harness parameter

Workspace creation shows an **Agent harness** selector named `agent_harness`:

| Value | Behavior |
| --- | --- |
| `none` | Do not install HAPI and do not install any agent harness. |
| `hapi-only` | Install and start HAPI only. |
| `code` | Install and start HAPI, then install Claude Code (`claude`). |
| `agy` | Install and start HAPI, then install Antigravity CLI (`agy`). |
| `codex` | Install and start HAPI, then install Codex (`codex`). |
| `opencode` | Install and start HAPI, then install OpenCode (`opencode`). |
| `all` | Install and start HAPI plus Claude Code, Antigravity CLI, Codex, and OpenCode. |

Every mode except `none` includes Node 22 and HAPI (`npm:@twsxtd/hapi`) in the managed mise config.

## Runtime layout

- Workspace root: `/workspaces`
- HAPI state: `/home/coder/.hapi`
- HAPI hub log: `/home/coder/.hapi/hub.log`
- HAPI runner log: `/home/coder/.hapi/runner.log`
- Generated mise config: `/home/coder/.config/coder-hapi/mise.toml`

The startup script starts:

```text
hapi hub --no-relay
hapi runner start --workspace-root /workspaces
```

It checks for existing matching processes before starting HAPI, so workspace restarts do not create duplicate hub or runner processes.

## Opening HAPI

After the workspace starts with any harness mode except `none`, open the **HAPI** app from the Coder dashboard. The app points to `http://localhost:3006`, uses subdomains, and is shared with the workspace owner only.

## Credentials

No API keys or provider credentials are committed by this template. Users should authenticate through each tool's normal login flow or provide per-user/per-workspace environment variables or mounted secrets. HAPI state and any local auth material should remain under `/home/coder/.hapi` or in user-provided secret mounts.

## Known limitations

- Live HAPI sessions do not survive pod deletion.
- This iteration runs a per-workspace HAPI hub only.
- There is no shared HAPI control plane yet.
- Changing `agent_harness` does not necessarily uninstall tools from previous selections.
- Some harnesses may require user login after install.
- Tool installation depends strictly on the configured mise aliases; if a mise alias breaks, the selected harness fails until the alias or config is fixed.
- The generated mise config is separate from the user's project `.mise.toml`.
