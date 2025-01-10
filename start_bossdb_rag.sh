#!/bin/bash

# Make sure to modify paths to appropriate locations

cd /home/ubuntu/bossdb-rag-chatbot/

LOG_FILE="startup.log"

if [ -f .env ]; then
    echo "$(date): Loading environment variables..." >> $LOG_FILE
    set -a  # automatically export all variables
    source .env
    set +a
else
    echo "$(date): ERROR - Environment file not found!" >> $LOG_FILE
    exit 1
fi

echo "$(date): Starting services..." >> $LOG_FILE

echo "$(date): Starting MongoDB..." >> $LOG_FILE
sudo chmod 666 /var/run/docker.sock
docker start mongodb
if [ $? -ne 0 ]; then
    echo "$(date): Failed to start MongoDB" >> $LOG_FILE
    exit 1
fi

echo "$(date): Waiting for MongoDB to initialize..." >> $LOG_FILE
sleep 10

source venv/bin/activate

echo "$(date): Starting Chainlit server..." >> $LOG_FILE
chainlit run main.py --host "127.0.0.1" >> $LOG_FILE 2>&1
