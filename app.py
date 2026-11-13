import re
import os
import uuid
import csv
import io
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask, render_template, redirect, url_for, flash, request,
    session, abort, send_from_directory, jsonify, send_file
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "private_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-secret-key-before-deployment")
database_url = os.getenv("DATABASE_URL", "sqlite:///" + str(BASE_DIR / "pharmasphere.db"))
if database_url.startswith("mysql://"):
    database_url = database_url.replace("mysql://", "mysql+pymysql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = str(UPLOAD_DIR)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["REMEMBER_COOKIE_HTTPONLY"] = True

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to continue."
csrf = CSRFProtect(app)

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}
ORDER_STATUSES = ["Placed", "Processing", "Shipped", "Delivered", "Cancelled"]


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="customer", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, default="")
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    emoji = db.Column(db.String(12), default="✳")
    prescription_required = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class StockMovement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True)
    product_name = db.Column(db.String(150), nullable=False)
    movement_type = db.Column(db.String(30), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    previous_stock = db.Column(db.Integer, nullable=False)
    new_stock = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(255), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    product = db.relationship("Product", backref="stock_movements")


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(24), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    customer_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    address = db.Column(db.Text, nullable=False)
    total = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(30), default="Placed")
    payment_method = db.Column(db.String(40), default="Cash on Delivery")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref="orders")
    items = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan")


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True)
    product_name = db.Column(db.String(150), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)


class Prescription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), unique=True, nullable=False)
    status = db.Column(db.String(30), default="Pending")
    admin_note = db.Column(db.Text, default="")
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)
    user = db.relationship("User", backref="prescriptions")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.context_processor
def inject_globals():
    return {"csrf_token": generate_csrf, "cart_count": sum(session.get("cart", {}).values())}


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_cart_details():
    cart = session.get("cart", {})
    items, total = [], 0
    for product_id, quantity in cart.items():
        product = db.session.get(Product, int(product_id))
        if product and product.active and quantity > 0:
            subtotal = product.price * quantity
            items.append({"product": product, "quantity": quantity, "subtotal": subtotal})
            total += subtotal
    return items, total


@app.route("/")
def home():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    products_query = Product.query.filter_by(active=True)
    if query:
        products_query = products_query.filter(
            db.or_(Product.name.ilike(f"%{query}%"), Product.category.ilike(f"%{query}%"))
        )
    if category:
        products_query = products_query.filter_by(category=category)
    products = products_query.order_by(Product.created_at.desc()).all()
    categories = [row[0] for row in db.session.query(Product.category).filter_by(active=True).distinct().all()]
    return render_template("home.html", products=products, categories=categories, q=query, selected_category=category)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard" if current_user.role == "admin" else "home"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Enter your name, a valid email and a password of at least 8 characters.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(name=name, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Welcome to PharmaSphere. Your account is ready!", "success")
            return redirect(url_for("home"))
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard" if current_user.role == "admin" else "home"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            flash("Welcome back!", "success")
            next_url = request.args.get("next")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("admin_dashboard" if user.role == "admin" else "home"))
        flash("Email or password is incorrect.", "error")
    return render_template("auth.html", mode="login")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("home"))


@app.route("/cart")
def cart():
    items, total = get_cart_details()
    return render_template("cart.html", items=items, total=total)


@app.post("/cart/add/<int:product_id>")
def add_to_cart(product_id):
    product = db.session.get(Product, product_id)

    if not product or not product.active:
        abort(404)

    if product.prescription_required:
        flash(
            "This item requires pharmacist prescription review.",
            "error"
        )
        return redirect(url_for("prescriptions"))

    # Get the page to return to
    next_url = request.form.get("next", "")

    # Allow only local website paths
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = url_for("home")

    cart_data = session.get("cart", {})
    key = str(product_id)
    quantity = int(cart_data.get(key, 0))

    if quantity + 1 > product.stock:
        flash("There is not enough stock available.", "error")
    else:
        cart_data[key] = quantity + 1
        session["cart"] = cart_data
        flash(f"{product.name} added to your bag.", "success")

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({
                "success": True,
                "cart_count": sum(session.get("cart", {}).values()),
                "message": f"{product.name} added to your bag."
            })

    return redirect(next_url)
    


@app.post("/cart/update")
def update_cart():
    cart_data = session.get("cart", {})
    for key in list(cart_data.keys()):
        try:
            quantity = int(request.form.get(f"quantity_{key}", 0))
        except ValueError:
            quantity = 0
        product = db.session.get(Product, int(key))
        if quantity <= 0 or not product:
            cart_data.pop(key, None)
        elif quantity <= product.stock:
            cart_data[key] = quantity
        else:
            flash(f"Only {product.stock} units are available for product #{key}.", "error")
    session["cart"] = cart_data
    return redirect(url_for("cart"))


@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    items, total = get_cart_details()

    if not items:
        flash("Your bag is empty.", "error")
        return redirect(url_for("home"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        payment = request.form.get("payment_method", "Cash on Delivery")

        if not name or not phone or not address:
            flash("Please complete all delivery details.", "error")

        elif not re.fullmatch(r"[A-Za-z ]+", name):
            flash("Name should contain letters and spaces only.", "error")

        elif not re.fullmatch(r"[0-9]{10}", phone):
            flash("Phone number must contain exactly 10 digits.", "error")

        else:
            for row in items:
                if row["quantity"] > row["product"].stock:
                    flash(
                        f"Stock changed for {row['product'].name}. Please update your bag.",
                        "error"
                    )
                    return redirect(url_for("cart"))

            order = Order(
                order_number="PS-" + uuid.uuid4().hex[:10].upper(),
                user_id=current_user.id,
                customer_name=name,
                phone=phone,
                address=address,
                total=total,
                payment_method=payment,
                status="Placed"
            )

            db.session.add(order)

            for row in items:
                product = row["product"]
                previous_stock = product.stock
                product.stock -= row["quantity"]
                db.session.add(StockMovement(
                    product_id=product.id,
                    product_name=product.name,
                    movement_type="Sale",
                    quantity=row["quantity"],
                    previous_stock=previous_stock,
                    new_stock=product.stock,
                    note=f"Order {order.order_number}"
                ))

                db.session.add(OrderItem(
                    order=order,
                    product_id=product.id,
                    product_name=product.name,
                    quantity=row["quantity"],
                    unit_price=product.price
                ))

            db.session.commit()
            session["cart"] = {}

            flash(
                "Order placed successfully! .",
                "success"
            )

            return redirect(url_for("order_detail", order_id=order.id))

    return render_template("checkout.html", items=items, total=total)


@app.route("/orders")
@login_required
def orders():
    user_orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template("orders.html", orders=user_orders)


@app.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        abort(404)
    if current_user.role != "admin" and order.user_id != current_user.id:
        abort(403)
    return render_template("order_detail.html", order=order)


@app.route("/prescriptions", methods=["GET", "POST"])
@login_required
def prescriptions():
    if request.method == "POST":
        file = request.files.get("prescription")
        if not file or not file.filename:
            flash("Choose a prescription file first.", "error")
        elif not allowed_file(file.filename):
            flash("Only PDF, PNG, JPG and JPEG files are accepted.", "error")
        else:
            original = secure_filename(file.filename)[:240]
            stored = uuid.uuid4().hex + "." + original.rsplit(".", 1)[1].lower()
            file.save(UPLOAD_DIR / stored)
            record = Prescription(user_id=current_user.id, original_name=original, stored_name=stored)
            db.session.add(record)
            db.session.commit()
            flash("Prescription uploaded securely for review.", "success")
            return redirect(url_for("prescriptions"))
    records = Prescription.query.filter_by(user_id=current_user.id).order_by(Prescription.uploaded_at.desc()).all()
    return render_template("prescriptions.html", records=records)


@app.route("/admin")
@admin_required
def admin_dashboard():
    stats = {
        "products": Product.query.filter_by(active=True).count(),
        "orders": Order.query.count(),
        "customers": User.query.filter_by(role="customer").count(),
        "pending_rx": Prescription.query.filter_by(status="Pending").count(),
        "revenue": db.session.query(db.func.sum(Order.total)).filter(Order.status != "Cancelled").scalar() or 0,
        "low_stock": Product.query.filter(Product.active.is_(True), Product.stock.between(1, 5)).count(),
        "out_of_stock": Product.query.filter(Product.active.is_(True), Product.stock <= 0).count()
    }

    latest_orders = Order.query.order_by(Order.created_at.desc()).limit(6).all()
    low_stock_products = (
        Product.query.filter(Product.active.is_(True), Product.stock <= 5)
        .order_by(Product.stock.asc(), Product.name.asc()).limit(6).all()
    )

    # Build a simple seven-day order-value chart from non-cancelled orders.
    weekly_sales = []
    today = datetime.utcnow().date()
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        start = datetime.combine(day, datetime.min.time())
        end = start + timedelta(days=1)
        amount = (
            db.session.query(db.func.sum(Order.total))
            .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
            .scalar() or 0
        )
        weekly_sales.append({"label": day.strftime("%a"), "amount": float(amount)})

    chart_max = max((item["amount"] for item in weekly_sales), default=0) or 1
    for item in weekly_sales:
        item["height"] = max(5, round(item["amount"] / chart_max * 100))

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        latest_orders=latest_orders,
        low_stock_products=low_stock_products,
        weekly_sales=weekly_sales
    )


@app.route("/admin/products")
@admin_required
def admin_products():
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("admin/products.html", products=products)


@app.route("/admin/products/new", methods=["GET", "POST"])
@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def product_form(product_id=None):
    product = db.session.get(Product, product_id) if product_id else None
    if product_id and not product:
        abort(404)
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            category = request.form.get("category", "").strip()
            price = float(request.form.get("price", 0))
            stock = int(request.form.get("stock", 0))
            if not name or not category or price < 0 or stock < 0:
                raise ValueError

            is_new = product is None
            previous_stock = 0 if is_new else product.stock
            if is_new:
                product = Product(name=name, category=category, price=price, stock=stock)
                db.session.add(product)
                db.session.flush()

            product.name = name
            product.category = category
            product.description = request.form.get("description", "").strip()
            product.price = price
            product.stock = stock
            product.emoji = request.form.get("emoji", "✳").strip()[:12] or "✳"
            product.prescription_required = request.form.get("prescription_required") == "yes"
            product.active = request.form.get("active") == "yes"

            if stock != previous_stock:
                db.session.add(StockMovement(
                    product_id=product.id,
                    product_name=product.name,
                    movement_type="Opening stock" if is_new else "Adjustment",
                    quantity=abs(stock - previous_stock),
                    previous_stock=previous_stock,
                    new_stock=stock,
                    note="Initial product stock" if is_new else "Stock changed from product editor"
                ))

            db.session.commit()
            flash("Product saved successfully.", "success")
            return redirect(url_for("admin_products"))
        except ValueError:
            db.session.rollback()
            flash("Enter valid product details, price and stock.", "error")
    return render_template("admin/product_form.html", product=product)


@app.route("/admin/inventory", methods=["GET", "POST"])
@admin_required
def admin_inventory():
    if request.method == "POST":
        try:
            product_id = int(request.form.get("product_id", ""))
            quantity = int(request.form.get("quantity", ""))
            movement_type = request.form.get("movement_type", "")
            note = request.form.get("note", "").strip()[:255]
            product = db.session.get(Product, product_id)

            if not product or quantity <= 0 or movement_type not in {"Stock in", "Adjustment"}:
                raise ValueError

            previous_stock = product.stock
            if movement_type == "Stock in":
                product.stock += quantity
            else:
                product.stock = quantity

            db.session.add(StockMovement(
                product_id=product.id,
                product_name=product.name,
                movement_type=movement_type,
                quantity=quantity,
                previous_stock=previous_stock,
                new_stock=product.stock,
                note=note or ("Goods received" if movement_type == "Stock in" else "Manual stock adjustment")
            ))
            db.session.commit()
            flash(f"Inventory updated for {product.name}.", "success")
            return redirect(url_for("admin_inventory"))
        except (TypeError, ValueError):
            db.session.rollback()
            flash("Choose a product and enter a valid positive quantity.", "error")

    products = Product.query.order_by(Product.name.asc()).all()
    movements = StockMovement.query.order_by(StockMovement.created_at.desc()).limit(30).all()
    summary = {
        "total_units": db.session.query(db.func.sum(Product.stock)).filter(Product.active.is_(True)).scalar() or 0,
        "low_stock": Product.query.filter(Product.active.is_(True), Product.stock.between(1, 5)).count(),
        "out_of_stock": Product.query.filter(Product.active.is_(True), Product.stock <= 0).count(),
    }
    return render_template(
        "admin/inventory.html",
        products=products,
        movements=movements,
        summary=summary
    )


@app.get("/admin/inventory/export")
@admin_required
def export_inventory():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Product ID", "Product", "Category", "Price", "Stock", "Stock status", "Visible"])
    for product in Product.query.order_by(Product.name.asc()).all():
        status = "Out of stock" if product.stock <= 0 else ("Low stock" if product.stock <= 5 else "In stock")
        writer.writerow([
            product.id, product.name, product.category, f"{product.price:.2f}",
            product.stock, status, "Yes" if product.active else "No"
        ])
    memory_file = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    memory_file.seek(0)
    return send_file(
        memory_file,
        mimetype="text/csv",
        as_attachment=True,
        download_name="pharmasphere_inventory.csv"
    )


@app.post("/admin/products/<int:product_id>/delete")
@admin_required
def delete_product(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)
    product.active = False
    db.session.commit()
    flash("Product hidden from the customer catalogue.", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/orders")
@admin_required
def admin_orders():
    all_orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template("admin/orders.html", orders=all_orders, statuses=ORDER_STATUSES)


@app.post("/admin/orders/<int:order_id>/status")
@admin_required
def update_order_status(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        abort(404)
    status = request.form.get("status")
    if status not in ORDER_STATUSES:
        abort(400)
    order.status = status
    db.session.commit()
    flash("Order status updated.", "success")
    return redirect(url_for("admin_orders"))


@app.route("/admin/prescriptions")
@admin_required
def admin_prescriptions():
    records = Prescription.query.order_by(Prescription.uploaded_at.desc()).all()
    return render_template("admin/prescriptions.html", records=records)


@app.route("/admin/prescriptions/<int:record_id>/file")
@admin_required
def view_prescription_file(record_id):
    record = db.session.get(Prescription, record_id)
    if not record:
        abort(404)
    return send_from_directory(UPLOAD_DIR, record.stored_name, as_attachment=False)


@app.post("/admin/prescriptions/<int:record_id>/review")
@admin_required
def review_prescription(record_id):
    record = db.session.get(Prescription, record_id)
    if not record:
        abort(404)
    status = request.form.get("status")
    if status not in {"Approved", "Rejected"}:
        abort(400)
    record.status = status
    record.admin_note = request.form.get("admin_note", "").strip()[:1000]
    record.reviewed_at = datetime.utcnow()
    db.session.commit()
    flash("Prescription review saved. This prototype does not authorize dispensing.", "success")
    return redirect(url_for("admin_prescriptions"))


@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, message="You do not have permission to view this page."), 403


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="We couldn't find that page."), 404


def seed_data():
    if not User.query.filter_by(email=os.getenv("ADMIN_EMAIL", "admin@pharmasphere.local")).first():
        admin = User(name="PharmaSphere Admin", email=os.getenv("ADMIN_EMAIL", "admin@pharmasphere.local"), role="admin")
        admin.set_password(os.getenv("ADMIN_PASSWORD", "ChangeMe123!"))
        db.session.add(admin)

    if Product.query.count() == 0:
        sample_products = [
            Product(name="Daily Vitamin C", category="Wellness", description="A bright start to your daily routine.", price=299, stock=40, emoji="🍊"),
            Product(name="Hydration Bottle", category="Daily Essentials", description="Your everyday reminder to hydrate.", price=399, stock=25, emoji="🧴"),
            Product(name="Gentle Face Wash", category="Personal Care", description="A fresh and simple skincare step.", price=249, stock=30, emoji="🫧"),
            Product(name="First Aid Kit", category="First Aid", description="A handy essential for your home.", price=499, stock=20, emoji="🩹"),
            Product(name="Wellness Gummies", category="Wellness", description="A cheerful addition to your routine.", price=349, stock=15, emoji="🍬"),
            Product(name="Digital Thermometer", category="First Aid", description="A useful household health essential.", price=299, stock=18, emoji="🌡️"),
        ]
        db.session.add_all(sample_products)
    db.session.commit()


with app.app_context():
    db.create_all()
    seed_data()


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "1") == "1")
