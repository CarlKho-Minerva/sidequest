# Deploy

```bash
kind create cluster --config deploy/kind-config.yaml
docker build -t sidequest-api:dev . && kind load docker-image sidequest-api:dev --name sidequest
kubectl create namespace sidequest
kubectl -n sidequest create secret generic sidequest-secrets \
  --from-literal=ES_PASSWORD="$ES_PASSWORD" \
  --from-literal=OTEL_EXPORTER_OTLP_ENDPOINT="$OTEL_EXPORTER_OTLP_ENDPOINT" \
  --from-literal=OTEL_EXPORTER_OTLP_HEADERS="$OTEL_EXPORTER_OTLP_HEADERS"
kubectl apply -k deploy/
open http://localhost:30080
```

Radar: paste the install command from app.radarhq.io "Connect a cluster" against the kind context.
