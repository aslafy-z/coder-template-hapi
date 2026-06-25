---
display_name: Coder HAPI Workspace Template
description: Provision Kubernetes pods with persistent home volumes, HAPI, and optional AI agent harnesses for Coder workspaces
icon: ./icon.svg
verified: false
tags: [kubernetes, hapi, ai, agents]
---

# Coder HAPI Workspace Template

This template provisions a Kubernetes pod as a Coder workspace with a persistent home volume, a pre-built Ubuntu-based image, a per-workspace [HAPI](https://hapi.run) hub and runner, and optional AI agent harness tooling. HAPI listens on loopback inside the workspace and is exposed through an owner-only Coder app instead of a public Kubernetes Service.

## Prerequisites

You need an existing Kubernetes cluster and namespace for workspace resources. The namespace must exist before workspaces are created.

The Coder provisioner must be able to authenticate to the target cluster. If Coder runs inside the same cluster, use in-cluster ServiceAccount credentials. If Coder runs outside the cluster, enable kubeconfig authentication and provide a valid `~/.kube/config` on the Coder host.

The template expects a pre-built workspace image that contains `mise`, Python, Git, curl, archive tools, and the bundled startup scripts. This repository's image release automation publishes the default image to GitHub Container Registry.

## Architecture

Workspace creation creates a persistent volume claim for `/home/coder` and a Kubernetes Deployment for the running workspace pod. The persistent volume keeps the user's home directory, tool caches, HAPI state, and authentication files across workspace restarts. The Deployment is ephemeral and is recreated when the workspace starts.

The pod runs the Coder agent init script as the `coder` user and passes workspace settings through environment variables. CPU, memory, home disk size, workspace image, HAPI token, and harness selection are exposed as Coder parameters.

When the selected harness is not `none`, the startup script installs the requested tools through the user's global `mise` config, starts the Agent Auth Companion on `127.0.0.1:43117`, starts the HAPI hub on `127.0.0.1:3006`, and starts a HAPI runner rooted at `/home/coder/project`.

```tf
resource "kubernetes_deployment_v1" "workspace" {
  count = data.coder_workspace.me.start_count
}
```

## Workspace image

The **Workspace image** parameter defaults to the latest released GHCR image for this template and is used directly by the Kubernetes Deployment. Release automation updates this default before creating the release commit, tag, and image so new template imports point at the matching pre-built image tag.

## Tool installation with mise

The base image contains `mise` plus common archive and network utilities. HAPI and optional AI agent harnesses are installed at workspace startup by `scripts/start-hapi.sh` using the global mise config at `/home/coder/.config/mise/config.toml`.

The generated config is global to the workspace user and does not overwrite `/home/coder/project/.mise.toml`. Tool state and shims live in the user's home directory, so restarting a workspace can reuse already-installed tools.

## Agent harnesses

The **Agent harness** selector controls which tools are installed. The `none` mode skips HAPI and all harness installation. Other modes install GitHub CLI, HAPI, Node 22, and the selected AI harness. The `all` mode installs Claude Code, Antigravity CLI, Codex, and OpenCode together.

Changing the harness selection affects future startup runs, but it does not remove tools that were installed by an earlier selection because those tools live in the persistent home volume.

## HAPI token

The mutable **HAPI CLI API token** parameter defaults to `token`, which matches the HAPI UI login token you can enter from a browser or mobile app. Change this parameter at runtime if you want a stronger per-workspace token.

The template passes the value to HAPI as `CLI_API_TOKEN`, so it overrides HAPI's first-run generated token behavior and is used by the hub and CLI/runner processes. The startup log prints the configured token value for convenience.

> [!WARNING]
> The default token is intended for easy first-run access. Change it for shared or sensitive environments.

## Runtime layout

The workspace project directory is `/home/coder/project`. HAPI state and logs are stored under `/home/coder/.hapi`, and the global `mise` config is stored under `/home/coder/.config/mise/config.toml`.

The startup script checks for existing matching HAPI processes before starting new ones, so workspace restarts do not create duplicate hub or runner processes.

## Agent Auth Companion

Every mode except `none` exposes an **Agent Auth** Coder app. The companion is a small Python web app bundled into the workspace image and started before HAPI. It provides a mobile-friendly dashboard for GitHub CLI, Codex, Claude, OpenCode, HAPI, and repository status.

The companion runs only allowlisted login commands in PTY sessions, detects login URLs and device codes from CLI output, supports paste-code flows through stdin, and can replay OAuth callback URLs to a loopback listener inside the workspace. Callback replay is limited to active sessions, loopback hosts, the detected port and path, and URLs that include OAuth `code` and `state` parameters.

The companion does not implement OAuth clients, embed provider login pages, redeem authorization codes, or store provider tokens. Official CLIs continue to handle PKCE/state validation, token exchange, and their normal auth caches.

## Opening HAPI

After the workspace starts with any harness mode except `none`, open the **HAPI** app from the Coder dashboard. Open the **Agent Auth** app when you need to authenticate GitHub or an AI harness before launching sessions.

## Credentials

No provider credentials are committed by this template. Users should authenticate through each tool's normal login flow or provide per-user and per-workspace environment variables or mounted secrets. HAPI state and any local auth material should remain under the user's persistent home directory or in user-provided secret mounts.

## Known limitations

Live HAPI sessions do not survive pod deletion. This template runs a per-workspace HAPI hub only and does not provide a shared HAPI control plane. Tool installation depends on the configured `mise` aliases; if an alias breaks, the selected harness fails until the alias or config is fixed.

## Image release automation

GitHub Actions publishes the workspace image to GitHub Container Registry as `ghcr.io/<owner>/<repo>`. On each push to `main`, release automation bumps the latest semantic version tag, writes the `VERSION` file, updates the Terraform `workspace_image` default, commits those changes, creates and pushes an annotated release tag, creates the GitHub Release, and publishes Docker image tags for the semantic version, the `v`-prefixed tag, `latest`, and the short commit SHA.

To choose a non-patch bump, run the **Release image** workflow manually and select `major`, `minor`, or `patch`.
