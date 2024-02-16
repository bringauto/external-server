# maximum number of messages in outgoing queue
# value reasoning: external server can handle cca 20 devices
MAX_QUEUED_MESSAGES = 20

# value reasoning: keepalive is half of the default timeout in Fleet protocol (30 s)
KEEPALIVE = 15

# Quality of Service used by Mqtt client
QOS = 1