import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, Text, Numeric, ForeignKey, Table
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.sql import func
from config import Base

# --- Association Tables (as defined in your description) ---
# We must define placeholders for tables your models relate to,
# even if we don't use them directly in the import.

lpo_mr_association_table = Table('lpo_mr_association', Base.metadata,
    Column('lpo_id', Integer, ForeignKey('lpos.id'), primary_key=True),
    Column('mr_id', Integer, ForeignKey('material_requisitions.id'), primary_key=True)
)

lpo_item_project_association = Table('lpo_item_project_association', Base.metadata,
    Column('lpo_item_id', Integer, ForeignKey('lpo_items.id'), primary_key=True),
    Column('project_id', Integer, ForeignKey('projects.id'), primary_key=True)
)

# --- Placeholder Models ---
# These are required because your LPO and Invoice models have ForeignKeys to them.
# The import script will find/create a single "default" entry for each.

class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    #username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)

class MaterialRequisition(Base):
    __tablename__ = 'material_requisitions'
    id = Column(Integer, primary_key=True)
    mr_number = Column(String, unique=True, nullable=False)
    # Define the relationship as your LPO model expects it
    supplier_id = Column(Integer, ForeignKey('suppliers.id'))
    supplier = relationship("Supplier", back_populates="requisitions")
    lpos = relationship("LPO", secondary=lpo_mr_association_table, back_populates="material_requisitions")


# --- Your Provided Models ---

class Supplier(Base):
    __tablename__ = 'suppliers'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    requisitions = relationship("MaterialRequisition", back_populates="supplier")
    # Add relationships from Invoice and LPO
    invoices = relationship("Invoice", back_populates="supplier")
    lpos = relationship("LPO", back_populates="supplier")

    def __str__(self) -> str: return self.name

class Material(Base):
    __tablename__ = 'materials'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    unit = Column(String, nullable=False) # e.g., 'nos', 'kg', 'm', 'ton'

    def __str__(self):
        return f"{self.name} ({self.unit})"

class LPO(Base):
    __tablename__ = 'lpos'
    id = Column(Integer, primary_key=True, index=True)
    lpo_number = Column(String, unique=True, nullable=False)
    lpo_date = Column(Date, nullable=False, default=func.current_date())
    status = Column(String, nullable=False, default='Pending') # Pending, Approved, Rejected
    subtotal = Column(Numeric(12, 2), nullable=True)
    tax_total = Column(Numeric(12, 2), nullable=True)
    grand_total = Column(Numeric(12, 2), nullable=True)
    message_to_supplier = Column(Text, nullable=True)
    memo = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    payment_mode = Column(String, nullable=True)

    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=False)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    created_by_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    supplier = relationship("Supplier", back_populates="lpos")
    project = relationship("Project")
    created_by = relationship("User")
    items = relationship("LPOItem", back_populates="lpo", cascade="all, delete-orphan")
    attachments = relationship("LPOAttachment", back_populates="lpo", cascade="all, delete-orphan")
    material_requisitions = relationship("MaterialRequisition", secondary=lpo_mr_association_table, back_populates="lpos")

class LPOItem(Base):
    __tablename__ = 'lpo_items'
    id = Column(Integer, primary_key=True, index=True)
    description = Column(Text, nullable=True)
    quantity = Column(Numeric(10, 2), nullable=False)
    rate = Column(Numeric(10, 2), nullable=False)
    tax_rate = Column(Numeric(4, 2), default=0.00) 

    lpo_id = Column(Integer, ForeignKey('lpos.id'), nullable=False)
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=False)

    lpo = relationship("LPO", back_populates="items")
    material = relationship("Material")
    projects = relationship("Project", secondary=lpo_item_project_association)

class LPOAttachment(Base):
    __tablename__ = 'lpo_attachments'
    id = Column(Integer, primary_key=True, index=True)
    blob_url = Column(String, nullable=False)
    file_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())
    lpo_id = Column(Integer, ForeignKey('lpos.id'), nullable=True)

    lpo = relationship("LPO", back_populates="attachments")

class Invoice(Base):
    __tablename__ = 'invoices'
    id = Column(Integer, primary_key=True, index=True)
    
    invoice_number = Column(String, unique=True, nullable=False)
    invoice_date = Column(Date, nullable=False, default=func.current_date())
    invoice_due_date = Column(Date, nullable=False, default=lambda: datetime.date.today() + datetime.timedelta(days=30))
    lpo_id = Column(Integer, ForeignKey('lpos.id'), nullable=True) # Link to LPO
    
    status = Column(String, nullable=False, default='Pending') # e.g., Pending, Paid
    subtotal = Column(Numeric(12, 2), nullable=True)
    tax_total = Column(Numeric(12, 2), nullable=True)
    grand_total = Column(Numeric(12, 2), nullable=True)
    message_to_customer = Column(Text, nullable=True) 
    memo = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    payment_mode = Column(String, nullable=True)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=False)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    created_by_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    lpo = relationship("LPO")
    supplier = relationship("Supplier", back_populates="invoices")
    project = relationship("Project")
    created_by = relationship("User")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    attachments = relationship("InvoiceAttachment", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base):
    __tablename__ = 'invoice_items'
    id = Column(Integer, primary_key=True, index=True)
    
    description = Column(Text, nullable=True)
    quantity = Column(Numeric(10, 2), nullable=False)
    rate = Column(Numeric(10, 2), nullable=False)
    tax_rate = Column(Numeric(4, 2), default=0.00)
    
    item_class = Column(String, nullable=True)
    customer_project = Column(String, nullable=True) 

    invoice_id = Column(Integer, ForeignKey('invoices.id'), nullable=False)
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=False)
    
    invoice = relationship("Invoice", back_populates="items")
    material = relationship("Material")

class InvoiceAttachment(Base):
    __tablename__ = 'invoice_attachments'
    id = Column(Integer, primary_key=True, index=True)
    blob_url = Column(String, nullable=False)
    file_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())
    
    invoice_id = Column(Integer, ForeignKey('invoices.id'), nullable=True)
    invoice = relationship("Invoice", back_populates="attachments")