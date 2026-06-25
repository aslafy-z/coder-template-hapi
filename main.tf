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

variable "use_kubeconfig" {
  type        = bool
  description = <<-EOF
  Use host kubeconfig? (true/false)

  Set this to false if the Coder host is itself running as a Pod on the same
  Kubernetes cluster as you are deploying workspaces to.

  Set this to true if the Coder host is running outside the Kubernetes cluster
  for workspaces. A valid "~/.kube/config" must be present on the Coder host.
  EOF
  default     = false
}

variable "namespace" {
  type        = string
  description = "The Kubernetes namespace to create workspaces in (must exist prior to creating workspaces). If the Coder host is itself running as a Pod on the same Kubernetes cluster as you are deploying workspaces to, set this to the same namespace."
}

provider "kubernetes" {
  # Authenticate via ~/.kube/config or a Coder-specific ServiceAccount, depending on admin preferences.
  config_path = var.use_kubeconfig == true ? "~/.kube/config" : null
}

data "coder_provisioner" "me" {}
data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}

data "coder_parameter" "workspace_image" {
  name         = "workspace_image"
  display_name = "Workspace image"
  description  = "Pre-built workspace image to run for this template. Release automation updates this default before tagging."
  type         = "string"
  mutable      = true
  default      = "ghcr.io/aslafy-z/coder-template-hapi:v0.0.8"
  order        = 1
}

data "coder_parameter" "cpu" {
  name         = "cpu"
  display_name = "CPU"
  description  = "The number of CPU cores"
  default      = "2"
  icon         = "/icon/memory.svg"
  mutable      = true
  order        = 2
  option {
    name  = "2 Cores"
    value = "2"
  }
  option {
    name  = "4 Cores"
    value = "4"
  }
  option {
    name  = "6 Cores"
    value = "6"
  }
  option {
    name  = "8 Cores"
    value = "8"
  }
}

data "coder_parameter" "memory" {
  name         = "memory"
  display_name = "Memory"
  description  = "The amount of memory in GB"
  default      = "2"
  icon         = "/icon/memory.svg"
  mutable      = true
  order        = 3
  option {
    name  = "2 GB"
    value = "2"
  }
  option {
    name  = "4 GB"
    value = "4"
  }
  option {
    name  = "6 GB"
    value = "6"
  }
  option {
    name  = "8 GB"
    value = "8"
  }
}

data "coder_parameter" "home_disk_size" {
  name         = "home_disk_size"
  display_name = "Home disk size"
  description  = "The size of the home disk in GB"
  default      = "10"
  type         = "number"
  icon         = "/emojis/1f4be.png"
  mutable      = false
  order        = 4
  validation {
    min = 1
    max = 99999
  }
}

data "coder_parameter" "agent_harness" {
  name         = "agent_harness"
  display_name = "Agent harness"
  description  = "Choose which AI agent harness to install when the workspace starts."
  default      = "hapi-only"
  order        = 5

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

data "coder_parameter" "hapi_cli_api_token" {
  name         = "hapi_cli_api_token"
  display_name = "HAPI CLI API token"
  description  = "Shared secret for HAPI UI and CLI authentication. Defaults to token for easy mobile login; change it at runtime for a stronger per-workspace token."
  type         = "string"
  default      = "token"
  mutable      = true
  order        = 6
}

resource "coder_agent" "main" {
  os   = "linux"
  arch = data.coder_provisioner.me.arch
  dir  = "/home/coder/project"

  metadata {
    display_name = "CPU Usage"
    key          = "0_cpu_usage"
    script       = "coder stat cpu"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "RAM Usage"
    key          = "1_ram_usage"
    script       = "coder stat mem"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Home Disk"
    key          = "3_home_disk"
    script       = "coder stat disk --path $${HOME}"
    interval     = 60
    timeout      = 1
  }
}

resource "coder_script" "hapi" {
  agent_id           = coder_agent.main.id
  display_name       = "Start HAPI"
  icon               = "/icon/terminal.svg"
  script             = file("${path.module}/scripts/start-hapi.sh")
  run_on_start       = true
  start_blocks_login = false
}

resource "coder_app" "auth_companion" {
  count        = data.coder_parameter.agent_harness.value == "none" ? 0 : 1
  agent_id     = coder_agent.main.id
  slug         = "auth"
  display_name = "Agent Auth"
  icon         = "/emojis/1f511.png"

  url       = "http://127.0.0.1:43117"
  subdomain = true
  share     = "owner"

  healthcheck {
    url       = "http://127.0.0.1:43117/healthz"
    interval  = 5
    threshold = 12
  }
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

locals {
  workspace_labels = {
    "app.kubernetes.io/name"     = "coder-workspace"
    "app.kubernetes.io/instance" = "coder-workspace-${data.coder_workspace.me.id}"
    "app.kubernetes.io/part-of"  = "coder"
    "com.coder.resource"         = "true"
    "com.coder.workspace.id"     = data.coder_workspace.me.id
    "com.coder.workspace.name"   = data.coder_workspace.me.name
    "com.coder.user.id"          = data.coder_workspace_owner.me.id
    "com.coder.user.username"    = data.coder_workspace_owner.me.name
  }
}

resource "kubernetes_persistent_volume_claim_v1" "home" {
  metadata {
    name      = "coder-${data.coder_workspace.me.id}-home"
    namespace = var.namespace
    labels = merge(local.workspace_labels, {
      "app.kubernetes.io/name"     = "coder-pvc"
      "app.kubernetes.io/instance" = "coder-pvc-${data.coder_workspace.me.id}"
    })
    annotations = {
      "com.coder.user.email" = data.coder_workspace_owner.me.email
    }
  }
  wait_until_bound = false

  spec {
    access_modes = ["ReadWriteOnce"]
    resources {
      requests = {
        storage = "${data.coder_parameter.home_disk_size.value}Gi"
      }
    }
  }
}

resource "kubernetes_deployment_v1" "workspace" {
  count = data.coder_workspace.me.start_count
  depends_on = [
    kubernetes_persistent_volume_claim_v1.home,
  ]
  wait_for_rollout = false

  metadata {
    name      = "coder-${data.coder_workspace.me.id}"
    namespace = var.namespace
    labels    = local.workspace_labels
    annotations = {
      "com.coder.user.email" = data.coder_workspace_owner.me.email
    }
  }

  spec {
    replicas = 1
    selector {
      match_labels = local.workspace_labels
    }
    strategy {
      type = "Recreate"
    }

    template {
      metadata {
        labels = local.workspace_labels
      }

      spec {
        security_context {
          run_as_user     = 1000
          fs_group        = 1000
          run_as_non_root = true
        }

        container {
          name              = "dev"
          image             = data.coder_parameter.workspace_image.value
          image_pull_policy = "IfNotPresent"
          command           = ["sh", "-c", coder_agent.main.init_script]

          security_context {
            run_as_user = "1000"
          }

          env {
            name  = "CODER_AGENT_TOKEN"
            value = coder_agent.main.token
          }

          env {
            name  = "AGENT_HARNESS"
            value = data.coder_parameter.agent_harness.value
          }

          env {
            name  = "CLI_API_TOKEN"
            value = data.coder_parameter.hapi_cli_api_token.value
          }

          env {
            name  = "PATH"
            value = "/home/coder/.local/bin:/home/coder/.local/share/mise/shims:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
          }

          resources {
            requests = {
              "cpu"    = "250m"
              "memory" = "512Mi"
            }
            limits = {
              "cpu"    = data.coder_parameter.cpu.value
              "memory" = "${data.coder_parameter.memory.value}Gi"
            }
          }

          volume_mount {
            mount_path = "/home/coder"
            name       = "home"
            read_only  = false
          }
        }

        volume {
          name = "home"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim_v1.home.metadata[0].name
            read_only  = false
          }
        }

        affinity {
          # This affinity attempts to spread out all workspace pods evenly across nodes.
          pod_anti_affinity {
            preferred_during_scheduling_ignored_during_execution {
              weight = 1
              pod_affinity_term {
                topology_key = "kubernetes.io/hostname"
                label_selector {
                  match_expressions {
                    key      = "app.kubernetes.io/name"
                    operator = "In"
                    values   = ["coder-workspace"]
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
