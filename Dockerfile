FROM bringauto/cpp-build-environment:latest AS cpp_builder

COPY --chown=bringauto:bringauto lib /home/bringauto/external_server/lib

RUN sudo apt update -y && sudo apt-get install -y libcpprest-dev
RUN mkdir /home/bringauto/modules
ARG export CMLIB_REQUIRED_ENV_TMP_PATH=/home/bringauto/modules/cmlib_cache

# Install IO module
WORKDIR /home/bringauto/external_server/lib/io-module
RUN mkdir _build && cd _build && \
    cmake .. && \
    make -j 8 && \
    mv ./libio_external_server.so /home/bringauto/modules/libio_external_server.so

# Install example module
WORKDIR /home/bringauto/external_server/lib/example-module
RUN mkdir _build && cd _build && \
    cmake .. && \
    make -j 8 && \
    mv ./libexample_external_server.so /home/bringauto/modules/libexample_external_server.so
# Install mission module
WORKDIR /home/bringauto/external_server/lib/mission-module
RUN mkdir _build && cd _build && \
    cmake .. && \
    make -j 8 && \
    mv ./libmission_external_server.so /home/bringauto/modules/libmission_external_server.so

FROM bringauto/python-environment:latest

# Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering.
ENV PYTHONUNBUFFERED=1

WORKDIR /home/bringauto/external_server

RUN sudo apt update -y && sudo apt-get install -y libcpprest-dev

COPY --from=cpp_builder /home/bringauto/modules /home/bringauto/modules

COPY external_server /home/bringauto/external_server/external_server
COPY config/for_docker.json /home/bringauto/config/for_docker.json
COPY --chown=bringauto:bringauto lib /home/bringauto/external_server/lib
COPY main.py /home/bringauto/external_server
COPY requirements.txt /home/bringauto/external_server/requirements.txt

RUN python3 -m pip install -r /home/bringauto/external_server/requirements.txt
