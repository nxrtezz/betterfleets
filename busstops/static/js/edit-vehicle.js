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
            } else {
                query.vehicle__operator = $('#id_operator').val();
            }
        }
        return query;
    }

    function processResults(data) {
        return {
            results: data.results.map(function(item) {
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
        },
        minimumInputLength: 1
    });

    // Vehicle management links
    const addPhotoLink = document.querySelector('.add-photo-link');
    if (addPhotoLink) {
        addPhotoLink.addEventListener('click', function(e) {
            e.preventDefault();
            // Open the existing photo form
            const photoDetails = document.querySelector('details[name="advanced"]');
            if (photoDetails) {
                photoDetails.open = true;
                photoDetails.scrollIntoView({ behavior: 'smooth' });
            }
        });
    }

    const mergeVehicleLink = document.querySelector('.merge-vehicle-link');
    if (mergeVehicleLink) {
        mergeVehicleLink.addEventListener('click', function(e) {
            e.preventDefault();
            const vehicleId = document.querySelector('meta[name="vehicle-id"]')?.content;
            const reg = prompt('Enter registration number to search for:');
            if (reg && vehicleId) {
                window.location.href = '/vehicles/merge/?reg=' + encodeURIComponent(reg) + '&active_vehicle_id=' + vehicleId;
            }
        });
    }

    const deleteVehicleLink = document.querySelector('.delete-vehicle-link');
    if (deleteVehicleLink) {
        deleteVehicleLink.addEventListener('click', function(e) {
            e.preventDefault();
            if (confirm('Are you sure you want to delete this vehicle? This action cannot be undone.')) {
                const vehicleId = document.querySelector('meta[name="vehicle-id"]')?.content;
                if (vehicleId) {
                    // Get CSRF token from cookie
                    function getCookie(name) {
                        let cookieValue = null;
                        if (document.cookie && document.cookie !== '') {
                            const cookies = document.cookie.split(';');
                            for (let i = 0; i < cookies.length; i++) {
                                const cookie = cookies[i].trim();
                                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                                    break;
                                }
                            }
                        }
                        return cookieValue;
                    }
                    const csrfToken = getCookie('csrftoken');
                    if (csrfToken) {
                        fetch('/admin/vehicles/vehicle/' + vehicleId + '/delete/', {
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': csrfToken,
                            },
                        }).then(response => {
                            if (response.ok) {
                                window.location.href = '/';
                            } else {
                                alert('Failed to delete vehicle');
                            }
                        });
                    } else {
                        alert('Could not get CSRF token');
                    }
                }
            }
        });
    }

})();
