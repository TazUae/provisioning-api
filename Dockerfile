FROM frappe/erpnext:v15

USER root
RUN apt-get update && apt-get install -y git

USER frappe

COPY provisioning_api /home/frappe/frappe-bench/apps/provisioning_api

RUN bench --site all install-app provisioning_api || true
