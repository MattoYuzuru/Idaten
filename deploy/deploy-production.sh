#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 --digest sha256:<64-hex> [--apply]" >&2
  exit 2
}

digest=""
apply=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --digest)
      [ "$#" -ge 2 ] || usage
      digest="$2"
      shift 2
      ;;
    --apply)
      apply=true
      shift
      ;;
    *) usage ;;
  esac
done

[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || usage
root="$(cd "$(dirname "$0")/.." && pwd)"
image="ghcr.io/mattoyuzuru/idaten-backend@$digest"

render() {
  kubectl kustomize "$root/deploy/kubernetes" |
    sed "s#ghcr.io/mattoyuzuru/idaten-backend:sha-RELEASE_COMMIT#$image#"
}

if ssh keykomi 'sudo k3s kubectl get namespace idaten >/dev/null 2>&1'; then
  render | ssh keykomi 'sudo k3s kubectl apply --dry-run=server -f -'
else
  ssh keykomi 'sudo k3s kubectl apply --dry-run=server -f -' < "$root/deploy/kubernetes/namespace.yaml"
  render | ssh keykomi 'sudo k3s kubectl apply --dry-run=client -f -'
  echo "namespace is not provisioned yet; full server-side dry-run will run after provisioning"
fi
if ! $apply; then
  echo "server-side dry-run passed; rerun with --apply after the production confirmation gate"
  exit 0
fi

render | ssh keykomi 'sudo k3s kubectl apply -f -'
ssh keykomi 'sudo k3s kubectl rollout status deployment/idaten-backend -n idaten --timeout=180s'
ssh keykomi 'sudo k3s kubectl get deployment,pod,service,ingress,certificate,pvc -n idaten'
