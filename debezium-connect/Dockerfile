FROM confluentinc/cp-kafka-connect:8.0.7

USER root
# Latest 3.x on Confluent Hub (upstream Debezium is newer but the Hub lags it).
RUN confluent-hub install --no-prompt debezium/debezium-connector-postgresql:3.2.6
