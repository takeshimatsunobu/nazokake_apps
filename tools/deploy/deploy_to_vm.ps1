<#
.SYNOPSIS
    Nazo-Agent verification server (GCP L4 GPU VM) closed-network GitOps
    kick script (instructions/187, refactored to direct-from-GitHub pull by
    instructions/299). Fully replaces tools/deploy/run_verification_server.ps1
    (ZIP compression + direct file transfer via gcloud compute scp/pscp.exe).

.DESCRIPTION
    The legacy approach (instructions/164-167) ran ClickOps: git archive the
    HEAD into a ZIP, transfer it to the VM with gcloud compute scp (which
    uses pscp.exe internally), then just unzip -o remotely. This physically
    destroyed the .git history on the VM's working directory (~/nazokake_apps),
    which structurally breaks the prerequisites for Nazo-Agent's autonomous
    escalation (diff evaluation against past commit hashes / autonomous
    rollback). It was rejected in an SRE audit as an anti-pattern.

    The immediate successor (instructions/187) replaced ClickOps with a
    relay: this script `git push --force`d from local (Windows) to a bare
    repo on the VM (~/nazokake_apps.git) over the IAP tunnel, and
    infra/verification_env/deploy_pull.sh then fetched from that local bare
    repo. In practice, pushing large objects through the IAP tunnel's
    bandwidth constraints produced "Broken pipe" failures. instructions/299
    removes that intermediary relay entirely: the VM now fetches directly
    from GitHub (https://github.com/takeshimatsunobu/nazokake_apps.git)
    inside deploy_pull.sh, so this script's job shrinks to exactly three
    concerns:
      1. Idempotent VM start via gcloud compute instances start (identical
         implementation to Step 1 of run_verification_server.ps1).
      2. Wait loop for port 22 (SSH) to open (identical to the same Step 2).
      3. Kick infra/verification_env/deploy_pull.sh on the server
         asynchronously over SSH (nohup + disown). deploy_pull.sh itself is
         now solely responsible for `git fetch origin` + `git reset --hard
         origin/main` directly against GitHub, followed by
         setup_verification_env.sh -> docker compose up --build.

    [ABSOLUTE CONSTRAINT] This script must never include ZIP compression
    (git archive/Compress-Archive), direct file transfer logic such as
    pscp.exe, or any git push/bare-repo relay step. The VM must be the one
    pulling directly from GitHub; this script only starts it and tells it to
    pull.

    [KNOWN LIMITATION (out of scope for instructions/187/299)] Step 3 only
    kicks deploy_pull.sh asynchronously on the VM side; this script itself
    does not wait for its completion (success/failure of docker compose up
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
    [int]$SshWaitMaxAttempts = 30,
    [int]$SshWaitDelaySeconds = 10,
    [int]$GcloudRetryMaxAttempts = 5,
    [int]$GcloudRetryInitialDelaySeconds = 5,
    # [instructions/210] Candidate CA bundle used to adapt gcloud's trust
    # chain for this machine's TLS-inspecting AV/proxy (e.g. Norton Web/Mail
    # Shield) in front of the IAP tunnel endpoint. Only ever used to add
    # trust for this script's own IAP calls -- never to bypass verification.
    [string]$CaCertBundlePath = (Join-Path $env:USERPROFILE ".certs\custom_ca_bundle.pem")
)

$ErrorActionPreference = "Stop"

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
# [instructions/210] IAP tunnel TLS trust adaptation. On a machine where a
# TLS-inspecting AV/proxy (e.g. Norton Web/Mail Shield) sits in front of
# tunnel.cloudproxy.app, gcloud's IAP websocket layer fails the handshake
# because gcloud only trusts the CA named in the *gcloud config* property
# core/custom_ca_certs_file (env vars like SSL_CERT_FILE have no effect on
# this specific path). This function adapts that trust chain for the
# duration of this script only, and Restore-IapTlsTrust below puts the
# config property back exactly as it was found. Bypassing verification
# (e.g. nulling the property or disabling checks) is explicitly prohibited.
$script:IapTlsTrustPreviousValue = $null
$script:IapTlsTrustWasChanged = $false

function Set-IapTlsTrust {
    param([string]$CaBundlePath)

    $script:IapTlsTrustPreviousValue = (Invoke-ExternalCommand -ScriptBlock {
        gcloud config get-value core/custom_ca_certs_file 2>$null
    } | Out-String).Trim()

    if ($script:IapTlsTrustPreviousValue -and (Test-Path $script:IapTlsTrustPreviousValue)) {
        Write-Host ("[OK] IAP tunnel TLS trust already configured " +
            "(core/custom_ca_certs_file = $($script:IapTlsTrustPreviousValue)).") -ForegroundColor Green
        return
    }

    if (-not (Test-Path $CaBundlePath)) {
        Write-Error (
            "[ERROR] The IAP tunnel's TLS handshake could not be verified, and no trusted CA " +
            "bundle was found at '$CaBundlePath' either.`n" +
            "This script will NOT bypass TLS verification (fail-open is prohibited).`n" +
            "Fix options:`n" +
            "  1. Ask your network/security team to register IAP's IP range " +
            "(35.235.240.0/20) as a TLS-inspection exclusion, OR`n" +
            "  2. Export the inspecting proxy/AV's root CA to a PEM file and either place it " +
            "at '$CaBundlePath' or pass -CaCertBundlePath <path>, then re-run this script."
        )
        exit 1
    }

    Invoke-ExternalCommand -ScriptBlock { gcloud config set core/custom_ca_certs_file $CaBundlePath } | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[ERROR] Failed to set core/custom_ca_certs_file to '$CaBundlePath'."
        exit 1
    }
    $script:IapTlsTrustWasChanged = $true
    Write-Host "[OK] Trusted the TLS-inspecting proxy's CA for this deploy session: $CaBundlePath" -ForegroundColor Green
}

function Restore-IapTlsTrust {
    if (-not $script:IapTlsTrustWasChanged) {
        return
    }
    if ($script:IapTlsTrustPreviousValue) {
        Invoke-ExternalCommand -ScriptBlock {
            gcloud config set core/custom_ca_certs_file $script:IapTlsTrustPreviousValue
        } | Out-Null
    } else {
        Invoke-ExternalCommand -ScriptBlock { gcloud config unset core/custom_ca_certs_file } | Out-Null
    }
    Write-Host "[INFO] Restored core/custom_ca_certs_file to its pre-script value." -ForegroundColor DarkGray
}

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
Write-Host "[1/3] Checking current status of VM: $InstanceName (zone=$Zone) ..." -ForegroundColor Cyan
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
Write-Host "[2/3] Waiting for SSH (port 22) to open..." -ForegroundColor Cyan

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

# [instructions/210] Everything from here on uses gcloud compute ssh over the
# IAP tunnel, which needs a trusted CA for this machine's TLS-inspecting
# proxy/AV. Establish that trust now, and always restore the prior gcloud
# config state afterwards, regardless of how this block exits.
Set-IapTlsTrust -CaBundlePath $CaCertBundlePath
try {
    # --- Step 3: Asynchronously kick deploy_pull.sh on the server -----------
    # [instructions/299] No bare-repo init and no git push happen here anymore.
    # deploy_pull.sh itself now fetches directly from GitHub on the VM side,
    # so this script's only remaining job (beyond starting the VM and waiting
    # for SSH) is to tell the VM to go pull and rebuild.
    Write-Host "[3/3] Kicking deploy_pull.sh asynchronously..." -ForegroundColor Cyan

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
} finally {
    Restore-IapTlsTrust
}

Write-Host "[DONE] GitOps deploy kick complete. See VM-side progress at " -ForegroundColor Green -NoNewline
Write-Host "~/nazokake_apps_deploy_pull.log" -ForegroundColor Green -NoNewline
Write-Host " on the VM." -ForegroundColor Green
