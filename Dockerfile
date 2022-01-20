#VERY LIGHTER THAN python:3.7 (python:3.7-alpine non fonctionnel)
FROM python:3.8-slim-buster

# INSTALL BASH, WGET, CURL, VIM
RUN apt-get update -y \
    && apt-get install -y --no-install-recommends apt-utils \
    && apt-get upgrade -y \
    && apt-get install -y curl vim \
    && rm -rf /var/lib/apt/lists/*

# INSTALL HELM3
RUN curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3 && \
    chmod 700 get_helm.sh && \
    ./get_helm.sh && \
    rm -r ./get_helm.sh

# INSTALL KUBECTL
ARG KUBECTL_VERSION="v1.18.3"
RUN curl -LO https://storage.googleapis.com/kubernetes-release/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl && \
    chmod +x ./kubectl && \
    mv ./kubectl /usr/local/bin/kubectl

# INSTALL HELM REPO
RUN helm repo add stable https://charts.helm.sh/stable && \
    helm repo add bitnami https://charts.bitnami.com/bitnami && \
    helm repo update

# OPERATOR
COPY nginx_transport_controller /opt/nginx_transport_controller
COPY nginx_transport_controller.py /opt/nginx_transport_controller.py
RUN chmod 744 /opt/nginx_transport_controller.py
WORKDIR /opt

# PYTHON PACKAGE
COPY requirements.txt /tmp
COPY setup.py /opt
RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt \
    && pip install -e /opt

#LAUNCH KOPF OPERATOR
# ENTRYPOINT ["./launch_kopf.sh"]
# CMD [""]
CMD ["/bin/bash", "-c", "sleep 800"]
