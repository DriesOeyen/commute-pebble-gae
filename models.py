from google.appengine.ext import ndb

class User(ndb.Model):
	token_timeline = ndb.StringProperty()
	
	address_home = ndb.StringProperty()
	address_work = ndb.StringProperty()
	route_avoid_tolls = ndb.BooleanProperty(default=False)
	route_avoid_highways = ndb.BooleanProperty(default=False)
	route_avoid_ferries = ndb.BooleanProperty(default=False)
	
	timeline_enabled = ndb.BooleanProperty(default=True)
	timeline_work_arrival = ndb.DateTimeProperty()
	timeline_work_departure = ndb.DateTimeProperty()
	timeline_work_timezone = ndb.StringProperty()
