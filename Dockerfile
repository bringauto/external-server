FROM bringauto/cpp-build-environment:latest AS mission_module_builder

ARG MISSION_MODULE_VERSION=v1.2.7

RUN mkdir /home/bringauto/modules
ARG CMLIB_REQUIRED_ENV_TMP_PATH=/home/bringauto/modules/cmlib_cache

# Build mission module
ADD --chown=bringauto:bringauto https://github.com/bringauto/mission-module.git#$MISSION_MODULE_VERSION mission-module
RUN mkdir mission-module/_build && \
    cd mission-module/_build && \
    cmake -DCMAKE_BUILD_TYPE=Release -DBRINGAUTO_INSTALL=ON -DCMAKE_INSTALL_PREFIX=/home/bringauto/modules/mission_module/ -DFLEET_PROTOCOL_BUILD_MODULE_GATEWAY=OFF .. && \
    make install

FROM bringauto/cpp-build-environment:latest AS io_module_builder

ARG IO_MODULE_VERSION=v1.2.7

RUN mkdir /home/bringauto/modules
ARG CMLIB_REQUIRED_ENV_TMP_PATH=/home/bringauto/modules/cmlib_cache

# Build io module
ADD --chown=bringauto:bringauto https://github.com/bringauto/io-module.git#$IO_MODULE_VERSION io-module
RUN mkdir io-module/_build && \
    cd io-module/_build && \
    cmake -DCMAKE_BUILD_TYPE=Release -DBRINGAUTO_INSTALL=ON -DCMAKE_INSTALL_PREFIX=/home/bringauto/modules/io_module/ -DFLEET_PROTOCOL_BUILD_MODULE_GATEWAY=OFF .. && \
    make install


FROM bringauto/python-environment:latest

# Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering.
ENV PYTHONUNBUFFERED=1

WORKDIR /home/bringauto/external_server

# Install python dependencies
COPY requirements.txt /home/bringauto/external_server/requirements.txt
RUN python3 -m pip install -r /home/bringauto/external_server/requirements.txt

# Copy project files into the docker image
COPY external_server /home/bringauto/external_server/external_server/
COPY config/for_docker.json /home/bringauto/config/for_docker.json
COPY --chown=bringauto:bringauto lib/ /home/bringauto/external_server/lib/
COPY external_server_main.py /home/bringauto/external_server/

# Copy module libraries
COPY --from=mission_module_builder /home/bringauto/modules /home/bringauto/modules
COPY --from=io_module_builder /home/bringauto/modules /home/bringauto/modules
