# Serving profiles

These files describe the deployment defaults for the model variants measured by
the project. They are configuration inputs, not secrets. Copy one to an
environment-specific file and override the upstream URL, pod name and keys
outside version control.

The runtime reads the same names through
`llm8g.serving.config.GatewaySettings.from_env()`.

