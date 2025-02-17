# app.py
import requests
from flask import Flask, render_template, request, jsonify, session
from geopy.distance import geodesic
from dotenv import load_dotenv
import os
import json
from datetime import datetime, timedelta
import polyline
import hashlib
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-key-replace-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///chargroute.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# API Keys
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
OPEN_CHARGE_API_KEY = os.getenv('OPEN_CHARGE_API_KEY')
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')  # OpenWeatherMap API key

# Vehicle database
vehicle_data = {
    'Tesla': {
        'Model X': {'range': 500, 'efficiency': 0.180, 'charging_curve': [{'soc': 0, 'power': 250}, {'soc': 50, 'power': 180}, {'soc': 80, 'power': 80}, {'soc': 100, 'power': 50}]},
        'Model Y': {'range': 450, 'efficiency': 0.160, 'charging_curve': [{'soc': 0, 'power': 250}, {'soc': 50, 'power': 180}, {'soc': 80, 'power': 80}, {'soc': 100, 'power': 50}]},
        'Model 3': {'range': 430, 'efficiency': 0.155, 'charging_curve': [{'soc': 0, 'power': 250}, {'soc': 50, 'power': 180}, {'soc': 80, 'power': 80}, {'soc': 100, 'power': 50}]},
        'Model S': {'range': 600, 'efficiency': 0.170, 'charging_curve': [{'soc': 0, 'power': 250}, {'soc': 50, 'power': 180}, {'soc': 80, 'power': 80}, {'soc': 100, 'power': 50}]}
    },
    'Tata': {
        'Nexon': {'range': 312, 'efficiency': 0.155, 'charging_curve': [{'soc': 0, 'power': 50}, {'soc': 50, 'power': 45}, {'soc': 80, 'power': 30}, {'soc': 100, 'power': 15}]},
        'Tigor': {'range': 306, 'efficiency': 0.160, 'charging_curve': [{'soc': 0, 'power': 25}, {'soc': 50, 'power': 25}, {'soc': 80, 'power': 20}, {'soc': 100, 'power': 10}]}
    },
    'Mahindra': {
        'e2o': {'range': 140, 'efficiency': 0.110, 'charging_curve': [{'soc': 0, 'power': 15}, {'soc': 50, 'power': 15}, {'soc': 80, 'power': 10}, {'soc': 100, 'power': 7}]},
        'XUV400': {'range': 456, 'efficiency': 0.170, 'charging_curve': [{'soc': 0, 'power': 50}, {'soc': 50, 'power': 45}, {'soc': 80, 'power': 30}, {'soc': 100, 'power': 15}]}
    },
    'Hyundai': {
        'Kona': {'range': 452, 'efficiency': 0.165, 'charging_curve': [{'soc': 0, 'power': 77}, {'soc': 50, 'power': 77}, {'soc': 80, 'power': 50}, {'soc': 100, 'power': 20}]},
        'Ioniq 5': {'range': 481, 'efficiency': 0.175, 'charging_curve': [{'soc': 0, 'power': 220}, {'soc': 50, 'power': 180}, {'soc': 80, 'power': 70}, {'soc': 100, 'power': 35}]}
    },
    'MG': {
        'ZS EV': {'range': 461, 'efficiency': 0.178, 'charging_curve': [{'soc': 0, 'power': 76}, {'soc': 50, 'power': 76}, {'soc': 80, 'power': 50}, {'soc': 100, 'power': 20}]},
        'Comet': {'range': 230, 'efficiency': 0.125, 'charging_curve': [{'soc': 0, 'power': 17}, {'soc': 50, 'power': 17}, {'soc': 80, 'power': 10}, {'soc': 100, 'power': 7}]}
    }
}

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    saved_trips = db.relationship('SavedTrip', backref='user', lazy=True)
    
    def set_password(self, password):
        self.password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    def check_password(self, password):
        return self.password_hash == hashlib.sha256(password.encode()).hexdigest()

class SavedTrip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    from_location = db.Column(db.String(200), nullable=False)
    to_location = db.Column(db.String(200), nullable=False)
    vehicle_make = db.Column(db.String(50), nullable=False)
    vehicle_model = db.Column(db.String(50), nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    route_data = db.Column(db.Text)  # Stores JSON data of the route

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

@app.route('/')
def home():
    # Get all vehicle makes and models for dropdown
    makes = list(vehicle_data.keys())
    return render_template('index.html', 
                           google_maps_api_key=GOOGLE_MAPS_API_KEY,
                           vehicle_makes=makes,
                           vehicle_data=vehicle_data)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return jsonify({'status': 'success', 'redirect': '/'})
        
        return jsonify({'status': 'error', 'message': 'Invalid username or password'})
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Check if username or email already exists
        if User.query.filter_by(username=username).first() or User.query.filter_by(email=email).first():
            return jsonify({'status': 'error', 'message': 'Username or email already exists'})
        
        # Create new user
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        return jsonify({'status': 'success', 'redirect': '/'})
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user)

@app.route('/save_trip', methods=['POST'])
@login_required
def save_trip():
    data = request.json
    name = data.get('name')
    from_location = data.get('from')
    to_location = data.get('to')
    vehicle_make = data.get('vehicle_make')
    vehicle_model = data.get('vehicle_model')
    route_data = json.dumps(data.get('route_data'))
    
    trip = SavedTrip(name=name, 
                     user_id=current_user.id,
                     from_location=from_location,
                     to_location=to_location,
                     vehicle_make=vehicle_make,
                     vehicle_model=vehicle_model,
                     route_data=route_data)
    
    db.session.add(trip)
    db.session.commit()
    
    return jsonify({'status': 'success', 'message': 'Trip saved successfully'})

@app.route('/saved_trips')
@login_required
def saved_trips():
    trips = SavedTrip.query.filter_by(user_id=current_user.id).order_by(SavedTrip.date_created.desc()).all()
    return render_template('saved_trips.html', trips=trips)

@app.route('/load_trip/<int:trip_id>')
@login_required
def load_trip(trip_id):
    trip = SavedTrip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id:
        return abort(403)
    
    route_data = json.loads(trip.route_data)
    return render_template('route.html', 
                         routes=route_data.get('routes'),
                         estimated_range=route_data.get('estimated_range'),
                         from_location=trip.from_location,
                         to_location=trip.to_location,
                         vehicle_make=trip.vehicle_make,
                         vehicle_model=trip.vehicle_model,
                         google_maps_api_key=GOOGLE_MAPS_API_KEY,
                         trip_loaded=True,
                         trip_id=trip_id)

@app.route('/delete_trip/<int:trip_id>', methods=['POST'])
@login_required
def delete_trip(trip_id):
    trip = SavedTrip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id:
        return abort(403)
    
    db.session.delete(trip)
    db.session.commit()
    
    return jsonify({'status': 'success', 'message': 'Trip deleted successfully'})

@app.route('/search', methods=['POST'])
def search():
    data = request.form
    from_location = data.get('from')
    to_location = data.get('to')
    vehicle_make = data.get('vehicle_make')
    vehicle_model = data.get('vehicle_model')
    battery_level = int(data.get('battery_level'))
    ac_usage = data.get('ac_usage', 'off')
    avg_speed = int(data.get('avg_speed', 80))
    
    # Get vehicle data
    if vehicle_make in vehicle_data and vehicle_model in vehicle_data[vehicle_make]:
        vehicle_info = vehicle_data[vehicle_make][vehicle_model]
    else:
        return "Error: Vehicle model not found"
    
    # Get multiple routes
    routes = get_routes(from_location, to_location)
    if not routes:
        return "Error: Could not fetch routes. Please check your input and try again."

    # Calculate estimated range based on battery level and efficiency factors
    base_range = vehicle_info['range']
    efficiency = vehicle_info['efficiency']
    estimated_range = (battery_level / 100) * base_range
    
    # Apply efficiency modifiers based on user inputs
    if ac_usage == 'on':
        estimated_range *= 0.9  # AC reduces range by about 10%
    
    # Speed efficiency curve (simplified)
    if avg_speed > 100:
        estimated_range *= 0.85  # High speeds reduce range
    elif avg_speed < 60:
        estimated_range *= 0.95  # Lower speeds may also slightly reduce range due to more city driving
    
    # Get charging stations for each route with enhanced details
    for route in routes:
        route['charging_stations'] = get_combined_charging_stations(route['points'])
        
        # Calculate charging stops needed
        route['charging_plan'] = calculate_charging_plan(route, estimated_range, vehicle_info)
        
        # Get weather for major points along the route
        route['weather'] = get_weather_along_route(route['points'])
        
        # Calculate elevation profile (would need elevation API)
        # route['elevation_profile'] = get_elevation_profile(route['points'])

    return render_template('route.html', 
                         routes=routes,
                         estimated_range=estimated_range,
                         from_location=from_location,
                         to_location=to_location,
                         vehicle_make=vehicle_make,
                         vehicle_model=vehicle_model,
                         battery_level=battery_level,
                         google_maps_api_key=GOOGLE_MAPS_API_KEY)

def get_routes(from_location, to_location):
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        'origin': from_location,
        'destination': to_location,
        'alternatives': 'true',
        'key': GOOGLE_MAPS_API_KEY
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if data['status'] != 'OK':
            return None

        routes = []
        for i, route in enumerate(data['routes']):
            points = []
            path = []
            distance = 0
            duration = 0
            segments = []  # Track segments for more granular analysis
            
            for leg in route['legs']:
                distance += leg['distance']['value']
                duration += leg['duration']['value']
                
                # Get points along the route for charging station search
                for step in leg['steps']:
                    points.append({
                        'lat': step['end_location']['lat'],
                        'lng': step['end_location']['lng']
                    })
                    path.append(step['polyline']['points'])
                    
                    # Add segment information
                    segments.append({
                        'start_point': {
                            'lat': step['start_location']['lat'],
                            'lng': step['start_location']['lng']
                        },
                        'end_point': {
                            'lat': step['end_location']['lat'],
                            'lng': step['end_location']['lng']
                        },
                        'distance': step['distance']['value'] / 1000,  # in km
                        'duration': step['duration']['value'] / 60,   # in minutes
                        'polyline': step['polyline']['points']
                    })

            routes.append({
                'id': i,
                'points': points,
                'path': path,
                'distance': round(distance / 1000, 2),  # Convert to km
                'duration': round(duration / 60),  # Convert to minutes
                'segments': segments,
                'charging_stations': [],
                'total_elevation_gain': 0,  # To be calculated
                'total_elevation_loss': 0,  # To be calculated
                'charging_plan': []
            })

        return routes
    except Exception as e:
        print(f"Error fetching routes: {e}")
        return None

def get_combined_charging_stations(route_points):
    stations = []
    seen_stations = set()  # To track unique stations

    # Sample points along the route to search for stations
    # Take every 5th point, but ensure at least 5 and at most 20 sample points
    step = max(1, len(route_points) // 10)
    sample_points = route_points[::step]
    if len(sample_points) > 20:
        sample_points = sample_points[:20]
    
    for point in sample_points:
        # Get stations from Google Places API
        google_stations = get_google_charging_stations(point)
        
        # Get stations from Open Charge Map API
        ocm_stations = get_ocm_charging_stations(point)

        # Combine stations from both sources
        for station in google_stations + ocm_stations:
            station_id = f"{station['lat']}-{station['lng']}"
            if station_id not in seen_stations:
                seen_stations.add(station_id)
                stations.append(station)

    return stations

def get_google_charging_stations(point):
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        'location': f"{point['lat']},{point['lng']}",
        'radius': 5000,  # 5km radius
        'keyword': 'EV charging station',  # Add keyword for better results
        'type': 'electric_vehicle_charging_station',
        'key': GOOGLE_MAPS_API_KEY
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        stations = []
        if data.get('status') == 'OK':
            for place in data['results']:
                # Verify this is actually an EV charging station by checking name/types
                name = place.get('name', '').lower()
                types = [t.lower() for t in place.get('types', [])]
                
                is_ev_station = (
                    'charge' in name or 
                    'charging' in name or 
                    'ev' in name or 
                    'electric' in name or
                    'electric_vehicle_charging_station' in types
                )
                
                if is_ev_station:
                    stations.append({
                        'source': 'google',
                        'name': place.get('name', 'Unknown Station'),
                        'lat': place['geometry']['location']['lat'],
                        'lng': place['geometry']['location']['lng'],
                        'address': place.get('vicinity', 'Address not available'),
                        'rating': place.get('rating', 'N/A'),
                        'is_operational': place.get('business_status', '') == 'OPERATIONAL',
                        'amenities': get_amenities_from_types(place.get('types', [])),
                        'opening_hours': place.get('opening_hours', {}).get('open_now', None),
                        'distance_from_route': 0
                    })
        return stations
    except Exception as e:
        print(f"Error fetching Google charging stations: {e}")
        return []

def get_ocm_charging_stations(point):
    url = "https://api.openchargemap.io/v3/poi"
    params = {
        'key': OPEN_CHARGE_API_KEY,
        'latitude': point['lat'],
        'longitude': point['lng'],
        'distance': 5,  # 5km radius
        'distanceunit': 'km',
        'maxresults': 10,
        'compact': True,
        'verbose': False,
        'operationalstatus': 'Operational'  # Only get operational stations
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        stations = []
        for station in data:
            # Skip stations with no connection data
            connections = station.get('Connections', [])
            if not connections:
                continue
                
            power_levels = [conn.get('PowerKW', 0) for conn in connections if conn.get('PowerKW')]
            max_power = max(power_levels) if power_levels else 0
            
            # Get connector types
            connector_types = []
            for conn in connections:
                conn_type = conn.get('ConnectionType', {}).get('Title')
                if conn_type and conn_type not in connector_types:
                    connector_types.append(conn_type)
            
            # Get operator info
            operator = station.get('OperatorInfo', {}).get('Title', 'Unknown Operator')
            
            # Get usage cost if available
            usage_cost = 'Not specified'
            if station.get('UsageCost'):
                usage_cost = station.get('UsageCost')
            
            # Only include stations with at least one connector type
            if connector_types:
                stations.append({
                    'source': 'ocm',
                    'name': station.get('AddressInfo', {}).get('Title', 'Unknown Station'),
                    'lat': station.get('AddressInfo', {}).get('Latitude'),
                    'lng': station.get('AddressInfo', {}).get('Longitude'),
                    'address': station.get('AddressInfo', {}).get('AddressLine1', 'Address not available'),
                    'power_kw': max_power,
                    'is_operational': station.get('StatusType', {}).get('IsOperational', True),
                    'connectors': connector_types,
                    'operator': operator,
                    'usage_cost': usage_cost,
                    'number_of_points': len(connections),
                    'distance_from_route': 0
                })
        return stations
    except Exception as e:
        print(f"Error fetching OCM charging stations: {e}")
        return []

def get_amenities_from_types(types):
    amenities = []
    amenity_mapping = {
        'convenience_store': 'Convenience Store',
        'restaurant': 'Restaurant',
        'cafe': 'Café',
        'supermarket': 'Supermarket',
        'parking': 'Parking',
        'lodging': 'Lodging',
        'gas_station': 'Gas Station',
        'atm': 'ATM',
        'pharmacy': 'Pharmacy',
        'shopping_mall': 'Shopping Mall',
        'restroom': 'Restroom'
    }
    
    for type_name in types:
        if type_name in amenity_mapping:
            amenities.append(amenity_mapping[type_name])
    
    return amenities

def calculate_charging_plan(route, estimated_range, vehicle_info):
    """Calculate charging stops needed for the route"""
    charging_plan = []
    remaining_range = estimated_range
    distance_covered = 0
    
    for i, segment in enumerate(route['segments']):
        segment_distance = segment['distance']  # in km
        
        # If remaining range is not enough for this segment
        if remaining_range < segment_distance:
            # Find closest charging station
            closest_station = find_closest_charging_station(
                route['charging_stations'], 
                segment['start_point'],
                max_distance=remaining_range * 0.9  # Add safety margin
            )
            
            if closest_station:
                # Add charging stop
                charge_to = min(80, (segment_distance / vehicle_info['range']) * 100 + 20)  # Charge to at least next segment + 20%
                charging_time = estimate_charging_time(closest_station, 10, charge_to, vehicle_info['charging_curve'])
                
                charging_plan.append({
                    'station': closest_station,
                    'distance_from_start': distance_covered,
                    'charge_from': 10,  # assuming we arrive with 10% left
                    'charge_to': charge_to,
                    'charging_time': charging_time
                })
                
                # Update remaining range after charging
                remaining_range = (charge_to / 100) * vehicle_info['range']
            else:
                # No suitable charging station found - this is a problem!
                charging_plan.append({
                    'problem': True,
                    'message': f"Warning: No charging stations found near {segment['start_point']['lat']},{segment['start_point']['lng']}. You might not make it through this segment!",
                    'distance_from_start': distance_covered
                })
        
        # Use energy for this segment
        remaining_range -= segment_distance
        distance_covered += segment_distance
    
    return charging_plan

def find_closest_charging_station(stations, point, max_distance):
    """Find the closest charging station within max_distance km"""
    closest_station = None
    min_distance = float('inf')
    
    for station in stations:
        distance = geodesic(
            (point['lat'], point['lng']), 
            (station['lat'], station['lng'])
        ).kilometers
        
        if distance < min_distance and distance <= max_distance:
            min_distance = distance
            closest_station = station
            
    if closest_station:
        closest_station['distance_from_point'] = min_distance
        
    return closest_station

def estimate_charging_time(station, charge_from, charge_to, charging_curve):
    """Estimate charging time based on station power and vehicle charging curve"""
    if station['source'] == 'ocm' and station.get('power_kw'):
        max_station_power = station['power_kw']
    else:
        max_station_power = 50  # default assumption for unknown stations
    
    total_time = 0
    current_soc = charge_from
    
    while current_soc < charge_to:
        # Find vehicle's max charging power at current SOC
        for i, point in enumerate(charging_curve):
            if point['soc'] >= current_soc:
                if i == 0:
                    vehicle_power = point['power']
                else:
                    # Interpolate between points
                    prev_point = charging_curve[i-1]
                    soc_diff = point['soc'] - prev_point['soc']
                    power_diff = point['power'] - prev_point['power']
                    vehicle_power = prev_point['power'] + power_diff * (current_soc - prev_point['soc']) / soc_diff
                break
        else:
            vehicle_power = charging_curve[-1]['power']
        
        # Actual charging power is the minimum of station and vehicle capability
        actual_power = min(max_station_power, vehicle_power)
        
        # Simplified: assume 1% SOC increase at this power level
        time_for_1_percent = 0.6 / actual_power  # 0.6 kWh per 1% for a typical 60kWh battery
        total_time += time_for_1_percent
        current_soc += 1
    
    return round(total_time * 60)  # Convert to minutes

def get_weather_along_route(points):
    """Get weather forecasts for key points along the route"""
    if not WEATHER_API_KEY:
        return []
    
    # Sample a few points along the route (start, middle, end, and a few in between)
    if len(points) < 3:
        sample_points = points
    else:
        indices = [0, len(points) // 2, len(points) - 1]  # start, middle, end
        sample_points = [points[i] for i in indices]
    
    weather_data = []
    for point in sample_points:
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather"
            params = {
                'lat': point['lat'],
                'lon': point['lng'],
                'appid': WEATHER_API_KEY,
                'units': 'metric'
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if response.status_code == 200:
                weather_data.append({
                    'location': {'lat': point['lat'], 'lng': point['lng']},
                    'temperature': data['main']['temp'],
                    'conditions': data['weather'][0]['main'],
                    'description': data['weather'][0]['description'],
                    'wind_speed': data['wind']['speed'],
                    'icon': data['weather'][0]['icon'],
                })
        except Exception as e:
            print(f"Error fetching weather data: {e}")
    
    return weather_data

if __name__ == '__main__':
    app.run(debug=True)