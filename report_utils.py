# utils/report_utils.py
import json
import logging
import pandas as pd
import requests
from datetime import datetime, timedelta
from airflow.models import Variable
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet
import matplotlib.pyplot as plt
import io
from reportlab.lib.units import inch

logger = logging.getLogger("report_utils")

def get_api_auth_token():
    """
    Get or refresh the API authentication token.
    In a production environment, this should handle proper token acquisition and refresh.
    """
    # Check if we have a valid token in Variables
    token = Variable.get("api_token", default_var=None)
    token_expiry = Variable.get("api_token_expiry", default_var=None)
    
    if token and token_expiry:
        # Check if token is still valid (not expired)
        expiry_time = datetime.fromisoformat(token_expiry)
        if datetime.now() < expiry_time:
            logger.info("Using existing API token")
            return token
    
    # If no token or expired, acquire a new one
    try:
        api_base_url = Variable.get("order_api_base_url")
        auth_endpoint = f"{api_base_url}/auth/token"
        
        # Replace with your actual authentication mechanism
        auth_payload = {
            "client_id": Variable.get("api_client_id"),
            "client_secret": Variable.get("api_client_secret"),
            "grant_type": "client_credentials"
        }
        
        response = requests.post(auth_endpoint, json=auth_payload)
        
        if response.status_code == 200:
            auth_data = response.json()
            new_token = auth_data["access_token"]
            
            # Calculate expiry (typically provided in response, but we'll estimate if not)
            expires_in = auth_data.get("expires_in", 3600)  # Default 1 hour
            expiry_time = datetime.now() + timedelta(seconds=expires_in)
            
            # Store token and expiry in Variables
            Variable.set("api_token", new_token)
            Variable.set("api_token_expiry", expiry_time.isoformat())
            
            logger.info("New API token acquired")
            return new_token
        else:
            logger.error(f"Failed to acquire API token: {response.status_code} - {response.text}")
            raise Exception("Authentication failed")
    
    except Exception as e:
        logger.exception(f"Error during authentication: {str(e)}")
        raise

def query_order_api(from_date, to_date, report_config=None):
    """
    Query the order search API with configurable parameters
    
    Args:
        from_date (str): Start date in format "DD MMM YYYY"
        to_date (str): End date in format "DD MMM YYYY"
        report_config (dict, optional): Report configuration with query parameters
        
    Returns:
        list: Order data results
    """
    # Get API configuration
    api_base_url = Variable.get("order_api_base_url")
    search_endpoint = f"{api_base_url}/order/search"
    
    # Get token for authentication
    token = get_api_auth_token()
    
    # Build default search payload
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
    
    # Customize payload based on report configuration
    if report_config:
        # Set request fields if specified
        if "report_fields" in report_config:
            payload["RequestAttributeIds"] = report_config["report_fields"]
            
        # Set view name if specified
        view_name = report_config.get("query_parameters", {}).get("view_name")
        if view_name:
            payload["ViewName"] = view_name
            payload["Filters"][0]["ViewName"] = view_name
            
        # Set sort field if specified
        sort_field = report_config.get("query_parameters", {}).get("sort_field")
        if sort_field:
            payload["Sort"] = sort_field
            
        # Add order type filter if specified
        order_type = report_config.get("query_parameters", {}).get("order_type")
        if order_type:
            payload["Filters"].append({
                "ViewName": payload["ViewName"],
                "AttributeId": "TextSearch",
                "DataType": "text",
                "requiredFilter": False,
                "FilterValues": [
                    f"\"{order_type}\""
                ],
                "negativeFilter": False
            })
    
    # Set headers with authentication
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
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
            logger.info(f"Retrieved {len(result_data['data'])} records from page {page}")
            
            # Check if we've reached the end
            if len(all_results) >= result_data.get("totalCount", 0) or len(result_data["data"]) < payload["Size"]:
                break
            
            page += 1
    
    except Exception as e:
        logger.error(f"Error during API search: {str(e)}")
        raise
    
    logger.info(f"Total records retrieved: {len(all_results)}")
    return all_results

def generate_pdf_report(report_title, results, report_config=None, execution_date=None):
    """
    Generate a PDF report from API results
    
    Args:
        report_title (str): Report title
        results (list): Data results from API
        report_config (dict, optional): Report configuration
        execution_date (datetime, optional): Execution date for the report
        
    Returns:
        str: Path to the generated PDF file
    """
    if not execution_date:
        execution_date = datetime.now()
        
    # Create file name based on title
    report_id = report_config.get("report_id", "report") if report_config else "report"
    pdf_file = f"/tmp/{report_id}_{execution_date.strftime('%Y%m%d')}.pdf"
    
    # Handle empty results
    if not results:
        logger.warning(f"No results found for report generation: {report_title}")
        # Create an empty PDF with a message
        doc = SimpleDocTemplate(pdf_file, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []
        elements.append(Paragraph(f"{report_title} - {execution_date.strftime('%Y-%m-%d')}", styles['Title']))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph("No records found for the specified period.", styles['Normal']))
        doc.build(elements)
        return pdf_file
    
    # Extract relevant fields for the report
    if report_config and "report_fields" in report_config:
        report_fields = report_config["report_fields"]
    else:
        # Use all fields from the first result
        report_fields = list(results[0].keys())
    
    # Create a DataFrame from the results
    df = pd.DataFrame(results)
    
    # Generate the PDF
    doc = SimpleDocTemplate(pdf_file, pagesize=landscape(letter))
    
    styles = getSampleStyleSheet()
    elements = []
    
    # Add title
    elements.append(Paragraph(f"{report_title} - {execution_date.strftime('%Y-%m-%d')}", styles['Title']))
    elements.append(Spacer(1, 12))
    
    # Add description if available
    if report_config and report_config.get("description"):
        elements.append(Paragraph(report_config["description"], styles['Normal']))
        elements.append(Spacer(1, 12))
    
    # Add summary section if configured
    if report_config and "summary_fields" in report_config:
        elements.append(Paragraph("Summary", styles['Heading2']))
        
        # Create summary table data
        summary_data = []
        
        for summary_field in report_config["summary_fields"]:
            field = summary_field["field"]
            operation = summary_field["operation"]
            label = summary_field["label"]
            
            # Skip if field doesn't exist in the data
            if field not in df.columns:
                continue
                
            try:
                # Calculate summary statistic based on operation
                if operation == "sum":
                    value = df[field].sum()
                    if isinstance(value, (int, float)):
                        value_str = f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
                    else:
                        value_str = str(value)
                elif operation == "avg" or operation == "mean":
                    value = df[field].mean()
                    value_str = f"{value:,.2f}"
                elif operation == "count":
                    value = len(df)
                    value_str = f"{value:,}"
                elif operation == "min":
                    value = df[field].min()
                    value_str = str(value)
                elif operation == "max":
                    value = df[field].max()
                    value_str = str(value)
                elif operation == "group":
                    # Skip in summary table, will create chart instead
                    continue
                else:
                    logger.warning(f"Unknown summary operation: {operation}")
                    continue
                    
                summary_data.append([label, value_str])
                
            except Exception as e:
                logger.error(f"Error calculating summary for {field}: {str(e)}")
                continue
        
        if summary_data:
            # Create summary table
            summary_table = Table(summary_data, colWidths=[300, 200])
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
        
        # Generate charts for group operations
        for summary_field in report_config["summary_fields"]:
            if summary_field["operation"] == "group":
                field = summary_field["field"]
                label = summary_field["label"]
                
                # Skip if field doesn't exist in the data
                if field not in df.columns:
                    continue
                    
                try:
                    # Count values in the field
                    value_counts = df[field].value_counts().head(10)  # Limit to top 10
                    
                    # Create chart
                    plt.figure(figsize=(8, 4))
                    value_counts.plot(kind='bar', color='skyblue')
                    plt.title(label)
                    plt.xlabel(field)
                    plt.ylabel('Count')
                    plt.tight_layout()
                    
                    # Save chart to buffer
                    img_buffer = io.BytesIO()
                    plt.savefig(img_buffer, format='png')
                    img_buffer.seek(0)
                    
                    # Add chart to PDF
                    elements.append(Paragraph(label, styles['Heading3']))
                    elements.append(Spacer(1, 6))
                    img = Image(img_buffer, width=6*inch, height=3*inch)
                    elements.append(img)
                    elements.append(Spacer(1, 12))
                    
                    plt.close()
                    
                except Exception as e:
                    logger.error(f"Error generating chart for {field}: {str(e)}")
                    continue
    
    # Add main table with data
    elements.append(Paragraph("Detailed Data", styles['Heading2']))
    
    # Prepare table data
    # Filter to only include configured fields or all available fields
    table_fields = [field for field in report_fields if field in df.columns]
    
    # Add header row with field names
    table_data = [table_fields]
    
    # Add data rows
    for _, row in df.iterrows():
        table_row = []
        for field in table_fields:
            value = row.get(field, "")
            if isinstance(value, (int, float)):
                if isinstance(value, float):
                    formatted_value = f"{value:,.2f}"
                else:
                    formatted_value = f"{value:,}"
            else:
                formatted_value = str(value)
            table_row.append(formatted_value)
        table_data.append(table_row)
    
    # Create table with appropriate column widths
    col_widths = [max(100, min(200, 600 // len(table_fields)))] * len(table_fields)
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    
    # Style the table
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.blue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
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
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            table_style.add('BACKGROUND', (0, i), (-1, i), colors.lightgrey)
    
    table.setStyle(table_style)
    elements.append(table)
    
    # Build the PDF
    doc.build(elements)
    
    logger.info(f"PDF report generated: {pdf_file}")
    return pdf_file