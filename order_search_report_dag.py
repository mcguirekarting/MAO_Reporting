# order_report_dag.py
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.email import EmailOperator
from airflow.models import Variable
import requests
import json
import pandas as pd
import logging
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from airflow.utils.dates import days_ago

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("order_report_service")

# Define default arguments for the DAG
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
}

# Function to query the order search API
def query_order_api(**kwargs):
    """
    Query the order search API for a specific date range
    """
    # Get execution date from context
    execution_date = kwargs['execution_date']
    
    # Get API configuration from Airflow Variables
    api_base_url = Variable.get("order_api_base_url")
    search_endpoint = f"{api_base_url}/order/search"
    
    # Calculate date range (yesterday to execution date)
    to_date = execution_date.strftime("%d %b %Y")
    from_date = (execution_date - timedelta(days=1)).strftime("%d %b %Y")
    
    logger.info(f"Searching orders from {from_date} to {to_date}")
    
    # Build API search payload
    payload = {
        "ViewName": "orderdetails",
        "Filters": [
            {
                "ViewName": "orderdetails",
                "AttributeId": "OrderDate",
                "DataType": None,
                "requiredFilter": False,
                "FilterValues": [
                    {
                        "filter": {
                            "date": {
                                "from": from_date,
                                "to": to_date
                            },
                            "time": {
                                "from": "00:00",
                                "to": "23:59",
                                "start": 0,
                                "end": 288
                            },
                            "quickSelect": "CUSTOM"
                        }
                    }
                ],
                "negativeFilter": False
            }
        ],
        "RequestAttributeIds": [],
        "SearchOptions": [],
        "SearchChains": [],
        "FilterExpression": None,
        "Page": 0,
        "TotalCount": -1,
        "SortOrder": "desc",
        "SortIndicator": "chevron-up",
        "TimeZone": "America/Chicago",
        "IsCommonUI": False,
        "ComponentShortName": None,
        "EnableMaxCountLimit": True,
        "MaxCountLimit": 1000,
        "ComponentName": "com-manh-cp-xint",
        "Size": 100,
        "Sort": "OrderDate"
    }

    # Query parameter - can be configured in Airflow Variables
    order_type = Variable.get("order_type", "StandardOrder")
    
    # Add order type filter if specified
    if order_type:
        payload["Filters"].append({
            "ViewName": "orderdetails",
            "AttributeId": "TextSearch",
            "DataType": "text",
            "requiredFilter": False,
            "FilterValues": [
                f"\"{order_type}\""
            ],
            "negativeFilter": False
        })
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {Variable.get('api_token', '')}"
    }
    
    all_results = []
    page = 0
    
    try:
        while True:
            payload["Page"] = page
            logger.info(f"Searching page {page}...")
            
            response = requests.post(
                search_endpoint, 
                json=payload,
                headers=headers
            )
            
            if response.status_code != 200:
                logger.error(f"Error in API call: {response.status_code} - {response.text}")
                raise Exception(f"API returned error: {response.status_code}")
            
            result_data = response.json()
            
            # Check if we have results
            if not result_data.get("data") or len(result_data["data"]) == 0:
                logger.info(f"No more results found after page {page}")
                break
            
            all_results.extend(result_data["data"])
            logger.info(f"Retrieved {len(result_data['data'])} orders from page {page}")
            
            # Check if we've reached the end
            if len(all_results) >= result_data.get("totalCount", 0) or len(result_data["data"]) < payload["Size"]:
                break
            
            page += 1
    
    except Exception as e:
        logger.error(f"Error during API search: {str(e)}")
        raise
    
    logger.info(f"Total orders retrieved: {len(all_results)}")
    
    # Create a temporary file to store the results
    result_file = f"/tmp/order_results_{execution_date.strftime('%Y%m%d')}.json"
    with open(result_file, 'w') as f:
        json.dump(all_results, f)
    
    # Return the path to the result file for the next task
    return result_file

# Function to generate a PDF report from the API results
def generate_pdf_report(**kwargs):
    """
    Generate a PDF report from the API results
    """
    # Get the task instance
    ti = kwargs['ti']
    
    # Get the result file path from the previous task
    result_file = ti.xcom_pull(task_ids='query_order_api')
    execution_date = kwargs['execution_date']
    
    logger.info(f"Generating PDF report from {result_file}")
    
    # Load the results
    with open(result_file, 'r') as f:
        results = json.load(f)
    
    if not results:
        logger.warning("No results found for report generation")
        # Create an empty PDF with a message
        pdf_file = f"/tmp/order_report_{execution_date.strftime('%Y%m%d')}.pdf"
        doc = SimpleDocTemplate(pdf_file, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []
        elements.append(Paragraph(f"Order Report - {execution_date.strftime('%Y-%m-%d')}", styles['Title']))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph("No orders found for the specified period.", styles['Normal']))
        doc.build(elements)
        return pdf_file
    
    # Extract relevant fields for the report
    # Adjust these fields based on your API response structure
    report_data = []
    
    # Add header row
    headers = ["Order ID", "Order Date", "Customer", "Status", "Total Items", "Total Value"]
    report_data.append(headers)
    
    # Add data rows
    for order in results:
        try:
            row = [
                order.get("OrderId", "N/A"),
                order.get("OrderDate", "N/A"),
                order.get("CustomerName", "N/A"),
                order.get("Status", "N/A"),
                str(order.get("TotalItems", 0)),
                f"${order.get('TotalValue', 0):.2f}"
            ]
            report_data.append(row)
        except KeyError as e:
            logger.error(f"Error extracting order data: {str(e)}")
            continue
    
    # Create a DataFrame for summary statistics
    df = pd.DataFrame(report_data[1:], columns=report_data[0])
    df['Total Value'] = df['Total Value'].str.replace('$', '').astype(float)
    df['Total Items'] = df['Total Items'].astype(int)
    
    # Calculate summary statistics
    total_orders = len(df)
    total_value = df['Total Value'].sum()
    total_items = df['Total Items'].sum()
    average_value = df['Total Value'].mean() if total_orders > 0 else 0
    
    # Generate the PDF
    pdf_file = f"/tmp/order_report_{execution_date.strftime('%Y%m%d')}.pdf"
    doc = SimpleDocTemplate(pdf_file, pagesize=landscape(letter))
    
    styles = getSampleStyleSheet()
    elements = []
    
    # Add title
    title = f"Order Report - {execution_date.strftime('%Y-%m-%d')}"
    elements.append(Paragraph(title, styles['Title']))
    elements.append(Spacer(1, 12))
    
    # Add summary section
    elements.append(Paragraph("Summary", styles['Heading2']))
    summary_data = [
        ["Total Orders", str(total_orders)],
        ["Total Items", str(total_items)],
        ["Total Value", f"${total_value:.2f}"],
        ["Average Order Value", f"${average_value:.2f}"]
    ]
    
    summary_table = Table(summary_data, colWidths=[200, 150])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 24))
    
    # Add main table
    elements.append(Paragraph("Order Details", styles['Heading2']))
    
    # Create the table
    table = Table(report_data)
    
    # Style the table
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.blue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ])
    
    # Add a zebra striping pattern
    for i in range(1, len(report_data)):
        if i % 2 == 0:
            table_style.add('BACKGROUND', (0, i), (-1, i), colors.lightgrey)
    
    table.setStyle(table_style)
    elements.append(table)
    
    # Build the PDF
    doc.build(elements)
    
    logger.info(f"PDF report generated: {pdf_file}")
    return pdf_file

# Create the DAG
dag = DAG(
    'order_search_report',
    default_args=default_args,
    description='Search for orders, generate a PDF report, and email it',
    schedule_interval='0 8 * * *',  # Run daily at 8:00 AM
    start_date=days_ago(1),
    catchup=False,
    tags=['order', 'report'],
)

# Task 1: Query the order API
task_query_api = PythonOperator(
    task_id='query_order_api',
    python_callable=query_order_api,
    provide_context=True,
    dag=dag,
)

# Task 2: Generate the PDF report
task_generate_pdf = PythonOperator(
    task_id='generate_pdf_report',
    python_callable=generate_pdf_report,
    provide_context=True,
    dag=dag,
)

# Task 3: Email the PDF report
task_email_report = EmailOperator(
    task_id='email_report',
    to="{{ var.value.report_recipients }}",
    subject="Daily Order Report - {{ ds }}",
    html_content="""
        <p>Hello,</p>
        <p>Please find attached the daily order report for {{ ds }}.</p>
        <p>This report contains a summary of all orders processed in the last 24 hours.</p>
        <p>Best regards,<br/>Automated Reporting System</p>
    """,
    files=["{{ ti.xcom_pull(task_ids='generate_pdf_report') }}"],
    dag=dag,
)

# Define task dependencies
task_query_api >> task_generate_pdf >> task_email_report