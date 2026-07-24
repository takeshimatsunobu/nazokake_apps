$ErrorActionPreference = 'SilentlyContinue'
$found = @()
foreach ($loc in @('CurrentUser','LocalMachine')) {
  Get-ChildItem -Path "Cert:\$loc" | ForEach-Object {
    $storeName = $_.Name
    Get-ChildItem -Path "Cert:\$loc\$storeName" | Where-Object {
      $_.Subject -like '*Norton*' -or $_.Issuer -like '*Norton*'
    } | ForEach-Object {
      $found += [PSCustomObject]@{ Store="$loc\$storeName"; Subject=$_.Subject; Thumbprint=$_.Thumbprint }
    }
  }
}
if ($found.Count -eq 0) {
  Write-Output 'NO_NORTON_CA_FOUND_ANYWHERE'
} else {
  $found | Format-List | Out-String | Write-Output
}
