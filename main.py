from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field, condecimal, field_validator
from typing import List
from uuid import uuid4
from sqlalchemy import create_engine, Column, Integer, String, Numeric, ForeignKey, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.future import select

DATABASE_URL = "sqlite:///./invoices.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI()

class InvoiceHeader(Base):
    __tablename__ = "invoice_headers"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    date = Column(String, nullable=False)
    invoice_number = Column(Integer, unique=True, autoincrement=True)
    customer_name = Column(String, nullable=False)
    billing_address = Column(String, nullable=False)
    shipping_address = Column(String, nullable=False)
    gstin = Column(String, nullable=True)
    total_amount = Column(Numeric, nullable=False)
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    billsundries = relationship("InvoiceBillSundry", back_populates="invoice", cascade="all, delete-orphan")

class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    item_name = Column(String, nullable=False)
    quantity = Column(Numeric, nullable=False)
    price = Column(Numeric, nullable=False)
    amount = Column(Numeric, nullable=False)
    invoice_id = Column(String, ForeignKey("invoice_headers.id"))
    invoice = relationship("InvoiceHeader", back_populates="items")

class InvoiceBillSundry(Base):
    __tablename__ = "invoice_billsundry"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    bill_sundry_name = Column(String, nullable=False)
    amount = Column(Numeric, nullable=False)
    invoice_id = Column(String, ForeignKey("invoice_headers.id"))
    invoice = relationship("InvoiceHeader", back_populates="billsundries")

Base.metadata.create_all(bind=engine)

# Pydantic Schemas
class InvoiceItemSchema(BaseModel):
    item_name: str
    quantity: float
    price: float
    amount: float

    @field_validator("amount")
    def validate_amount(cls, v, values):
        if "quantity" in values and "price" in values:
            expected_amount = values["quantity"] * values["price"]
            if v != expected_amount:
                raise ValueError("Amount must be equal to Quantity * Price")
        return v

class InvoiceBillSundrySchema(BaseModel):
    bill_sundry_name: str
    amount: float

class InvoiceHeaderSchema(BaseModel):
    date: str
    customer_name: str
    billing_address: str
    shipping_address: str
    gstin: str
    items: List[InvoiceItemSchema]
    billsundries: List[InvoiceBillSundrySchema]
    total_amount: float

    @field_validator("total_amount")
    def validate_total_amount(cls, v, values):
        item_total = sum(item.amount for item in values.get("items", []))
        billsundry_total = sum(bill.amount for bill in values.get("billsundries", []))
        if v != item_total + billsundry_total:
            raise ValueError("TotalAmount must be the sum of InvoiceItems' and InvoiceBillSundrys' amounts.")
        return v

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/invoices", response_model=InvoiceHeaderSchema)
async def create_invoice(invoice: InvoiceHeaderSchema, db: SessionLocal = Depends(get_db)):
    db_invoice = InvoiceHeader(
        date=invoice.date,
        customer_name=invoice.customer_name,
        billing_address=invoice.billing_address,
        shipping_address=invoice.shipping_address,
        gstin=invoice.gstin,
        total_amount=invoice.total_amount
    )
    db.add(db_invoice)
    db.flush()

    for item in invoice.items:
        db_item = InvoiceItem(
            item_name=item.item_name,
            quantity=item.quantity,
            price=item.price,
            amount=item.amount,
            invoice=db_invoice
        )
        db.add(db_item)

    for bill in invoice.billsundries:
        db_bill = InvoiceBillSundry(
            bill_sundry_name=bill.bill_sundry_name,
            amount=bill.amount,
            invoice=db_invoice
        )
        db.add(db_bill)

    db.commit()
    db.refresh(db_invoice)
    return db_invoice

@app.get("/invoices/{invoice_id}", response_model=InvoiceHeaderSchema)
async def get_invoice(invoice_id: str, db: SessionLocal = Depends(get_db)):
    invoice = db.query(InvoiceHeader).filter(InvoiceHeader.id == invoice_id).first()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice

@app.get("/invoices", response_model=List[InvoiceHeaderSchema])
async def list_invoices(db: SessionLocal = Depends(get_db)):
    invoices = db.query(InvoiceHeader).all()
    return invoices

@app.put("/invoices/{invoice_id}", response_model=InvoiceHeaderSchema)
async def update_invoice(invoice_id: str, invoice: InvoiceHeaderSchema, db: SessionLocal = Depends(get_db)):
    db_invoice = db.query(InvoiceHeader).filter(InvoiceHeader.id == invoice_id).first()
    if db_invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    db_invoice.date = invoice.date
    db_invoice.customer_name = invoice.customer_name
    db_invoice.billing_address = invoice.billing_address
    db_invoice.shipping_address = invoice.shipping_address
    db_invoice.gstin = invoice.gstin
    db_invoice.total_amount = invoice.total_amount

    db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).delete()
    db.query(InvoiceBillSundry).filter(InvoiceBillSundry.invoice_id == invoice_id).delete()

    for item in invoice.items:
        db_item = InvoiceItem(
            item_name=item.item_name,
            quantity=item.quantity,
            price=item.price,
            amount=item.amount,
            invoice=db_invoice
        )
        db.add(db_item)

    for bill in invoice.billsundries:
        db_bill = InvoiceBillSundry(
            bill_sundry_name=bill.bill_sundry_name,
            amount=bill.amount,
            invoice=db_invoice
        )
        db.add(db_bill)

    db.commit()
    db.refresh(db_invoice)
    return db_invoice

@app.delete("/invoices/{invoice_id}")
async def delete_invoice(invoice_id: str, db: SessionLocal = Depends(get_db)):
    invoice = db.query(InvoiceHeader).filter(InvoiceHeader.id == invoice_id).first()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    db.delete(invoice)
    db.commit()
    return {"message": "Invoice deleted successfully"}
