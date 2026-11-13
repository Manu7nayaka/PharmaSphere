# PharmaSphere — Full-stack academic prototype

A Flask + SQLAlchemy pharmacy storefront with customer accounts, a session cart,
checkout/order history, prescription upload/review, and an admin dashboard.

## Included
- Responsive crimson / black-red / champagne storefront
- Customer registration, login and logout (hashed passwords)
- Product search and category filtering
- Cart with quantity changes and stock checks
- Checkout and order history
- Prescription document upload (PDF/JPG/PNG, 5 MB limit)
- Admin product management, order status updates and prescription review
- SQLite by default; MySQL supported through `DATABASE_URL`
- CSRF protection on POST forms

## Run locally (Windows)

1. Install Python 3.10 or newer.
2. Extract this ZIP.
3. Open the `PharmaSphere_FullStack` folder in VS Code.
4. Open Terminal → New Terminal.
5. Create a virtual environment:

   ```powershell
   py -m venv .venv
   .venv\Scripts\activate
   ```

6. Install packages:

   ```powershell
   pip install -r requirements.txt
   ```

7. Copy `.env.example` to `.env`. Change `SECRET_KEY` and `ADMIN_PASSWORD`.
   For a first local demo, the defaults work, but change them before sharing/deploying.
8. Start the server:

   ```powershell
   python app.py
   ```

9. Open `http://127.0.0.1:5000` in your browser.

## First admin login
The seed admin is created automatically if it does not already exist.

- Email: `admin@pharmasphere.local`
- Password: `ChangeMe123!`

Change these in `.env` before the first run. If the database already exists,
changing the environment password does not reset an existing admin password.

## MySQL setup (optional)

1. Create a database, for example `pharmasphere`.
2. Create a MySQL user and grant it access to that database.
3. Install the dependencies from `requirements.txt`.
4. Set this in `.env`:

   ```env
   DATABASE_URL=mysql+pymysql://username:password@localhost/pharmasphere
   ```

5. Run `python app.py`. SQLAlchemy creates the tables automatically for this prototype.

## Important prototype limitations

- Checkout records an order and offers Cash on Delivery as a demo choice. No real payment is collected.
- Prescription upload/review is a workflow demonstration only. An “Approved” status here is not a legal authorization to dispense medicines.
- Sample catalogue entries are illustrative. This is not a live pharmacy or a substitute for a licensed pharmacist.
- Before any real deployment, obtain legal/compliance review for Indian pharmacy licensing, prescription validation, pharmacist oversight, privacy/data retention, payment security, tax/invoicing, delivery and consumer-protection obligations.
- Replace the development server with a production WSGI server, set `FLASK_DEBUG=0`, use HTTPS, secure secrets, backups, malware scanning for uploads, audit logs, rate limiting and tested database migrations.
