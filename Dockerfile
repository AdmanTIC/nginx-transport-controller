FROM python:3.8-slim-buster

WORKDIR /opt

# OPERATOR
COPY src /opt
RUN pip install -r /opt/requirements.txt

# RUN OPERATOR
ENTRYPOINT ["/opt/nginx_transport_controller.py"]
CMD []
