# improved_report_config_dag.py
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.http.operators.http import SimpleHttpOperator
from airflow.utils.dates import days_ago
from airflow.models import Variable
from airflow.hooks.base import BaseHook
import json
import logging
import os
import sys

# Add project root to path for local imports
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from utils.report_utils import get_api_auth_token

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
        # Check if we should load from a file instead of hardcoded configs
        config_path = Variable.get("report_config_path", default_var=None)
        
        if config_path and os.path.exists(config_path):
            logger.info(f"Loading report configurations from file: {config_path}")
            with open(config_path, 'r') as f:
                report_configs = json.load(f)
        else:
            # In a real scenario, this might come from a database or external API
            # For now, we'll use the hardcoded example configs
            logger.info("Using default hardcoded report configurations")
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
        
        # Validate configurations
        validated_configs = []
        for config in report_configs:
            # Check required fields
            required_fields = ["report_id", "name", "query_parameters"]
            if all(field in config for field in required_fields):
                validated_configs.append(config)
            else:
                missing = [field for field in required_fields if field not in config]
                logger.warning(f"Skipping invalid config missing fields: {missing}")
        
        # Store each configuration as a separate variable
        for config in validated_configs:
            Variable.set(
                f"report_config_{config['report_id']}", 
                json.dumps(config),
                serialize_json=True
            )
            logger.info(f"Updated configuration for report: {config['report_id']}")
        
        # Store the list of available reports
        report_ids = [config["report_id"] for config in validated_configs if config.get("active", True)]
        Variable.set("active_report_ids", json.dumps(report_ids), serialize_json=True)
        
        # Log summary
        logger.info(f"Configuration update complete. {len(validated_configs)} configurations processed, {len(report_ids)} active.")
        return report_ids
        
    except Exception as e:
        logger.error(f"Error updating report configurations: {str(e)}")
        raise

# Function to set up API connection
def setup_api_connection(**kwargs):
    """
    Set up the API connection parameters and get an auth token
    """
    try:
        # Check if connection exists in Airflow connections
        conn_id = "order_api"
        try:
            conn = BaseHook.get_connection(conn_id)
            logger.info(f"Using existing connection: {conn_id}")
            
            # Set Variables from connection
            api_base_url = conn.host
            if api_base_url.startswith(('http://', 'https://')):
                Variable.set("order_api_base_url", api_base_url)
            else:
                Variable.set("order_api_base_url", f"https://{api_base_url}")
                
            # Store credentials
            Variable.set("api_client_id", conn.login)
            Variable.set("api_client_secret", conn.password)
            
        except:
            logger.warning(f"Connection {conn_id} not found, using environment variables or defaults")
            
            # Use environment variables or defaults
            api_base_url = os.environ.get("ORDER_API_BASE_URL", "https://api.example.com")
            Variable.set("order_api_base_url", api_base_url)
            
            # Use environment variables for credentials
            Variable.set("api_client_id", os.environ.get("ORDER_API_CLIENT_ID", "default_client_id"))
            Variable.set("api_client_secret", os.environ.get("ORDER_API_CLIENT_SECRET", "default_client_secret"))
        
        # Get an initial auth token
        token = get_api_auth_token()
        logger.info("Successfully acquired API authentication token")
        
        # Set default report recipients if not set
        if not Variable.get("default_report_recipients", default_var=None):
            Variable.set("default_report_recipients", "admin@example.com")
        
        return True
        
    except Exception as e:
        logger.error(f"Error setting up API connection: {str(e)}")
        return False

# Function to test API connectivity
def test_api_connectivity(**kwargs):
    """
    Test the connectivity to the order search API
    """
    api_base_url = Variable.get("order_api_base_url")
    test_endpoint = f"{api_base_url}/health"
    
    try:
        import requests
        
        # Get token for authentication
        token = get_api_auth_token()
        
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        response = requests.get(test_endpoint, headers=headers)
        
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

# Task 1: Set up API connection
task_setup_api = PythonOperator(
    task_id='setup_api_connection',
    python_callable=setup_api_connection,
    provide_context=True,
    dag=dag,
)

# Task 2: Update report configurations
task_update_configs = PythonOperator(
    task_id='update_report_configs',
    python_callable=update_report_configs,
    provide_context=True,
    dag=dag,
)

# Task 3: Test API connectivity
task_test_api = PythonOperator(
    task_id='test_api_connectivity',
    python_callable=test_api_connectivity,
    provide_context=True,
    dag=dag,
)

# Define task dependencies
task_setup_api >> task_update_configs >> task_test_api