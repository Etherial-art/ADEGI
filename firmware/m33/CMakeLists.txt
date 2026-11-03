cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(adegi_m33)

target_include_directories(app PRIVATE src)
target_sources(app PRIVATE
  src/main.c
  src/fsm.c
  src/drive.c
  src/protocol.c
  src/motor.c)

if(CONFIG_ADEGI_LINK_RPMSG)
  target_sources(app PRIVATE src/link_rpmsg.c)
else()
  target_sources(app PRIVATE src/link_stub.c)
endif()
