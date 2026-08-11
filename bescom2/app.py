import os
import requests
import json
import logging
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from sqlalchemy import text
from models import db, Admin, Area, User, Outage
from messaging import notify_users

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

database_url = os.environ.get('DATABASE_URL', 'sqlite:///database.db')
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+pg8000://", 1)
if database_url.startswith("postgresql://") and "pg8000" not in database_url:
    database_url = database_url.replace("postgresql://", "postgresql+pg8000://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'bescom-secret-key-2024')
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please login to access the admin panel.'
login_manager.login_message_category = 'error'

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))

with app.app_context():
    db.create_all()
    try:
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE area ADD COLUMN IF NOT EXISTS latitude FLOAT;"))
            conn.execute(text("ALTER TABLE area ADD COLUMN IF NOT EXISTS longitude FLOAT;"))
            conn.execute(text("ALTER TABLE area ADD COLUMN IF NOT EXISTS pincode VARCHAR(20);"))
            conn.execute(text("ALTER TABLE outage ADD COLUMN IF NOT EXISTS latitude FLOAT;"))
            conn.execute(text("ALTER TABLE outage ADD COLUMN IF NOT EXISTS longitude FLOAT;"))
            conn.execute(text("ALTER TABLE outage ADD COLUMN IF NOT EXISTS street VARCHAR(255);"))
            conn.execute(text("ALTER TABLE outage ADD COLUMN IF NOT EXISTS reason VARCHAR(255);"))
            conn.execute(text("ALTER TABLE outage ADD COLUMN IF NOT EXISTS estimated_restoration TIMESTAMP;"))
            conn.execute(text("ALTER TABLE outage ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'ongoing';"))
            conn.execute(text("ALTER TABLE outage ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();"))
            conn.execute(text("ALTER TABLE outage ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP;"))
            conn.execute(text("ALTER TABLE outage ADD COLUMN IF NOT EXISTS start_time TIMESTAMP DEFAULT NOW();"))
            conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS street VARCHAR(200);'))
            conn.commit()
    except Exception as e:
        logger.error(f"Migration check: {e}")
    if not Admin.query.first():
        db.session.add(Admin(username='admin', password=generate_password_hash('bescom@123')))
        db.session.commit()

def get_coordinates(query):
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {'q': query + ', Bangalore, Karnataka, India', 'format': 'json', 'limit': 1}
        headers = {'User-Agent': 'BESCOM-Power-Alert/1.0'}
        r = requests.get(url, params=params, headers=headers, timeout=5)
        data = r.json()
        if data:
            return float(data[0]['lat']), float(data[0]['lon'])
    except Exception as e:
        logger.error(f"Geocoding error: {e}")
    return None, None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin = Admin.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password, password):
            login_user(admin)
            flash('Welcome back!', 'success')
            return redirect(url_for('index'))
        flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    outages = Outage.query.order_by(Outage.created_at.desc()).all()
    areas = Area.query.all()
    ongoing_count = Outage.query.filter_by(status='ongoing').count()
    resolved_count = Outage.query.filter(
        Outage.status == 'resolved',
        db.func.date(Outage.resolved_at) == datetime.utcnow().date()
    ).count()

    map_data = []
    for o in outages:
        if o.latitude and o.longitude:
            map_data.append({
                'name': o.area.name,
                'street': o.street or '',
                'lat': o.latitude,
                'lng': o.longitude,
                'status': o.status,
                'reason': o.reason,
                'time': o.estimated_restoration.strftime('%d %b, %I:%M %p'),
                'id': o.id
            })

    return render_template('index.html', outages=outages, areas=areas,
                           ongoing_count=ongoing_count, resolved_count=resolved_count,
                           area_count=len(areas), active_page='home',
                           map_data=json.dumps(map_data))

@app.route('/areas', methods=['GET', 'POST'])
@login_required
def manage_areas():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        pincode = request.form.get('pincode', '').strip()
        if Area.query.filter_by(name=name).first():
            flash(f"Area '{name}' already exists.", 'error')
        else:
            lat, lng = get_coordinates(name)
            db.session.add(Area(name=name, pincode=pincode, latitude=lat, longitude=lng))
            db.session.commit()
            flash(f"Area '{name}' added!", 'success')
        return redirect(url_for('manage_areas'))
    return render_template('add_area.html', areas=Area.query.all(), active_page='areas')

@app.route('/register', methods=['GET', 'POST'])
@login_required
def register_user():
    areas = Area.query.all()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        area_id = request.form.get('area_id')
        area_id = int(area_id) if area_id else None
        street = request.form.get('street', '').strip()
        if not phone.startswith('+'):
            flash('Phone must include country code, e.g. +91XXXXXXXXXX', 'error')
        else:
            db.session.add(User(name=name, phone=phone, area_id=area_id, street=street))
            db.session.commit()
            flash(f"User '{name}' registered!", 'success')
        return redirect(url_for('register_user'))
    return render_template('register_user.html', areas=areas, users=User.query.all(), active_page='users')

@app.route('/public-register', methods=['GET', 'POST'])
def public_register():
    areas = Area.query.all()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        area_id = request.form.get('area_id')
        area_id = int(area_id) if area_id else None
        street = request.form.get('street', '').strip()
        if not name or not phone or not area_id:
            flash('Please fill all fields.', 'error')
            return redirect(url_for('public_register'))
        if not phone.startswith('+'):
            flash('Phone must include country code, e.g. +91XXXXXXXXXX', 'error')
            return redirect(url_for('public_register'))
        if User.query.filter_by(phone=phone).first():
            flash('This phone number is already registered!', 'error')
            return redirect(url_for('public_register'))
        db.session.add(User(name=name, phone=phone, area_id=area_id, street=street))
        db.session.commit()
        flash('You are now registered for power alerts! ✅', 'success')
        return redirect(url_for('public_register'))
    return render_template('public_register.html', areas=areas)

@app.route('/report-outage', methods=['GET', 'POST'])
@login_required
def report_outage():
    areas = Area.query.all()
    if request.method == 'POST':
        area_id = request.form.get('area_id')
        area_id = int(area_id) if area_id else None
        street = request.form.get('street', '').strip()
        reason = request.form.get('reason', '').strip()
        rest_str = request.form.get('estimated_restoration')
        try:
            estimated = datetime.strptime(rest_str, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Invalid date/time.', 'error')
            return redirect(url_for('report_outage'))

        area = Area.query.get(area_id)

        lat, lng = None, None
        if street:
            lat, lng = get_coordinates(f"{street}, {area.name}")
        if not lat and area.latitude:
            lat, lng = area.latitude, area.longitude

        outage = Outage(area_id=area_id, street=street, reason=reason,
                       estimated_restoration=estimated, latitude=lat, longitude=lng)
        db.session.add(outage)
        db.session.commit()

        if street:
            users = User.query.filter_by(area_id=area_id, street=street).all()
            if not users:
                users = User.query.filter_by(area_id=area_id).all()
        else:
            users = User.query.filter_by(area_id=area_id).all()

        location = f"{street}, {area.name}" if street else area.name
        msg = (
            f"⚡ BESCOM Power Alert\n"
            f"Location: {location}\n"
            f"Reason: {reason}\n"
            f"Power is currently OFF.\n"
            f"Expected restoration by: {estimated.strftime('%d %b %Y, %I:%M %p')}\n"
            f"We apologize for the inconvenience."
        )
        if users:
            notify_users(users, msg)
            flash(f"Outage reported for '{location}'. Notified {len(users)} user(s).", 'success')
        else:
            flash(f"Outage reported for '{location}'. No users registered yet.", 'info')
        return redirect(url_for('index'))
    return render_template('report_outage.html', areas=areas, active_page='report')

@app.route('/resolve/<int:outage_id>', methods=['POST'])
@login_required
def resolve_outage(outage_id):
    outage = Outage.query.get_or_404(outage_id)
    outage.status = 'resolved'
    outage.resolved_at = datetime.utcnow()
    db.session.commit()
    area = Area.query.get(outage.area_id)
    users = User.query.filter_by(area_id=outage.area_id).all()
    location = f"{outage.street}, {area.name}" if outage.street else area.name
    msg = (
        f"✅ BESCOM Power Restored\n"
        f"Location: {location}\n"
        f"Power supply has been restored.\n"
        f"Thank you for your patience."
    )
    if users:
        notify_users(users, msg)
    flash(f"Power in '{location}' marked as restored. Users notified.", 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
