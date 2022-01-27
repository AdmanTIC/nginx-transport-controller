""" NginxTransportIngress class
    Represents service to be exposed by NGINX Ingress Controller.
    The services data is fed by retrieving informations in 
    NginxTransportIngress custom resources.

    Parameters :
    - name: Service name
    - ns: Service namespace
    - external_port: Port exposed by NGINX Ingress Controller
    - internal_port: Port on which trafic is forwarded to inside the cluster
    - protocol: Transport protocol (TCP or UDP)
    - resource_version: NginxTransportIngress resource version
"""

class NginxTransportIngress:
    def __init__(self, name, ns, external_port, internal_port, protocol, resource_version):
        self.name = name
        self.ns = ns
        self.external_port = external_port
        self.internal_port = internal_port
        self.protocol = protocol
        self.resource_version = resource_version

    def display(self):
        return ("%s/%s: %s/%s:%s" % (
            self.external_port,
            self.protocol.upper(),
            self.ns,
            self.name,
            self.internal_port
            )
        )
    
    def get_name(self):
        return self.name

    def get_ns(self):
        return self.ns

    def get_external_port(self):
        return self.external_port

    def get_internal_port(self):
        return self.internal_port

    def get_protocol(self):
        return self.protocol.lower()

    def get_resource_version(self):
        return self.resource_version

    """
        Format data to fit in ConfigMap 
        (cf. https://kubernetes.github.io/ingress-nginx/user-guide/exposing-tcp-udp-services/)
    """
    def format_configmap(self):
        return "%s/%s:%s" % (self.ns, self.name, self.internal_port)

    def format_service(self):
        return {
            'name' : "nginx-%s-%s" % (self.external_port, self.internal_port),
            'port': self.external_port,
            'target_port': self.internal_port,
            'protocol': self.protocol
        }