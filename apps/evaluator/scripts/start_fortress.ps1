# TODO: 2026-08-11を以て、このファイルは完全に削除すること (Sunset Date)
# instructions/272: Tombstoned (legacy, unreferenced manual VM-start + Cloud Run
# redeploy script for the old "always-on L4 fortress" pattern). Permanently disabled.

Write-Host "ERROR: This deployment script is deprecated and has been permanently disabled." -ForegroundColor Red
Write-Host "All deployments are now managed exclusively via GitHub Actions (GitOps)." -ForegroundColor Red
Write-Host "Please merge your changes to the main branch to trigger the CD pipeline." -ForegroundColor Red
exit 1
