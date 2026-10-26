# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x | yes |
| < 0.2 | no |

This is a portfolio/reference project, not a hosted production service. There
is no SLA or 24/7 security response commitment.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's
private vulnerability reporting / Security Advisories for this repository:

1. Go to the repository's **Security** tab.
2. Choose **Advisories** → **Report a vulnerability**.
3. Include the affected version, a minimal reproduction, and the impact.

If private reporting is unavailable, contact the maintainer through the GitHub
profile and ask for a private channel.

## Scope

In scope:

- gateway authentication bypass (when `GATEWAY_API_KEY` is configured);
- admission-control bypass or resource exhaustion;
- request smuggling, header injection, or unsafe upstream proxying;
- secrets exposure in logs, images, or repository files;
- container configuration issues in the shipped image/manifests.

Out of scope:

- model quality or factual correctness;
- benchmark numbers or performance claims;
- vulnerabilities in third-party model weights or datasets;
- issues that require a compromised host or cluster admin;
- denial of service from an intentionally unbounded external load generator.

## Secrets

- `GATEWAY_API_KEY` must come from an environment variable or a Kubernetes
  Secret (`inference-gateway-secret`), never from Git.
- Model weights, datasets, `.env` files, and local benchmark artifacts must not
  be committed.
- If a key is exposed, rotate it and restart the gateway pods.

## Known limitations

- The demo includes a self-signed Nginx TLS terminator
  (`deploy/observability/nginx/`). It is for local validation only; production
  must use a trusted ingress/ACME certificate. See `docs/TLS.md`.
- API-key authentication is optional and disabled when `GATEWAY_API_KEY` is
  empty; health and metrics endpoints are intentionally unauthenticated for
  probes and Prometheus.
- The gateway is single-tenant in the reference deployment; per-tenant quota
  and isolation are not implemented.
- Kubernetes GPU scheduling and stable in-cluster vLLM were not validated on
  this host; see `docs/K3S_GPU_EXPERIMENT.md`.
