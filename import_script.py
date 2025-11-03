import argparse
import datetime
import uuid
import sys
from decimal import Decimal
from azure.storage.blob import BlobServiceClient, ContentSettings
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from quickbooks.objects.invoice import Invoice
from quickbooks.objects.purchaseorder import PurchaseOrder
from quickbooks.objects.vendor import Vendor as QBSupplier
from quickbooks.objects.item import Item as QBItem
from quickbooks.client import QuickBooks

import config
import models
import quickbooks_client as qb

# --- Helper Functions ---

def get_azure_blob_service_client():
    """Initializes and returns the Azure BlobServiceClient."""
    if not config.AZURE_CONNECTION_STRING:
        config.logger.warning("Azure Connection String not configured. Cannot upload attachments.")
        return None
    try:
        return BlobServiceClient.from_connection_string(config.AZURE_CONNECTION_STRING)
    except Exception as e:
        config.logger.error(f"Failed to connect to Azure Blob Storage: {e}")
        return None

def upload_attachment_to_azure(blob_service_client, file_name, file_content):
    """Uploads a file to Azure Blob Storage and returns the URL."""
    if not blob_service_client:
        config.logger.warning(f"Skipping upload for {file_name}: Blob service client is not available.")
        return None

    unique_file_name = f"{uuid.uuid4()}-{file_name}"
    
    try:
        container_client = blob_service_client.get_container_client(config.AZURE_CONTAINER_NAME)
        blob_client = container_client.get_blob_client(unique_file_name)
        
        content_type = "application/octet-stream"
        if file_name.lower().endswith('.pdf'): content_type = "application/pdf"
        elif file_name.lower().endswith('.txt'): content_type = "text/plain"
        elif file_name.lower().endswith('.png'): content_type = "image/png"
        elif file_name.lower().endswith(('.jpg', '.jpeg')): content_type = "image/jpeg"
            
        content_settings = ContentSettings(content_type=content_type)
        
        blob_client.upload_blob(file_content, content_settings=content_settings)
        config.logger.debug(f"Uploaded attachment {file_name} to {blob_client.url}")
        return blob_client.url
    except Exception as e:
        config.logger.error(f"Failed to upload attachment {file_name} to Azure: {e}")
        return None

def get_or_create_supplier(session: Session, qb_supplier: QBSupplier) -> models.Supplier:
    """Finds a supplier by name, or creates it if it doesn't exist."""
    supplier_name = qb_supplier.DisplayName
    if not supplier_name:
        raise ValueError(f"QB Supplier ID {qb_supplier.Id} has no DisplayName.")
        
    db_supplier = session.query(models.Supplier).filter_by(name=supplier_name).first()
    
    if db_supplier:
        config.logger.debug(f"Found existing supplier: {supplier_name}")
        return db_supplier
    else:
        config.logger.info(f"Creating new supplier: {supplier_name}")
        new_supplier = models.Supplier(
            name=supplier_name,
            email=qb_supplier.PrimaryEmailAddr.Address if qb_supplier.PrimaryEmailAddr else None,
            phone=qb_supplier.PrimaryPhone.FreeFormNumber if qb_supplier.PrimaryPhone else None
        )
        session.add(new_supplier)
        session.flush() # Flush to get the new ID
        return new_supplier

def get_or_create_material(session: Session, qb_item: QBItem) -> models.Material:
    """Finds a material by name, or creates it if it doesn't exist."""
    material_name = qb_item.Name
    if not material_name:
         raise ValueError(f"QB Item ID {qb_item.Id} has no Name.")

    db_material = session.query(models.Material).filter_by(name=material_name).first()
    
    if db_material:
        config.logger.debug(f"Found existing material: {material_name}")
        return db_material
    else:
        config.logger.info(f"Creating new material: {material_name}")
        # Map QB Item Type to your 'unit' field, or default to 'nos'
        unit = 'nos' # Default
        if qb_item.Type == 'Service':
            unit = 'service'
        elif qb_item.Type == 'Inventory':
            unit = 'each' # You might have a UOM field in QB
        
        new_material = models.Material(
            name=material_name,
            unit=unit 
        )
        session.add(new_material)
        session.flush() # Flush to get the new ID
        return new_material

def get_default_project(session: Session) -> models.Project:
    """Finds or creates the default project for imported items."""
    project_name = "Default Imported Project"
    db_project = session.query(models.Project).filter_by(name=project_name).first()
    if not db_project:
        config.logger.info(f"Creating '{project_name}'")
        db_project = models.Project(name=project_name)
        session.add(db_project)
        session.flush()
    return db_project

def get_default_user(session: Session) -> models.User:
    """Finds or creates the default user for imported items."""
    admin_email = "import_admin@yourcompany.com"
    db_user = session.query(models.User).filter_by(email=admin_email).first()
    if not db_user:
        config.logger.info(f"Creating default user '{admin_email}'")
        db_user = models.User(
            email=admin_email,
            hashed_password="!!!SET-A-DUMMY-PASSWORD-HERE!!!" # This is not used for login
        )
        session.add(db_user)
        session.flush()
    return db_user

def process_lpo_items(session: Session, qb_client: QuickBooks, qb_lpo: PurchaseOrder, db_lpo: models.LPO):
    """Processes and adds line items from a QB LPO to a DB LPO."""
    if not qb_lpo.Line:
        return
        
    for line in qb_lpo.Line:
        # We only care about Item-based lines, not account lines
        if line.DetailType == 'ItemBasedExpenseLineDetail':
            detail = line.ItemBasedExpenseLineDetail
            if not detail.ItemRef or not detail.ItemRef.value:
                config.logger.warning(f"Skipping LPO item (no ItemRef): {line.Description}")
                continue
                
            qb_item = qb.get_material(qb_client, detail.ItemRef.value)
            if not qb_item:
                config.logger.error(f"Could not find QB Item {detail.ItemRef.value}. Skipping LPO item.")
                continue
            
            db_material = get_or_create_material(session, qb_item)
            
            # QB tax rate calculation is complex. We'll simplify.
            # If TaxCodeRef is 'TAX', we assume 5%. This is a simplification.
            tax_rate = Decimal("0.00")
            if detail.TaxCodeRef and detail.TaxCodeRef.value != 'NON':
                 # You might need to fetch TaxRate objects to be precise
                 # For now, let's use a flat 5% if *any* tax is applied
                 tax_rate = Decimal("0.05") 

            lpo_item = models.LPOItem(
                description=line.Description,
                quantity=detail.Qty or Decimal("0.0"),
                rate=detail.UnitPrice or Decimal("0.0"),
                tax_rate=tax_rate,
                lpo=db_lpo,
                material_id=db_material.id
            )
            session.add(lpo_item)
            
def process_invoice_items(session: Session, qb_client: QuickBooks, qb_invoice: Invoice, db_invoice: models.Invoice):
    """Processes and adds line items from a QB Invoice to a DB Invoice."""
    if not qb_invoice.Line:
        return

    for line in qb_invoice.Line:
        if line.DetailType == 'SalesItemLineDetail':
            detail = line.SalesItemLineDetail
            if not detail.ItemRef or not detail.ItemRef.value:
                config.logger.warning(f"Skipping Invoice item (no ItemRef): {line.Description}")
                continue

            qb_item = qb.get_material(qb_client, detail.ItemRef.value)
            if not qb_item:
                config.logger.error(f"Could not find QB Item {detail.ItemRef.value}. Skipping Invoice item.")
                continue
            
            db_material = get_or_create_material(session, qb_item)
            
            tax_rate = Decimal("0.00")
            if detail.TaxCodeRef and detail.TaxCodeRef.value != 'NON':
                 tax_rate = Decimal("0.05") # Same simplification as LPO

            inv_item = models.InvoiceItem(
                description=line.Description,
                quantity=detail.Qty or Decimal("0.0"),
                rate=detail.UnitPrice or Decimal("0.0"),
                tax_rate=tax_rate,
                # item_class=detail.ClassRef.value if detail.ClassRef else None,
                invoice=db_invoice,
                material_id=db_material.id
            )
            session.add(inv_item)
            
def process_attachments(session: Session, qb_client: QuickBooks, blob_service_client,
                        qb_object_type: str, qb_object_id: str, db_object):
    """Downloads QB attachments, uploads to Azure, and links to the DB object."""
    qb_attachments = qb.get_attachments(qb_client, qb_object_type, qb_object_id)
    
    for att in qb_attachments:
        if not att.FileName:
            config.logger.warning(f"Skipping attachment for {qb_object_type} {qb_object_id}: No file name.")
            continue
            
        file_content = qb.download_attachment(qb_client, att)
        if not file_content:
            continue # Download failed, already logged

        blob_url = upload_attachment_to_azure(blob_service_client, att.FileName, file_content)
        if not blob_url:
            continue # Upload failed, already logged

        # Create the correct attachment model based on type
        if qb_object_type == 'PurchaseOrder':
            db_att = models.LPOAttachment(
                blob_url=blob_url,
                file_name=att.FileName,
                lpo=db_object
            )
        elif qb_object_type == 'Invoice':
            db_att = models.InvoiceAttachment(
                blob_url=blob_url,
                file_name=att.FileName,
                invoice=db_object
            )
        else:
            continue
            
        session.add(db_att)

# --- Main Processing Function ---

def process_imports(limit=None):
    """
    Main function to process the import.
    """
    if not config.all_qb_keys_present():
        config.logger.critical("Missing QuickBooks credentials in .env file.")
        config.logger.critical("Please run 'python get_oauth_tokens.py' first and copy the tokens to .env")
        return

    start_date = datetime.date(2025, 4, 1)
    end_date = datetime.date(2025, 9, 30)
    
    config.logger.info(f"--- Starting Import Process ---")
    config.logger.info(f"Fetching Invoices from {start_date} to {end_date}")
    if limit:
        config.logger.warning(f"*** TEST MODE: Importing at most {limit} invoices. ***")

    # Initialize services
    db: Session = config.SessionLocal()
    blob_service_client = get_azure_blob_service_client()
    qb_client = qb.get_qb_client()
    
    if not qb_client:
        config.logger.critical("Failed to connect to QuickBooks. Exiting.")
        db.close()
        return

    success_count = 0
    skipped_count = 0
    fail_count = 0
    
    try:
        # Get default user/project to assign all items to
        default_project = get_default_project(db)
        default_user = get_default_user(db)
        
        # 1. Fetch Invoices from QuickBooks
        qb_invoices = qb.get_invoices(qb_client, start_date, end_date, limit)
        config.logger.info(f"Found {len(qb_invoices)} invoices in QB to process.")

        for qb_invoice in qb_invoices:
            invoice_number = qb_invoice.DocNumber
            if not invoice_number:
                config.logger.warning(f"Skipping QB Invoice ID {qb_invoice.Id}: It has no Invoice Number (DocNumber).")
                skipped_count += 1
                continue
            
            try:
                # 2. Check for Duplicates (Idempotency)
                existing_invoice = db.query(models.Invoice).filter_by(invoice_number=invoice_number).first()
                if existing_invoice:
                    config.logger.warning(f"Skipping Invoice {invoice_number}: Already exists in database.")
                    skipped_count += 1
                    continue
                    
                # 3. Check for LPO
                qb_lpo = qb.get_lpo_for_invoice(qb_client, qb_invoice)
                if not qb_lpo:
                    config.logger.warning(f"Skipping Invoice {invoice_number}: No related LPO (PurchaseOrder) found in QB.")
                    skipped_count += 1
                    continue

                lpo_number = qb_lpo.DocNumber
                if not lpo_number:
                    config.logger.warning(f"Skipping Invoice {invoice_number}: Linked LPO {qb_lpo.Id} has no LPO Number (DocNumber).")
                    skipped_count += 1
                    continue
                    
                config.logger.debug(f"Processing Invoice {invoice_number}, linked to LPO {lpo_number}")

                # 4. Process LPO (Find or Create)
                db_lpo = db.query(models.LPO).filter_by(lpo_number=lpo_number).first()
                
                if not db_lpo:
                    config.logger.info(f"LPO {lpo_number} not found. Creating new LPO.")
                    
                    # 4a. Get/Create Supplier
                    if not qb_lpo.VendorRef or not qb_lpo.VendorRef.value:
                         raise Exception(f"LPO {lpo_number} has no Supplier (VendorRef).")
                    
                    qb_supplier = qb.get_supplier(qb_client, qb_lpo.VendorRef.value)
                    if not qb_supplier:
                        raise Exception(f"Supplier ID {qb_lpo.VendorRef.value} not found in QB.")
                    db_supplier = get_or_create_supplier(db, qb_supplier)
                    
                    # 4b. Create LPO
                    db_lpo = models.LPO(
                        lpo_number=lpo_number,
                        lpo_date=qb_lpo.TxnDate,
                        status=qb_lpo.POStatus,
                        subtotal=qb_lpo.TotalAmt - (qb_lpo.TxnTaxDetail.TotalTax if qb_lpo.TxnTaxDetail else 0),
                        tax_total=qb_lpo.TxnTaxDetail.TotalTax if qb_lpo.TxnTaxDetail else 0,
                        grand_total=qb_lpo.TotalAmt,
                        message_to_supplier=qb_lpo.PrivateNote, # Or ShipTo.Name, etc. Map as needed.
                        memo=qb_lpo.Memo,
                        payment_mode=None, # QB POs don't have payment_mode
                        supplier_id=db_supplier.id,
                        project_id=default_project.id,
                        created_by_id=default_user.id
                    )
                    db.add(db_lpo)
                    
                    # 4c. Process LPO Items
                    process_lpo_items(db, qb_client, qb_lpo, db_lpo)
                        
                    # 4d. Process LPO Attachments
                    process_attachments(db, qb_client, blob_service_client, 'PurchaseOrder', qb_lpo.Id, db_lpo)
                    
                    # We must flush here so the LPO gets an ID before the Invoice uses it
                    db.flush()
                    config.logger.info(f"Successfully created new LPO {lpo_number} (ID: {db_lpo.id})")
                
                else:
                    config.logger.info(f"Found existing LPO {lpo_number} (ID: {db_lpo.id}). Linking to it.")
                
                # 5. Create Invoice
                config.logger.info(f"Creating new Invoice {invoice_number}")
                
                db_invoice = models.Invoice(
                    invoice_number=invoice_number,
                    invoice_date=qb_invoice.TxnDate,
                    invoice_due_date=qb_invoice.DueDate,
                    lpo_id=db_lpo.id,
                    status="Paid" if qb_invoice.Balance == 0 else "Pending",
                    subtotal=qb_invoice.TotalAmt - (qb_invoice.TxnTaxDetail.TotalTax if qb_invoice.TxnTaxDetail else 0),
                    tax_total=qb_invoice.TxnTaxDetail.TotalTax if qb_invoice.TxnTaxDetail else 0,
                    grand_total=qb_invoice.TotalAmt,
                    message_to_customer=qb_invoice.CustomerMemo,
                    memo=qb_invoice.PrivateNote,
                    payment_mode=None, # You may get this from linked payments
                    supplier_id=db_lpo.supplier_id, # Inherit from LPO
                    project_id=db_lpo.project_id,   # Inherit from LPO
                    created_by_id=db_lpo.created_by_id # Inherit from LPO
                )
                db.add(db_invoice)
                
                # 6. Process Invoice Items
                process_invoice_items(db, qb_client, qb_invoice, db_invoice)
                
                # 7. Process Invoice Attachments
                process_attachments(db, qb_client, blob_service_client, 'Invoice', qb_invoice.Id, db_invoice)
                
                # Commit this one transaction (Invoice + new LPO if any)
                db.commit()
                config.logger.info(f"--- SUCCESSFULLY IMPORTED INVOICE {invoice_number} ---")
                success_count += 1

            except Exception as e:
                config.logger.error(f"--- FAILED to process Invoice {invoice_number}: {e} ---")
                import traceback
                config.logger.error(traceback.format_exc())
                db.rollback() # Roll back changes for this specific invoice
                fail_count += 1
                
    except Exception as e:
        config.logger.critical(f"A critical error occurred: {e}. Rolling back any pending changes.")
        import traceback
        config.logger.critical(traceback.format_exc())
        db.rollback()
    finally:
        db.close()
        config.logger.info("--- Import Process Finished ---")
        config.logger.info(f"Summary: {success_count} Succeeded, {skipped_count} Skipped, {fail_count} Failed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import Invoices and LPOs from QuickBooks.")
    parser.add_argument(
        '--limit', 
        type=int, 
        help='Limit the number of invoices to import for testing.'
    )
    args = parser.parse_args()
    
    process_imports(limit=args.limit)