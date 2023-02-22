CMAKE_MINIMUM_REQUIRED(VERSION 3.21)
PROJECT(car_accessory_api)

SET(CMAKE_CXX_STANDARD 20)

#FIND_PACKAGE(CMLIB
#        COMPONENTS CMDEF CMUTIL
#        REQUIRED
#        )

FIND_PACKAGE(Protobuf 3.17.3 REQUIRED)
ADD_LIBRARY(protobuf_lib STATIC
        ${CMAKE_CURRENT_SOURCE_DIR}/proto/CarAccessoryModule.pb.cc
        ${CMAKE_CURRENT_SOURCE_DIR}/proto/CarAccessoryModule.pb.h)
TARGET_LINK_LIBRARIES(protobuf_lib PUBLIC protobuf::libprotobuf)

FILE(GLOB_RECURSE source_files "${CMAKE_CURRENT_SOURCE_DIR}/source/*")
ADD_LIBRARY(car_accessory_api SHARED ${source_files})
TARGET_INCLUDE_DIRECTORIES(car_accessory_api PUBLIC "proto/" "include/")

ADD_EXECUTABLE(test_api main.cpp)
TARGET_LINK_LIBRARIES(test_api PUBLIC car_accessory_api protobuf_lib)

#INSTALL(TARGETS car_accessory_api
#        DESTINATION lib/)