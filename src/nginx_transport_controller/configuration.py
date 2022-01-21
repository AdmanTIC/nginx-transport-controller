# coding: utf-8

"""
    Set controller CONST
"""

import logging
import os

NGINXTRANSPORTINGRESS_CRD = {
    "group": "admantic.fr",
    "version": "v1",
    "plural": "nginxtransportingresses",
}

# Set env. vars.
HOME = os.environ['HOME']
KUBERNETES_NAMESPACE = os.environ.get('KUBERNETES_NAMESPACE', '')
KUBERNETES_SERVICE_PORT_HTTPS = os.environ.get('KUBERNETES_SERVICE_PORT_HTTPS', '')
KUBERNETES_SERVICE_HOST = os.environ.get('KUBERNETES_SERVICE_HOST', '')
OPERATOR_CLUSTER = os.environ.get('OPERATOR_CLUSTER', 'default')
OPERATOR_CONTEXT = os.environ.get('OPERATOR_CONTEXT', 'default')
OPERATOR_USER = os.environ.get('OPERATOR_USER', 'default')
