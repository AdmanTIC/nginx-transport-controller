#VERY LIGHTER THAN python:3.7 (python:3.7-alpine non fonctionnel)
FROM python:3.8-slim-buster

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

# RUN OPERATOR
ENTRYPOINT ["/opt/nginx_transport_controller.py"]
# CMD [""]
