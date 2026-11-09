# ERP Demo

A modular ERP built with Django and PostgreSQL, covering inventory, purchasing, sales and accounting for a retail/distribution business.

> **Note:** This is a sanitized portfolio version of a commercial project. All branding, credentials and data have been removed or replaced. Any names in the code or tests are fictional.

## Features

| Module | What it does |
|---|---|
| **Product** | Categories, sub-categories and products |
| **Supplier / Warehouse** | Supplier and warehouse management |
| **Purchase** | Purchase orders with adjustments (discounts, charges), stock lots and cost calculation |
| **Transfer** | Stock transfers between warehouses |
| **Sale** | Sales with line items, adjustments and payment tracking |
| **Income / Expense** | Categorized income and expense records |
| **Payment accounts** | Accounts and a transaction ledger kept in sync with purchases, sales, income and expenses |
| **Employees** | Employee records |
| **Company pads** | Company documents that can be released, signed (admin and employee), shared through a public link and exported to PDF |
| **Accounts** | Authentication and user management |

## Design highlights

- **Service layer.** Business rules live in `services.py` modules (`purchase`, `transfer`, `sale`, `income`, `expense`, `payment_account`, `company_pad`), keeping views thin and logic testable.
- **Transaction sync.** Money-moving operations write to the payment-account ledger so balances stay consistent when records are created or edited.
- **Stock lots and costing.** Purchases create stock lots, with dedicated costing tests in `purchase/test_costing.py`.
- **Tests.** Service-level and view-level tests across the main modules.
- **PDF generation** with xhtml2pdf, and server-side DataTables for list pages.
- **Configuration through environment variables** (`django-environ`). No secrets in the repository.

## Tech stack

Python, Django 4.2, PostgreSQL, django-environ, WhiteNoise, Gunicorn, Pillow, xhtml2pdf, Bootstrap-based admin theme, jQuery/DataTables.

## Getting started

```bash
git clone https://github.com/fakhrul-islam849/erp-demo.git
cd erp-demo

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then edit the values
# create an empty PostgreSQL database matching DB_NAME / DB_USER in .env

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Run the tests:

```bash
python manage.py test
```

## Project layout

```
config/          Django settings and root URLs
accounts/        Authentication
product/ supplier/ warehouse/
purchase/ transfer/ sale/
income/ expense/ payment_account/
employees/ company/ company_pad/
templates/ static/
docs/DEV_NOTES.md   Running log of design decisions
```

## Author

MD Fakhrul Islam
