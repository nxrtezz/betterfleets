from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ...importing import import_netex_path


class Command(BaseCommand):
    help = "Import all local NeTEx XML or ZIP files from a directory."

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("directory", type=str)
        parser.add_argument(
            "--pattern",
            action="append",
            dest="patterns",
            default=["*.xml", "*.zip"],
            help="Glob pattern to include. Can be passed multiple times.",
        )
        parser.add_argument(
            "--no-recursive",
            action="store_true",
            help="Only import files from the top level of the directory.",
        )

    def handle(self, directory, patterns, no_recursive=False, **options):
        base_dir = Path(directory).expanduser()
        if not base_dir.is_dir():
            raise CommandError(f"Directory not found: {base_dir}")

        paths = []
        for pattern in patterns:
            globber = base_dir.glob if no_recursive else base_dir.rglob
            paths.extend(globber(pattern))

        paths = sorted({path.resolve() for path in paths if path.is_file()})
        if not paths:
            raise CommandError(f"No matching files found in {base_dir}")

        imported = 0
        for path in paths:
            result = import_netex_path(path)
            if isinstance(result, list):
                for dataset, preview, member_name in result:
                    imported += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Imported {path.name}:{member_name} -> {preview.get('frame_name') or dataset.name}"
                        )
                    )
            else:
                dataset, preview = result
                imported += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Imported {path.name} -> {preview.get('frame_name') or dataset.name}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(f"Imported {imported} file(s) from {base_dir}")
        )
