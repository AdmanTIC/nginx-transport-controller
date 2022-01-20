#!/usr/bin/env python
# coding: utf-8

import argparse
import logging
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

from nginx_transport_controller.utils.ExposedService import ExposedService
import nginx_transport_controller.utils.kube_config as KubeConfig

""" nginx transport controller
    Python script used to configure NGINX Ingress Controller by watching 
    Kubernetes events :
    1. Watch ServiceExposer (CRD) :
        * For each ServiceExposer :
            * Access NGINX Ingress Controller ConfigMap
            * Edit its ConfigMap according to ServiceExposer data

    Parameters :
    -n, --nginx-ns : NGINX Ingress Controller namespace
    -t, --tcp-services-configmap : NGINX Ingress Controller ConfigMap name for TCP services (--tcp-services-configmap NGINX Ingress Controller parameters)
    -u, --udp-services-configmap : NGINX Ingress Controller ConfigMap name for UDP services (--udp-services-configmap NGINX Ingress Controller parameters)

    (cf. https://kubernetes.github.io/ingress-nginx/user-guide/exposing-tcp-udp-services/)

    Output - RC :
    0 : OK
    !=0 : NOK
"""

logging.basicConfig(
    format='[%(asctime)s] NGINX_TRANSPORT_CONTROLLER [%(levelname)-8.8s] %(message)s',
    filename='/dev/stdout',
    encoding='utf-8',
    level=logging.INFO
)


def get_service_exposers():
    global custom_object_api, service_exposers_lastrev
    service_exposers_lastrev = {}
    service_exposers_list = custom_object_api.list_cluster_custom_object(group="admantic.fr", version="v1", plural="serviceexposers")
    
    for service_exposer in service_exposers_list['items']:
        for exposed_service in service_exposer['spec']['exposedServices']:
            current_exposed_service = ExposedService(
                name=exposed_service['targetServiceName'],
                ns=service_exposer['metadata']['namespace'],
                external_port=exposed_service['externalPort'],
                internal_port=exposed_service['internalPort'],
                protocol=exposed_service['protocol'],
                resource_version=service_exposer['metadata']['namespace']
            )
            service_exposers_lastrev[exposed_service['externalPort']] = current_exposed_service
    
    configure_nginx_transport_controller()


def configure_nginx_transport_controller():
    global v1, NGINX_NAMESPACE, TCP_CONFIGMAP, UDP_CONFIGMAP, service_exposers_lastrev

    new_tcp_configmap_data = {}
    new_udp_configmap_data = {}

    for key, exposed_service in service_exposers_lastrev.items():
        if exposed_service.get_protocol() == "tcp":
            new_tcp_configmap_data[key] = exposed_service.format()
        elif exposed_service.get_protocol() == "udp":
            new_udp_configmap_data[key] = exposed_service.format()

    # Patch TCP ConfigMap
    try:
        if len(new_tcp_configmap_data) != 0:
            new_tcp_configmap = client.V1ConfigMap()
            new_tcp_configmap.metadata = client.V1ObjectMeta(name=TCP_CONFIGMAP, namespace=NGINX_NAMESPACE)
            new_tcp_configmap.data = new_tcp_configmap_data
            v1.delete_namespaced_config_map(name=TCP_CONFIGMAP, namespace=NGINX_NAMESPACE)
            v1.create_namespaced_config_map(namespace=NGINX_NAMESPACE, body=new_tcp_configmap)
    except ApiException as e:
        logging.error("Failed to patch ConfigMap %s/%s: %s" % (NGINX_NAMESPACE, TCP_CONFIGMAP, e))
        exit(1)

    # Patch UDP ConfigMap
    try:
        if len(new_udp_configmap_data) != 0:
            new_udp_configmap = client.V1ConfigMap()
            new_udp_configmap.metadata = client.V1ObjectMeta(name=UDP_CONFIGMAP, namespace=NGINX_NAMESPACE)
            new_udp_configmap.data = new_udp_configmap_data
            v1.delete_namespaced_config_map(name=UDP_CONFIGMAP, namespace=NGINX_NAMESPACE)
            v1.create_namespaced_config_map(namespace=NGINX_NAMESPACE, body=new_udp_configmap)
    except ApiException as e:
        logging.error("Failed to patch ConfigMap %s/%s: %s" % (NGINX_NAMESPACE, UDP_CONFIGMAP, e))
        exit(1)


def main():
    global custom_object_api, service_exposers_lastrev

    logging.info("Get initial ServiceExposers...")
    get_service_exposers()

    logging.info("Entering watch loop...")
    event_watcher = watch.Watch()
    while True:
        for event in event_watcher.stream(custom_object_api.list_cluster_custom_object, group="admantic.fr", version="v1", plural="serviceexposers", watch=True, timeout_seconds=900):
            if event['type'] == 'ADDED':
                for exposed_service in event['object']['spec']['exposedServices']:
                    current_ext_port = exposed_service['externalPort']
                    if current_ext_port not in service_exposers_lastrev or service_exposers_lastrev[current_ext_port].get_resource_version() != event['object']['metadata']['resourceVersion']:
                        get_service_exposers()
                        logging.info("Processing event for %s" % service_exposers_lastrev[current_ext_port].display())


if __name__ == '__main__':

    # Parse arguments
    parser = argparse.ArgumentParser(description='Move specified IP to current node service')
    parser.add_argument('-n', '--nginx-ns', help='<Required> NGINX Ingress Controller namespace', required=True)
    parser.add_argument('-t', '--tcp-services-configmap', help='<Required> NGINX Ingress Controller ConfigMap name for TCP services (--tcp-services-configmap NGINX Ingress Controller parameters)', required=True)
    parser.add_argument('-u', '--udp-services-configmap', help='<Required> NGINX Ingress Controller ConfigMap name for UDP services (--udp-services-configmap NGINX Ingress Controller parameters)', required=True)
    args = parser.parse_args()

    NGINX_NAMESPACE = args.nginx_ns
    TCP_CONFIGMAP = args.tcp_services_configmap
    UDP_CONFIGMAP = args.udp_services_configmap

    # Generate kubeconfig file
    logging.info("Generate kubeconfig file")
    kubeconfig_file = KubeConfig.KubeConfFile()
    kubeconfig_file.set_sa_data()
    kubeconfig_file.generate_file()

    # Connect to Kubernetes cluster API using generated kubeconfig file
    try:
        logging.info("Loading kubeconfig...")
        config.load_kube_config("../kubeconfig.yaml")
    except TypeError:
        logging.error("Failed to load kubeconfig")
        exit(1)

    v1 = client.CoreV1Api()
    v1beta1 = client.ExtensionsV1beta1Api()
    custom_object_api = client.CustomObjectsApi()

    main()