FROM python:3.11.9-bookworm

WORKDIR /opt/relabeler

COPY ./src/ /opt/relabeler/
COPY ./requirements.txt /opt/relabeler/

RUN apt-get update \
    && apt-get upgrade -y \
    && pip install -r requirements.txt

ENV PYTHONPATH /opt/relabeler

ENTRYPOINT [ "python", "main.py" ]
