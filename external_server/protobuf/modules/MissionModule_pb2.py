# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: modules/MissionModule.proto
"""Generated protocol buffer code."""
from google.protobuf.internal import builder as _builder
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x1bmodules/MissionModule.proto\x12\rMissionModule\"\xd5\x02\n\x0e\x41utonomyStatus\x12:\n\ttelemetry\x18\x01 \x01(\x0b\x32\'.MissionModule.AutonomyStatus.Telemetry\x12\x32\n\x05state\x18\x02 \x01(\x0e\x32#.MissionModule.AutonomyStatus.State\x12-\n\x08nextStop\x18\x03 \x01(\x0b\x32\x16.MissionModule.StationH\x00\x88\x01\x01\x1aS\n\tTelemetry\x12\r\n\x05speed\x18\x01 \x01(\x01\x12\x0c\n\x04\x66uel\x18\x02 \x01(\x01\x12)\n\x08position\x18\x03 \x01(\x0b\x32\x17.MissionModule.Position\"B\n\x05State\x12\x08\n\x04IDLE\x10\x00\x12\t\n\x05\x44RIVE\x10\x01\x12\x0b\n\x07IN_STOP\x10\x02\x12\x0c\n\x08OBSTACLE\x10\x03\x12\t\n\x05\x45RROR\x10\x04\x42\x0b\n\t_nextStop\"\xac\x01\n\x0f\x41utonomyCommand\x12%\n\x05stops\x18\x01 \x03(\x0b\x32\x16.MissionModule.Station\x12\r\n\x05route\x18\x02 \x01(\t\x12\x35\n\x06\x61\x63tion\x18\x03 \x01(\x0e\x32%.MissionModule.AutonomyCommand.Action\",\n\x06\x41\x63tion\x12\r\n\tNO_ACTION\x10\x00\x12\x08\n\x04STOP\x10\x01\x12\t\n\x05START\x10\x02\">\n\rAutonomyError\x12-\n\rfinishedStops\x18\x01 \x03(\x0b\x32\x16.MissionModule.Station\"B\n\x07Station\x12\x0c\n\x04name\x18\x01 \x01(\t\x12)\n\x08position\x18\x02 \x01(\x0b\x32\x17.MissionModule.Position\"A\n\x08Position\x12\x10\n\x08latitude\x18\x01 \x01(\x01\x12\x11\n\tlongitude\x18\x02 \x01(\x01\x12\x10\n\x08\x61ltitude\x18\x03 \x01(\x01\x42>Z!../internal/pkg/ba_proto;ba_proto\xaa\x02\x18Google.Protobuf.ba_protob\x06proto3')

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'modules.MissionModule_pb2', globals())
if _descriptor._USE_C_DESCRIPTORS == False:

  DESCRIPTOR._options = None
  DESCRIPTOR._serialized_options = b'Z!../internal/pkg/ba_proto;ba_proto\252\002\030Google.Protobuf.ba_proto'
  _AUTONOMYSTATUS._serialized_start=47
  _AUTONOMYSTATUS._serialized_end=388
  _AUTONOMYSTATUS_TELEMETRY._serialized_start=224
  _AUTONOMYSTATUS_TELEMETRY._serialized_end=307
  _AUTONOMYSTATUS_STATE._serialized_start=309
  _AUTONOMYSTATUS_STATE._serialized_end=375
  _AUTONOMYCOMMAND._serialized_start=391
  _AUTONOMYCOMMAND._serialized_end=563
  _AUTONOMYCOMMAND_ACTION._serialized_start=519
  _AUTONOMYCOMMAND_ACTION._serialized_end=563
  _AUTONOMYERROR._serialized_start=565
  _AUTONOMYERROR._serialized_end=627
  _STATION._serialized_start=629
  _STATION._serialized_end=695
  _POSITION._serialized_start=697
  _POSITION._serialized_end=762
# @@protoc_insertion_point(module_scope)