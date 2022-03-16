#!/usr/bin/env python
# coding: utf-8

import argparse
import logging
import time
import os
import threading

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
    -s, --service' : NGINX Ingress Controller service name
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
    and call add_port_entries() to patch (replace) corresponding ConfigMaps 
    and to patch NGINX Ingress Controller Service.
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

    return add_port_entries()


""" add_port_entries()
    Patch (replace) TCP and UDP ConfigMaps by using exposed services' list
    (`nginx_transport_ingresses_lastrev`)
"""
def add_port_entries():
    global v1, NGINX_NAMESPACE, TCP_CONFIGMAP, UDP_CONFIGMAP, NGINX_SERVICE, nginx_transport_ingresses_lastrev

    tcp_data_patch = {}
    udp_data_patch = {}

    service_data_patch = [
        {
            'name': 'http',
            'port': 80,
            'targetPort': 80,
            'protocol': 'TCP'
        },
        {
            'name': 'https',
            'port': 443,
            'targetPort': 443,
            'protocol': 'TCP'
        }
    ]

    # Format ConfigMap and Service data to be patched
    for nginx_transport_ingress, exposed_services in nginx_transport_ingresses_lastrev.items():
        for external_port, exposed_service in exposed_services.items():
            service_data_patch.append(exposed_service.format_service())
            if exposed_service.get_protocol() == "tcp":
                tcp_data_patch[external_port] = exposed_service.format_configmap()
            elif exposed_service.get_protocol() == "udp":
                udp_data_patch[external_port] = exposed_service.format_configmap()

    # Patch current TCP and UDP ConfigMaps
    try:
        # TCP
        CONFIGMAP = TCP_CONFIGMAP
        configmap_patch = client.V1ConfigMap()
        configmap_patch.metadata = client.V1ObjectMeta(name=CONFIGMAP, namespace=NGINX_NAMESPACE)
        configmap_patch.metadata.labels = {"app.kubernetes.io/managed-by": "nginx-transport-controller"}
        configmap_patch.data = tcp_data_patch
        v1.replace_namespaced_config_map(name=CONFIGMAP, namespace=NGINX_NAMESPACE, body=configmap_patch)
        
        # UDP
        CONFIGMAP = UDP_CONFIGMAP
        configmap_patch = client.V1ConfigMap()
        configmap_patch.metadata = client.V1ObjectMeta(name=CONFIGMAP, namespace=NGINX_NAMESPACE)
        configmap_patch.metadata.labels = {"app.kubernetes.io/managed-by": "nginx-transport-controller"}
        configmap_patch.data = udp_data_patch
        v1.replace_namespaced_config_map(name=CONFIGMAP, namespace=NGINX_NAMESPACE, body=configmap_patch)
    except ApiException as e:
        logging.error("Failed to patch ConfigMap %s/%s: %s" % (NGINX_NAMESPACE, CONFIGMAP, e.reason))
        return -1

    # Patch current NGINX Ingress Controller Service
    try:
        service_patch = v1.read_namespaced_service(name=NGINX_SERVICE, namespace=NGINX_NAMESPACE)
        service_patch.spec.ports = service_data_patch
        v1.patch_namespaced_service(name=NGINX_SERVICE, namespace=NGINX_NAMESPACE, body=service_patch)
    except ApiException as e:
        logging.error("Failed to patch Service %s/%s: %s" % (NGINX_NAMESPACE, NGINX_SERVICE, e.reason))
        return -1

    return 0


def watch_nginx_transport_ingresses():
    global custom_object_api
    event_watcher1 = watch.Watch()

    logging.info("Reading NginxTransportIngress events...")
    for event in event_watcher1.stream(custom_object_api.list_cluster_custom_object, group=NGINXTRANSPORTINGRESS_CRD['group'], version=NGINXTRANSPORTINGRESS_CRD['version'], plural=NGINXTRANSPORTINGRESS_CRD['plural'], watch=True, timeout_seconds=900):
        logging.info("Processing event [%s] for %s/%s" % (event['type'], event['object']['metadata']['namespace'], event['object']['metadata']['name']))
        process_nginx_transport_ingresses()


def watch_configmaps():
    global v1, NGINX_NAMESPACE, TCP_CONFIGMAP, UDP_CONFIGMAP
    event_watcher = watch.Watch()

    logging.info("Reading ConfigMap events...")
    for event in event_watcher.stream(v1.list_namespaced_config_map, namespace=NGINX_NAMESPACE, watch=True, timeout_seconds=900):
        if event['object'].metadata.name in (TCP_CONFIGMAP, UDP_CONFIGMAP):
            if event['object'].metadata.labels != None and "app.kubernetes.io/managed-by" in event['object'].metadata.labels:
                    if event['object'].metadata.labels['app.kubernetes.io/managed-by'] == 'Helm':
                        logging.info("ConfigMap %s/%s has been reset, recomputing..." % (event['object'].metadata.namespace, event['object'].metadata.name))
                        process_nginx_transport_ingresses()


def main():
    global custom_object_api, nginx_transport_ingresses_lastrev

    nginx_transport_ingresses_lastrev = {}

    threads = {
        'watch_configmaps': watch_configmaps,
        'watch_nginx_transport_ingresses': watch_nginx_transport_ingresses
    }

    # Pre-processing
    logging.info("Get initial NginxTransportIngresses...")
    threading.Thread(target=watch_configmaps, name="watch_configmaps").start()
    threading.Thread(target=watch_nginx_transport_ingresses, name="watch_nginx_transport_ingresses").start()

    # Watch loop
    while len(threading.enumerate()) > 1:
        for thread_name in threads.keys():
            if thread_name not in [thread.name for thread in threading.enumerate()]:
                threading.Thread(target=threads[thread_name], name=thread_name).start()
        time.sleep(10)


if __name__ == '__main__':

    # Parse arguments
    parser = argparse.ArgumentParser(description='Move specified IP to current node service')
    parser.add_argument('-s', '--service', help='<Required> NGINX Ingress Controller service name', required=True)
    parser.add_argument('-t', '--tcp-services-configmap', help='<Required> NGINX Ingress Controller ConfigMap name for TCP services (--tcp-services-configmap NGINX Ingress Controller parameters)', required=True)
    parser.add_argument('-u', '--udp-services-configmap', help='<Required> NGINX Ingress Controller ConfigMap name for UDP services (--udp-services-configmap NGINX Ingress Controller parameters)', required=True)
    args = parser.parse_args()

    with open(os.path.join("/var/run/secrets/kubernetes.io/serviceaccount", "namespace")) as infile:
        NGINX_NAMESPACE = infile.read().rstrip("\n")
    NGINX_SERVICE = args.service
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
    except ApiException as e:
        logging.error("Failed to load kubeconfig: %s" % (e.reason))
        exit(-1)

    v1 = client.CoreV1Api()
    v1beta1 = client.ExtensionsV1beta1Api()
    custom_object_api = client.CustomObjectsApi()

    for CONFIGMAP in (TCP_CONFIGMAP, UDP_CONFIGMAP):
        try:
            v1.read_namespaced_config_map(name=CONFIGMAP, namespace=NGINX_NAMESPACE)
        except ApiException as e:
            logging.error("Failed to read ConfigMap %s/%s: %s" % (NGINX_NAMESPACE, CONFIGMAP, e.reason))
            exit(-1)

    main()