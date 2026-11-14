from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from busstops.models import DataSource

from ...utils import get_sha1, log_time_taken


class Command(BaseCommand):
    """Downloads fresh Traveline National Dataset (TNDS) data
    from the password-protected FTP server
    (I know, not my choice of technology)
    and calls the import_transxchange command"""

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("username", type=str)
        parser.add_argument("password", type=str)
        parser.add_argument("--regions", nargs="+", help="Only import these TNDS regions, e.g. L S")

    def list_files(self) -> dict:
        # Include London: a separate original TfL timetable importer is not
        # configured in this deployment, while London vehicles are tracking.
        files = [
            (name, details)
            for name, details in self.ftp.mlsd()
            if name.endswith(".zip")
        ]
        files.sort(key=lambda item: int(item[1]["size"]))  # smallest files first
        return dict(files)

    def do_files(self, files: dict):
        for name, details in files.items():
            self.do_file(name, details)

    def do_file(self, name, details):
        url = f"ftp://{self.ftp.host}/{name}"
        region_name = name.removesuffix(".zip").upper()
        if region_name == "IOM":
            region_name = "IM"
        # Historical download-only rows may share a URL with the named
        # source used by TransXChange. Reuse the named source deterministically.
        source = DataSource.objects.filter(url=url, name=region_name).first()
        if source is None:
            source = DataSource.objects.filter(url=url).order_by("id").first()
        if source is None:
            source = DataSource.objects.create(url=url, name=region_name)

        path = settings.TNDS_DIR / name

        # yes we use file size as a hash function
        # to decide whether to download the file
        if not path.exists() or path.stat().st_size != int(details["size"]):
            with open(path, "wb") as open_file:
                self.ftp.retrbinary(f"RETR {name}", open_file.write)

        sha1 = get_sha1(path)
        if sha1 != source.sha1:
            source.sha1 = sha1
            self.changed_files.append((path, source))

    def handle(self, username, password, *args, **options):
        import logging
        from ftplib import FTP

        logger = logging.getLogger(__name__)

        self.ftp = FTP(
            host="ftp.tnds.basemap.co.uk", user=username, passwd=password, timeout=120
        )

        settings.TNDS_DIR.mkdir(parents=True, exist_ok=True)
        self.changed_files = []
        self.ftp.cwd("TNDSV2.5")
        v2_files = self.list_files()
        if options.get("regions"):
            regions = {value.upper() for value in options["regions"]}
            v2_files = {name: details for name, details in v2_files.items()
                        if name.removesuffix(".zip").upper() in regions}
        self.do_files(v2_files)

        self.ftp.quit()

        for file, source in self.changed_files:
            logger.info(file.name)
            with log_time_taken(logger):
                call_command("import_transxchange", file)

            source.save(update_fields=["sha1"])
