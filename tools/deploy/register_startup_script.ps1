<#
.SYNOPSIS
    One-time, human/admin-run registration of infra/verification_env/startup-script.sh
    as the verification VM's GCE `startup-script` metadata (instructions/214).

.DESCRIPTION
    instructions/213 asked to automate VM bootstrap (bare-repo init, dependency
    resolution) by adding gcloud compute ssh --command="..." calls into
    tools/deploy/deploy_to_vm.ps1. That was rejected: it would have reintroduced
    the exact SSH-based privileged command execution that instructions/212's SRE
    audit had just purged from the deploy/agent pipeline.

    instructions/214 achieves the same bootstrap goal without any SSH/privileged
    commands in the deploy pipeline, by instead registering
    infra/verification_env/startup-script.sh as this VM's `startup-script`
    metadata. GCE executes that script as root on every VM boot; it idempotently
    (1) sets a deadman's-switch TTL auto-shutdown (see below), (2) initializes
    the bare repo (~/nazokake_apps.git), and (3) resolves the dependencies
    infra/verification_env/deploy_pull.sh needs to write deploy status to
    Firestore (firebase-admin, via packages/shared_core/pyproject.toml).

    [PRIVILEGE SEPARATION] This script is never called by deploy_to_vm.ps1, by
    tools/nazo_agent.py, or by any other automated/agent-driven flow. It is a
    separate, one-time, human-run administrative action -- running it is a
    deliberate infra change, not something the deploy pipeline or an autonomous
    agent should ever trigger on its own.

    [TAKES EFFECT ON NEXT BOOT ONLY] GCE's google-startup-scripts.service only
    executes `startup-script` metadata at boot time. Writing new metadata to an
    already-RUNNING VM does NOT retroactively run it. This script deliberately
    does NOT force a reboot/reset itself (that would interrupt anything
    currently running on the VM -- a benchmark, an in-flight deploy_pull.sh).
    If you need the new script to take effect immediately, separately and
    explicitly run:
        gcloud compute instances reset <InstanceName> --project=<ProjectId> --zone=<Zone>

    [SHARED WITH run_ephemeral_pipeline.ps1] tools/deploy/run_ephemeral_pipeline.ps1
    also writes this VM's `startup-script` metadata key on every ephemeral run
    (instructions/178's deadman's-switch TTL injection). GCE has exactly one
    `startup-script` key -- there is no merge, so whichever script last wrote it
    wins the whole value. This is intentionally safe as of instructions/214:
    both this script and run_ephemeral_pipeline.ps1 now register the *same*
    infra/verification_env/startup-script.sh content (which unconditionally
    re-arms the deadman's-switch as its own first step) and only vary the TTL
    via the separate `deadman-switch-minutes` metadata attribute set below. So
    regardless of which script ran most recently, neither the deadman's-switch
    nor the bootstrap logic can end up silently absent.

.EXAMPLE
    .\tools\deploy\register_startup_script.ps1
    .\tools\deploy\register_startup_script.ps1 -DeadmanSwitchMinutes 1440
#>

[CmdletBinding()]
param(
    [string]$ProjectId = "nazokakeapp-137e5",
    [string]$InstanceName = "nazokake-l4-vm",
    [string]$Zone = "us-east1-b",
    [string]$StartupScriptPath = (Join-Path $PSScriptRoot "..\..\infra\verification_env\startup-script.sh"),
    # [instructions/178/214] Kept consistent with run_ephemeral_pipeline.ps1's own
    # default (720 min = 12h), which is itself aligned with
    # tools/config.py:settings.mlops_trigger_stale_after_hours. This sets the
    # `deadman-switch-minutes` metadata attribute that startup-script.sh reads
    # at boot; the script also has its own hardcoded 720-minute fallback if this
    # attribute is ever unset, so the safety net cannot silently disappear.
    [int]$DeadmanSwitchMinutes = 720
)

$ErrorActionPreference = "Stop"

# [instructions/208: root cause of NativeCommandError false positives] Any
# stderr line written by gcloud (including its internal python.exe) is
# promoted to a terminating error under $ErrorActionPreference = "Stop",
# independent of exit code. This script checks $LASTEXITCODE explicitly after
# every gcloud call, so that promotion is a false positive here; external
# commands run with $ErrorActionPreference relaxed to avoid it. Identical
# implementation to deploy_to_vm.ps1's Invoke-ExternalCommand.
function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$ScriptBlock
    )
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $ScriptBlock
    } finally {
        $ErrorActionPreference = $previousEap
    }
}

$resolvedStartupScriptPath = (Resolve-Path -Path $StartupScriptPath -ErrorAction SilentlyContinue)
if (-not $resolvedStartupScriptPath) {
    Write-Error "Startup script not found: $StartupScriptPath"
    exit 1
}
$resolvedStartupScriptPath = $resolvedStartupScriptPath.Path

Write-Host "[INFO] Registering startup-script metadata on $InstanceName (zone=$Zone)..." -ForegroundColor Cyan
Write-Host "       Source file: $resolvedStartupScriptPath" -ForegroundColor DarkGray
Write-Host ("[WARN] This OVERWRITES the VM's entire startup-script metadata value " +
    "(GCE has exactly one such key; there is no merge). " +
    "tools/deploy/run_ephemeral_pipeline.ps1 also writes this same key on every ephemeral " +
    "run -- see this script's header comment for why that is safe as of instructions/214.") -ForegroundColor Yellow

Invoke-ExternalCommand -ScriptBlock {
    gcloud compute instances add-metadata $InstanceName --project=$ProjectId --zone=$Zone `
        --metadata-from-file=startup-script=$resolvedStartupScriptPath 2>&1
} | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to register startup-script metadata on $InstanceName (zone=$Zone)."
    exit 1
}

Write-Host "[INFO] Setting deadman-switch-minutes=$DeadmanSwitchMinutes ..." -ForegroundColor Cyan
Invoke-ExternalCommand -ScriptBlock {
    gcloud compute instances add-metadata $InstanceName --project=$ProjectId --zone=$Zone `
        --metadata="deadman-switch-minutes=$DeadmanSwitchMinutes" 2>&1
} | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to set deadman-switch-minutes metadata on $InstanceName (zone=$Zone)."
    exit 1
}

Write-Host "[OK] Registered." -ForegroundColor Green
Write-Host ("[INFO] This takes effect starting from the VM's NEXT boot/reset -- an already-" +
    "RUNNING VM does not re-run startup-script retroactively. To apply immediately (this " +
    "WILL interrupt anything currently running on the VM):") -ForegroundColor DarkGray
Write-Host "    gcloud compute instances reset $InstanceName --project=$ProjectId --zone=$Zone" -ForegroundColor DarkGray
