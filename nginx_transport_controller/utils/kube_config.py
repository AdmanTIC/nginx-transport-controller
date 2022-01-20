# coding: utf-8
"""
    Library gathering functions to connect operator to Kubernetes cluster using 
    kubeconfig.
"""

"""
    Generate kubeconfig file according to Kubernetes SA
    (/var/run/secrets/kubernetes.io/serviceaccount)
"""

from pathlib import Path
import os
import yaml
import base64
import logging

from nginx_transport_controller.configuration import (
    HOME,
    KUBERNETES_SERVICE_PORT_HTTPS,
    KUBERNETES_SERVICE_HOST,
    OPERATOR_CLUSTER,
    OPERATOR_CONTEXT,
    OPERATOR_USER,
)


class KubeConfFile():
    """
        Object class representing kubeconfig file. Each parameters is a field of 
        the kubeconfig file which is a YAML file.
    """
    def __init__(self, path=None):
        if path is None:
            self.path = f"{HOME}/.kube"

        self.token = ''
        self.data = {}
        self.data['apiVersion'] = 'v1'
        self.data['kind'] = 'Config'
        self.data['clusters'] = []
        self.data['contexts'] = []
        self.data['users'] = []
        self.data['current-context'] = f"{OPERATOR_CONTEXT}"


    def set_sa_data(self):
        """
            Set cluster infos. passed through Pod ServiceAccount
        """

        envpath = "/var/run/secrets/kubernetes.io/serviceaccount"

        # Set CLUSTER
        with open(os.path.join(envpath, "ca.crt"), 'rb') as infile:
            temp = infile.read()
            temp = base64.b64encode(temp)
            cert = temp.decode("utf-8")

        server = f"https://{KUBERNETES_SERVICE_HOST}:{KUBERNETES_SERVICE_PORT_HTTPS}"

        cluster = {
            "cluster": {
                "certificate-authority-data": cert,
                "server": server,
                },
            "name": f"{OPERATOR_CLUSTER}"
        }
        self.data['clusters'].append(cluster)

        # Set CONTEXTS
        context = {
            "name": f"{OPERATOR_CONTEXT}",
            "context": {
                "cluster": f"{OPERATOR_CLUSTER}",
                "user": f"{OPERATOR_USER}",
                }
        }
        self.data['contexts'].append(context)

        # Set USERS
        with open(os.path.join(envpath, "token")) as infile:
            self.token = infile.read()
        user = {
            "name": f"{OPERATOR_USER}",
            "user": {
                "token": self.token,
            }
        }
        self.data['users'].append(user)


    def generate_file(self, operator_or_resellername="operator"):
        """
            Generate kubeconfig file in `path` according to object parameters.
        """

        try:
            # Ensure parent directory exists
            if not os.path.exists(self.path):
                os.mkdir(self.path)

            # Write file
            with open(f"{self.path}/config", 'w') as outfile:
                yaml.dump(self.data, outfile, default_flow_style=False)

        except FileNotFoundError as error:
            logging.critical("kubeconfig file could not been created: %s", error)
            raise

if __name__ == "__main__":
    pass