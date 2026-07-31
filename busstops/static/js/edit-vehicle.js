/*jslint browser: true*/

(function () {
    'use strict';


    function formatLivery(livery) {
        if (!livery.id) {
            return livery.text;
        }
        if (livery.css) {
            return $(
                '<div><div class="livery" style="background:'+ livery.css + '"></div>' + livery.text + '</div>'
            );
        }
        return $(
            '<div><div class="livery livery-'+ livery.id + '"></div>' + livery.text + '</div>'
        );
    }

    function data(params) {
        // return the query for the vehicle types/liveries API
        var query = {
            limit: 100,
            published: true,
            offset: ((params.page | 1) - 1) * 100,
        };
        if (params.term) {
            query.name__icontains = params.term;
        } else {
            var suggested = this.data("suggested");
            if (suggested) {
                query.id__in = this.data("suggested");
            } else if ($('#id_operator').val()) {
                query.vehicle__operator = $('#id_operator').val();
            }
        }
        return query;
    }

    function processResults(data) {
        var results = data.results || data;
        return {
            results: results.map(function(item) {
                var name = item.name;
                if (item.noc) {
                    name += " (" + item.noc + ")";
                } else if (item.fuel) {
                    name += " (" + item.fuel;
                    if (item.style) {
                        name += " " + item.style;
                    }
                    name += ")";
                }
                return {
                    id: item.id || item.noc,
                    text: name,
                    css: item.left_css
                };
            }),
            pagination: {
                more: data.next ? true : false
            }
        };
    }

    $('#id_vehicle_type').select2({
        allowClear: true,
        placeholder: "",
        ajax: {
            url: '/api/vehicletypes/',
            data: data,
            processResults: processResults,
            delay: 250
        },
    });

    $('#id_colours').select2({
        allowClear: true,
        placeholder: "",
        ajax: {
            url: '/api/liveries/',
            data: data,
            processResults: processResults,
            delay: 250
        },
        templateResult: formatLivery,
        templateSelection: formatLivery,
    });


    $('#id_operator').select2({
        allowClear: true,
        placeholder: "",
        ajax: {
            url: '/api/operators/',
            data: data,
            processResults: processResults,
            delay: 250
        }
    });

    $('#id_operated_by').select2({
        allowClear: true,
        placeholder: "",
        ajax: {
            url: '/api/operators/',
            data: data,
            processResults: processResults,
            delay: 250
        }
    });

    // Update garage options when operator changes
    $('#id_operator').on('change', function() {
        var operatorNoc = $(this).val();
        var garageSelect = $('#id_garage');
        
        // Clear current garage selection
        garageSelect.val(null);
        
        if (operatorNoc) {
            // Fetch garages for the selected operator
            $.ajax({
                url: '/api/garages/',
                data: {
                    operator: operatorNoc,
                    limit: 100
                },
                success: function(data) {
                    var results = data.results || data;
                    // Clear existing options
                    garageSelect.empty();
                    garageSelect.append('<option value=""></option>');
                    // Add new options
                    results.forEach(function(item) {
                        garageSelect.append('<option value="' + item.garage_id + '">' + item.name + '</option>');
                    });
                }
            });
        } else {
            // No operator selected, clear garage options
            garageSelect.empty();
            garageSelect.append('<option value=""></option>');
        }
    });


    (function syncFleetSupport() {
        var fleetSupportStatus = $('#id_fleet_support_vehicle');
        var fleetSupportFeature = $('#id_features input[value="8"]');

        if (!fleetSupportStatus.length || !fleetSupportFeature.length) {
            return;
        }

        function syncFromStatus() {
            fleetSupportFeature.prop('checked', fleetSupportStatus.prop('checked'));
        }

        function syncFromFeature() {
            fleetSupportStatus.prop('checked', fleetSupportFeature.prop('checked'));
        }

        fleetSupportStatus.on('change', syncFromStatus);
        fleetSupportFeature.on('change', syncFromFeature);
    }());

})();
