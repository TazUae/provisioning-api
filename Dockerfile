FROM frappe/erpnext:v15

USER root
RUN apt-get update && apt-get install -y git

USER frappe
WORKDIR /home/frappe/frappe-bench

COPY --chown=frappe:frappe provisioning_api /home/frappe/frappe-bench/apps/provisioning_api

RUN /home/frappe/frappe-bench/env/bin/pip install -e /home/frappe/frappe-bench/apps/provisioning_api

RUN echo "provisioning_api" >> /home/frappe/frappe-bench/sites/apps.txt

USER root
RUN chown -R frappe:frappe /home/frappe/frappe-bench/apps/provisioning_api

USER frappe
