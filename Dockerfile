# syntax=docker/dockerfile:1

FROM bringauto/cpp-build-environment:latest AS mission_module_builder

ARG MISSION_MODULE_VERSION=update_packages

WORKDIR /home/bringauto/modules
ARG CMLIB_REQUIRED_ENV_TMP_PATH=/home/bringauto/modules/cmlib_cache

RUN mkdir /home/bringauto/modules/cmake && \
    wget -O CMakeLists.txt https://github.com/bringauto/mission-module/raw/"$MISSION_MODULE_VERSION"/CMakeLists.txt && \
    wget -O CMLibStorage.cmake https://github.com/bringauto/mission-module/raw/"$MISSION_MODULE_VERSION"/CMLibStorage.cmake && \
    wget -O cmake/Dependencies.cmake https://github.com/bringauto/mission-module/raw/"$MISSION_MODULE_VERSION"/cmake/Dependencies.cmake

WORKDIR /home/bringauto/modules/package_build
RUN cmake .. -DCMAKE_BUILD_TYPE=Release -DBRINGAUTO_GET_PACKAGES_ONLY=ON

# Build mission module
WORKDIR /home/bringauto
ADD --chown=bringauto:bringauto https://github.com/bringauto/mission-module.git#$MISSION_MODULE_VERSION mission-module
WORKDIR /home/bringauto/mission-module/_build
RUN cmake -DCMAKE_BUILD_TYPE=Release -DBRINGAUTO_INSTALL=ON -DCMAKE_INSTALL_PREFIX=/home/bringauto/modules/mission_module/ -DFLEET_PROTOCOL_BUILD_MODULE_GATEWAY=OFF .. && \
    make install


FROM bringauto/cpp-build-environment:latest AS io_module_builder

ARG IO_MODULE_VERSION=update_packages

WORKDIR /home/bringauto/modules
ARG CMLIB_REQUIRED_ENV_TMP_PATH=/home/bringauto/modules/cmlib_cache

RUN mkdir /home/bringauto/modules/cmake && \
    wget -O CMakeLists.txt https://github.com/bringauto/io-module/raw/"$IO_MODULE_VERSION"/CMakeLists.txt && \
    wget -O CMLibStorage.cmake https://github.com/bringauto/io-module/raw/"$IO_MODULE_VERSION"/CMLibStorage.cmake && \
    wget -O cmake/Dependencies.cmake https://github.com/bringauto/io-module/raw/"$IO_MODULE_VERSION"/cmake/Dependencies.cmake

WORKDIR /home/bringauto/modules/package_build
RUN cmake .. -DCMAKE_BUILD_TYPE=Release -DBRINGAUTO_GET_PACKAGES_ONLY=ON

# Build io module
WORKDIR /home/bringauto
ADD --chown=bringauto:bringauto https://github.com/bringauto/io-module.git#$IO_MODULE_VERSION io-module
WORKDIR /home/bringauto/io-module/_build
RUN cmake -DCMAKE_BUILD_TYPE=Release -DBRINGAUTO_INSTALL=ON -DCMAKE_INSTALL_PREFIX=/home/bringauto/modules/io_module/ -DFLEET_PROTOCOL_BUILD_MODULE_GATEWAY=OFF .. && \
    make install


FROM bringauto/python-environment:test-ubuntu-24-04

# Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering.
ENV PYTHONUNBUFFERED=1

WORKDIR /home/bringauto/external_server

# Copy project files into the docker image
COPY external_server /home/bringauto/external_server/external_server
COPY config/for_docker.json /home/bringauto/external_server/config/for_docker.json
COPY --chown=bringauto:bringauto lib/ /home/bringauto/external_server/lib/
COPY external_server_main.py /home/bringauto/external_server/
COPY requirements.txt /home/bringauto/external_server/requirements.txt
COPY log /home/bringauto/log
COPY config /home/bringauto/config

# Copy module libraries
COPY --from=mission_module_builder /home/bringauto/modules /home/bringauto/modules
COPY --from=io_module_builder /home/bringauto/modules /home/bringauto/modules

# Install Python dependencies while ignoring overriding system packages inside the container
RUN pip3 install -r /home/bringauto/external_server/requirements.txt --break-system-packages