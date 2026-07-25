<#
.SYNOPSIS
    Wrapper that git (via GIT_SSH_COMMAND) invokes as an ssh-binary-compatible
    interface, bridging the actual connection to gcloud compute ssh (over an
    IAP tunnel) (instructions/187).

.DESCRIPTION
    This VM (nazokake-l4-vm) lives in a fully closed IAP-only network and is
    unreachable with a plain ssh client (there is no directly reachable
    fixed IP/open-port SSH endpoint). Git's ssh transport can only invoke an
    external ssh client through the fixed interface
    `<GIT_SSH_COMMAND> [-p <port>] <host> "<remote-command>"`, so this
    wrapper registers itself as GIT_SSH_COMMAND (standing in for the ssh
    binary), pulls out only the trailing argument git passes (the actual
    remote command, e.g. git-receive-pack '~/nazokake_apps.git'), and
    forwards it as-is to gcloud compute ssh.

    The leading arguments (user@host, -p <port>, etc.) are always passed
    because of how git parses its URL, but the actual connection target is
    already fixed explicitly via -InstanceName/-ProjectId/-Zone, so they are
    intentionally ignored (the hostname string written into the git remote
    URL is not actually used. This is the one non-obvious aspect of this
    wrapper, and since that reasoning cannot be expressed in the git remote
    URL itself, it is recorded explicitly here instead).

.EXAMPLE
    $env:GIT_SSH_COMMAND = "powershell -NoProfile -ExecutionPolicy Bypass -File " + `
        "`"$PSScriptRoot\gcloud_ssh_wrapper.ps1`" -InstanceName nazokake-l4-vm " + `
        "-ProjectId nazokakeapp-137e5 -Zone us-east1-b"
    git push --force verification-vm HEAD:refs/heads/deploy
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InstanceName,
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [Parameter(Mandatory = $true)][string]$Zone,
    # The actual trailing argument list git appends (e.g. "user@host",
    # "git-receive-pack '~/nazokake_apps.git'"). The leading elements
    # (host/port) are ignored; only the last element is used as the remote
    # command.
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"

if (-not $RemainingArgs -or $RemainingArgs.Count -eq 0) {
    Write-Error "[ERROR] gcloud_ssh_wrapper.ps1: no remote command argument was passed by git."
    exit 1
}

$RemoteCommand = $RemainingArgs[$RemainingArgs.Count - 1]

gcloud compute ssh $InstanceName --project=$ProjectId --zone=$Zone `
    --tunnel-through-iap --command=$RemoteCommand

exit $LASTEXITCODE
