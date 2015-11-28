import models
import flask

import datetime
import math
import pytz
import urllib
import urllib2

app = flask.Flask(__name__)

google_maps_key = "AIzaSyDLG4q9x0pkI-eRyyL7x__pl2btULRRK8k"
google_maps_base_url = "https://maps.googleapis.com/maps/api"

REQUEST_TYPE_LOCATION = 0
REQUEST_TYPE_HOME = 1
REQUEST_TYPE_WORK = 2


@app.errorhandler(404)
def page_not_found(e):
	return flask.render_template("error.html", error_title = "Not found (error 404)", error_message = "The page you requested could not be found."), 404


@app.errorhandler(500)
def application_error(e):
	return flask.render_template("error.html", error_title = "Server error (error 500)", error_message = "Something went wrong. Please try again later."), 500


@app.route('/config/<token_account>')
def get_config(token_account):
	token_timeline = flask.request.args['token_timeline']
	return_to = flask.request.args.get('return_to', "pebblejs://close#")
	
	# Fetch user
	user = models.User.get_by_id(token_account)
	if user:
		# Existing user -> calculate hours
		timeline_work_timezone = pytz.timezone(user.timeline_work_timezone)
		timeline_work_arrival_utc = pytz.utc.localize(user.timeline_work_arrival)
		timeline_work_arrival_local = timeline_work_timezone.normalize(timeline_work_arrival_utc.astimezone(timeline_work_timezone))
		timeline_work_arrival_string = timeline_work_arrival_local.strftime('%H:%M')
		timeline_work_departure_utc = pytz.utc.localize(user.timeline_work_departure)
		timeline_work_departure_local = timeline_work_timezone.normalize(timeline_work_departure_utc.astimezone(timeline_work_timezone))
		timeline_work_departure_string = timeline_work_departure_local.strftime('%H:%M')
	else:
		# New user -> Create temporary user object
		user = models.User(
			address_home = "",
			address_work = "",
		)
		timeline_work_arrival_string = "09:00"
		timeline_work_departure_string = "17:00"
	
	# New or existing user -> Render config page
	prefill = {
		'token_account': token_account,
		'token_timeline': token_timeline,
		'return_to': return_to,
		'address_home': user.address_home,
		'address_work': user.address_work,
		'route_avoid_tolls': user.route_avoid_tolls,
		'route_avoid_highways': user.route_avoid_highways,
		'route_avoid_ferries': user.route_avoid_ferries,
		'timeline_enabled': user.timeline_enabled,
		'timeline_work_arrival': timeline_work_arrival_string,
		'timeline_work_departure': timeline_work_departure_string
	}
	
	return flask.render_template("config.html", prefill = prefill)


@app.route('/user/<token_account>', methods=['PUT'])
def put_user(token_account):
	# Fetch user
	user = models.User.get_by_id(token_account)
	if user == None:
		# Create new user
		user = models.User(
			id = token_account,
			token_timeline = flask.request.form['token_timeline']
		)
	
	# Parse times
	timeline_work_timezone = pytz.timezone(flask.request.form['timeline_work_timezone'])
	timeline_work_arrival_h = int(flask.request.form['timeline_work_arrival_h'])
	timeline_work_arrival_m = int(flask.request.form['timeline_work_arrival_m'])
	timeline_work_arrival = datetime.datetime.combine(datetime.date.today(), datetime.time(timeline_work_arrival_h, timeline_work_arrival_m))
	timeline_work_arrival_local = timeline_work_timezone.localize(timeline_work_arrival)
	timeline_work_arrival_utc = pytz.utc.normalize(timeline_work_arrival_local.astimezone(pytz.utc))
	timeline_work_departure_h = int(flask.request.form['timeline_work_departure_h'])
	timeline_work_departure_m = int(flask.request.form['timeline_work_departure_m'])
	timeline_work_departure = datetime.datetime.combine(datetime.date.today(), datetime.time(timeline_work_departure_h, timeline_work_departure_m))
	timeline_work_departure_local = timeline_work_timezone.localize(timeline_work_departure)
	timeline_work_departure_utc = pytz.utc.normalize(timeline_work_departure_local.astimezone(pytz.utc))
	
	# Change and persist information
	user.address_home = flask.request.form['address_home']
	user.address_work = flask.request.form['address_work']
	user.route_avoid_tolls = flask.request.form['route_avoid_tolls'] == "true"
	user.route_avoid_highways = flask.request.form['route_avoid_highways'] == "true"
	user.route_avoid_ferries = flask.request.form['route_avoid_ferries'] == "true"
	user.timeline_enabled = flask.request.form['timeline_enabled'] == "true"
	user.timeline_work_arrival = timeline_work_arrival_utc.replace(tzinfo=None) # Datastore won't accept datetime.datetime with tzinfo
	user.timeline_work_departure = timeline_work_departure_utc.replace(tzinfo=None) # Datastore won't accept datetime.datetime with tzinfo
	user.timeline_work_timezone = timeline_work_timezone.zone
	user.put()
	return "", 200


@app.route('/directions/<token_account>')
def get_directions(token_account):
	request_orig = int(flask.request.args['request_orig'])
	request_dest = int(flask.request.args['request_dest'])
	request_coord = flask.request.args.get('request_coord', "")
	
	# Fetch user
	user = models.User.get_by_id(token_account)
	if user == None:
		# User not found
		return "", 404
	
	# Determine origin and destination
	if request_orig == REQUEST_TYPE_LOCATION:
		orig = request_coord
	elif request_orig == REQUEST_TYPE_HOME:
		orig = user.address_home
	elif request_orig == REQUEST_TYPE_WORK:
		orig = user.address_work
	
	if request_dest == REQUEST_TYPE_LOCATION:
		dest = request_coord
	elif request_dest == REQUEST_TYPE_HOME:
		dest = user.address_home
	elif request_dest == REQUEST_TYPE_WORK:
		dest = user.address_work
	
	# Construct avoid parameter
	avoid = []
	if user.route_avoid_tolls:
		avoid.append('tolls')
	if user.route_avoid_highways:
		avoid.append('highways')
	if user.route_avoid_ferries:
		avoid.append('ferries')
	
	# Get directions
	data_params = {
		'key': google_maps_key.encode('utf-8'),
		'origin': orig.encode('utf-8'),
		'destination': dest.encode('utf-8'),
		'mode': "driving",
		'departure_time': "now",
		'avoid': '|'.join(avoid)
	}
	
	try:
		return urllib2.urlopen(google_maps_base_url + "/directions/json?{}".format(urllib.urlencode(data_params))).read()
	except (urllib2.URLError, urllib2.HTTPError):
		return "Request: {}".format(data_params), 502
