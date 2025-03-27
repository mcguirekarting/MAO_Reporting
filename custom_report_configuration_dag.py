# custom_report_config_dag.py
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.http.operators.http import SimpleHttpOperator
from airflow.utils.dates import days_ago
from airflow.models import Variable
import json
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("report_config_service")

# Define default arguments for the DAG
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# Function to update report configurations
def update_report_configs(**kwargs):
    """
    Update report configurations from a configuration file or API
    """
    try:
        # In a real scenario, this might come from a database or external API
        report_configs = [
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
                "active": True
            },
            {
                "report_id": "exception_orders",
                "name": "Exception Orders Report",
                "description": "Orders with exceptions or errors",
                "schedule": "0 9 * * *",
                "query_parameters": {
                    "order_type": "ExceptionOrder",
                    "view_name": "orderdetails",
                    "sort_field": "OrderDate"
                },
                "email": {
                    "recipients": ["exceptions@example.com", "support@example.com"],
                    "subject": "Exception Orders Report - {date}",
                    "body": "Please find attached the exception orders report that requires attention."
                },
                "report_fields": [
                    "OrderId", "OrderDate", "CustomerName", "ExceptionCode", "ExceptionDesc", "PriorityLevel"
                ],
                "summary_fields": [
                    {"field": "ExceptionCode", "operation": "group", "label": "Exceptions by Type"},
                    {"field": "PriorityLevel", "operation": "group", "label": "Exceptions by Priority"}
                ],
                "active": True
            }
        ]
        
        # Store each configuration as a separate variable
        for config in report_configs:
            Variable.set(
                f"report_config_{config['report_id']}", 
                json.dumps(config),
                serialize_json=True
            )
            logger.info(f"Updated configuration for report: {config['report_id']}")
        
        # Store the list of available reports
        report_ids = [config["report_id"] for config in report_configs if config.get("active", True)]
        Variable.set("active_report_ids", json.dumps(report_ids), serialize_json=True)
        
        return report_ids
        
    except Exception as e:
        logger.error(f"Error updating report configurations: {str(e)}")
        raise

# Function to test API connectivity
def test_api_connectivity(**kwargs):
    """
    Test the connectivity to the order search API
    """
    api_base_url = Variable.get("order_api_base_url")
    test_endpoint = f"{api_base_url}/health"
    
    try:
        import requests
        response = requests.get(test_endpoint)
        
        if response.status_code == 200:
            logger.info("API connectivity test successful")
            return True
        else:
            logger.error(f"API connectivity test failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"API connectivity test exception: {str(e)}")
        return False

# Create the DAG
dag = DAG(
    'report_configuration_manager',
    default_args=default_args,
    description='Manage and update report configurations',
    schedule_interval='@daily',  # Run once per day
    start_date=days_ago(1),
    catchup=False,
    tags=['config', 'report'],
)

# Task 1: Update report configurations
task_update_configs = PythonOperator(
    task_id='update_report_configs',
    python_callable=update_report_configs,
    provide_context=True,
    dag=dag,
)

# Task 2: Test API connectivity
task_test_api = PythonOperator(
    task_id='test_api_connectivity',
    python_callable=test_api_connectivity,
    provide_context=True,
    dag=dag,
)

# Define task dependencies
task_update_configs >> task_test_api