from flask import Flask, render_template, request
import requests
import os
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

@app.route('/')
def home():
    return render_template('index.html', google_maps_api_key=GOOGLE_MAPS_API_KEY)

@app.route('/search', methods=['POST'])
def search():
    try:
        from_location = request.form['from']
        to_location = request.form['to']
        vehicle_model = request.form['vehicle_model']

        # Fetch multiple routes
        routes = get_routes(from_location, to_location)
        if not routes:
            return "Error: Could not fetch routes. Please check your input and try again."

        return render_template('route_selection.html',
                               routes=routes,
                               google_maps_api_key=GOOGLE_MAPS_API_KEY)
    except Exception as e:
        return f"An error occurred: {str(e)}", 500

@app.route('/select_route', methods=['POST'])
def select_route():
    try:
        selected_route_index = int(request.form['route_index'])
        routes = request.form.getlist('routes[]')  # Get all routes as JSON strings
        routes = [eval(route) for route in routes]  # Safely parse JSON strings

        selected_route = routes[selected_route_index]['route']
        charging_stations = get_charging_stations(selected_route)

        return render_template('route.html',
                               selected_route=selected_route,
                               stations=charging_stations,
                               google_maps_api_key=GOOGLE_MAPS_API_KEY)
    except Exception as e:
        return f"An error occurred: {str(e)}", 500

def get_routes(from_location, to_location):
    params = {
        'origin': from_location,
        'destination': to_location,
        'alternatives': 'true',  # Fetch alternative routes
        'key': GOOGLE_MAPS_API_KEY,
    }
    try:
        response = requests.get('https://maps.googleapis.com/maps/api/directions/json', params=params)
        response.raise_for_status()
        data = response.json()
        if data.get('status') == 'OK':
            routes = []
            for route in data['routes']:
                total_distance = 0
                total_duration = 0
                steps = []
                for leg in route['legs']:
                    total_distance += leg['distance']['value']
                    total_duration += leg['duration']['value']
                    for step in leg['steps']:
                        steps.append({
                            'lat': step['end_location']['lat'],
                            'lng': step['end_location']['lng']
                        })
                routes.append({
                    'distance': total_distance,
                    'duration': total_duration,
                    'route': steps,
                })
            return routes
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching routes: {e}")
        return None

def get_charging_stations(route):
    stations = []
    for point in route:
        params = {
            'location': f"{point['lat']},{point['lng']}",
            'radius': 5000,  # Search radius in meters (5 km)
            'type': 'electric_vehicle_charging_station',
            'key': GOOGLE_MAPS_API_KEY,
        }
        try:
            response = requests.get('https://maps.googleapis.com/maps/api/place/nearbysearch/json', params=params)
            response.raise_for_status()
            data = response.json()
            if data.get('status') == 'OK':
                for place in data['results']:
                    stations.append({
                        'name': place.get('name', 'Unknown'),
                        'address': place.get('vicinity', 'Unknown'),
                        'lat': place['geometry']['location']['lat'],
                        'lng': place['geometry']['location']['lng'],
                    })
        except requests.exceptions.RequestException as e:
            print(f"Error fetching charging stations: {e}")
    return stations

if __name__ == '__main__':
    app.run(debug=True)