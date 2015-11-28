// @codekit-prepend "dist/jstz.js"
/* global jstz:true */

$('.save').on('click', function() {
	var regex_time = /([01]\d|2[0-3]):([0-5]\d)/;
	
	if($('#address_home').val() === "" || $('#address_work').val() === "") {
		window.alert("Please enter your home and work address.");
	} else if(!regex_time.test($('#timeline_work_arrival').val()) || !regex_time.test($('#timeline_work_departure').val())) {
		window.alert("Please enter your arrival and departure times.");
	} else {
		var timeline_work_arrival = $('#timeline_work_arrival').val().split(':');
		var timeline_work_departure = $('#timeline_work_departure').val().split(':');
		var data = {
			'token_timeline': $('#token_timeline').val(),
			'address_home': $('#address_home').val(),
			'address_work': $('#address_work').val(),
			'route_avoid_tolls': $('#route_avoid_tolls').prop('checked'),
			'route_avoid_highways': $('#route_avoid_highways').prop('checked'),
			'route_avoid_ferries': $('#route_avoid_ferries').prop('checked'),
			'timeline_enabled': $('#timeline_enabled').prop('checked'),
			'timeline_work_arrival_h': timeline_work_arrival[0],
			'timeline_work_arrival_m': timeline_work_arrival[1],
			'timeline_work_departure_h': timeline_work_departure[0],
			'timeline_work_departure_m': timeline_work_departure[1],
			'timeline_work_timezone': jstz.determine().name()
		};
		
		if(data.timeline_work_timezone === "Etc/Unknown") {
			window.alert("Sorry, we can't determine your timezone. Please check the timezone settings on your phone, then try again.");
		} else {
			$.ajax({
				type: 'PUT',
				url: $('#submit_to').val(),
				data: data,
				timeout: 10000,
				success: function() {
					window.location = $('#return_to').val();
				},
				error: function() {
					window.alert("Couldn't save your preferences.");
				}
			});
		}
	}
});
