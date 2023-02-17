CMAKE_MINIMUM_REQUIRED(VERSION 3.21)
PROJECT(car_accessory_api)

SET(CMAKE_CXX_STANDARD 11)

FILE(GLOB_RECURSE source_files "source/*")
ADD_LIBRARY(car_accessory_api SHARED ${source_files})
TARGET_INCLUDE_DIRECTORIES(car_accessory_api PUBLIC "${PROTO_DIR}" "include/")

INSTALL(TARGETS car_accessory_api
        DESTINATION lib)