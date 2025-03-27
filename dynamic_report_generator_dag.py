# improved_dynamic_report_generator_dag.py
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.operators.email import EmailOperator
from airflow.operators.empty import EmptyOperator as DummyOperator
from airflow.models import Variable
from airflow.utils.task_group import TaskGroup
from airflow.utils.dates import days_ago
import json
import logging
import os
import sys



# Add project root to path for local imports
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from utils.report_utils import query_order_api, generate_pdf_report

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("dynamic_report_generator")

# Define default arguments for the DAG
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
}

# Function to get active report configurations
def get_active_reports(**kwargs):
    """
    Get the list of active report configurations and decide which branches to execute
    """
    try:
        active_report_ids = json.loads(Variable.get("active_report_ids", "[]"))
        if not active_report_ids:
            logger.warning("No active reports found")
            return ['no_active_reports']
        
        logger.info(f"Found {len(active_report_ids)} active reports: {active_report_ids}")
        
        # Return task IDs corresponding to each report
        return [f"process_report_{report_id}" for report_id in active_report_ids]
    
    except Exception as e:
        logger.error(f"Error retrieving active reports: {str(e)}")
        return ['no_active_reports']

# Function to query the API for a specific report
def query_report_data(report_id, **kwargs):
    """
    Query the API based on report configuration
    """
    # Get execution date from context
    execution_date = kwargs['execution_date']
    
    # Load report configuration
    try:
        report_config = json.loads(Variable.get(f"report_config_{report_id}"))
    except Exception as e:
        logger.error(f"Error loading configuration for report {report_id}: {str(e)}")
        raise
    
    # Calculate date range (yesterday to execution date)
    to_date = execution_date.strftime("%d %b %Y")
    from_date = (execution_date - timedelta(days=1)).strftime("%d %b %Y")
    
    logger.info(f"[{report_id}] Searching from {from_date} to {to_date}")
    
    # Query the API using the utility function
    results = query_order_api(from_date, to_date, report_config)
    
    # Create a temporary file to store the results
    result_file = f"/tmp/{report_id}_results_{execution_date.strftime('%Y%m%d')}.json"
    with open(result_file, 'w') as f:
        json.dump({
            "report_id": report_id,
            "config": report_config,
            "data": results,
            "executed_at": execution_date.isoformat()
        }, f)
    
    # Return the path to the result file
    return result_file

# Function to generate PDF for a specific report
def generate_report_pdf(report_id, **kwargs):
    """
    Generate a PDF report based on the query results and report configuration
    """
    # Get the task instance
    ti = kwargs['ti']
    execution_date = kwargs['execution_date']
    
    # Get the result file path from the previous task
    result_file = ti.xcom_pull(task_ids=f"query_data_{report_id}")
    
    logger.info(f"[{report_id}] Generating PDF report from {result_file}")
    
    # Load the results and configuration
    with open(result_file, 'r') as f:
        result_data = json.load(f)
    
    report_config = result_data["config"]
    results = result_data["data"]
    
    # Generate the PDF using the utility function
    pdf_file = generate_pdf_report(
        report_title=report_config['name'],
        results=results,
        report_config=report_config,
        execution_date=execution_date
    )
    
    return pdf_file

# Function to email the report
def prepare_email(report_id, **kwargs):
    """
    Prepare email parameters for the generated PDF report
    """
    # Get the task instance
    ti = kwargs['ti']
    execution_date = kwargs['execution_date']
    
    # Get the PDF file path from the previous task
    pdf_file = ti.xcom_pull(task_ids=f"generate_pdf_{report_id}")
    
    # Load report configuration to get email settings
    try:
        report_config = json.loads(Variable.get(f"report_config_{report_id}"))
    except Exception as e:
        logger.error(f"Error loading configuration for report {report_id}: {str(e)}")
        raise
    
    # Get email configuration
    email_config = report_config.get("email", {})
    recipients = email_config.get("recipients", [])
    subject = email_config.get("subject", "Report").format(date=execution_date.strftime('%Y-%m-%d'))
    body = email_config.get("body", "Please find attached the requested report.")
    
    if not recipients:
        logger.warning(f"[{report_id}] No recipients configured for report, using default")
        recipients = Variable.get("default_report_recipients", "admin@example.com").split(',')
    
    logger.info(f"[{report_id}] Sending report to {len(recipients)} recipients: {recipients}")
    
    # Return the email parameters
    return {
        "file_path": pdf_file,
        "recipients": recipients,
        "subject": subject,
        "body": body
    }

# Create the DAG
dag = DAG(
    'dynamic_report_generator',
    default_args=default_args,
    description='Dynamically generate and email reports based on configurations',
    schedule_interval='0 7 * * *',  # Run daily at 7:00 AM
    start_date=days_ago(1),
    catchup=False,
    tags=['report', 'dynamic'],
)

# Task to determine which reports to run
branching = BranchPythonOperator(
    task_id='get_active_reports',
    python_callable=get_active_reports,
    provide_context=True,
    dag=dag,
)

# End task
end = DummyOperator(
    task_id='end',
    trigger_rule='none_failed_min_one_success',
    dag=dag,
)

# No active reports task
no_active_reports = DummyOperator(
    task_id='no_active_reports',
    dag=dag,
)

# Connect no_active_reports to branching and end
branching >> no_active_reports >> end

# Get the active report IDs at DAG definition time
# This is only used for setting up the task structure
# The actual active reports will be determined at runtime
try:
    active_report_ids = json.loads(Variable.get("active_report_ids", "[]"))
except:
    active_report_ids = []

# Create task groups for each report
for report_id in active_report_ids:
    with TaskGroup(group_id=f"process_report_{report_id}", dag=dag) as report_group:
        # Task to query the API
        query_task = PythonOperator(
            task_id=f"query_data_{report_id}",
            python_callable=query_report_data,
            op_kwargs={"report_id": report_id},
            provide_context=True,
        )
        
        # Task to generate the PDF
        pdf_task = PythonOperator(
            task_id=f"generate_pdf_{report_id}",
            python_callable=generate_report_pdf,
            op_kwargs={"report_id": report_id},
            provide_context=True,
        )
        
        # Task to prepare email
        email_prep_task = PythonOperator(
            task_id=f"prepare_email_{report_id}",
            python_callable=prepare_email,
            op_kwargs={"report_id": report_id},
            provide_context=True,
        )
        
        # Task to send email with enhanced HTML template
        email_task = EmailOperator(
            task_id=f"send_email_{report_id}",
            to="{{ ti.xcom_pull(task_ids='prepare_email_" + report_id + "')['recipients'] }}",
            subject="{{ ti.xcom_pull(task_ids='prepare_email_" + report_id + "')['subject'] }}",
            html_content="""
                <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; margin: 0; padding: 0; color: #333; }
                        .header { background-color: #4285f4; color: white; padding: 20px; }
                        .content { padding: 20px; }
                        .footer { font-size: 12px; color: #999; padding: 20px; border-top: 1px solid #eee; }
                        .note { background-color: #f8f9fa; border-left: 4px solid #4285f4; padding: 15px; margin: 15px 0; }
                    </style>
                </head>
                <body>
                    <div class="header">
                        <h2>{{ ti.xcom_pull(task_ids='prepare_email_""" + report_id + """')['subject'] }}</h2>
                    </div>
                    <div class="content">
                        <p>{{ ti.xcom_pull(task_ids='prepare_email_""" + report_id + """')['body'] }}</p>
                        <div class="note">
                            <p><strong>Report Date Range:</strong> {{ (execution_date - macros.timedelta(days=1)).strftime('%Y-%m-%d') }} to {{ execution_date.strftime('%Y-%m-%d') }}</p>
                            <p><strong>Generated On:</strong> {{ execution_date.strftime('%Y-%m-%d %H:%M:%S') }}</p>
                        </div>
                    </div>
                    <div class="footer">
                        <p>This is an automated report. Please do not reply to this email.</p>
                        <p>If you have any questions about this report, please contact the operations team.</p>
                    </div>
                </body>
                </html>
            """,
            files=["{{ ti.xcom_pull(task_ids='prepare_email_" + report_id + "')['file_path'] }}"],
        )
        
        # Set up dependencies within the group
        query_task >> pdf_task >> email_prep_task >> email_task
    
    # Connect group to branching and end tasks
    branching >> report_group >> end