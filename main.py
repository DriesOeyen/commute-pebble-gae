import models
import flask

import datetime
import json
import logging
import math
import pytz
import urllib
import urllib2
from google.appengine.ext import ndb

app = flask.Flask(__name__)

google_maps_key = "AIzaSyDLG4q9x0pkI-eRyyL7x__pl2btULRRK8k"
google_maps_base_url = "https://maps.googleapis.com/maps/api"

pebble_timeline_base_url = "https://timeline-api.getpebble.com/v1"

date_epoch = datetime.date(1970, 1, 1)

REQUEST_TYPE_LOCATION = 0
REQUEST_TYPE_HOME = 1
REQUEST_TYPE_WORK = 2

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
	if user:
		# Existing user -> calculate hours
		now = datetime.datetime.utcnow()
		timeline_work_timezone = pytz.timezone(user.timeline_work_timezone)
		timeline_work_arrival = datetime.datetime.combine(now.date(), user.timeline_work_arrival.time())
		timeline_work_arrival_utc = pytz.utc.localize(timeline_work_arrival)
		timeline_work_arrival_local = timeline_work_timezone.normalize(timeline_work_arrival_utc.astimezone(timeline_work_timezone))
		timeline_work_arrival_string = timeline_work_arrival_local.strftime('%H:%M')
		timeline_work_departure = datetime.datetime.combine(now.date(), user.timeline_work_departure.time())
		timeline_work_departure_utc = pytz.utc.localize(timeline_work_departure)
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


@app.route('/user/<token_account>', methods=['PUT'])
def put_user(token_account):
	# Fetch user
	user = models.User.get_by_id(token_account)
	if user == None:
		# Create new user
		user = models.User(
			id = token_account
		)
	
	# Parse times
	now = datetime.datetime.utcnow()
	timeline_work_timezone = pytz.timezone(flask.request.form['timeline_work_timezone'])
	timeline_work_arrival_h = int(flask.request.form['timeline_work_arrival_h'])
	timeline_work_arrival_m = int(flask.request.form['timeline_work_arrival_m'])
	timeline_work_arrival = datetime.datetime.combine(now.date(), datetime.time(timeline_work_arrival_h, timeline_work_arrival_m))
	timeline_work_arrival_local = timeline_work_timezone.localize(timeline_work_arrival)
	timeline_work_arrival_utc_temp = pytz.utc.normalize(timeline_work_arrival_local.astimezone(pytz.utc))
	timeline_work_arrival_utc = timeline_work_arrival_utc_temp.replace(date_epoch.year, date_epoch.month, date_epoch.day) # Make UTC date epoch day
	timeline_work_departure_h = int(flask.request.form['timeline_work_departure_h'])
	timeline_work_departure_m = int(flask.request.form['timeline_work_departure_m'])
	timeline_work_departure = datetime.datetime.combine(now.date(), datetime.time(timeline_work_departure_h, timeline_work_departure_m))
	timeline_work_departure_local = timeline_work_timezone.localize(timeline_work_departure)
	timeline_work_departure_utc_temp = pytz.utc.normalize(timeline_work_departure_local.astimezone(pytz.utc))
	timeline_work_departure_utc = timeline_work_departure_utc_temp.replace(date_epoch.year, date_epoch.month, date_epoch.day) # Make UTC date epoch day
	
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
	user.trip_home_work_mean = 0
	user.trip_home_work_count = 0
	user.trip_work_home_mean = 0
	user.trip_work_home_count = 0
	user.put()
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
	request_orig = int(flask.request.args['request_orig'])
	request_dest = int(flask.request.args['request_dest'])
	request_coord = flask.request.args.get('request_coord', "")
	
	# Fetch user
	user = models.User.get_by_id(token_account)
	if user == None:
		# User not found
		return "", 404
	
	# Update timeline token if necessary
	if token_timeline != "" and token_timeline != user.token_timeline:
		logging.debug("Persisting new timeline token for user {}: {} (was {})".format(user.key.id(), token_timeline, user.token_timeline))
		user.token_timeline = token_timeline
		user.put()
	
	# Fetch and return directions
	try:
		return fetch_directions(user, request_orig, request_dest, request_coord)
	except (urllib2.URLError, urllib2.HTTPError):
		return "", 502


@app.route('/tasks/pins')
def task_run_pins():
	# Get users of interest: pick and run a query based on the time of day
	# 		Legend for schematic descriptions:
	# 		00:00 ----x----x---- 23:59 (timeline doesn't take date into account)
	# 		a = lower boundary of interest
	# 		b = upper boundary of interest
	# 		- = timespan that's not affected by this part of the query
	# 		* = timespan that's affected by this part of the query
	now = datetime.datetime.utcnow()
	bound_25_min = datetime.datetime.combine(date_epoch, (now + datetime.timedelta(minutes=25)).time())
	bound_30_min = datetime.datetime.combine(date_epoch, (now + datetime.timedelta(minutes=30)).time())
	bound_55_min = datetime.datetime.combine(date_epoch, (now + datetime.timedelta(minutes=55)).time())
	bound_4_hour = datetime.datetime.combine(date_epoch, (now + datetime.timedelta(hours=4)).time())
	if bound_4_hour > bound_55_min and bound_30_min > bound_25_min:
		users = models.User.query(
			ndb.OR(
				# Check if work arrival is within bounds of interest
				# ----a****b----
				ndb.AND(
					models.User.timeline_enabled == True,
					models.User.timeline_work_arrival >= bound_55_min,
					models.User.timeline_work_arrival <= bound_4_hour
				),
				
				# Check if work departure is within bounds of interest
				# ----a****b----
				ndb.AND(
					models.User.timeline_enabled == True,
					models.User.timeline_work_departure >= bound_25_min,
					models.User.timeline_work_departure <= bound_30_min
				)
			)
		)
	elif bound_4_hour > bound_55_min and bound_30_min < bound_25_min:
		users = models.User.query(
			ndb.OR(
				# Check if work arrival is within bounds of interest
				# ----a****b----
				ndb.AND(
					models.User.timeline_enabled == True,
					models.User.timeline_work_arrival >= bound_55_min,
					models.User.timeline_work_arrival <= bound_4_hour
				),
				
				# Check if work departure is within bounds of interest
				# ----b----a****
				ndb.AND(
					models.User.timeline_enabled == True,
					models.User.timeline_work_departure >= bound_25_min
				),
				# ****b----a----
				ndb.AND(
					models.User.timeline_enabled == True,
					models.User.timeline_work_departure <= bound_30_min
				)
			)
		)
	elif bound_4_hour < bound_55_min and bound_30_min > bound_25_min:
		users = models.User.query(
			ndb.OR(
				# Check if work arrival is within bounds of interest
				# ----b----a****
				ndb.AND(
					models.User.timeline_enabled == True,
					models.User.timeline_work_arrival >= bound_55_min
				),
				# ****b----a----
				ndb.AND(
					models.User.timeline_enabled == True,
					models.User.timeline_work_arrival <= bound_4_hour
				),
				
				# Check if work departure is within bounds of interest
				# ----a****b----
				ndb.AND(
					models.User.timeline_enabled == True,
					models.User.timeline_work_departure >= bound_25_min,
					models.User.timeline_work_departure <= bound_30_min
				)
			)
		)
	elif bound_4_hour < bound_55_min and bound_30_min < bound_25_min:
		users = models.User.query(
			ndb.OR(
				# Check if work arrival is within bounds of interest
				# ----b----a****
				ndb.AND(
					models.User.timeline_enabled == True,
					models.User.timeline_work_arrival >= bound_55_min
				),
				# ****b----a----
				ndb.AND(
					models.User.timeline_enabled == True,
					models.User.timeline_work_arrival <= bound_4_hour
				),
				
				# Check if work departure is within bounds of interest
				# ----b----a****
				ndb.AND(
					models.User.timeline_enabled == True,
					models.User.timeline_work_departure >= bound_25_min
				),
				# ****b----a----
				ndb.AND(
					models.User.timeline_enabled == True,
					models.User.timeline_work_departure <= bound_30_min
				)
			)
		)
	else:
		return 500, ""
	
	# Loop through users of interest, push pin if necessary
	for user in users:
		if user.token_timeline != "":
			# Skip this user if it's a weekend in their timezone
			timeline_work_timezone = pytz.timezone(user.timeline_work_timezone)
			now_utc = pytz.utc.localize(now)
			now_local = timeline_work_timezone.normalize(now_utc.astimezone(timeline_work_timezone))
			if now_local.isoweekday() == 6 or now_local.isoweekday() == 7:
				continue
			
			# Calculate (estimated) departure time ("T")
			t_home_work = user.timeline_work_arrival - datetime.timedelta(seconds = user.trip_home_work_mean + 1800)
			t_work_home = user.timeline_work_departure
			
			# Calculate seconds until (estimated) departure time ("T-minus")
			t_minus_home_work = (t_home_work - now).seconds # timedelta.seconds ignores difference in date
			t_minus_work_home = (t_work_home - now).seconds
			
			# Calculate how long it has been since the last pins were sent
			timeline_pins_delta_min = datetime.timedelta(hours=4)
			if user.timeline_pins_home_work_last == None:
				timeline_pins_home_work_last_delta = timeline_pins_delta_min
			else:
				timeline_pins_home_work_last_delta = now - user.timeline_pins_home_work_last
			if user.timeline_pins_work_home_last == None:
				timeline_pins_work_home_last_delta = timeline_pins_delta_min
			else:
				timeline_pins_work_home_last_delta = now - user.timeline_pins_work_home_last
			
			# Home -> work trip
			if t_minus_home_work >= 25*60 and t_minus_home_work < 30*60 and timeline_pins_home_work_last_delta >= timeline_pins_delta_min:
				try:
					logging.debug("Pushing home -> work pin for account {}".format(user.key.id()))
					
					# Fetch directions, parse results
					directions_json = fetch_directions(user, REQUEST_TYPE_HOME, REQUEST_TYPE_WORK)
					directions = parse_directions(directions_json)
					
					# Handle Google Maps errors, shut off timeline if user intervention is required
					if directions['status'] != "OK":
						logging.warning("Google Maps error for account {}: {}".format(user.key.id(), directions['status']))
						if directions['status'] == "NOT_FOUND" or directions['status'] == "ZERO_RESULTS":
							logging.warning("Disabling timeline setting for account {}".format(user.key.id()))
							user.timeline_enabled = False
							user.put()
						continue
					
					# Update user stats (part 1 of 2)
					user.timeline_pins_home_work_last = now
					user.trip_home_work_mean = (user.trip_home_work_mean * user.trip_home_work_count + directions['duration_traffic']) / (user.trip_home_work_count + 1)
					user.trip_home_work_count += 1
					
					# Stop here if this is the first home -> work trip
					# Because user.trip_home_work_mean was initialized as 0, this pin would likely be pushed to the past
					if user.trip_home_work_count == 1:
						logging.debug("This is the first home -> work pin for account {}, user stats are now initialized. This pin is being dropped, but subsequent pins will be sent.".format(user.key.id()))
						user.put()
						continue
					
					# Update user stats (part 2 of 2)
					user.timeline_pins_sent += 1
					user.put()
					
					# Calculate departure/arrival times
					if now.time() <= user.timeline_work_arrival.time():
						timeline_work_arrival_date = now.date()
					else: # If arrival time is tomorrow, put tomorrow as the date
						timeline_work_arrival_date = now.date() + datetime.timedelta(days=1)
					timeline_work_arrival_utc = pytz.utc.localize(datetime.datetime.combine(timeline_work_arrival_date, user.timeline_work_arrival.time()))
					timeline_work_arrival_local = timeline_work_timezone.normalize(timeline_work_arrival_utc.astimezone(timeline_work_timezone))
					timeline_work_arrival_string = timeline_work_arrival_local.strftime('%H:%M')
					timeline_home_departure_utc = timeline_work_arrival_utc - datetime.timedelta(seconds = directions['duration_traffic'])
					timeline_home_departure_local = timeline_work_timezone.normalize(timeline_home_departure_utc.astimezone(timeline_work_timezone))
					timeline_home_departure_string = timeline_home_departure_local.strftime('%H:%M')
					
					# Build pin
					id = "{}-{}".format(user.key.id(), user.timeline_pins_sent)
					if int(round(directions['duration_delay'] / 60)) == 0:
						duration_delay_label_minutes = "minutes"
						duration_delay_label_cause = "thanks to"
					elif int(round(directions['duration_delay'] / 60)) == 1:
						duration_delay_label_minutes = "minute"
						duration_delay_label_cause = "due to"
					else:
						duration_delay_label_minutes = "minutes"
						duration_delay_label_cause = "due to"
					pin = dict(
						id = id,
						time = timeline_home_departure_utc.isoformat(),
						duration = int(round(directions['duration_traffic'] / 60)),
						layout = dict(
							type = "sportsPin",
							title = "Home > work",
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
								"Home > work",
								"{} - {}".format(timeline_home_departure_string, timeline_work_arrival_string)
							],
							lastUpdated = now.isoformat(),
							nameAway = "Total",
							nameHome = "Delay",
							scoreAway = "{}".format(int(round(directions['duration_traffic'] / 60))),
							scoreHome = "{}".format(int(round(directions['duration_delay'] / 60))),
							sportsGameState = "in-game"
						),
						reminders = [
							dict(
								time = (timeline_home_departure_utc - datetime.timedelta(minutes=10)).isoformat(),
								layout = dict(
									type = "genericReminder",
									title = "Leave for work",
									body = u"Drive via {} to arrive by {}, with {} {} of delay {} {} traffic.".format(directions['via'], timeline_work_arrival_string, int(round(directions['duration_delay'] / 60)), duration_delay_label_minutes, duration_delay_label_cause, directions['conditions_text']),
									tinyIcon = "system://images/CAR_RENTAL"
								)
							)
						],
						actions = [
							dict(
								type = "openWatchApp",
								title = "Open Commute",
								launchCode = PAGE_HOME_WORK
							)
						]
					)
					
					# Send pin
					logging.debug(json.dumps(pin))
					opener = urllib2.build_opener(urllib2.HTTPHandler)
					request = urllib2.Request("{}/user/pins/{}".format(pebble_timeline_base_url, id), data = json.dumps(pin))
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
				except:
					logging.error("Error pushing pin for account {}".format(user.key.id()))
			# Work -> home trip
			if t_minus_work_home >= 25*60 and t_minus_work_home < 30*60 and timeline_pins_work_home_last_delta >= timeline_pins_delta_min:
				try:
					logging.debug("Pushing work -> home pin for account {}".format(user.key.id()))
					
					# Fetch directions, parse results
					directions_json = fetch_directions(user, REQUEST_TYPE_WORK, REQUEST_TYPE_HOME)
					directions = parse_directions(directions_json)
					
					# Handle Google Maps errors, shut off timeline if user intervention is required
					if directions['status'] != "OK":
						logging.warning("Google Maps error for account {}: {}".format(user.key.id(), directions['status']))
						if directions['status'] == "NOT_FOUND" or directions['status'] == "ZERO_RESULTS":
							logging.warning("Disabling timeline setting for account {}".format(user.key.id()))
							user.timeline_enabled = False
							user.put()
						continue
					
					# Update user stats
					user.timeline_pins_work_home_last = now
					user.trip_work_home_mean = (user.trip_work_home_mean * user.trip_work_home_count + directions['duration_traffic']) / (user.trip_work_home_count + 1)
					user.trip_work_home_count += 1
					user.timeline_pins_sent += 1
					user.put()
					
					# Calculate departure/arrival times
					if now.time() <= user.timeline_work_departure.time():
						timeline_work_departure_date = now.date()
					else: # If departure time is tomorrow, put tomorrow as the date
						timeline_work_departure_date = now.date() + datetime.timedelta(days=1)
					timeline_work_departure_utc = pytz.utc.localize(datetime.datetime.combine(timeline_work_departure_date, user.timeline_work_departure.time()))
					timeline_work_departure_local = timeline_work_timezone.normalize(timeline_work_departure_utc.astimezone(timeline_work_timezone))
					timeline_work_departure_string = timeline_work_departure_local.strftime('%H:%M')
					timeline_home_arrival_utc = timeline_work_departure_utc + datetime.timedelta(seconds = directions['duration_traffic'])
					timeline_home_arrival_local = timeline_work_timezone.normalize(timeline_home_arrival_utc.astimezone(timeline_work_timezone))
					timeline_home_arrival_string = timeline_home_arrival_local.strftime('%H:%M')
					
					# Build pin
					id = "{}-{}".format(user.key.id(), user.timeline_pins_sent)
					if int(round(directions['duration_delay'] / 60)) == 0:
						duration_delay_label_minutes = "minutes"
						duration_delay_label_cause = "thanks to"
					elif int(round(directions['duration_delay'] / 60)) == 1:
						duration_delay_label_minutes = "minute"
						duration_delay_label_cause = "due to"
					else:
						duration_delay_label_minutes = "minutes"
						duration_delay_label_cause = "due to"
					pin = dict(
						id = id,
						time = timeline_work_departure_utc.isoformat(),
						duration = int(round(directions['duration_traffic'] / 60)),
						layout = dict(
							type = "sportsPin",
							title = "Work > home",
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
								"Work > home",
								"{} - {}".format(timeline_work_departure_string, timeline_home_arrival_string)
							],
							lastUpdated = now.isoformat(),
							nameAway = "Total",
							nameHome = "Delay",
							scoreAway = "{}".format(int(round(directions['duration_traffic'] / 60))),
							scoreHome = "{}".format(int(round(directions['duration_delay'] / 60))),
							sportsGameState = "in-game"
						),
						reminders = [
							dict(
								time = (timeline_work_departure_utc - datetime.timedelta(minutes=10)).isoformat(),
								layout = dict(
									type = "genericReminder",
									title = "Your drive home",
									body = u"Drive via {} to arrive by {}, with {} {} of delay {} {} traffic.".format(directions['via'], timeline_home_arrival_string, int(round(directions['duration_delay'] / 60)), duration_delay_label_minutes, duration_delay_label_cause, directions['conditions_text']),
									tinyIcon = "system://images/CAR_RENTAL"
								)
							)
						],
						actions = [
							dict(
								type = "openWatchApp",
								title = "Open Commute",
								launchCode = PAGE_WORK_HOME
							)
						]
					)
					
					# Add onboarding notification if this is the user's first visible pin
					if user.timeline_onboarding_sent == False:
						if user.trip_home_work_count == 0:
							notification_body = "You'll get timeline pins and reminders telling you when to leave for work to arrive on time, or how long it'll take to get back home. Your first pin is available now. Quick note: you won't get a pin for your first trip to work, since Commute needs to collect some typical traffic data first. Enjoy!"
						else:
							notification_body = "You'll get timeline pins and reminders telling you when to leave for work to arrive on time, or how long it'll take to get back home. Your first pin is available now. Enjoy!"
						pin['createNotification'] = dict(
							layout = dict(
								type = "genericNotification",
								title = "Commute is on your timeline!",
								tinyIcon = "system://images/CAR_RENTAL",
								body = notification_body,
								primaryColor = "black",
								backgroundColor = "orange"
							)
						)
						user.timeline_onboarding_sent = True
						user.put()
					
					# Send pin
					logging.debug(json.dumps(pin))
					opener = urllib2.build_opener(urllib2.HTTPHandler)
					request = urllib2.Request("{}/user/pins/{}".format(pebble_timeline_base_url, id), data = json.dumps(pin))
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
				except:
					logging.error("Error pushing pin for account {}".format(user.key.id()))
	return "", 200
