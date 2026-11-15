import logging

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from orders.models import SellerFulfillment
from control_panel.models import SellerPayout
from control_panel.services.automatic_payouts import prepare_automatic_payout
from control_panel.services.payout_initiation import (
    claim_payout_for_initiation,
    submit_claimed_payout,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Prepare eligible payouts and optionally submit authorized payouts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--payout-ids",
            nargs="+",
            type=int,
            help="Explicit payout IDs authorized for live submission.",
        )
        parser.add_argument(
            "--submit",
            action="store_true",
            help="Submit the specified payout IDs to AzamPay.",
        )

    def handle(self, *args, **options):
        payout_ids = options["payout_ids"]
        submit = options["submit"]

        if submit and not payout_ids:
            raise CommandError(
                "Live submission requires explicit --payout-ids."
            )

        if payout_ids and not submit:
            raise CommandError(
                "Use --submit with --payout-ids."
            )

        if not submit:
            now = timezone.now()

            fulfillments = (
                SellerFulfillment.objects
                .filter(
                    shipped_at__isnull=False,
                    order__payment__status="paid",
                )
                .filter(
                    Q(buyer_confirmed_at__isnull=False)
                    | Q(release_at__lte=now)
                    | Q(dispute_status=SellerFulfillment.DISPUTE_RELEASE)
                )
                .order_by("pk")
                .values_list("pk", flat=True)
                .iterator(chunk_size=200)
            )

            prepared = skipped = failed = 0

            for fulfillment_id in fulfillments:
                try:
                    payout = prepare_automatic_payout(fulfillment_id)

                    if payout is None:
                        skipped += 1
                        continue

                    prepared += 1
                    self.stdout.write(
                        f"Prepared payout {payout.pk} "
                        f"for fulfillment {fulfillment_id}"
                    )
                except Exception:
                    failed += 1
                    logger.exception(
                        "Payout preparation failed: fulfillment=%s",
                        fulfillment_id,
                    )

            self.stdout.write(
                f"Prepared: {prepared}, "
                f"Skipped: {skipped}, Failed: {failed}"
            )
            return

        for payout_id in dict.fromkeys(payout_ids):
            try:
                payout = SellerPayout.objects.get(pk=payout_id)

                self.stdout.write(
                    f"Processing payout {payout.pk}: "
                    f"{payout.amount} {payout.currency}, "
                    f"{payout.channel_provider}"
                )

                attempt = claim_payout_for_initiation(payout.pk)

                if attempt is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Payout {payout_id} not claimed."
                        )
                    )
                    continue

                result = submit_claimed_payout(attempt.pk)

                self.stdout.write(
                    f"Payout {payout_id}: "
                    f"submission function returned {result}. "
                    "Check recorded payout status."
                )

            except Exception:
                logger.exception(
                    "Automatic submission failed: payout=%s",
                    payout_id,
                )
                self.stderr.write(
                    self.style.ERROR(
                        f"Payout {payout_id} failed. "
                        "Inspect the attempt before any retry."
                    )
                )
