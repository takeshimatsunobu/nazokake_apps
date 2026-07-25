<#
.SYNOPSIS
    Nazo-Agent verification server (GCP L4 GPU VM) closed-network GitOps
    (pull-style deploy via bare repo) kick script (instructions/187). Fully
    replaces tools/deploy/run_verification_server.ps1 (ZIP compression +
    direct file transfer via gcloud compute scp/pscp.exe).

.DESCRIPTION
    The legacy approach (instructions/164-167) ran ClickOps: git archive the
    HEAD into a ZIP, transfer it to the VM with gcloud compute scp (which
    uses pscp.exe internally), then just unzip -o remotely. This physically
    destroyed the .git history on the VM's working directory (~/nazokake_apps),
    which structurally breaks the prerequisites for Nazo-Agent's autonomous
    escalation (diff evaluation against past commit hashes / autonomous
    rollback). It was rejected in an SRE audit as an anti-pattern.

    This script replaces that flow end-to-end as follows:
      1. Idempotent VM start via gcloud compute instances start (identical
         implementation to Step 1 of run_verification_server.ps1).
      2. Wait loop for port 22 (SSH) to open (identical to the same Step 2).
      3. If a bare repo (~/nazokake_apps.git) does not exist on the VM,
         initialize one with git init --bare (idempotent).
      4. git push --force from local (Windows) to the VM's bare repo, to a
         fixed branch name (default "deploy"). The actual SSH connection is
         bridged through gcloud_ssh_wrapper.ps1 to gcloud compute ssh (IAP
         tunnel), via a GIT_SSH_COMMAND wrapper.
      5. After a successful push, kick infra/verification_env/deploy_pull.sh
         on the server asynchronously over SSH (nohup + disown). The
         sequence of git fetch/reset --hard -> setup_verification_env.sh ->
         docker compose up --build is deploy_pull.sh's own responsibility.

    [ABSOLUTE CONSTRAINT] This script must never include ZIP compression
    (git archive/Compress-Archive) or direct file transfer logic such as
    pscp.exe. Transfer relies solely on git's native push/fetch protocol.

    [KNOWN LIMITATION (out of scope for instructions/187)] Step 5 only kicks
    deploy_pull.sh asynchronously on the VM side; this script itself does
    not wait for its completion (success/failure of docker compose up
    --build). Therefore the dashboard that polls this process's stdout
    (apps/evaluator/backend/api/routers/admin.py: deploy.log) will only show
    that the kick happened, while the VM side's actual build progress is
    recorded only in ~/nazokake_apps_deploy_pull.log on the VM. Relaying that
    log to the dashboard is out of scope and tracked as a separate ticket.

.EXAMPLE
    .\tools\deploy\deploy_to_vm.ps1
    .\tools\deploy\deploy_to_vm.ps1 -Zone us-east1-b -InstanceName nazokake-l4-vm
#>

[CmdletBinding()]
param(
    [string]$ProjectId = "nazokakeapp-137e5",
    [string]$InstanceName = "nazokake-l4-vm",
    [string]$Zone = "us-east1-b",
    [string]$DeployBranch = "deploy",
    [string]$RemoteUser = "takes",
    [int]$SshWaitMaxAttempts = 30,
    [int]$SshWaitDelaySeconds = 10,
    [int]$GcloudRetryMaxAttempts = 5,
    [int]$GcloudRetryInitialDelaySeconds = 5
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$SshWrapperPath = Join-Path $PSScriptRoot "gcloud_ssh_wrapper.ps1"

# [instructions/201: handling ZONE_RESOURCE_POOL_EXHAUSTED]
# The originally considered approach (auto-retry by switching --zone on
# start failure) was not adopted. Because GCE instances (including their
# persistent disks) are permanently pinned to the zone they were created in,
# $InstanceName has no real instance in any zone other than $Zone, so
# retrying `instances start` with a different --zone would just fail with
# "resource not found" and would not work around pool exhaustion (real
# failover would require replicating the instance into each candidate zone,
# or recreating it from a disk snapshot, which is far beyond this script's
# responsibility). So when pool exhaustion is detected, this script only
# surfaces $CandidateZones below as a manual-response option; it does not
# switch zones automatically.
$CandidateZones = @('us-east1-b', 'us-east1-c', 'us-east1-d')

# [instructions/208: root cause of the NativeCommandError crashes] With
# $ErrorActionPreference = "Stop" above, PowerShell promotes ANY line an
# external command (git/gcloud, including gcloud.ps1's own internal
# python.exe invocation) writes to its real stderr into a terminating
# error -- independent of exit code, and even when the call site redirects
# that stream (2>&1/2>$null only controls where the resulting object ends
# up, not whether $ErrorActionPreference fires on it in the first place).
# This script already checks $LASTEXITCODE explicitly after every external
# command, so termination-on-stderr is a false positive here; external
# commands are run with $ErrorActionPreference relaxed to avoid it.
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

# [instructions/166: autonomous retry (exponential backoff)] GCP's OS
# Login/IAP permission provisioning can take effect with a time lag even
# after the VM has started and SSH has opened. Same implementation as
# run_verification_server.ps1 (treating this transient auth error the same
# as a "real" failure and aborting immediately would violate the "one-touch
# provisioning" requirement).
function Invoke-GcloudWithRetry {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$ScriptBlock,
        [Parameter(Mandatory = $true)][string]$Description,
        [int]$MaxAttempts = $GcloudRetryMaxAttempts,
        [int]$InitialDelaySeconds = $GcloudRetryInitialDelaySeconds
    )

    $delay = $InitialDelaySeconds
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        Invoke-ExternalCommand -ScriptBlock $ScriptBlock
        if ($LASTEXITCODE -eq 0) {
            return
        }

        if ($attempt -eq $MaxAttempts) {
            Write-Error ("$Description did not succeed after $MaxAttempts attempts " +
                "(final exit code: $LASTEXITCODE). This may be a permanent problem " +
                "unrelated to OS Login/IAP permission propagation lag.")
            exit 1
        }

        Write-Host ("[WARN] $Description failed (exit code: $LASTEXITCODE, " +
            "attempt $attempt/$MaxAttempts). Assuming this is GCP permission " +
            "provisioning lag; retrying automatically in ${delay}s...") -ForegroundColor Yellow
        Start-Sleep -Seconds $delay
        $delay = $delay * 2
    }
}

# --- Step 1: Start the VM (idempotent) --------------------------------------
Write-Host "[1/5] Checking current status of VM: $InstanceName (zone=$Zone) ..." -ForegroundColor Cyan
$currentStatus = Invoke-ExternalCommand -ScriptBlock {
    gcloud compute instances describe $InstanceName `
        --project=$ProjectId --zone=$Zone --format="get(status)" 2>&1
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to get VM status ($InstanceName, zone=$Zone)."
    exit 1
}
$currentStatus = ($currentStatus -join "").Trim()

if ($currentStatus -eq "RUNNING") {
    Write-Host "[INFO] VM is already in RUNNING state. Skipping start (idempotent)." -ForegroundColor Yellow
} else {
    Write-Host "[INFO] Starting VM (current state: $currentStatus)..." -ForegroundColor Cyan
    $startOutput = Invoke-ExternalCommand -ScriptBlock {
        gcloud compute instances start $InstanceName --project=$ProjectId --zone=$Zone 2>&1
    }
    $startOutput | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        $startOutputText = ($startOutput | Out-String)
        if ($startOutputText -match 'ZONE_RESOURCE_POOL_EXHAUSTED' -or $startOutputText -match 'is currently unavailable') {
            $otherZones = $CandidateZones | Where-Object { $_ -ne $Zone }
            Write-Error (
                "[POOL EXHAUSTED] Zone '$Zone' has no physical inventory available for " +
                "$InstanceName (L4 GPU) (ZONE_RESOURCE_POOL_EXHAUSTED / is currently unavailable).`n" +
                "This VM (including its persistent disk) is permanently pinned to zone '$Zone', " +
                "so automatic failover by changing -Zone is not possible " +
                "(no instance of $InstanceName exists in any other zone).`n" +
                "Manual options:`n" +
                "  1. Wait and retry later (pool exhaustion is often temporary).`n" +
                "  2. For a permanent fix, snapshot the disk and recreate the instance in one of " +
                "the candidate zones ($($otherZones -join ', ')) " +
                "(requires evaluating data consistency/downtime; out of scope for this script)."
            )
            exit 1
        }
        Write-Error "Failed to start VM ($InstanceName, zone=$Zone)."
        exit 1
    }
}

# --- Step 2: Wait for SSH (port 22) to open ---------------------------------
Write-Host "[2/5] Waiting for SSH (port 22) to open..." -ForegroundColor Cyan

$externalIp = Invoke-ExternalCommand -ScriptBlock {
    gcloud compute instances describe $InstanceName `
        --project=$ProjectId --zone=$Zone `
        --format="get(networkInterfaces[0].accessConfigs[0].natIP)" 2>&1
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to get the VM's external IP address."
    exit 1
}
$externalIp = ($externalIp -join "").Trim()
if (-not $externalIp) {
    Write-Error ("VM '$InstanceName' has no external IP address assigned " +
        "(direct reachability check via Test-NetConnection may not be possible in an " +
        "IAP-only configuration).")
    exit 1
}

$sshReady = $false
for ($attempt = 1; $attempt -le $SshWaitMaxAttempts; $attempt++) {
    Write-Host "    Attempt $attempt/$SshWaitMaxAttempts`: ${externalIp}:22 ..."
    $probe = Test-NetConnection -ComputerName $externalIp -Port 22 -WarningAction SilentlyContinue
    if ($probe.TcpTestSucceeded) {
        $sshReady = $true
        break
    }
    Start-Sleep -Seconds $SshWaitDelaySeconds
}

if (-not $sshReady) {
    $totalWaitSec = $SshWaitMaxAttempts * $SshWaitDelaySeconds
    Write-Error "Timeout: port 22 did not open after waiting ${totalWaitSec}s."
    exit 1
}
Write-Host "[OK] SSH is open." -ForegroundColor Green

# --- Step 3: Initialize the bare repo (idempotent) --------------------------
Write-Host "[3/5] Checking for the bare repo (~/nazokake_apps.git) on the VM..." -ForegroundColor Cyan

$bareRepoInitCommand = 'test -d ~/nazokake_apps.git || git init --bare ~/nazokake_apps.git'
Invoke-GcloudWithRetry -Description "Bare repo initialization check" -ScriptBlock {
    gcloud compute ssh $InstanceName --project=$ProjectId --zone=$Zone `
        --tunnel-through-iap --command=$bareRepoInitCommand 2>&1
}

# --- Step 4: Git push to the bare repo (via IAP tunnel) ---------------------
Write-Host "[4/5] Pushing branch '$DeployBranch' to the VM's bare repo..." -ForegroundColor Cyan

# [instructions/187] This VM lives in a fully closed IAP-only network and is
# unreachable with a plain ssh client, so GIT_SSH_COMMAND is redirected to
# gcloud_ssh_wrapper.ps1 (which bridges to gcloud compute ssh
# --tunnel-through-iap). The hostname written into the remote URL below
# ($InstanceName) is not actually used by the wrapper itself (the connection
# target is already fixed via the -InstanceName/-Zone/-ProjectId arguments);
# it is kept as the real instance name purely for readability in `git remote`
# listings.
$env:GIT_SSH_COMMAND = "powershell -NoProfile -ExecutionPolicy Bypass -File " +
    "`"$SshWrapperPath`" -InstanceName $InstanceName -ProjectId $ProjectId -Zone $Zone"

$remoteUrl = "${RemoteUser}@${InstanceName}:~/nazokake_apps.git"

Push-Location $ProjectRoot
try {
    # [Deterministic remote name] Use a remote name dedicated to this
    # verification VM, explicitly separate from any future real source
    # control remote (e.g. "origin"), to avoid name collisions.
    $existingRemote = Invoke-ExternalCommand -ScriptBlock { git remote get-url verification-vm 2>&1 }
    if ($LASTEXITCODE -ne 0) {
        Invoke-ExternalCommand -ScriptBlock { git remote add verification-vm $remoteUrl }
    } else {
        $existingRemote = ($existingRemote -join "").Trim()
        if ($existingRemote -ne $remoteUrl) {
            Invoke-ExternalCommand -ScriptBlock { git remote set-url verification-vm $remoteUrl }
        }
    }

    # [Inherited from instructions/166] Push is also subject to automatic
    # retry, anticipating transient auth errors caused by OS Login/IAP
    # permission provisioning lag. Force-pushing to the fixed deploy branch
    # ($DeployBranch) is safe to re-run (idempotent re-push of the same
    # commit) since it is not a branch shared between developers.
    Invoke-GcloudWithRetry -Description "git push (verification-vm)" -ScriptBlock {
        git push --force verification-vm "HEAD:refs/heads/$DeployBranch"
    }
} finally {
    Pop-Location
    Remove-Item Env:\GIT_SSH_COMMAND -ErrorAction SilentlyContinue
}

Write-Host "[OK] Push complete." -ForegroundColor Green

# --- Step 5: Asynchronously kick deploy_pull.sh on the server ---------------
Write-Host "[5/5] Kicking deploy_pull.sh asynchronously..." -ForegroundColor Cyan

# Using nohup + disown lets this run continue on the VM side without waiting
# for this SSH command itself (i.e. the gcloud compute ssh process) to exit
# ("asynchronous kick", instructions/187). deploy_pull.sh's own stdout/stderr
# accumulates in ~/nazokake_apps_deploy_pull.log on the VM (not relayed to
# this dashboard's deploy.log; see the known limitation in .SYNOPSIS).
$kickCommand = 'nohup bash ~/nazokake_apps/infra/verification_env/deploy_pull.sh ' +
    '> ~/nazokake_apps_deploy_pull.log 2>&1 < /dev/null & disown; ' +
    'echo "Kicked deploy_pull.sh in the background (PID: $!)"'

Invoke-GcloudWithRetry -Description "Asynchronous kick of deploy_pull.sh" -ScriptBlock {
    gcloud compute ssh $InstanceName --project=$ProjectId --zone=$Zone `
        --tunnel-through-iap --command=$kickCommand 2>&1
}

Write-Host "[DONE] GitOps deploy kick complete. See VM-side progress at " -ForegroundColor Green -NoNewline
Write-Host "~/nazokake_apps_deploy_pull.log" -ForegroundColor Green -NoNewline
Write-Host " on the VM." -ForegroundColor Green
