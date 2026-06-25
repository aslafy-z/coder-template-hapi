terraform {
  required_providers {
    coder = {
      source = "coder/coder"
    }
    kubernetes = {
      source = "hashicorp/kubernetes"
    }
  }
}

provider "coder" {}
provider "kubernetes" {}

data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}

variable "namespace" {
  type        = string
  description = "Kubernetes namespace for workspace resources."
  default     = "coder"
}

data "coder_parameter" "agent_harness" {
  name         = "agent_harness"
  display_name = "Agent harness"
  description  = "Choose which AI agent harness to install when the workspace starts."
  default      = "hapi-only"

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

resource "coder_agent" "main" {
  os   = "linux"
  arch = "amd64"
  dir  = "/home/coder/project"
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

resource "kubernetes_persistent_volume_claim_v1" "home" {
  metadata {
    name      = "coder-${data.coder_workspace_owner.me.name}-${data.coder_workspace.me.name}-home"
    namespace = var.namespace
    labels = {
      "app.kubernetes.io/name"     = "coder-workspace"
      "app.kubernetes.io/instance" = data.coder_workspace.me.id
    }
  }

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
  count = data.coder_workspace.me.start_count

  metadata {
    name      = "coder-${data.coder_workspace_owner.me.name}-${data.coder_workspace.me.name}"
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

    template {
      metadata {
        labels = {
          "app.kubernetes.io/name"     = "coder-workspace"
          "app.kubernetes.io/instance" = data.coder_workspace.me.id
        }
      }

      spec {
        security_context {
          run_as_user     = 1000
          run_as_group    = 1000
          fs_group        = 1000
          run_as_non_root = true
        }

        container {
          name              = "dev"
          image             = "coder-template-hapi:latest"
          image_pull_policy = "IfNotPresent"
          command           = ["sh", "-c", coder_agent.main.init_script]

          env {
            name  = "CODER_AGENT_TOKEN"
            value = coder_agent.main.token
          }

          env {
            name  = "AGENT_HARNESS"
            value = data.coder_parameter.agent_harness.value
          }

          env {
            name  = "PATH"
            value = "/home/coder/.local/bin:/home/coder/.local/share/mise/shims:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
          }

          volume_mount {
            mount_path = "/home/coder"
            name       = "home"
          }
        }

        volume {
          name = "home"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim_v1.home.metadata[0].name
          }
        }
      }
    }
  }
}
