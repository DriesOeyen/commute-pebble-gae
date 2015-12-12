from google.appengine.ext import ndb

class User(ndb.Model):
	token_timeline = ndb.StringProperty()
	tester = ndb.BooleanProperty(default=False)
	
	address_home = ndb.StringProperty()
	address_work = ndb.StringProperty()
	route_avoid_tolls = ndb.BooleanProperty(default=False)
	route_avoid_highways = ndb.BooleanProperty(default=False)
	route_avoid_ferries = ndb.BooleanProperty(default=False)
	
	timeline_enabled = ndb.BooleanProperty(default=True)
	timeline_pins_sent = ndb.IntegerProperty(default=0)
	timeline_pins_home_work_last = ndb.DateTimeProperty()
	timeline_pins_work_home_last = ndb.DateTimeProperty()
	timeline_onboarding_sent = ndb.BooleanProperty(default=False)
	timeline_work_arrival = ndb.DateTimeProperty()
	timeline_work_departure = ndb.DateTimeProperty()
	timeline_work_timezone = ndb.StringProperty()
	
	trip_home_work_mean = ndb.IntegerProperty(default=0)
	trip_home_work_count = ndb.IntegerProperty(default=0)
	trip_work_home_mean = ndb.IntegerProperty(default=0)
	trip_work_home_count = ndb.IntegerProperty(default=0)
