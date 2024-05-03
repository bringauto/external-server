FROM bringauto/cpp-build-environment:latest AS cpp_builder

ARG MISSION_MODULE_VERSION=v1.2.5
ARG IO_MODULE_VERSION=v1.2.5

RUN mkdir /home/bringauto/modules
ARG CMLIB_REQUIRED_ENV_TMP_PATH=/home/bringauto/modules/cmlib_cache

RUN git clone https://github.com/bringauto/mission-module.git && \
    mkdir mission-module/_build && \
    cd mission-module/_build && \
    git checkout $MISSION_MODULE_VERSION && \
    cmake -DCMAKE_BUILD_TYPE=Release -DBRINGAUTO_INSTALL=ON -DCMAKE_INSTALL_PREFIX=/home/bringauto/modules/mission_module/ -DFLEET_PROTOCOL_BUILD_MODULE_GATEWAY=OFF .. && \
    make install

RUN git clone https://github.com/bringauto/io-module.git && \
    mkdir io-module/_build && \
    cd io-module/_build && \
    git checkout $IO_MODULE_VERSION && \
    cmake -DCMAKE_BUILD_TYPE=Release -DBRINGAUTO_INSTALL=ON -DCMAKE_INSTALL_PREFIX=/home/bringauto/modules/io_module/ -DFLEET_PROTOCOL_BUILD_MODULE_GATEWAY=OFF .. && \
    make install


FROM bringauto/python-environment:latest

# Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering.
ENV PYTHONUNBUFFERED=1

WORKDIR /home/bringauto/external_server

COPY --from=cpp_builder /home/bringauto/modules /home/bringauto/modules

COPY external_server /home/bringauto/external_server/external_server/
COPY config/for_docker.json /home/bringauto/config/for_docker.json
COPY --chown=bringauto:bringauto lib/ /home/bringauto/external_server/lib/
COPY external_server_main.py /home/bringauto/external_server/
COPY requirements.txt /home/bringauto/external_server/requirements.txt

RUN python3 -m pip install -r /home/bringauto/external_server/requirements.txt
