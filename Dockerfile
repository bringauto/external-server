FROM eu.gcr.io/bringauto-infrastructure/teamcity-build-images/ubuntu22.04:latest

# Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering.
ENV PYTHONUNBUFFERED=1

WORKDIR /home/bringauto/external_server

COPY external_server /home/bringauto/external_server/external_server
COPY config/for_docker.json /home/bringauto/config/for_docker.json
COPY --chown=bringauto:bringauto lib /home/bringauto/external_server/lib
COPY main.py /home/bringauto/external_server
COPY requirements.txt /home/bringauto/external_server/requirements.txt

RUN sudo apt update -y && sudo apt-get install -y libcpprest-dev

RUN python3 -m pip install -r /home/bringauto/external_server/requirements.txt && \
    mkdir -p /home/bringauto/modules

# Install IO module
WORKDIR /home/bringauto/external_server/lib/io-module
RUN mkdir _build && cd _build && \
    cmake -DCMLIB_DIR=/cmakelib .. && \
    make -j 8 && \
    mv ./libio_external_server.so /home/bringauto/modules/libio_external_server.so && \
    cd .. && rm -rf _build

# Install example module
WORKDIR /home/bringauto/external_server/lib/example-module
RUN mkdir _build && cd _build && \
    cmake -DCMLIB_DIR=/cmakelib .. && \
    make -j 8 && \
    mv ./libexample_external_server.so /home/bringauto/modules/libexample_external_server.so && \
    cd .. && rm -rf _build

# Install mission module
WORKDIR /home/bringauto/external_server/lib/mission-module
RUN mkdir _build && cd _build && \
    cmake -DCMLIB_DIR=/cmakelib .. && \
    make -j 8 && \
    mv ./libmission_external_server.so /home/bringauto/modules/libmission_external_server.so && \
    cd .. && rm -rf _build

WORKDIR /home/bringauto/external_server
