<#
.SYNOPSIS
    git(GIT_SSH_COMMAND)がsshバイナリ互換のインターフェースとして呼び出すことを前提に、
    実際の接続をgcloud compute ssh(IAPトンネル経由)へ橋渡しするラッパー
    (instructions/187)。

.DESCRIPTION
    このVM(nazokake-l4-vm)はIAP完全閉域環境であり、素のsshクライアントでは到達できない
    (直接到達可能な固定IP/ポート開放のSSHエンドポイントが無い)。gitのssh transportは
    `<GIT_SSH_COMMAND> [-p <port>] <host> "<remote-command>"` という固定インターフェース
    でしか外部のsshクライアントを呼び出せないため、このラッパー自身を「sshバイナリの
    代わり」としてGIT_SSH_COMMANDへ登録し、gitが渡す引数のうち末尾(実際のリモートコマンド、
    例: git-receive-pack '~/nazokake_apps.git')だけを取り出してgcloud compute sshへ
    そのまま橋渡しする。

    先頭側の引数(ユーザー@ホスト、-p <port>等)はgitのURLパース都合で必ず渡されるが、
    接続先自体は-InstanceName/-ProjectId/-Zoneで明示的に固定されているため意図的に無視する
    (git remoteのURLに書くホスト名文字列は実際には使われない。これがこのラッパーの
    唯一の非直感的な点であり、この理由をgit remoteのURL自体には表現できないため、
    ここに明示的に記録する)。

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
    # gitが末尾に付加する実際の引数列(例: "user@host", "git-receive-pack '~/nazokake_apps.git'")。
    # 先頭側(ホスト/ポート)は無視し、最後の要素だけをリモートコマンドとして使う。
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"

if (-not $RemainingArgs -or $RemainingArgs.Count -eq 0) {
    Write-Error "gcloud_ssh_wrapper.ps1: gitから渡されるリモートコマンド引数がありません。"
    exit 1
}

$RemoteCommand = $RemainingArgs[$RemainingArgs.Count - 1]

gcloud compute ssh $InstanceName --project=$ProjectId --zone=$Zone `
    --tunnel-through-iap --command=$RemoteCommand

exit $LASTEXITCODE
