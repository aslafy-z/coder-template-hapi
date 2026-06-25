# Coder HAPI Workspace Template

This template runs a per-workspace [HAPI](https://hapi.run) hub and runner inside a Kubernetes-based Coder workspace using a pre-built workspace image. HAPI listens only on `127.0.0.1:3006` and is exposed through an owner-only Coder app, not a public Kubernetes Service.

## Prerequisites

- An existing Kubernetes cluster and namespace for workspace resources.
- Kubernetes authentication from the Coder provisioner, either via in-cluster ServiceAccount credentials or by setting `use_kubeconfig` and providing `~/.kube/config` on the Coder host.
- A pre-built workspace image. The included release workflow publishes this image to GHCR.

## Workspace image

Workspace creation includes a **Workspace image** parameter named `workspace_image`. It defaults to the latest released GHCR image for this template and is used directly by the Kubernetes Deployment. Release automation updates this default before creating the release commit, tag, and image so new template imports point at the matching pre-built image tag.

## Tool installation with mise

The base image contains `mise` plus common archive and network utilities. HAPI and optional AI agent harnesses are installed at workspace startup by `scripts/start-hapi.sh` using a generated mise config at:

```text
/home/coder/.config/coder-hapi/mise.toml
```

The generated config is separate from the user's project and does not overwrite `/home/coder/project/.mise.toml`. Tool state and shims live in the user's home directory, so restarting a workspace can reuse already-installed tools.

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

- Project root: `/home/coder/project`
- HAPI state: `/home/coder/.hapi`
- HAPI hub log: `/home/coder/.hapi/hub.log`
- HAPI runner log: `/home/coder/.hapi/runner.log`
- Generated mise config: `/home/coder/.config/coder-hapi/mise.toml`

The startup script starts:

```text
hapi hub --no-relay
hapi runner start --workspace-root /home/coder/project
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

## Image release automation

GitHub Actions publishes the workspace image to GitHub Container Registry as `ghcr.io/<owner>/<repo>`. The release workflow does not rely on conventional commit messages. Instead, every push to `main` bumps the latest `vMAJOR.MINOR.PATCH` tag by one patch version, writes the resulting `VERSION` file, updates the Terraform `workspace_image` default to the next `ghcr.io/<owner>/<repo>:vMAJOR.MINOR.PATCH` image, commits those changes, creates and pushes an annotated release tag, creates the GitHub Release, and publishes Docker image tags for the semantic version, the `v`-prefixed tag, `latest`, and the short commit SHA.

To choose a non-patch bump, run the **Release image** workflow manually and select `major`, `minor`, or `patch`.
