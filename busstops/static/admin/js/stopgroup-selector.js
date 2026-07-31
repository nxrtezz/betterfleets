(function () {
    "use strict";

    const DEFAULT_CENTER = [-2.5, 54.5];
    const DEFAULT_ZOOM = 6;
    const MIN_FETCH_ZOOM = 11;

    function escapeHtml(value) {
        return String(value || "").replace(/[&<>"']/g, function (char) {
            return {
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;",
            }[char];
        });
    }

    function parseSelectedIds(value) {
        return (value || "")
            .split(",")
            .map(function (item) { return item.trim(); })
            .filter(Boolean);
    }

    document.addEventListener("DOMContentLoaded", function () {
        const root = document.querySelector(".stop-group-selector");
        if (!root || !window.ol) {
            return;
        }

        let hiddenInput = document.querySelector('input[name="stops_selection"]');
        if (!hiddenInput) {
            hiddenInput = document.createElement("input");
            hiddenInput.type = "hidden";
            hiddenInput.name = "stops_selection";
            const form = root.closest("form");
            if (form) {
                form.appendChild(hiddenInput);
            }
        }
        if (!hiddenInput) {
            return;
        }

        if (!hiddenInput.value) {
            hiddenInput.value = root.dataset.selectedStopIds || "";
        }

        const status = root.querySelector(".stop-group-selector-status");
        const list = root.querySelector(".stop-group-selector-list");
        const mapElement = root.querySelector(".stop-group-selector-map");
        const diagnostics = document.createElement("pre");
        diagnostics.className = "stop-group-selector-diagnostics";
        diagnostics.style.whiteSpace = "pre-wrap";
        diagnostics.style.marginTop = "0.75rem";
        diagnostics.style.padding = "0.75rem";
        diagnostics.style.border = "1px solid #d4d4d4";
        diagnostics.style.background = "#fff";
        diagnostics.style.display = "none";
        root.appendChild(diagnostics);
        const selectedIds = parseSelectedIds(hiddenInput.value);
        const selectedStops = new Map();
        const availableStops = new Map();

        function showDiagnostics(lines) {
            diagnostics.style.display = "block";
            diagnostics.textContent = lines.join("\n");
        }

        list.querySelectorAll("li[data-stop-id]").forEach(function (item) {
            const stopId = item.getAttribute("data-stop-id");
            if (stopId) {
                selectedStops.set(stopId, {
                    properties: {
                        atco_code: stopId,
                        name: item.getAttribute("data-stop-name") || stopId,
                        indicator: "",
                    },
                });
            }
        });

        function syncHiddenInput() {
            hiddenInput.value = selectedIds.join(",");
        }

        function renderSelectedList() {
            if (!selectedIds.length) {
                list.innerHTML = '<li class="empty">No stops selected yet.</li>';
                return;
            }

            list.innerHTML = selectedIds.map(function (stopId) {
                const stop = selectedStops.get(stopId);
                const name = stop && stop.properties ? stop.properties.name : stopId;
                return (
                    '<li data-stop-id="' + escapeHtml(stopId) + '" data-stop-name="' + escapeHtml(name) + '">' +
                    '<button type="button" class="stop-group-selector-remove" data-stop-id="' + escapeHtml(stopId) + '">Remove</button> ' +
                    escapeHtml(name) +
                    ' <span class="quiet">' + escapeHtml(stopId) + "</span></li>"
                );
            }).join("");
        }

        function selectedStyle() {
            return new ol.style.Style({
                image: new ol.style.Circle({
                    radius: 7,
                    fill: new ol.style.Fill({ color: "#d97706" }),
                    stroke: new ol.style.Stroke({ color: "#ffffff", width: 2 }),
                }),
            });
        }

        function availableStyle(feature) {
            const stopId = feature.get("atco_code");
            const isSelected = selectedIds.indexOf(stopId) !== -1;
            return new ol.style.Style({
                image: new ol.style.Circle({
                    radius: isSelected ? 7 : 5,
                    fill: new ol.style.Fill({ color: isSelected ? "#d97706" : "#1d4ed8" }),
                    stroke: new ol.style.Stroke({ color: "#ffffff", width: isSelected ? 2 : 1.5 }),
                }),
            });
        }

        const availableSource = new ol.source.Vector();
        const selectedSource = new ol.source.Vector();

        let map;
        try {
            map = new ol.Map({
                target: mapElement,
                layers: [
                    new ol.layer.Tile({
                        source: new ol.source.OSM(),
                    }),
                    new ol.layer.Vector({
                        source: availableSource,
                        style: availableStyle,
                    }),
                    new ol.layer.Vector({
                        source: selectedSource,
                        style: selectedStyle,
                    }),
                ],
                view: new ol.View({
                    center: ol.proj.fromLonLat(DEFAULT_CENTER),
                    zoom: DEFAULT_ZOOM,
                }),
            });
        } catch (error) {
            const detail =
                error && error.message ? ": " + error.message : ".";
            status.textContent = "Stop selector failed to initialise" + detail;
            showDiagnostics([
                "Stop selector diagnostics",
                "window.ol: " + Boolean(window.ol),
                "ol.Map: " + Boolean(window.ol && ol.Map),
                "ol.View: " + Boolean(window.ol && ol.View),
                "ol.layer.Tile: " + Boolean(window.ol && ol.layer && ol.layer.Tile),
                "ol.source.OSM: " + Boolean(window.ol && ol.source && ol.source.OSM),
                "ol.proj.fromLonLat: " + Boolean(window.ol && ol.proj && ol.proj.fromLonLat),
                "map element found: " + Boolean(mapElement),
                "map element size: "
                    + (mapElement ? mapElement.clientWidth + "x" + mapElement.clientHeight : "n/a"),
                "selected ids: " + selectedIds.length,
                "error.name: " + (error && error.name ? error.name : "(none)"),
                "error.message: " + (error && error.message ? error.message : "(none)"),
                "error.string: " + String(error),
            ]);
            if (window.console && console.error) {
                console.error("Stop selector init failed", error);
            }
            return;
        }

        const locationLng = parseFloat(root.dataset.locationLng || "");
        const locationLat = parseFloat(root.dataset.locationLat || "");
        if (!Number.isNaN(locationLng) && !Number.isNaN(locationLat)) {
            map.getView().setCenter(ol.proj.fromLonLat([locationLng, locationLat]));
            map.getView().setZoom(14);
        }

        function selectedFeatureData(stop) {
            return {
                type: "Feature",
                geometry: stop.geometry,
                properties: {
                    atco_code: stop.properties.atco_code,
                    name: stop.properties.name,
                    indicator: stop.properties.indicator || "",
                },
            };
        }

        function rebuildSelectedSource() {
            selectedSource.clear();
            selectedIds.forEach(function (stopId) {
                const stop = selectedStops.get(stopId);
                if (!stop || !stop.geometry || !stop.geometry.coordinates) {
                    return;
                }
                const feature = new ol.Feature({
                    geometry: new ol.geom.Point(
                        ol.proj.fromLonLat(stop.geometry.coordinates)
                    ),
                });
                feature.setProperties(stop.properties);
                selectedSource.addFeature(feature);
            });
        }

        function addStop(stopId) {
            if (!stopId || selectedIds.indexOf(stopId) !== -1) {
                return;
            }
            const stop = availableStops.get(stopId) || selectedStops.get(stopId);
            if (!stop) {
                return;
            }
            selectedIds.push(stopId);
            selectedStops.set(stopId, selectedFeatureData(stop));
            syncHiddenInput();
            renderSelectedList();
            rebuildSelectedSource();
            availableSource.changed();
        }

        function removeStop(stopId) {
            const index = selectedIds.indexOf(stopId);
            if (index === -1) {
                return;
            }
            selectedIds.splice(index, 1);
            selectedStops.delete(stopId);
            syncHiddenInput();
            renderSelectedList();
            rebuildSelectedSource();
            availableSource.changed();
        }

        list.addEventListener("click", function (event) {
            const button = event.target.closest(".stop-group-selector-remove");
            if (!button) {
                return;
            }
            event.preventDefault();
            removeStop(button.getAttribute("data-stop-id"));
        });

        async function loadStops() {
            const zoom = map.getView().getZoom() || 0;
            if (zoom < MIN_FETCH_ZOOM) {
                availableSource.clear();
                availableStops.clear();
                status.textContent = "Zoom in to load stops.";
                return;
            }

            const extent = map.getView().calculateExtent(map.getSize());
            const southWest = ol.proj.transform(
                ol.extent.getBottomLeft(extent),
                "EPSG:3857",
                "EPSG:4326"
            );
            const northEast = ol.proj.transform(
                ol.extent.getTopRight(extent),
                "EPSG:3857",
                "EPSG:4326"
            );
            const params = new URLSearchParams({
                xmin: southWest[0],
                ymin: southWest[1],
                xmax: northEast[0],
                ymax: northEast[1],
            });
            if (root.dataset.includeUnlinkedStops === "1") {
                params.set("include_unlinked", "1");
            }

            status.textContent = "Loading stops...";

            const response = await fetch(root.dataset.stopsUrl + "?" + params.toString(), {
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });

            if (!response.ok) {
                status.textContent = "Could not load stops for this area.";
                return;
            }

            const payload = await response.json();
            const geojson = new ol.format.GeoJSON();
            const features = (payload.features || []).filter(function (feature) {
                const properties = feature.properties || {};
                return properties.atco_code && !properties.stop_group;
            });

            availableStops.clear();
            features.forEach(function (feature) {
                availableStops.set(feature.properties.atco_code, feature);
                if (selectedIds.indexOf(feature.properties.atco_code) !== -1) {
                    selectedStops.set(
                        feature.properties.atco_code,
                        selectedFeatureData(feature)
                    );
                }
            });

            availableSource.clear();
            availableSource.addFeatures(
                geojson.readFeatures(
                    {
                        type: "FeatureCollection",
                        features: features,
                    },
                    {
                        dataProjection: "EPSG:4326",
                        featureProjection: "EPSG:3857",
                    }
                )
            );

            rebuildSelectedSource();
            renderSelectedList();
            status.textContent = features.length + " stops loaded in this area.";
        }

        map.on("singleclick", function (event) {
            const feature = map.forEachFeatureAtPixel(event.pixel, function (candidate) {
                return candidate;
            });
            if (!feature) {
                return;
            }
            const stopId = feature.get("atco_code");
            if (!stopId) {
                return;
            }
            if (selectedIds.indexOf(stopId) === -1) {
                addStop(stopId);
            } else {
                removeStop(stopId);
            }
        });

        map.on("moveend", function () {
            loadStops().catch(function () {
                status.textContent = "Could not load stops for this area.";
            });
        });

        syncHiddenInput();
        renderSelectedList();
        rebuildSelectedSource();
        loadStops().catch(function () {
            status.textContent = "Could not load stops for this area.";
        });
    });
})();
