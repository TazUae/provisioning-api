# provisioning_api

Custom ERPNext app that provides a **provisioning layer** for creating and managing sites from within the ERP stack.

## Purpose

- **Enables ERP provisioning**: exposes system-level helpers (for example `create_site`) that wrap `bench` operations so automation can provision new sites in a controlled way.
- **Used by erp-execution-service**: the execution service can invoke this app’s methods (for example via `bench execute provisioning_api.api.provisioning.create_site`) instead of shelling out ad hoc from unrelated services.
- **Runs `bench new-site` internally**: site creation is performed by calling `bench new-site` with MariaDB and ERPNext installation, as implemented in `provisioning_api.api.provisioning`.

## Docker image

Build from the **parent** directory of this repo so the `COPY provisioning_api` path in the `Dockerfile` resolves correctly:

```bash
docker build -f provisioning_api/Dockerfile -t your-registry/provisioning-erpnext:v15 .
```

## Execute

From a bench environment where this app is installed:

```bash
bench execute provisioning_api.api.provisioning.create_site --kwargs '{"site_name": "mysite"}'
```

## License

MIT (see `hooks.py`).
