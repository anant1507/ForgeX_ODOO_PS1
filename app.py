# forgeX

import datetime
import random
from functools import wraps
import io
from flask import send_file
from openpyxl import Workbook
from weasyprint import HTML
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from datetime import date, timedelta


app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-very-secret-key-that-should-be-changed'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///forgex.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'anantmann157@gmail.com'
app.config['MAIL_PASSWORD'] = 'kazxxplvznckegsn'
app.config['MAIL_DEFAULT_SENDER'] = 'anantmann157@gmail.com'

db = SQLAlchemy(app)
mail = Mail(app)


MANAGER_SECRET_CODE = "FORGEX_MGR_2025"


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(20), nullable=False)
    secret_code = db.Column(db.String(100), nullable=True)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    orders = db.relationship('CustomerOrder', backref='customer', lazy=True)

class Product(db.Model):
    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sku = db.Column(db.String(50), unique=True, nullable=False)
    finished_stock = db.Column(db.Integer, default=0)
    bom_items = db.relationship('BomItem', backref='product', lazy=True, cascade="all, delete-orphan")

    @property
    def bom_cost(self):
        return sum(item.quantity * item.material.price for item in self.bom_items if item.material and item.material.price)

class RawMaterial(db.Model):
    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    stock = db.Column(db.Float, default=0)
    unit = db.Column(db.String(20))
    price = db.Column(db.Float, default=0)

class BomItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quantity = db.Column(db.Float, nullable=False)
    operation = db.Column(db.String(100))
    operation_duration = db.Column(db.Float, nullable=True)
    product_id = db.Column(db.String(50), db.ForeignKey('product.id'), nullable=False)
    material_id = db.Column(db.String(50), db.ForeignKey('raw_material.id'), nullable=False)
    material = db.relationship('RawMaterial')

class CustomerOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_name = db.Column(db.String(100), nullable=False)
    is_custom = db.Column(db.Boolean, default=False)
    description = db.Column(db.Text, nullable=True)
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    manufacturing_order_id = db.Column(db.Integer, db.ForeignKey('manufacturing_order.id'), nullable=True)
    manufacturing_order = db.relationship('ManufacturingOrder', backref='customer_order', uselist=False)

class ManufacturingOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.String(50), db.ForeignKey('product.id'), nullable=False)
    product = db.relationship('Product')
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), default='Planned')
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    work_orders = db.relationship('WorkOrder', backref='manufacturing_order', lazy=True, cascade="all, delete-orphan")

class WorkOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mo_id = db.Column(db.Integer, db.ForeignKey('manufacturing_order.id'), nullable=False)
    operation = db.Column(db.String(100))
    status = db.Column(db.String(50), default='Pending')
    material_id = db.Column(db.String(50), db.ForeignKey('raw_material.id'))
    material = db.relationship('RawMaterial')
    required_qty = db.Column(db.Float)
    work_center_id = db.Column(db.String(50), db.ForeignKey('work_center.id'), nullable=True)
    work_center = db.relationship('WorkCenter')
    expected_duration = db.Column(db.Float, nullable=True)
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)

    @property
    def real_duration(self):
        if self.start_time and self.end_time:
            return round((self.end_time - self.start_time).total_seconds() / 3600, 2)
        elif self.start_time:
            return round((datetime.datetime.utcnow() - self.start_time).total_seconds() / 3600, 2)
        return None
    
    @property
    def customer_status(self):
        if self.status == 'Done': return "Completed"
        if self.status == 'In Progress':
            if self.expected_duration and self.real_duration and self.real_duration > self.expected_duration: return "Delayed"
            return "In Progress"
        return "Queued"

class WorkCenter(db.Model):
    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(200), nullable=True)
    hourly_cost = db.Column(db.Float, nullable=True)

class StockLedger(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    item_id = db.Column(db.String(50), nullable=False)
    item_name = db.Column(db.String(100))
    change = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(200))


def get_throughput_data(base_query):
    labels = [(date.today() - timedelta(days=i)).strftime("%b %d") for i in range(6, -1, -1)]
    product_throughput = {}
    completed_wos = base_query.filter(WorkOrder.status == 'Done', WorkOrder.end_time >= date.today() - timedelta(days=7)).all()
    for wo in completed_wos:
        product_name = wo.manufacturing_order.product.name
        if product_name not in product_throughput:
            product_throughput[product_name] = [0] * 7
        try:
            day_str = wo.end_time.strftime("%b %d")
            idx = labels.index(day_str)
            product_throughput[product_name][idx] += 1
        except (ValueError, AttributeError):
            continue
    datasets = []
    colors = ['#0d6efd', '#6f42c1', '#d63384', '#fd7e14', '#198754', '#20c997', '#dc3545', '#ffc107', '#0dcaf0', '#6c757d']
    for i, (name, data) in enumerate(product_throughput.items()):
        color = colors[i % len(colors)]
        datasets.append({'label': name, 'data': data, 'borderColor': color, 'tension': 0.1, 'fill': False})
    return {'labels': labels, 'datasets': datasets}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        user = User.query.filter_by(username=session['username']).first()
        if not user:
            session.clear()
            flash("Your login session was invalid. Please log in again.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(required_role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get('role') != required_role:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def send_otp_email(recipient_email, otp):
    try:
        msg = Message('Your ForgeX Verification Code', recipients=[recipient_email])
        msg.body = f'Your ForgeX verification code is: {otp}'
        mail.send(msg)
    except Exception as e:
        print(f"Error sending email: {e}")
        print(f"--- FALLBACK OTP for {recipient_email}: {otp} ---")


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if 'username' in session: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')

        
        if User.query.filter_by(username=username).first():
            flash('That username is already taken. Please choose a different one.', 'danger')
            return redirect(url_for('signup'))
        if User.query.filter_by(email=email).first():
            flash('That email address is already in use. Please use a different one.', 'danger')
            return redirect(url_for('signup'))
        

        role, secret_code = request.form['role'], None
        if role == 'manager':
            secret_code = request.form.get('secret_code')
            if secret_code != MANAGER_SECRET_CODE:
                flash('Invalid Manager Secret Code.', 'danger')
                return render_template('signup.html')
                
        new_user = User(
            username=username, 
            password=generate_password_hash(request.form['password']), 
            name=request.form['name'], 
            role=role, 
            secret_code=secret_code, 
            email=email, 
            is_verified=False
        )
        db.session.add(new_user)
        db.session.commit()
        
        otp = random.randint(100000, 999999)
        session['otp_for_verification'], session['username_for_verification'] = otp, username
        send_otp_email(email, otp)
        
        flash('Account created! Please verify with the OTP sent to your email.', 'info')
        return redirect(url_for('verify_account'))
        
    return render_template('signup.html')

@app.route('/verify', methods=['GET', 'POST'])
def verify_account():
    if 'username_for_verification' not in session: return redirect(url_for('signup'))
    if request.method == 'POST':
        if int(request.form.get('otp', 0)) == session.get('otp_for_verification'):
            user = User.query.filter_by(username=session['username_for_verification']).first()
            if user:
                user.is_verified = True
                db.session.commit()
            session.pop('otp_for_verification', None)
            session.pop('username_for_verification', None)
            flash('Account successfully verified! You may now log in.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Invalid OTP. Please try again.', 'danger')
    return render_template('verify.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session: return redirect(url_for('index'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            if not user.is_verified:
                otp = random.randint(100000, 999999)
                session['otp_for_verification'], session['username_for_verification'] = otp, user.username
                send_otp_email(user.email, otp)
                flash('Your account is not verified. A new OTP has been sent to your email.', 'warning')
                return redirect(url_for('verify_account'))
            session['username'], session['role'] = user.username, user.role
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

@app.route('/request_password_reset', methods=['POST'])
def request_password_reset():
    email = request.form['email']
    user = User.query.filter_by(email=email).first()
    if user:
        otp = random.randint(100000, 999999)
        session['otp_for_reset'] = otp
        session['email_for_reset'] = email
        send_otp_email(email, otp)
        flash(f"A password reset OTP has been sent to {email}.", "info")
        return redirect(url_for('reset_with_otp'))
    else:
        flash("Email address not found.", "danger")
        return redirect(url_for('login'))

@app.route('/reset_with_otp', methods=['GET', 'POST'])
def reset_with_otp():
    if 'email_for_reset' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        user_otp = int(request.form.get('otp', 0))
        if user_otp == session.get('otp_for_reset'):
            user = User.query.filter_by(email=session['email_for_reset']).first()
            if user:
                new_password = request.form['password']
                user.password = generate_password_hash(new_password)
                db.session.commit()
                session.pop('otp_for_reset', None); session.pop('email_for_reset', None)
                flash("Password updated successfully! You can now log in.", "success")
                return redirect(url_for('login'))
        else:
            flash("Invalid OTP. Please try again.", "danger")
    return render_template('reset_with_otp.html')


@app.route('/')
@login_required
def index():
    return redirect(url_for('manager_dashboard' if session.get('role') == 'manager' else 'customer_dashboard'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = User.query.filter_by(username=session['username']).first()
    if request.method == 'POST':
        user.name = request.form['name']
        new_password = request.form.get('password')
        if new_password: user.password = generate_password_hash(new_password)
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=user)

@app.route('/search')
@login_required
def search():
    query = request.args.get('q', '').lower()
    page_keywords = {
        'home': 'index', 'dashboard': 'index', 'order': 'my_orders', 'orders': 'my_orders',
        'product': 'products_customer', 'products': 'products_customer', 'manufacture': 'products_customer',
        'work order': 'my_work_orders', 'work orders': 'my_work_orders',
        'bom': 'customer_bill_of_materials', 'bill of materials': 'customer_bill_of_materials',
        'work center': 'customer_work_centers', 'work centers': 'customer_work_centers',
        'stock': 'customer_stock_ledger', 'ledger': 'customer_stock_ledger', 'profile': 'profile',
        'manager': 'manager_dashboard', 'customer orders': 'customer_orders_manager'
    }
    if query in page_keywords:
        endpoint = page_keywords[query]
        if session['role'] == 'customer':
            if endpoint in ['manager_dashboard', 'customer_orders_manager']:
                flash("You do not have permission to access that page.", "warning")
                return redirect(url_for('customer_dashboard'))
        elif session['role'] == 'manager':
            if endpoint in ['my_orders', 'my_work_orders', 'customer_bill_of_materials', 'customer_work_centers', 'customer_stock_ledger']:
                 flash("Redirecting to the manager equivalent page.", "info")
                 if 'order' in query: endpoint = 'customer_orders_manager'
                 elif 'work' in query: endpoint = 'work_orders'
                 elif 'bom' in query or 'bill' in query: endpoint = 'bill_of_materials'
                 elif 'center' in query: endpoint = 'work_centers'
                 elif 'stock' in query: endpoint = 'stock_ledger'
        return redirect(url_for(endpoint))
    product_results = Product.query.filter(Product.name.ilike(f'%{query}%')).all()
    return render_template('search_results.html', query=query, products=product_results)

@app.route('/order/delete/<int:order_id>')
@login_required
def delete_order(order_id):
    order_to_delete = CustomerOrder.query.get_or_404(order_id)
    user = User.query.filter_by(username=session['username']).first()
    if order_to_delete.customer_id != user.id and session['role'] != 'manager':
        flash("You do not have permission to delete this order.", "danger")
    elif order_to_delete.status in ['Pending', 'Pending Quote']:
        db.session.delete(order_to_delete)
        db.session.commit()
        flash(f"Order #{order_id} has been successfully canceled.", "success")
    else:
        flash("This order can no longer be canceled.", "warning")
    return redirect(url_for('customer_orders_manager' if session['role'] == 'manager' else 'my_orders'))


@app.route('/dashboard/customer')
@login_required
@role_required('customer')
def customer_dashboard():
    user = User.query.filter_by(username=session['username']).first()
    mo_ids = [order.manufacturing_order_id for order in user.orders if order.manufacturing_order_id]
    base_query = WorkOrder.query.filter(WorkOrder.mo_id.in_(mo_ids)) if mo_ids else WorkOrder.query.filter(db.false())
    throughput = get_throughput_data(base_query)
    on_time_count, delayed_count = 0, 0
    completed_wos = base_query.filter(WorkOrder.status == 'Done').all()
    for wo in completed_wos:
        if wo.expected_duration and wo.real_duration and wo.real_duration > wo.expected_duration:
            delayed_count += 1
        else:
            on_time_count += 1
    analytics_data = {'throughput': throughput, 'delays': {'on_time': on_time_count, 'delayed': delayed_count}}
    recent_orders = CustomerOrder.query.filter_by(customer_id=user.id).order_by(CustomerOrder.created_at.desc()).limit(5).all()
    return render_template('customer_dashboard.html', analytics_data=analytics_data, recent_orders=recent_orders)

@app.route('/my_work_orders')
@login_required
@role_required('customer')
def my_work_orders():
    user = User.query.filter_by(username=session['username']).first()
    customer_orders_with_mo = CustomerOrder.query.filter(CustomerOrder.customer_id == user.id, CustomerOrder.manufacturing_order_id.isnot(None)).all()
    mo_ids = [order.manufacturing_order_id for order in customer_orders_with_mo]
    work_orders = WorkOrder.query.filter(WorkOrder.mo_id.in_(mo_ids)).order_by(WorkOrder.id).all()
    return render_template('my_work_orders.html', work_orders=work_orders)

@app.route('/customer_boms')
@login_required
@role_required('customer')
def customer_bill_of_materials():
    products = Product.query.options(db.joinedload(Product.bom_items).joinedload(BomItem.material)).order_by(Product.id).all()
    return render_template('customer_bill_of_materials.html', products=products)

@app.route('/customer_work_centers')
@login_required
@role_required('customer')
def customer_work_centers():
    work_centers = WorkCenter.query.order_by(WorkCenter.id).all()
    return render_template('customer_work_centers.html', work_centers=work_centers)

@app.route('/customer_stock_ledger')
@login_required
@role_required('customer')
def customer_stock_ledger():
    products = Product.query.order_by(Product.name).all()
    stock_data = []
    for product in products:
        incoming_qty = db.session.query(db.func.sum(ManufacturingOrder.quantity)).filter(
            ManufacturingOrder.product_id == product.id, ManufacturingOrder.status != 'Done').scalar() or 0
        outgoing_qty = db.session.query(db.func.sum(CustomerOrder.quantity)).filter(
            CustomerOrder.product_name == product.name, CustomerOrder.status.in_(['Accepted', 'In Production'])).scalar() or 0
        stock_data.append({'product': product, 'incoming': incoming_qty, 'outgoing': outgoing_qty})
    return render_template('customer_stock_ledger.html', stock_data=stock_data)

@app.route('/products/customer')
@login_required
@role_required('customer')
def products_customer():
    products, materials = Product.query.all(), RawMaterial.query.all()
    return render_template('products_customer.html', products=products, materials=materials)

@app.route('/my_orders')
@login_required
@role_required('customer')
def my_orders():
    user = User.query.filter_by(username=session['username']).first()
    orders = CustomerOrder.query.filter_by(customer_id=user.id).order_by(CustomerOrder.created_at.desc()).all()
    return render_template('my_orders.html', orders=orders)

@app.route('/order/place', methods=['POST'])
@login_required
@role_required('customer')
def place_order():
    user = User.query.filter_by(username=session['username']).first()
    product = Product.query.get_or_404(request.form['product_id'])
    new_order = CustomerOrder(customer_id=user.id, product_name=product.name, quantity=int(request.form['quantity']))
    db.session.add(new_order)
    db.session.commit()
    flash('Your order has been placed!', 'success')
    return redirect(url_for('my_orders'))

@app.route('/order/place_custom', methods=['POST'])
@login_required
@role_required('customer')
def place_custom_order():
    user = User.query.filter_by(username=session['username']).first()
    new_order = CustomerOrder(customer_id=user.id, product_name=request.form['product_name'], quantity=int(request.form['quantity']), description=request.form['description'], is_custom=True, status='Pending Quote')
    db.session.add(new_order)
    db.session.commit()
    flash('Your custom product request has been submitted!', 'success')
    return redirect(url_for('my_orders'))


@app.route('/dashboard/manager')
@login_required
@role_required('manager')
def manager_dashboard():
    base_query = WorkOrder.query.join(ManufacturingOrder).join(Product)
    throughput = get_throughput_data(base_query)
    completed_wos = WorkOrder.query.filter_by(status='Done').all()
    on_time_count = sum(1 for wo in completed_wos if not (wo.expected_duration and wo.real_duration and wo.real_duration > wo.expected_duration))
    delayed_count = len(completed_wos) - on_time_count
    work_centers = WorkCenter.query.all()
    utilization_labels = [wc.name for wc in work_centers]
    utilization_data = []
    for wc in work_centers:
        completed_wos_for_wc = WorkOrder.query.filter(WorkOrder.work_center_id == wc.id, WorkOrder.status == 'Done', WorkOrder.end_time >= date.today() - timedelta(days=7)).all()
        total_hours_worked = sum(wo.real_duration for wo in completed_wos_for_wc if wo.real_duration)
        utilization_percent = (total_hours_worked / (8 * 7)) * 100 if total_hours_worked > 0 else 0
        utilization_data.append(round(utilization_percent, 2))
    analytics_data = {'throughput': throughput, 'delays': {'on_time': on_time_count, 'delayed': delayed_count}, 'utilization': {'labels': utilization_labels, 'data': utilization_data}}
    recent_pending_orders = CustomerOrder.query.filter(CustomerOrder.status.in_(['Pending', 'Pending Quote'])).order_by(CustomerOrder.created_at.desc()).limit(5).all()
    return render_template('manager_dashboard.html', analytics_data=analytics_data, recent_pending_orders=recent_pending_orders)

@app.route('/customer_orders/manager')
@login_required
@role_required('manager')
def customer_orders_manager():
    products = Product.query.order_by(Product.name).all()
    orders = CustomerOrder.query.options(db.joinedload(CustomerOrder.customer)).order_by(CustomerOrder.created_at.desc()).all()
    return render_template('customer_orders_manager.html', orders=orders, products=products)

@app.route('/bill_of_materials')
@login_required
@role_required('manager')
def bill_of_materials():
    products = Product.query.options(db.joinedload(Product.bom_items).joinedload(BomItem.material)).order_by(Product.id).all()
    materials = RawMaterial.query.order_by(RawMaterial.id).all()
    return render_template('bill_of_materials.html', products=products, materials=materials)

@app.route('/product/bom/add/<prod_id>', methods=['POST'])
@login_required
@role_required('manager')
def add_bom_item(prod_id):
    product = Product.query.get_or_404(prod_id)
    new_bom_item = BomItem(product_id=product.id, material_id=request.form['material_id'], quantity=float(request.form['quantity']), operation=request.form['operation'], operation_duration=float(request.form['duration']))
    db.session.add(new_bom_item)
    db.session.commit()
    flash("BOM item added.", "success")
    return redirect(url_for('bill_of_materials'))

@app.route('/customer_order/<int:order_id>/create_mo', methods=['POST'])
@login_required
@role_required('manager')
def create_mo_from_co(order_id):
    customer_order = CustomerOrder.query.get_or_404(order_id)
    product_id = request.form.get('product_id')
    if not product_id:
        flash('You must select a product to manufacture.', 'danger')
        return redirect(url_for('customer_orders_manager'))
    product = Product.query.get_or_404(product_id)
    if not product.bom_items:
        flash(f'Product {product.name} has no Bill of Materials. Cannot create MO.', 'warning')
        return redirect(url_for('customer_orders_manager'))
    new_mo = ManufacturingOrder(product_id=product.id, quantity=customer_order.quantity)
    db.session.add(new_mo)
    db.session.flush()
    customer_order.manufacturing_order_id = new_mo.id
    customer_order.status = 'In Production'
    for bom_item in product.bom_items:
        new_wo = WorkOrder(mo_id=new_mo.id, operation=bom_item.operation, material_id=bom_item.material_id, required_qty=bom_item.quantity * customer_order.quantity, expected_duration=bom_item.operation_duration)
        db.session.add(new_wo)
    db.session.commit()
    flash(f"Manufacturing Order MO-{new_mo.id} created for Customer Order #{customer_order.id}.", "success")
    return redirect(url_for('customer_orders_manager'))

@app.route('/work_order/<int:wo_id>/update_status', methods=['POST'])
@login_required
@role_required('manager')
def update_wo_status(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    new_status = request.form.get('status')
    if new_status == 'In Progress':
        wo.status = 'In Progress'
        wo.start_time = datetime.datetime.utcnow()
        wo.work_center_id = request.form.get('work_center_id')
    elif new_status == 'Done':
        wo.status = 'Done'
        wo.end_time = datetime.datetime.utcnow()
    db.session.commit()
    flash(f'Work Order WO-{wo.id} status updated to {wo.status}.', 'info')
    return redirect(url_for('work_orders'))

@app.route('/products/manager')
@login_required
@role_required('manager')
def products_manager():
    products = Product.query.order_by(Product.id).all()
    materials = RawMaterial.query.order_by(RawMaterial.id).all()
    return render_template('products_manager.html', products=products, materials=materials)

@app.route('/material/add', methods=['POST'])
@login_required
@role_required('manager')
def add_material():
    mat_id = request.form['id'].upper()
    if RawMaterial.query.get(mat_id):
        flash(f"Raw Material ID {mat_id} already exists.", "danger")
    else:
        new_material = RawMaterial(
            id=mat_id,
            name=request.form['name'],
            stock=float(request.form.get('stock', 0)),
            unit=request.form['unit'],
            price=float(request.form.get('price', 0))
        )
        db.session.add(new_material)
        db.session.commit()
        flash(f"Raw Material '{new_material.name}' added successfully.", "success")
    return redirect(url_for('bill_of_materials'))

@app.route('/stock/adjust', methods=['POST'])
@login_required
@role_required('manager')
def adjust_stock():
    material_id = request.form.get('material_id')
    change_str = request.form.get('change')
    reason = request.form.get('reason')

    if not all([material_id, change_str, reason]):
        flash("All fields are required for a stock adjustment.", "danger")
        return redirect(url_for('stock_ledger'))

    try:
        change_amount = float(change_str)
    except ValueError:
        flash("Invalid change amount. Please enter a number.", "danger")
        return redirect(url_for('stock_ledger'))

    material = RawMaterial.query.get(material_id)
    if not material:
        flash("Selected raw material not found.", "danger")
        return redirect(url_for('stock_ledger'))

    
    material.stock += change_amount
    
    
    ledger_entry = StockLedger(
        item_id=material.id,
        item_name=material.name,
        change=change_amount,
        reason=f"Manual Adjustment: {reason}"
    )
    
    db.session.add(ledger_entry)
    db.session.commit()
    
    flash(f"Stock for '{material.name}' adjusted by {change_amount} {material.unit}.", "success")
    return redirect(url_for('stock_ledger'))

@app.route('/order/edit/<int:order_id>', methods=['GET', 'POST'])
@login_required
@role_required('customer')
def edit_order(order_id):
    order_to_edit = CustomerOrder.query.get_or_404(order_id)
    user = User.query.filter_by(username=session['username']).first()

    
    if order_to_edit.customer_id != user.id:
        flash("You do not have permission to edit this order.", "danger")
        return redirect(url_for('my_orders'))
    
    if order_to_edit.status not in ['Pending', 'Pending Quote']:
        flash("This order can no longer be edited as it is already in process.", "warning")
        return redirect(url_for('my_orders'))

    if request.method == 'POST':
        
        new_quantity = request.form.get('quantity')
        if new_quantity:
            order_to_edit.quantity = int(new_quantity)

        
        if order_to_edit.is_custom:
            order_to_edit.product_name = request.form.get('product_name')
            order_to_edit.description = request.form.get('description')
        
        db.session.commit()
        flash(f"Order #{order_to_edit.id} has been updated successfully.", "success")
        return redirect(url_for('my_orders'))

    
    return render_template('edit_order.html', order=order_to_edit)

@app.route('/product/add', methods=['POST'])
@login_required
@role_required('manager')
def add_product():
    prod_id = request.form['id'].upper()
    if Product.query.get(prod_id):
        flash(f"Product ID {prod_id} already exists.", "danger")
    else:
        new_product = Product(id=prod_id, name=request.form['name'], sku=request.form['sku'])
        db.session.add(new_product)
        db.session.commit()
        flash(f"Product {prod_id} added successfully.", "success")
    return redirect(url_for('bill_of_materials'))

@app.route('/manufacturing_orders')
@login_required
@role_required('manager')
def manufacturing_orders():
    mos = ManufacturingOrder.query.order_by(ManufacturingOrder.created_at.desc()).all()
    products = Product.query.all()
    return render_template('manufacturing_orders.html', mos=mos, products=products)

@app.route('/work_orders')
@login_required
@role_required('manager')
def work_orders():
    wos = WorkOrder.query.options(db.joinedload(WorkOrder.manufacturing_order).joinedload(ManufacturingOrder.product)).order_by(WorkOrder.id.desc()).all()
    work_centers = {wc.id: wc for wc in WorkCenter.query.all()}
    return render_template('work_orders.html', wos=wos, work_centers=work_centers)

@app.route('/work_centers')
@login_required
@role_required('manager')
def work_centers():
    work_centers = WorkCenter.query.order_by(WorkCenter.id).all()
    return render_template('work_centers.html', work_centers=work_centers)

@app.route('/work_center/add', methods=['POST'])
@login_required
@role_required('manager')
def add_work_center():
    wc_id = request.form['id'].upper()
    if WorkCenter.query.get(wc_id):
        flash(f"Work Center {wc_id} already exists.", "danger")
    else:
        new_wc = WorkCenter(id=wc_id, name=request.form['name'], location=request.form['location'], hourly_cost=float(request.form['hourly_cost']))
        db.session.add(new_wc)
        db.session.commit()
        flash(f"Work Center {wc_id} added.", "success")
    return redirect(url_for('work_centers'))

@app.route('/stock_ledger')
@login_required
@role_required('manager')
def stock_ledger():
    materials = RawMaterial.query.order_by(RawMaterial.id).all()
    ledger_entries = StockLedger.query.order_by(StockLedger.timestamp.desc()).all()
    return render_template('stock_ledger.html', materials=materials, ledger=ledger_entries)


def generate_report_excel(headers, data_rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in data_rows: sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer

def generate_report_pdf(title, headers, data_rows):
    today_date = date.today().strftime('%Y-%m-%d')
    html_out = render_template('reports/report_template.html', title=title, headers=headers, data=data_rows, today_date=today_date)
    pdf = HTML(string=html_out).write_pdf()
    buffer = io.BytesIO(pdf)
    buffer.seek(0)
    return buffer

@app.route('/export/<report_name>/<file_format>')
@login_required
def export_report(report_name, file_format):
    user = User.query.filter_by(username=session['username']).first()
    title, headers, data_rows = "", [], []
    if report_name == 'customer_orders':
        title = "Customer Orders Report"
        headers = ["Order ID", "Customer", "Product", "Qty", "Status", "Date"]
        query = CustomerOrder.query.options(db.joinedload(CustomerOrder.customer)).order_by(CustomerOrder.created_at.desc())
        if session['role'] == 'customer':
            query = query.filter_by(customer_id=user.id)
        orders = query.all()
        data_rows = [[o.id, o.customer.name, o.product_name, o.quantity, o.status, o.created_at.strftime('%Y-%m-%d')] for o in orders]
    elif report_name == 'work_centers' and session['role'] == 'manager':
        title = "Work Centers Report"
        headers = ["ID", "Name", "Location", "Hourly Cost"]
        centers = WorkCenter.query.order_by(WorkCenter.id).all()
        data_rows = [[c.id, c.name, c.location, f"Rs.{c.hourly_cost:.2f}"] for c in centers]
    else:
        flash("Unknown report type or insufficient permissions.", "danger")
        return redirect(url_for('index'))
    filename = f"{report_name}_{date.today()}.{file_format}"
    if file_format == 'xlsx':
        buffer = generate_report_excel(headers, data_rows)
        return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    elif file_format == 'pdf':
        buffer = generate_report_pdf(title, headers, data_rows)
        return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            print("Populating initial data...")
            admin_user = User(username='admin', password=generate_password_hash('admin123'), name='Admin Manager', role='manager', secret_code=MANAGER_SECRET_CODE, is_verified=True, email='admin@forgex.com')
            customer_user = User(username='customer', password=generate_password_hash('cust123'), name='Test Customer', role='customer', is_verified=True, email='customer@forgex.com')
            db.session.add_all([admin_user, customer_user])
            work_centers_data = [
                {'id': 'WC01', 'name': 'CNC Milling Station', 'location': 'Bay A1', 'hourly_cost': 75.50},
                {'id': 'WC02', 'name': 'Robotic Assembly Line', 'location': 'Bay A2', 'hourly_cost': 120.00},
                {'id': 'WC03', 'name': 'Quality Assurance Lab', 'location': 'Clean Room B', 'hourly_cost': 60.00},
                {'id': 'WC04', 'name': '3D Printing Farm', 'location': 'Prototyping Lab', 'hourly_cost': 85.00},
                {'id': 'WC05', 'name': 'Sheet Metal Fabrication', 'location': 'Bay C1', 'hourly_cost': 65.75},
                {'id': 'WC06', 'name': 'Electronics Soldering Bench', 'location': 'Clean Room A', 'hourly_cost': 55.00},
                {'id': 'WC07', 'name': 'Hydraulic Press', 'location': 'Heavy Works, Floor 1', 'hourly_cost': 95.20},
                {'id': 'WC08', 'name': 'Painting and Finishing', 'location': 'Ventilated Room D', 'hourly_cost': 45.00},
                {'id': 'WC09', 'name': 'Casting and Molding', 'location': 'Foundry', 'hourly_cost': 110.50},
                {'id': 'WC10', 'name': 'Packaging Station', 'location': 'Shipping Dept', 'hourly_cost': 30.00},
                {'id': 'WC11', 'name': 'Laser Cutting Unit', 'location': 'Bay C2', 'hourly_cost': 150.00},
                {'id': 'WC12', 'name': 'Final Calibration Stand', 'location': 'Clean Room B', 'hourly_cost': 70.00}
            ]
            for wc_data in work_centers_data: db.session.add(WorkCenter(**wc_data))
            materials_data = [
                {'id': 'STEEL-P', 'name': 'Steel Plate', 'stock': 1000, 'unit': 'sq ft', 'price': 15.50},
                {'id': 'ALUM-R', 'name': 'Aluminum Rod', 'stock': 500, 'unit': 'meters', 'price': 8.20},
                {'id': 'COPP-W', 'name': 'Copper Wire', 'stock': 2000, 'unit': 'meters', 'price': 2.75},
                {'id': 'PLAS-C', 'name': 'Plastic Casing', 'stock': 5000, 'unit': 'units', 'price': 1.50},
                {'id': 'MICRO-C', 'name': 'Microcontroller', 'stock': 1500, 'unit': 'units', 'price': 12.00},
                {'id': 'LCD-S', 'name': 'LCD Screen', 'stock': 800, 'unit': 'units', 'price': 25.00},
                {'id': 'RUB-G', 'name': 'Rubber Gasket', 'stock': 10000, 'unit': 'units', 'price': 0.50},
                {'id': 'TIT-B', 'name': 'Titanium Bolt', 'stock': 8000, 'unit': 'units', 'price': 3.10},
                {'id': 'GEAR-S', 'name': 'Hardened Steel Gear', 'stock': 2500, 'unit': 'units', 'price': 18.00},
                {'id': 'BRONZE-B', 'name': 'Bronze Bushing', 'stock': 3000, 'unit': 'units', 'price': 4.50}
            ]
            for mat_data in materials_data: db.session.add(RawMaterial(**mat_data))
            products_data = [
                "Industrial Gearbox", "High-Torque Actuator", "Precision Bearing Assembly", "Hydraulic Piston", "Pneumatic Valve", "Conveyor Roller", "Drive Shaft", "Mounting Bracket", "Spring Damper", "Chain Sprocket",
                "Control Panel Unit", "Sensor Array Module", "Power Distribution Board", "LED Indicator Panel", "Data Logger", "Signal Amplifier", "Servo Motor Controller", "Emergency Stop Button", "IoT Gateway", "Frequency Inverter",
                "Robotic Arm Joint", "Automated Gripper", "Linear Motion Guide", "CNC Spindle Housing", "Filtration System Pump", "Cooling Fan Assembly", "Pressure Regulator", "Flow Control Manifold", "Cable Harness", "Enclosure Lock Mechanism"
            ]
            operations = ["Cutting", "Milling", "Lathing", "Casting", "Molding", "Assembly", "Soldering", "Wiring", "Testing", "Calibration", "Finishing", "Sealing"]
            materials = RawMaterial.query.all()
            for i, prod_name in enumerate(products_data):
                prod_id = f"PROD{i+1:03d}"
                sku = f"{''.join(word[0] for word in prod_name.split())}-{i+1:03d}"
                new_prod = Product(id=prod_id, name=prod_name, sku=sku, finished_stock=random.randint(5, 50))
                db.session.add(new_prod)
                db.session.flush()
                for _ in range(random.randint(2, 5)):
                    material = random.choice(materials)
                    bom = BomItem(product_id=new_prod.id, material_id=material.id, quantity=round(random.uniform(1.0, 10.0), 2), operation=random.choice(operations), operation_duration=round(random.uniform(0.5, 4.0), 1))
                    db.session.add(bom)
            db.session.commit()
            print("Initial data, including 30 products and 12 work centers, populated.")
    app.run(debug=True)