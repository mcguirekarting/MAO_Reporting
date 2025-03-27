# Dockerfile for custom Airflow image with additional dependencies
FROM apache/airflow:2.10.5

USER root

# Install system dependencies for PDF generation and matplotlib
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        python3-dev \
        python3-pip \
        libssl-dev \
        libffi-dev \
        libxml2-dev \
        libxslt1-dev \
        zlib1g-dev \
        libjpeg-dev \
        libpng-dev \
        libfreetype6-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Install Python dependencies
RUN pip install --no-cache-dir \
    pandas \
    matplotlib \
    reportlab \
    requests \
    psycopg2-binary

# Create directory structure for the project
RUN mkdir -p /opt/airflow/utils

# Set the PYTHONPATH to include our custom modules
ENV PYTHONPATH=/opt/airflow

# Copy project files
COPY --chown=airflow:root ./utils/ /opt/airflow/utils/