# TODO: 2026-08-11を以て、このファイルは完全に削除すること (Sunset Date)
# instructions/272: Tombstoned (legacy, unreferenced multi-zone L4 GPU VM creation
# script for the old manual "always-on fortress" pattern). Permanently disabled.
import sys

print("ERROR: This deployment script is deprecated and has been permanently disabled.", file=sys.stderr)
print("All deployments are now managed exclusively via GitHub Actions (GitOps).", file=sys.stderr)
print("Please merge your changes to the main branch to trigger the CD pipeline.", file=sys.stderr)
sys.exit(1)
