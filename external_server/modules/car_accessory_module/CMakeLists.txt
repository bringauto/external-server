CMAKE_MINIMUM_REQUIRED(VERSION 3.21)
PROJECT(car_accessory_api)

SET(CMAKE_CXX_STANDARD 17)

FILE(GLOB_RECURSE source_files "source/*")
ADD_LIBRARY(car_accessory_api SHARED ${source_files})
TARGET_INCLUDE_DIRECTORIES(car_accessory_api PUBLIC "proto/" "include/")

ADD_EXECUTABLE(test_api main.cpp ${source_files})
TARGET_LINK_LIBRARIES(test_api PUBLIC car_accessory_api)

#INSTALL(TARGETS car_accessory_api
#        DESTINATION lib/)