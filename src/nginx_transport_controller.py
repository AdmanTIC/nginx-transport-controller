#!/usr/bin/env python
# coding: utf-8

import argparse
import logging
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

from nginx_transport_controller.utils.ExposedService import ExposedService
import nginx_transport_controller.utils.kube_config as KubeConfig

from nginx_transport_controller.configuration import (
    SERVICEEXPOSER_CRD
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


def update_service_exposer_status(name, ns, status):
    global custom_object_api

    patch_data = custom_object_api.get_namespaced_custom_object(group=SERVICEEXPOSER_CRD['group'], version=SERVICEEXPOSER_CRD['version'], plural=SERVICEEXPOSER_CRD['plural'], namespace=ns, name=name)
    patch_data['status'] = {}
    patch_data['status']['configStatus'] = status
    custom_object_api.patch_namespaced_custom_object(group=SERVICEEXPOSER_CRD['group'], version=SERVICEEXPOSER_CRD['version'], plural=SERVICEEXPOSER_CRD['plural'], namespace=ns, name=name, body=patch_data)


def process_service_exposers():
    global custom_object_api, service_exposers_lastrev
    service_exposers_list = custom_object_api.list_cluster_custom_object(group=SERVICEEXPOSER_CRD['group'], version=SERVICEEXPOSER_CRD['version'], plural=SERVICEEXPOSER_CRD['plural'])
    
    for service_exposer in service_exposers_list['items']:
        
        if "%s_%s" % (service_exposer['metadata']['namespace'], service_exposer['metadata']['name']) in service_exposers_lastrev:
            for port, exposed_service in service_exposers_lastrev["%s_%s" % (service_exposer['metadata']['namespace'], service_exposer['metadata']['name'])].items():
                delete_port_entry(exposed_service)
        service_exposers_lastrev["%s_%s" % (service_exposer['metadata']['namespace'], service_exposer['metadata']['name'])] = {}
        for exposed_service in service_exposer['spec']['exposedServices']:
            current_exposed_service = ExposedService(
                name=exposed_service['targetServiceName'],
                ns=service_exposer['metadata']['namespace'],
                external_port=exposed_service['externalPort'],
                internal_port=exposed_service['internalPort'],
                protocol=exposed_service['protocol'],
                resource_version=service_exposer['metadata']['namespace']
            )

            add_port_entry(current_exposed_service)
            service_exposers_lastrev["%s_%s" % (service_exposer['metadata']['namespace'], service_exposer['metadata']['name'])][exposed_service['externalPort']] = current_exposed_service

        # Added
        update_service_exposer_status(service_exposer['metadata']['name'], service_exposer['metadata']['namespace'], "Added")


def delete_port_entry(deleted_service):
    global v1, NGINX_NAMESPACE, TCP_CONFIGMAP, UDP_CONFIGMAP, service_exposers_lastrev

    if deleted_service.get_protocol() == "tcp":
        CONFIGMAP = TCP_CONFIGMAP
    elif deleted_service.get_protocol() == "udp":
        CONFIGMAP = UDP_CONFIGMAP

    try:
        current_configmap = v1.read_namespaced_config_map(name=CONFIGMAP, namespace=NGINX_NAMESPACE)
        if current_configmap.data != None and str(deleted_service.get_external_port()) in current_configmap.data:
            del current_configmap.data[str(deleted_service.get_external_port())]    

        new_configmap = client.V1ConfigMap()
        new_configmap.metadata = client.V1ObjectMeta(name=CONFIGMAP, namespace=NGINX_NAMESPACE)
        new_configmap.data = current_configmap.data

        v1.delete_namespaced_config_map(name=CONFIGMAP, namespace=NGINX_NAMESPACE)
        v1.create_namespaced_config_map(namespace=NGINX_NAMESPACE, body=new_configmap)
    except ApiException as e:
        logging.error("Failed to patch ConfigMap %s/%s: %s" % (NGINX_NAMESPACE, CONFIGMAP, e))
        exit(1)


def add_port_entry(added_service):
    global v1, NGINX_NAMESPACE, TCP_CONFIGMAP, UDP_CONFIGMAP, service_exposers_lastrev

    if added_service.get_protocol() == "tcp":
        CONFIGMAP = TCP_CONFIGMAP
    elif added_service.get_protocol() == "udp":
        CONFIGMAP = UDP_CONFIGMAP

    data_patch = {}
    try:
        data_patch[added_service.get_external_port()] = added_service.format()
        patch = client.V1ConfigMap()
        patch.metadata = client.V1ObjectMeta(name=CONFIGMAP, namespace=NGINX_NAMESPACE)
        patch.data = data_patch
        v1.patch_namespaced_config_map(name=CONFIGMAP, namespace=NGINX_NAMESPACE, body=patch)
    except ApiException as e:
        logging.error("Failed to patch ConfigMap %s/%s: %s" % (NGINX_NAMESPACE, CONFIGMAP, e))
        exit(1)


def main():
    global custom_object_api, service_exposers_lastrev

    service_exposers_lastrev = {}
    service_exposers_list = custom_object_api.list_cluster_custom_object(group=SERVICEEXPOSER_CRD['group'], version=SERVICEEXPOSER_CRD['version'], plural=SERVICEEXPOSER_CRD['plural'])

    # Pre-processing
    logging.info("Get initial ServiceExposers...")
    
    # Set initial ServiceExposer as `Pending` status
    for service_exposer in service_exposers_list['items']:
        # Pending
        update_service_exposer_status(service_exposer['metadata']['name'], service_exposer['metadata']['namespace'], "Pending")

    process_service_exposers()


    logging.info("Entering watch loop...")
    event_watcher = watch.Watch()
    while True:
        for event in event_watcher.stream(custom_object_api.list_cluster_custom_object, group="admantic.fr", version="v1", plural="serviceexposers", watch=True, timeout_seconds=900):
            if event['type'] == 'ADDED' or event['type'] == 'MODIFIED':
                for exposed_service in event['object']['spec']['exposedServices']:
                    current_ext_port = exposed_service['externalPort']
                    process_service_exposers()
                    logging.info("Processing event [%s] for %s" % (event['type'], service_exposers_lastrev["%s_%s" % (event['object']['metadata']['namespace'], event['object']['metadata']['name'])][current_ext_port].display()))
            elif event['type'] == 'DELETED':
                for exposed_service in event['object']['spec']['exposedServices']:
                    current_ext_port = exposed_service['externalPort']
                    logging.info("Processing event [%s] for %s" % (event['type'], service_exposers_lastrev["%s_%s" % (event['object']['metadata']['namespace'], event['object']['metadata']['name'])][current_ext_port].display()))                    
                    delete_port_entry(service_exposers_lastrev["%s_%s" % (event['object']['metadata']['namespace'], event['object']['metadata']['name'])][current_ext_port])
                    process_service_exposers()


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