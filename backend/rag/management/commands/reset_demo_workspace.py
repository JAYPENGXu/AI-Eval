from django.core.management.base import BaseCommand, CommandError

from rag.demo_seed import DEMO_ORG_SLUGS, reset_demo_workspace, seed_demo_workspace


class Command(BaseCommand):
    help = "Reset only the organizations marked as the fixed demo tenants."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", required=True, help="Must equal 'demo-workspace'.")
        parser.add_argument("--no-process", action="store_true")
        parser.add_argument("--delete-only", action="store_true")

    def handle(self, *args, **options):
        if options["confirm"] != "demo-workspace":
            raise CommandError("Refusing reset: pass --confirm demo-workspace")
        count = reset_demo_workspace(delete_users=True)
        if not options["delete_only"]:
            seed_demo_workspace(process=not options["no_process"])
        self.stdout.write(self.style.SUCCESS(f"Reset {count} demo tenants: {', '.join(DEMO_ORG_SLUGS)}"))
