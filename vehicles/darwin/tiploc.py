"""TIPLOC -> coordinate resolution.

Order of attempts:
1. StopPoint.tiploc (populated by the NaPTAN importer)
2. StopPoint.atco_code == "9100" + tpl (the NaPTAN convention for rail stations)
3. CRS code from the Darwin reference data -> StopPoint.crs
4. nearest rail StopPoint within ~1.5km (junction TIPLOCs etc)
"""

import logging

logger = logging.getLogger(__name__)


class TiplocResolver:
    def __init__(self, reference: dict | None = None):
        self.reference = reference or {}
        self.locations = self.reference.get("locations", {})
        self._cache: dict[str, tuple[float, float] | None] = {}

    def _stop_for_tiploc(self, tpl: str):
        from busstops.models import StopPoint

        stop = StopPoint.objects.filter(tiploc__iexact=tpl).first()
        if stop is None:
            stop = StopPoint.objects.filter(atco_code__iexact=f"9100{tpl}").first()
        return stop

    def _stop_for_crs(self, crs: str):
        from busstops.models import StopPoint

        if hasattr(StopPoint, "crs"):
            return StopPoint.objects.filter(crs__iexact=crs).first()
        return None

    def get_coord(self, tpl: str) -> tuple[float, float] | None:
        """-> (lon, lat)"""
        if tpl in self._cache:
            return self._cache[tpl]

        coord = self._resolve(tpl)
        self._cache[tpl] = coord
        return coord

    def _resolve(self, tpl: str) -> tuple[float, float] | None:
        stop = self._stop_for_tiploc(tpl)
        if stop and stop.latlong:
            return (stop.latlong.x, stop.latlong.y)

        # try the CRS code via reference data
        if (crs := self.locations.get(tpl, {}).get("crs")) and (
            stop := self._stop_for_crs(crs)
        ) and stop.latlong:
            return (stop.latlong.x, stop.latlong.y)

        return None

    def get_name(self, tpl: str) -> str | None:
        """official location name from the reference data, else StopPoint name"""
        if loc := self.locations.get(tpl):
            if name := loc.get("locname"):
                if name != tpl:
                    return name
        if stop := self._stop_for_tiploc(tpl):
            return stop.common_name or stop.naptan_code
        return None
