import os
import requests
from quickbooks.client import QuickBooks
from quickbooks.objects.invoice import Invoice
from quickbooks.objects.purchaseorder import PurchaseOrder
from quickbooks.objects.vendor import Vendor as Supplier
from quickbooks.objects.item import Item
from quickbooks.objects.attachable import Attachable
from intuitlib.client import AuthClient
from quickbooks.objects.company_info import CompanyInfo
from config import (
    logger, QB_CLIENT_ID, QB_CLIENT_SECRET, QB_ENVIRONMENT, 
    QB_ACCESS_TOKEN, QB_REFRESH_TOKEN, QB_REALM_ID
)

def update_env_file(new_access_token, new_refresh_token):
    """
    Updates the .env file with new tokens.
    This is a robust way to handle token refreshes.
    """
    env_path = '.env'
    if not os.path.exists(env_path):
        logger.warning(".env file not found. Cannot persist new tokens.")
        return

    try:
        with open(env_path, 'r') as f:
            lines = f.readlines()

        with open(env_path, 'w') as f:
            for line in lines:
                if line.startswith('QB_ACCESS_TOKEN='):
                    f.write(f'QB_ACCESS_TOKEN={new_access_token}\n')
                elif line.startswith('QB_REFRESH_TOKEN='):
                    f.write(f'QB_REFRESH_TOKEN={new_refresh_token}\n')
                else:
                    f.write(line)
        logger.info("Successfully updated .env file with new refresh token.")
    except Exception as e:
        logger.error(f"Error updating .env file: {e}. New tokens will not be saved.")

def token_refreshed_callback(auth_client):
    """
    This function is called by the QB client *after* it refreshes the token.
    We save the new tokens back to the .env file.
    """
    logger.info("QuickBooks token was refreshed.")
    update_env_file(auth_client.access_token, auth_client.refresh_token)

def get_qb_client() -> QuickBooks:
    """
    Initializes and returns an authenticated QuickBooks client.
    Handles automatic token refreshes.
    """
    try:
        auth_client = AuthClient(
            client_id=QB_CLIENT_ID,
            client_secret=QB_CLIENT_SECRET,
            environment=QB_ENVIRONMENT,
            redirect_uri="http://localhost:8000/callback", # Must match
            access_token=QB_ACCESS_TOKEN,
            refresh_token=QB_REFRESH_TOKEN
        )
        
        client = QuickBooks(
            auth_client=auth_client,
            refresh_token=QB_REFRESH_TOKEN,
            company_id=QB_REALM_ID,
            minorversion=65 # Specify a recent minor version
        )
        
        # Test connection by fetching company info
        # Test connection by fetching company info
        company_info_list = CompanyInfo.all(qb=client)
        if company_info_list:
            logger.info(f"QuickBooks connection successful for company: {company_info_list[0].CompanyName} (ID: {QB_REALM_ID})")
        else:
            # This case shouldn't happen, but it's good to have
            logger.warning(f"QuickBooks connection successful but could not fetch CompanyInfo (ID: {QB_REALM_ID})")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize QuickBooks client: {e}")
        logger.error("Please check your QB_... credentials in the .env file.")
        logger.error("If this is your first time, run 'python get_oauth_tokens.py' first.")
        return None

def get_invoices(client: QuickBooks, start_date, end_date, limit=None):
    """
    Fetches invoices from QuickBooks within a date range.
    Handles pagination.
    """
    query = f"SELECT * FROM Invoice WHERE TxnDate >= '{start_date}' AND TxnDate <= '{end_date}'"
    if limit:
        query += f" MAXRESULTS {limit}"
        
    try:
        if limit:
            # If limited, just one call is needed
            invoices = Invoice.query(query, qb=client)
            logger.info(f"QB: Found {len(invoices)} invoices (limit of {limit}).")
            return invoices
        else:
            # Handle pagination for full import
            all_invoices = []
            start_pos = 1
            max_results = 100 # QB API limit per call
            while True:
                paginated_query = f"{query} STARTPOSITION {start_pos} MAXRESULTS {max_results}"
                invoices_batch = Invoice.query(paginated_query, qb=client)
                
                if not invoices_batch:
                    break # No more invoices
                    
                all_invoices.extend(invoices_batch)
                start_pos += max_results
                logger.debug(f"QB: Fetched {len(invoices_batch)} invoices. Total: {len(all_invoices)}")
            
            logger.info(f"QB: Found a total of {len(all_invoices)} invoices.")
            return all_invoices

    except Exception as e:
        logger.error(f"Error fetching invoices from QB: {e}")
        return []

def get_lpo_for_invoice(client: QuickBooks, invoice: Invoice):
    """
    Checks an invoice for a linked LPO (PurchaseOrder) and returns it.
    """
    if not invoice.LinkedTxn:
        return None

    for txn in invoice.LinkedTxn:
        # FIX: Use dot notation (txn.TxnType) instead of dictionary .get()
        if txn.TxnType == 'PurchaseOrder':
            # FIX: Use dot notation (txn.TxnId) here as well
            lpo_id = txn.TxnId
            try:
                lpo = PurchaseOrder.get(lpo_id, qb=client)
                logger.debug(f"QB: Found linked LPO {lpo.DocNumber} for Invoice {invoice.DocNumber}")
                return lpo
            except Exception as e:
                logger.error(f"QB: Error fetching linked LPO {lpo_id}: {e}")
                return None
    return None

def get_supplier(client: QuickBooks, supplier_id: str):
    """Fetches a Supplier by its ID."""
    try:
        supplier = Supplier.get(supplier_id, qb=client)
        return supplier
    except Exception as e:
        logger.error(f"QB: Error fetching Supplier {supplier_id}: {e}")
        return None

def get_material(client: QuickBooks, item_id: str):
    """Fetches an Item by its ID."""
    try:
        item = Item.get(item_id, qb=client)
        return item
    except Exception as e:
        logger.error(f"QB: Error fetching Item {item_id}: {e}")
        return None

def get_attachments(client: QuickBooks, object_type: str, object_id: str):
    """
    Fetches a list of Attachable objects (metadata) for a given QB object.
    object_type = 'Invoice' or 'PurchaseOrder'
    """
    query = f"SELECT * FROM Attachable WHERE AttachableRef.EntityRef.value = '{object_id}' AND AttachableRef.EntityRef.type = '{object_type}'"
    try:
        attachments = Attachable.where(query, qb=client)
        logger.debug(f"QB: Found {len(attachments)} attachments for {object_type} {object_id}")
        return attachments
    except Exception as e:
        logger.error(f"QB: Error fetching attachments for {object_type} {object_id}: {e}")
        return []

def download_attachment(client: QuickBooks, attachment: Attachable):
    """
    Downloads the actual file content of an Attachable.
    This requires an authenticated request to the FileAccessUri.
    """
    if not attachment.FileAccessUri:
        logger.warning(f"QB: Attachment {attachment.FileName} has no FileAccessUri. Skipping.")
        return None
        
    download_url = attachment.FileAccessUri
    
    try:
        # We must use the auth client's authenticated session
        response = client.auth_client.session.get(download_url)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        logger.debug(f"QB: Successfully downloaded attachment: {attachment.FileName}")
        return response.content
    except requests.exceptions.RequestException as e:
        logger.error(f"QB: Failed to download attachment {attachment.FileName}: {e}")
        return None