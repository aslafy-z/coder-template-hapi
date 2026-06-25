terraform {
  required_providers {
    coder = {
      source = "coder/coder"
    }
    kubernetes = {
      source = "hashicorp/kubernetes"
    }
    envbuilder = {
      source = "coder/envbuilder"
    }
  }
}

provider "coder" {}
provider "kubernetes" {}
provider "envbuilder" {}

data "coder_provisioner" "me" {}
data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}

variable "namespace" {
  type        = string
  description = "Kubernetes namespace for workspace resources."
  default     = "coder"
}

variable "cache_repo" {
  type        = string
  description = "Optional container registry repository for Envbuilder cache images. Leave empty to build directly with Envbuilder."
  default     = ""
}

variable "insecure_cache_repo" {
  type        = bool
  description = "Allow HTTP when using cache_repo."
  default     = false
}

variable "cache_repo_secret_name" {
  type        = string
  description = "Optional Kubernetes dockerconfigjson Secret name with credentials for cache_repo."
  default     = ""
  sensitive   = true
}

data "coder_parameter" "repo" {
  name         = "repo"
  display_name = "Repository URL"
  description  = "Git repository containing .devcontainer/devcontainer.json."
  type         = "string"
  mutable      = true
  default      = "https://github.com/coder/coder-template-hapi"
  order        = 1
}

data "coder_parameter" "devcontainer_builder" {
  name         = "devcontainer_builder"
  display_name = "Devcontainer builder"
  description  = "Envbuilder image used to build and run the dev container. Pin this in production instead of using latest."
  type         = "string"
  mutable      = true
  default      = "ghcr.io/coder/envbuilder:latest"
  order        = 2
}

data "coder_parameter" "fallback_image" {
  name         = "fallback_image"
  display_name = "Fallback image"
  description  = "Image Envbuilder runs if the dev container build fails."
  type         = "string"
  mutable      = true
  default      = "codercom/enterprise-base:ubuntu"
  order        = 3
}

data "coder_parameter" "agent_harness" {
  name         = "agent_harness"
  display_name = "Agent harness"
  description  = "Choose which AI agent harness to install when the workspace starts."
  default      = "hapi-only"
  order        = 4

  option {
    name  = "None"
    value = "none"
  }

  option {
    name  = "HAPI only"
    value = "hapi-only"
  }

  option {
    name  = "Claude Code"
    value = "code"
  }

  option {
    name  = "Antigravity CLI"
    value = "agy"
  }

  option {
    name  = "Codex"
    value = "codex"
  }

  option {
    name  = "OpenCode"
    value = "opencode"
  }

  option {
    name  = "All"
    value = "all"
  }
}

data "kubernetes_secret_v1" "cache_repo_dockerconfig_secret" {
  count = var.cache_repo_secret_name == "" ? 0 : 1

  metadata {
    name      = var.cache_repo_secret_name
    namespace = var.namespace
  }
}

locals {
  deployment_name            = "coder-${data.coder_workspace_owner.me.name}-${data.coder_workspace.me.name}"
  devcontainer_builder_image = data.coder_parameter.devcontainer_builder.value
  repo_url                   = data.coder_parameter.repo.value
  workspace_dir              = "/workspaces"

  envbuilder_env = {
    CODER_AGENT_TOKEN               = coder_agent.main.token
    CODER_AGENT_URL                 = replace(data.coder_workspace.me.access_url, "/localhost|127\\.0\\.0\\.1/", "host.docker.internal")
    ENVBUILDER_GIT_URL              = var.cache_repo == "" ? local.repo_url : ""
    ENVBUILDER_INIT_SCRIPT          = replace(coder_agent.main.init_script, "/localhost|127\\.0\\.0\\.1/", "host.docker.internal")
    ENVBUILDER_FALLBACK_IMAGE       = data.coder_parameter.fallback_image.value
    ENVBUILDER_DOCKER_CONFIG_BASE64 = base64encode(try(data.kubernetes_secret_v1.cache_repo_dockerconfig_secret[0].data[".dockerconfigjson"], ""))
    ENVBUILDER_PUSH_IMAGE           = var.cache_repo == "" ? "" : "true"
    AGENT_HARNESS                   = data.coder_parameter.agent_harness.value
    PROJECT_DIR                     = local.workspace_dir
  }
}

resource "envbuilder_cached_image" "cached" {
  count         = var.cache_repo == "" ? 0 : data.coder_workspace.me.start_count
  builder_image = local.devcontainer_builder_image
  git_url       = local.repo_url
  cache_repo    = var.cache_repo
  extra_env     = local.envbuilder_env
  insecure      = var.insecure_cache_repo
}

resource "coder_agent" "main" {
  os   = "linux"
  arch = data.coder_provisioner.me.arch
  dir  = local.workspace_dir
}

resource "coder_script" "hapi" {
  agent_id           = coder_agent.main.id
  display_name       = "Start HAPI"
  icon               = "/icon/terminal.svg"
  script             = file("${path.module}/scripts/start-hapi.sh")
  run_on_start       = true
  start_blocks_login = false
}

resource "coder_app" "hapi" {
  count        = data.coder_parameter.agent_harness.value == "none" ? 0 : 1
  agent_id     = coder_agent.main.id
  slug         = "hapi"
  display_name = "HAPI"
  icon         = "/icon/terminal.svg"

  url       = "http://localhost:3006"
  subdomain = true
  share     = "owner"

  healthcheck {
    url       = "http://localhost:3006"
    interval  = 5
    threshold = 12
  }
}

resource "kubernetes_persistent_volume_claim_v1" "workspaces" {
  metadata {
    name      = "coder-${data.coder_workspace_owner.me.name}-${data.coder_workspace.me.name}-workspaces"
    namespace = var.namespace
    labels = {
      "app.kubernetes.io/name"     = "coder-workspace"
      "app.kubernetes.io/instance" = data.coder_workspace.me.id
    }
  }

  wait_until_bound = false

  spec {
    access_modes = ["ReadWriteOnce"]
    resources {
      requests = {
        storage = "10Gi"
      }
    }
  }
}

resource "kubernetes_deployment_v1" "workspace" {
  count            = data.coder_workspace.me.start_count
  wait_for_rollout = false

  metadata {
    name      = local.deployment_name
    namespace = var.namespace
    labels = {
      "app.kubernetes.io/name"     = "coder-workspace"
      "app.kubernetes.io/instance" = data.coder_workspace.me.id
    }
  }

  spec {
    replicas = 1
    selector {
      match_labels = {
        "app.kubernetes.io/name"     = "coder-workspace"
        "app.kubernetes.io/instance" = data.coder_workspace.me.id
      }
    }

    strategy {
      type = "Recreate"
    }

    template {
      metadata {
        labels = {
          "app.kubernetes.io/name"     = "coder-workspace"
          "app.kubernetes.io/instance" = data.coder_workspace.me.id
        }
      }

      spec {
        container {
          name              = "dev"
          image             = var.cache_repo == "" ? local.devcontainer_builder_image : envbuilder_cached_image.cached[0].image
          image_pull_policy = "Always"

          dynamic "env" {
            for_each = nonsensitive(var.cache_repo == "" ? local.envbuilder_env : envbuilder_cached_image.cached[0].env_map)
            content {
              name  = env.key
              value = env.value
            }
          }

          volume_mount {
            mount_path = local.workspace_dir
            name       = "workspaces"
            read_only  = false
          }
        }

        volume {
          name = "workspaces"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim_v1.workspaces.metadata[0].name
            read_only  = false
          }
        }
      }
    }
  }
}

resource "coder_metadata" "devcontainer" {
  count       = data.coder_workspace.me.start_count
  resource_id = coder_agent.main.id

  item {
    key   = "repository"
    value = local.repo_url
  }

  item {
    key   = "builder image"
    value = local.devcontainer_builder_image
  }

  item {
    key   = "cache repo"
    value = var.cache_repo == "" ? "not enabled" : var.cache_repo
  }
}
