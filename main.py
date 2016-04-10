import models
import flask

import datetime
import json
import logging
import math
import pytz
import urllib
import urllib2
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

app = flask.Flask(__name__)

google_maps_key = "AIzaSyDLG4q9x0pkI-eRyyL7x__pl2btULRRK8k"
google_maps_base_url = "https://maps.googleapis.com/maps/api"

pebble_timeline_base_url = "https://timeline-api.getpebble.com/v1"


REQUEST_TYPE_LOCATION = 0
REQUEST_TYPE_HOME = 1
REQUEST_TYPE_WORK = 2

PIN_REASON_MORNING = 0
PIN_REASON_EVENING = 1

PAGE_LOCATION_WORK = 0
PAGE_LOCATION_HOME = 1
PAGE_HOME_WORK = 2
PAGE_WORK_HOME = 3


@app.errorhandler(404)
def page_not_found(e):
	return flask.render_template("error.html", error_title = "Not found (error 404)", error_message = "The page you requested could not be found."), 404


@app.errorhandler(500)
def application_error(e):
	return flask.render_template("error.html", error_title = "Server error (error 500)", error_message = "Something went wrong. Please try again later."), 500


@app.route('/config/<token_account>')
def get_config(token_account):
	return_to = flask.request.args.get('return_to', "pebblejs://close#")
	
	# Fetch user
	user = models.User.get_by_id(token_account)
	if user != None:
		# Existing user
		timeline_work_arrival_string = user.timeline_work_arrival_local.strftime('%H:%M')
		timeline_work_departure_string = user.timeline_work_departure_local.strftime('%H:%M')
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
		'tester': user.tester,
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


@app.route('/user/<token_account>', methods = ['PUT'])
def put_user(token_account):
	# Fetch user
	user = models.User.get_by_id(token_account)
	if user == None:
		# Create new user
		user = models.User(
			id = token_account
		)
	
	# Parse times
	timeline_work_timezone = pytz.timezone(flask.request.form['timeline_work_timezone'])
	timeline_work_arrival_h = int(flask.request.form['timeline_work_arrival_h'])
	timeline_work_arrival_m = int(flask.request.form['timeline_work_arrival_m'])
	timeline_work_arrival_local = datetime.time(timeline_work_arrival_h, timeline_work_arrival_m)
	timeline_work_departure_h = int(flask.request.form['timeline_work_departure_h'])
	timeline_work_departure_m = int(flask.request.form['timeline_work_departure_m'])
	timeline_work_departure_local = datetime.time(timeline_work_departure_h, timeline_work_departure_m)
	
	# Change and persist information
	user.address_home = flask.request.form['address_home']
	user.address_work = flask.request.form['address_work']
	user.route_avoid_tolls = flask.request.form['route_avoid_tolls'] == "true"
	user.route_avoid_highways = flask.request.form['route_avoid_highways'] == "true"
	user.route_avoid_ferries = flask.request.form['route_avoid_ferries'] == "true"
	user.timeline_enabled = flask.request.form['timeline_enabled'] == "true"
	user.timeline_work_arrival_local = timeline_work_arrival_local
	user.timeline_work_departure_local = timeline_work_departure_local
	user.timeline_work_timezone = timeline_work_timezone.zone
	user.trip_home_work_mean = 0
	user.trip_home_work_count = 0
	user.trip_work_home_mean = 0
	user.trip_work_home_count = 0
	user.updated = datetime.datetime.utcnow()
	user.put()
	
	# Schedule regular pins
	if user.timeline_enabled:
		now_local = get_local_time(timeline_work_timezone)
		schedule_next_pin_regular(user, PIN_REASON_MORNING, now_local, timeline_work_timezone)
		schedule_next_pin_regular(user, PIN_REASON_EVENING, now_local, timeline_work_timezone)
	
	return "", 200


def fetch_directions(user, request_orig, request_dest, request_coord = ""):
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
		return urllib2.urlopen("{}/directions/json?{}".format(google_maps_base_url, urllib.urlencode(data_params))).read()
	except urllib2.HTTPError, e:
		logging.error("Error while fetching directions. HTTP status: {} / Request: {}".format(e.code, data_params))
		raise
	except:
		logging.error("Error while fetching directions. Request: {}".format(data_params))
		raise


def parse_directions(directions_json):
	# Parse JSON
	directions = json.loads(directions_json)
	status = directions['status']
	if status == "OK":
		duration_normal = directions['routes'][0]['legs'][0]['duration']['value']
		duration_traffic = directions['routes'][0]['legs'][0]['duration_in_traffic']['value']
		duration_difference = duration_traffic - duration_normal
		if duration_difference < 0: # Prevent negative delays
			duration_difference = 0
		if duration_normal == 0: # Prevent division by 0
			duration_normal = 1
		delay_ratio = float(duration_difference) / duration_normal
		if delay_ratio > 0.25:
			conditions_color = "darkcandyapplered"
			conditions_text = "heavy"
		elif delay_ratio > 0.1:
			conditions_color = "orange"
			conditions_text = "moderate"
		else:
			conditions_color = "darkgreen"
			conditions_text = "light"
		via = directions['routes'][0]['summary']
		
		# Return interesting data as dict
		directions_dict = dict(
			status = status,
			duration_normal = duration_normal,
			duration_traffic = duration_traffic,
			duration_delay = duration_difference,
			conditions_color = conditions_color,
			conditions_text = conditions_text,
			via = via
		)
	else:
		directions_dict = dict(
			status = status
		)
	return directions_dict


@app.route('/directions/<token_account>')
def get_directions(token_account):
	token_timeline = flask.request.args.get('token_timeline', "")
	am_pm_string = flask.request.args.get('am_pm', "")
	request_orig = int(flask.request.args['request_orig'])
	request_dest = int(flask.request.args['request_dest'])
	request_coord = flask.request.args.get('request_coord', "")
	
	# Fetch user
	user = models.User.get_by_id(token_account)
	if user == None:
		# User not found
		flask.abort(404)
	
	# Update timeline token if necessary
	if token_timeline != "" and token_timeline != user.token_timeline:
		logging.debug("Persisting new timeline token for user {}: {} (was {})".format(user.key.id(), token_timeline, user.token_timeline))
		user.token_timeline = token_timeline
		user.put()
	
	# Update AM/PM setting if necessary
	if am_pm_string != "":
		am_pm = am_pm_string == "true"
		if am_pm != user.am_pm:
			logging.debug("Persisting new AM/PM setting for user {}: {} (was {})".format(user.key.id(), am_pm, user.am_pm))
			user.am_pm = am_pm
			user.put()
	
	# Fetch and return directions
	try:
		return fetch_directions(user, request_orig, request_dest, request_coord)
	except (urllib2.URLError, urllib2.HTTPError):
		flask.abort(502)


def get_local_time(timezone):
	now = datetime.datetime.utcnow()
	now_utc = pytz.utc.localize(now)
	return timezone.normalize(now_utc.astimezone(timezone))


def get_next_local_time_occurence(target_time, now_local, timezone):
	if now_local.time() <= target_time:
		target_date = now_local
	else:
		target_date = now_local + datetime.timedelta(days = 1)
	return timezone.localize(datetime.datetime.combine(target_date.date(), target_time))


def send_pin(user, route, route_title, directions, departure_local, app_launch_code):
	logging.debug("Pushing {} pin to {}".format(route, user.key.id()))
	
	# Prepare some variables
	duration_traffic = int(round(directions['duration_traffic'] / 60))
	duration_delay = int(round(directions['duration_delay'] / 60))
	
	if user.am_pm:
		time_format = "%I:%M %p"
	else:
		time_format = "%H:%M"
	
	timezone = pytz.timezone(user.timeline_work_timezone)
	departure_string = departure_local.strftime(time_format)
	departure_utc = pytz.utc.normalize(departure_local.astimezone(pytz.utc))
	
	arrival_local = departure_local + datetime.timedelta(minutes = duration_traffic)
	arrival_string = arrival_local.strftime(time_format)
	
	if duration_delay == 0:
		duration_delay_label_minutes = "minutes"
		duration_delay_label_cause = "thanks to"
	elif duration_delay == 1:
		duration_delay_label_minutes = "minute"
		duration_delay_label_cause = "due to"
	else:
		duration_delay_label_minutes = "minutes"
		duration_delay_label_cause = "due to"
	
	# Build pin
	id = "{}-{}".format(user.key.id(), user.timeline_pins_sent)
	pin = dict(
		id = id,
		time = departure_utc.isoformat(),
		duration = duration_traffic,
		layout = dict(
			type = "sportsPin",
			title = route_title,
			subtitle = u"Via {}".format(directions['via']),
			tinyIcon = "system://images/CAR_RENTAL",
			largeIcon = "system://images/CAR_RENTAL",
			primaryColor = "white",
			secondaryColor = "white",
			backgroundColor = directions['conditions_color'],
			headings = [
				"Route",
				"Travel time"
			],
			paragraphs = [
				route,
				"{} - {}".format(departure_string, arrival_string)
			],
			lastUpdated = datetime.datetime.utcnow().isoformat(),
			nameAway = "Total",
			nameHome = "Delay",
			scoreAway = "{}".format(duration_traffic),
			scoreHome = "{}".format(duration_delay),
			sportsGameState = "in-game"
		),
		reminders = [
			dict(
				time = (departure_utc - datetime.timedelta(minutes = 10)).isoformat(),
				layout = dict(
					type = "genericReminder",
					title = route_title,
					body = u"Drive via {} to arrive by {}, with {} {} of delay {} {} traffic.".format(directions['via'], arrival_string, duration_delay, duration_delay_label_minutes, duration_delay_label_cause, directions['conditions_text']),
					tinyIcon = "system://images/CAR_RENTAL"
				)
			)
		],
		actions = [
			dict(
				type = "openWatchApp",
				title = "Open Commute",
				launchCode = app_launch_code
			)
		]
	)
	
	# Add onboarding notification if this is the user's first
	if not user.timeline_onboarding_sent:
		pin['createNotification'] = dict(
			layout = dict(
				type = "genericNotification",
				title = "Commute is on your timeline!",
				tinyIcon = "system://images/CAR_RENTAL",
				body = "You'll get timeline pins and reminders telling you when to leave for work to arrive on time, or how long it'll take to get back home. Your first pin is available now. Enjoy!",
				primaryColor = "black",
				backgroundColor = "orange"
			)
		)
		user.timeline_onboarding_sent = True
		user.put()
	
	# Send pin
	try:
		pin_json = json.dumps(pin)
		logging.debug(pin_json)
		opener = urllib2.build_opener(urllib2.HTTPHandler)
		request = urllib2.Request("{}/user/pins/{}".format(pebble_timeline_base_url, id), data = pin_json)
		request.add_header('Content-Type', "application/json")
		request.add_header('X-User-Token', user.token_timeline)
		request.get_method = lambda: 'PUT'
		url = opener.open(request)
	except urllib2.HTTPError, e:
		if e.code == 410:
			# Timeline token invalid, remove
			logging.warning("Timeline token {} for account {} has been invalidated, removing...".format(user.token_timeline, user.key.id()))
			user.token_timeline = ""
			user.put()
		else:
			logging.error("Error pushing pin for account {}: HTTP status {}".format(user.key.id(), e.code))
			raise
	except:
		logging.error("Error pushing pin for account {}".format(user.key.id()))
		raise


@app.route('/pins', methods=['POST'])
def create_pin():
	token_account = flask.request.form['token_account']
	reason = int(flask.request.form['reason'])
	user_config_version = flask.request.form['user_config_version']
	
	logging.debug("Creating scheduled pin for {} (reason: {})".format(token_account, reason))
	
	# Fetch user
	user = models.User.get_by_id(token_account)
	if user == None:
		# User not found
		flask.abort(404)
	
	if (reason == PIN_REASON_MORNING) or (reason == PIN_REASON_EVENING):
		create_pin_regular(user, reason, user_config_version)
	
	return "", 200


def create_pin_regular(user, reason, user_config_version):
	timezone = pytz.timezone(user.timeline_work_timezone)
	now_local = get_local_time(timezone)
	
	# Drop pin if user config changed
	if user_config_version != user.updated.isoformat():
		logging.debug("User config changed since this pin was scheduled, dropping pin")
		return
	
	# Drop pin and schedule next one if timeline token is currently unknown
	if user.token_timeline == "":
		logging.debug("User doesn't currently have a timeline token, dropping pin and scheduling next pin")
		schedule_next_pin_regular(user, reason, now_local, timezone)
		return
	
	# Drop pin and schedule next one if it's a weekend
	if now_local.isoweekday() == 6 or now_local.isoweekday() == 7:
		logging.debug("It's a weekend day for this user, dropping pin and scheduling next pin")
		schedule_next_pin_regular(user, reason, now_local, timezone)
		return
	
	# Fetch directions, parse results
	if reason == PIN_REASON_MORNING:
		orig = REQUEST_TYPE_HOME
		dest = REQUEST_TYPE_WORK
	elif reason == PIN_REASON_EVENING:
		orig = REQUEST_TYPE_WORK
		dest = REQUEST_TYPE_HOME
	else:
		raise ValueError("Unexpected pin reason {}".format(reason))
	directions_json = fetch_directions(user, orig, dest)
	directions = parse_directions(directions_json)
	
	# Handle Google Maps errors, shut off timeline if user intervention is required
	if directions['status'] != "OK":
		logging.warning("Google Maps error for account {}: {}".format(user.key.id(), directions['status']))
		if directions['status'] == "NOT_FOUND" or directions['status'] == "ZERO_RESULTS":
			logging.warning("Disabling timeline setting for account {}".format(user.key.id()))
			user.timeline_enabled = False
			user.updated = datetime.datetime.utcnow()
			user.put()
			return
		else:
			raise Exception("Google Maps returned an unexpected status: {}".format(directions['status']))
	
	# Send pin
	if reason == PIN_REASON_MORNING:
		route = "Home > work"
		route_title = "Drive to work"
		app_launch_code = PAGE_HOME_WORK
		
		# Calculate departure time
		arrival = get_next_local_time_occurence(user.timeline_work_arrival_local, now_local, timezone)
		departure = arrival - datetime.timedelta(seconds = directions['duration_traffic'])
		
		# Update user stats
		user.trip_home_work_mean = (user.trip_home_work_mean * user.trip_home_work_count + directions['duration_traffic']) / (user.trip_home_work_count + 1)
		user.trip_home_work_count += 1
		user.timeline_pins_sent += 1
		user.put()
		
		# Calculate ETA for next pin
		next_arrival = arrival + datetime.timedelta(days = 1)
		next_departure = next_arrival - datetime.timedelta(seconds = user.trip_home_work_mean)
		eta = next_departure - datetime.timedelta(minutes = 40)
	elif reason == PIN_REASON_EVENING:
		route = "Work > home"
		route_title = "Drive home"
		app_launch_code = PAGE_WORK_HOME
		
		# Calculate departure time
		departure = get_next_local_time_occurence(user.timeline_work_departure_local, now_local, timezone)
		
		# Update user stats
		user.trip_work_home_mean = (user.trip_work_home_mean * user.trip_work_home_count + directions['duration_traffic']) / (user.trip_work_home_count + 1)
		user.trip_work_home_count += 1
		user.timeline_pins_sent += 1
		user.put()
		
		# Calculate ETA for next pin
		next_departure = departure + datetime.timedelta(days = 1)
		eta = next_departure - datetime.timedelta(minutes = 25)
	else:
		raise ValueError("Unexpected pin reason {}".format(reason))
	
	send_pin(user, route, route_title, directions, departure, app_launch_code)
	schedule_pin(user, reason, eta)


def schedule_pin(user, reason, eta, queue = "pins-regular"):
	logging.debug("Scheduling pin for {} (reason: {}, queue: {})".format(user.key.id(), reason, queue))
	
	# Add to task queue
	post_params = {
		'token_account': user.key.id(),
		'reason': reason,
		'user_config_version': user.updated.isoformat()
	}
	
	taskqueue.add(queue_name = queue, url = "/pins", params = post_params, eta = eta)


def schedule_next_pin_regular(user, reason, now_local, timezone):
	if reason == PIN_REASON_MORNING:
		next_arrival = get_next_local_time_occurence(user.timeline_work_arrival_local, now_local, timezone)
		if user.trip_home_work_count == 0:
			morning_directions_json = fetch_directions(user, REQUEST_TYPE_HOME, REQUEST_TYPE_WORK)
			morning_directions = parse_directions(morning_directions_json)
			duration_estimate = datetime.timedelta(seconds = morning_directions['duration_traffic'])
		else:
			duration_estimate = datetime.timedelta(seconds = user.trip_home_work_mean)
		next_departure = next_arrival - duration_estimate
		eta_time = next_departure - datetime.timedelta(minutes = 40)
	elif reason == PIN_REASON_EVENING:
		next_departure = get_next_local_time_occurence(user.timeline_work_departure_local, now_local, timezone)
		eta_time = next_departure - datetime.timedelta(minutes = 25)
	else:
		raise ValueError("Unexpected pin reason {}".format(reason))
	
	eta = get_next_local_time_occurence(eta_time.time(), now_local, timezone)
	schedule_pin(user, reason, eta)
