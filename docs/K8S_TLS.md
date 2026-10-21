# TLS and NetworkPolicy on Kubernetes

The Compose demo already terminates TLS in front of the gateway (see
[TLS.md](TLS.md)). This page covers the Kubernetes variant: the same shape, but
with a Service, a Secret, and a NetworkPolicy that the cluster actually
enforces.

Everything here runs on Docker Desktop Kubernetes with a CPU-only mock
upstream. No GPU is involved.

## Layout

`k8s/tls-demo/` is self-contained so `kubectl kustomize` works without lifting
the load restrictor:

| File | Contents |
|---|---|
| `namespace.yaml` | `k8s-tls-demo` namespace |
| `mock-vllm.yaml` | OpenAI-compatible stub Deployment + Service |
| `gateway.yaml` | 2 gateway replicas + ClusterIP Service on 9000 |
| `tls-proxy.yaml` | Nginx TLS terminator (non-root, port 8443) + Service on 443 |
| `networkpolicy.yaml` | Ingress allow-list for the gateway port |
| `kustomization.yaml` | Wires the above, generates the two ConfigMaps |

## Deploy

```bash
kubectl apply -f k8s/tls-demo/namespace.yaml
kubectl -n k8s-tls-demo create secret tls gateway-tls \
  --cert=deploy/observability/nginx/certs/server.crt \
  --key=deploy/observability/nginx/certs/server.key
kubectl apply -k k8s/tls-demo
```

The Secret has to exist before the pods start, otherwise the Nginx pod stays
in `ContainerCreating` waiting on its certificate volume.

## Verify TLS

```bash
kubectl -n k8s-tls-demo port-forward svc/tls-proxy 19443:443
curl -k https://127.0.0.1:19443/health
curl -k -X POST https://127.0.0.1:19443/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"tls demo","max_tokens":16}'
```

Port 19443 rather than 9443, because the Compose demo already binds 9443 on
the host.

Observed on 2026-10-22:

- the served certificate is the self-signed `CN=localhost` pair, valid to 2027;
- `GET /health` returned 200 and reported the real pod name;
- `POST /chat` returned 200 through the proxy.

Evidence: [`tls-endpoints.txt`](../benchmark/results/k8s-tls/tls-endpoints.txt).

The Nginx container runs as UID 101 with `readOnlyRootFilesystem: true`. It
listens on 8443 so it needs no `NET_BIND_SERVICE` capability, and the Service
maps 443 to it. Every temp path lives in an `emptyDir` mounted at `/tmp`, with
`fsGroup: 101` so the directory is group-writable.

## Verify NetworkPolicy

Same namespace should reach the gateway; another namespace should not:

```bash
kubectl -n k8s-tls-demo run same --image=busybox:1.36 --restart=Never -i --rm \
  --command -- wget -qO- -T 5 http://gateway:9000/health

kubectl -n default run other --image=busybox:1.36 --restart=Never -i --rm \
  --command -- wget -qO- -T 5 http://gateway.k8s-tls-demo.svc.cluster.local:9000/health
```

Observed on 2026-10-22, on Docker Desktop Kubernetes v1.36.1:

| Step | Policy | Source namespace | Result |
|---|---|---|---|
| A | present | `default` | denied, client times out (~8 s) |
| B | deleted | — | — |
| C | absent | `default` | reachable, HTTP 200 |
| D | re-applied | — | — |
| E | present | `default` | denied, client times out (~8 s) |
| F | present | `k8s-tls-demo` | reachable, HTTP 200 |

The toggle is the point. Reachability changes when only the policy object
changes, so the denial comes from the NetworkPolicy rather than from a broken
route, DNS, or Service configuration. Enforcement is DROP, so the client times
out instead of getting a connection refused.

Evidence: [`networkpolicy-matrix.txt`](../benchmark/results/k8s-tls/networkpolicy-matrix.txt),
[`pods.txt`](../benchmark/results/k8s-tls/pods.txt).

## One trap worth knowing

The policy looked like a no-op on the first re-apply. The manifest had no
explicit `namespace:`, so `kubectl apply -f` put the object in `default`,
where it matched no gateway pod. `kubectl apply -k` adds the namespace
automatically, `kubectl apply -f` does not.

Every manifest in `k8s/tls-demo/` now sets `namespace` explicitly, so both
commands behave the same way.

## Not claimed

- This is a single-node Docker Desktop cluster, not a production ingress path.
- There is no ingress controller, no ACME/Let's Encrypt, and no cert rotation.
- The workload is a mock upstream: this validates transport and policy, not
  model serving.
- No egress policy and no cross-node traffic were tested.
