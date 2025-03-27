# Airflow Order Processing Report System

A robust system for automatic order data retrieval, analysis, and report generation using Apache Airflow.

## Overview

This repository contains Apache Airflow DAGs (Directed Acyclic Graphs) that automate the process of:

- Retrieving order data from an API
- Processing and analyzing the data
- Generating detailed PDF reports
- Distributing reports via email

The system is designed to be configurable, allowing for multiple report types and scheduling options.

## Repository Structure

```
.
├── __init__.py
├── dags/
│   ├── report_configuration_dag.py     # DAG for managing report configurations
│   └── order_search_report_dag.py      # DAG for generating order reports
└── utils/
    └── report_utils.py                 # Utility functions for report generation
```

## Features

- **Configurable Reports**: Define and manage multiple report configurations
- **Automated API Authentication**: Token-based authentication with automatic refresh
- **Data Visualization**: Includes summary tables and charts in the generated reports
- **Scheduled Execution**: Reports run on configurable schedules
- **Email Distribution**: Automatically send reports to configured recipients
- **Error Handling**: Comprehensive logging and error management

## DAGs

### Report Configuration Manager (`report_configuration_dag.py`)

This DAG handles the management of report configurations:

- Sets up API connections
- Updates report configurations from a configuration file or default settings
- Tests API connectivity
- Runs on a daily schedule

#### Tasks:
1. `setup_api_connection`: Configures API connection details
2. `update_report_configs`: Updates the report configuration settings
3. `test_api_connectivity`: Validates the API connection

### Order Search Report (`order_search_report_dag.py`)

This DAG generates order reports based on data retrieved from the API:

- Queries the order search API for a specific date range
- Processes the retrieved data
- Generates a formatted PDF report
- Emails the report to configured recipients
- Runs daily at 8:00 AM

#### Tasks:
1. `query_order_api`: Retrieves order data from the API
2. `generate_pdf_report`: Creates a PDF report with the data
3. `email_report`: Sends the report via email

## Utilities

The `report_utils.py` file contains utility functions used by the DAGs:

- `get_api_auth_token()`: Handles API authentication
- `query_order_api()`: Retrieves data from the order API
- `generate_pdf_report()`: Creates PDF reports with tables and charts

## Configuration

Reports are configured using JSON structures with the following keys:

```json
{
  "report_id": "daily_order_summary",
  "name": "Daily Order Summary",
  "description": "Summary of all orders processed in the last 24 hours",
  "schedule": "0 8 * * *",
  "query_parameters": {
    "order_type": "StandardOrder",
    "view_name": "orderdetails",
    "sort_field": "OrderDate"
  },
  "email": {
    "recipients": ["team@example.com", "managers@example.com"],
    "subject": "Daily Order Summary - {date}",
    "body": "Please find attached the daily order summary report."
  },
  "report_fields": [
    "OrderId", "OrderDate", "CustomerName", "Status", "TotalItems", "TotalValue"
  ],
  "summary_fields": [
    {"field": "TotalValue", "operation": "sum", "label": "Total Revenue"},
    {"field": "TotalItems", "operation": "sum", "label": "Total Items"},
    {"field": "OrderId", "operation": "count", "label": "Order Count"}
  ],
  "active": true
}
```

## Prerequisites

- Apache Airflow 2.0+
- Python 3.6+
- Required Python packages:
  - pandas
  - requests
  - reportlab
  - matplotlib

## Installation

1. Clone this repository into your Airflow DAGs folder:
   ```
   git clone https://github.com/yourusername/airflow-order-reports.git
   ```

2. Install required dependencies:
   ```
   pip install pandas requests reportlab matplotlib
   ```

3. Configure Airflow variables:
   - `order_api_base_url`: Base URL for the order API
   - `report_recipients`: Email recipients for reports
   - `api_client_id`: API client ID for authentication
   - `api_client_secret`: API client secret for authentication

## Usage

Once installed and configured, the DAGs will run according to their schedules. You can also trigger them manually from the Airflow UI.

### Custom Report Configurations

To create a custom report configuration:

1. Create a JSON file with your report configuration
2. Set the `report_config_path` Airflow variable to point to your configuration file
3. The Report Configuration Manager DAG will load your configuration on its next run

## Development and Extension

To add new report types:

1. Define a new report configuration with the necessary parameters
2. Add any specific processing logic to the appropriate functions in `report_utils.py`
3. Test your changes before deploying to production

## Logging

The system uses Airflow's logging capabilities and additional custom logging to track execution and any issues that arise. Logs can be viewed in the Airflow UI.

## License

[Your license information here]

## Contributing

[Your contribution guidelines here]
