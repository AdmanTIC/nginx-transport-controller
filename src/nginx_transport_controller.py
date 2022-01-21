#!/usr/bin/env python
# coding: utf-8

import argparse
import logging
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

from nginx_transport_controller.utils.NginxTransportIngress import NginxTransportIngress
import nginx_transport_controller.utils.kube_config as KubeConfig

from nginx_transport_controller.configuration import (
    NGINXTRANSPORTINGRESS_CRD
)

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
    level=logging.INFO
)

# TODO REFACTORING...
# def update_nginx_transport_ingress_status(name, ns, status):
#     global custom_object_api

#     patch_data = custom_object_api.get_namespaced_custom_object(group=NGINXTRANSPORTINGRESS_CRD['group'], version=NGINXTRANSPORTINGRESS_CRD['version'], plural=NGINXTRANSPORTINGRESS_CRD['plural'], namespace=ns, name=name)
#     patch_data['status'] = {}
#     patch_data['status']['configStatus'] = status
#     custom_object_api.patch_namespaced_custom_object(group=NGINXTRANSPORTINGRESS_CRD['group'], version=NGINXTRANSPORTINGRESS_CRD['version'], plural=NGINXTRANSPORTINGRESS_CRD['plural'], namespace=ns, name=name, body=patch_data)


""" process_nginx_transport_ingresses()
    Put all exposed services into a list by retrieving all NginxTransportIngresses 
    and call add_port_entries() to patch (replace) corresponding ConfigMaps.
"""
def process_nginx_transport_ingresses():
    global custom_object_api, nginx_transport_ingresses_lastrev
    nginx_transport_ingresses_list = custom_object_api.list_cluster_custom_object(group=NGINXTRANSPORTINGRESS_CRD['group'], version=NGINXTRANSPORTINGRESS_CRD['version'], plural=NGINXTRANSPORTINGRESS_CRD['plural'])

    for nginx_transport_ingress in nginx_transport_ingresses_list['items']:
        nginx_transport_ingresses_lastrev["%s_%s" % (nginx_transport_ingress['metadata']['namespace'], nginx_transport_ingress['metadata']['name'])] = {}
        for exposed_service in nginx_transport_ingress['spec']['exposedServices']:
            current_exposed_service = NginxTransportIngress(
                name=exposed_service['targetServiceName'],
                ns=nginx_transport_ingress['metadata']['namespace'],
                external_port=exposed_service['externalPort'],
                internal_port=exposed_service['internalPort'],
                protocol=exposed_service['protocol'],
                resource_version=nginx_transport_ingress['metadata']['namespace']
            )
            nginx_transport_ingresses_lastrev["%s_%s" % (nginx_transport_ingress['metadata']['namespace'], nginx_transport_ingress['metadata']['name'])][exposed_service['externalPort']] = current_exposed_service

    add_port_entries() 


""" add_port_entries()
    Patch (replace) TCP and UDP ConfigMaps by using exposed services' list
    (`nginx_transport_ingresses_lastrev`)
"""
def add_port_entries():
    global v1, NGINX_NAMESPACE, TCP_CONFIGMAP, UDP_CONFIGMAP, nginx_transport_ingresses_lastrev

    tcp_data_patch = {}
    udp_data_patch = {}

    # Format data to be patched
    for nginx_transport_ingress, exposed_services in nginx_transport_ingresses_lastrev.items():
        for external_port, exposed_service in exposed_services.items():
            if exposed_service.get_protocol() == "tcp":
                tcp_data_patch[external_port] = exposed_service.format()
            elif exposed_service.get_protocol() == "udp":
                udp_data_patch[external_port] = exposed_service.format()
            
    # Patch current TCP and UDP ConfigMaps
    try:
        # TCP
        CONFIGMAP = TCP_CONFIGMAP
        configmap_patch = client.V1ConfigMap()
        configmap_patch.metadata = client.V1ObjectMeta(name=CONFIGMAP, namespace=NGINX_NAMESPACE)
        configmap_patch.data = tcp_data_patch
        v1.replace_namespaced_config_map(name=CONFIGMAP, namespace=NGINX_NAMESPACE, body=configmap_patch)
        
        # UDP
        CONFIGMAP = UDP_CONFIGMAP
        configmap_patch = client.V1ConfigMap()
        configmap_patch.metadata = client.V1ObjectMeta(name=CONFIGMAP, namespace=NGINX_NAMESPACE)
        configmap_patch.data = udp_data_patch
        v1.replace_namespaced_config_map(name=CONFIGMAP, namespace=NGINX_NAMESPACE, body=configmap_patch)
    except ApiException as e:
        logging.error("Failed to patch ConfigMap %s/%s: %s" % (NGINX_NAMESPACE, CONFIGMAP, e))
        exit(1)


def main():
    global custom_object_api, nginx_transport_ingresses_lastrev

    nginx_transport_ingresses_lastrev = {}

    # Pre-processing
    logging.info("Get initial NginxTransportIngresses...")
    process_nginx_transport_ingresses()

    # Watch loop
    logging.info("Entering watch loop...")
    event_watcher = watch.Watch()
    while True:
        for event in event_watcher.stream(custom_object_api.list_cluster_custom_object, group=NGINXTRANSPORTINGRESS_CRD['group'], version=NGINXTRANSPORTINGRESS_CRD['version'], plural=NGINXTRANSPORTINGRESS_CRD['plural'], watch=True, timeout_seconds=900):
            if event['type'] == 'ADDED' or event['type'] == 'MODIFIED' or event['type'] == 'DELETED':
                for exposed_service in event['object']['spec']['exposedServices']:
                    current_ext_port = exposed_service['externalPort']
                    logging.info("Processing event [%s] for %s" % (event['type'], nginx_transport_ingresses_lastrev["%s_%s" % (event['object']['metadata']['namespace'], event['object']['metadata']['name'])][current_ext_port].display()))
                process_nginx_transport_ingresses()


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
        config.load_kube_config()
    except TypeError:
        logging.error("Failed to load kubeconfig")
        exit(1)

    v1 = client.CoreV1Api()
    v1beta1 = client.ExtensionsV1beta1Api()
    custom_object_api = client.CustomObjectsApi()

    main()