FROM frappe/erpnext:v15

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY . /home/frappe/frappe-bench/apps/provisioning_api
RUN chown -R frappe:frappe /home/frappe/frappe-bench/apps/provisioning_api

USER frappe
WORKDIR /home/frappe/frappe-bench

ENV PATH="/home/frappe/frappe-bench/env/bin:${PATH}"

RUN /home/frappe/frappe-bench/env/bin/pip install --no-cache-dir -e /home/frappe/frappe-bench/apps/provisioning_api

RUN mkdir -p /home/frappe/frappe-bench/sites \
    && touch /home/frappe/frappe-bench/sites/apps.txt \
    && (grep -qxF provisioning_api /home/frappe/frappe-bench/sites/apps.txt || echo provisioning_api >> /home/frappe/frappe-bench/sites/apps.txt)

USER root
RUN chown -R frappe:frappe /home/frappe/frappe-bench/apps/provisioning_api

USER frappe
