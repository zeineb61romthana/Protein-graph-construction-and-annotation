# Use a Python + Java base image
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
    && echo "deb http://deb.debian.org/debian bullseye main" > /etc/apt/sources.list.d/bullseye.list \
    && apt-get update \
    && apt-get install -y openjdk-17-jdk \
    && rm -rf /var/lib/apt/lists/*

# Install Neo4j
RUN wget -O - https://deb.nodesource.com/setup_18.x | bash - \
    && wget -O - https://debian.neo4j.com/neotechnology.gpg.key | apt-key add - \
    && echo 'deb https://debian.neo4j.com stable 4.4' > /etc/apt/sources.list.d/neo4j.list \
    && apt-get update && apt-get install -y neo4j

# Copy project files
COPY ./app /app

# Set working directory
WORKDIR /app

# Install Python dependencies
RUN pip install pyspark==3.3.0 neo4j==5.8.1 flask==2.3.2 pandas==1.5.3

# Configure Neo4j
RUN echo "dbms.connector.bolt.listen_address=0.0.0.0" >> /etc/neo4j/neo4j.conf \
    && echo "dbms.connector.http.listen_address=0.0.0.0" >> /etc/neo4j/neo4j.conf

# Expose ports
EXPOSE 5000 7474 7687

# Start Neo4j and Flask app
CMD service neo4j start && sleep 15 && python app.py