FROM python:3.11.9-slim-bookworm

WORKDIR /opt/namespace-relabeler

COPY ./src/ /opt/namespace-relabeler/
COPY ./requirements_prod.txt /opt/namespace-relabeler/

RUN apt-get update \
    && apt-get upgrade -y \
    && pip install -r requirements_prod.txt

ENV PYTHONPATH /opt/namespace-relabeler

ENTRYPOINT [ "python", "main.py" ]
