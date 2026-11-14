
import logging

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from orders.models import SellerFulfillment

from control_panel.services.automatic_payouts import (
    prepare_automatic_payout,
)


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Prepare automatic seller payouts for eligible "
        "fulfillments after buyer confirmation or 60 hours."
    )

    def handle(self, *args, **options):
        now = timezone.now()

        # Find fulfillments that may be eligible.
        # The preparation service performs the final
        # eligibility and duplicate-payout checks.
        fulfillments = (
            SellerFulfillment.objects
            .filter(
                shipped_at__isnull=False,
                order__payment__status="paid",
            )
            .filter(
                Q(buyer_confirmed_at__isnull=False)
                | Q(release_at__lte=now)
            )
            .order_by("pk")
            .values_list("pk", flat=True)
            .iterator(chunk_size=200)
        )

        prepared_count = 0
        skipped_count = 0
        failed_count = 0

        for fulfillment_id in fulfillments:
            try:
                payout = prepare_automatic_payout(
                    fulfillment_id
                )

                if payout is None:
                    skipped_count += 1
                    continue

                prepared_count += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Prepared payout {payout.pk} "
                        f"for fulfillment {fulfillment_id}"
                    )
                )

            except Exception:
                failed_count += 1

                logger.exception(
                    "Automatic payout preparation failed "
                    "for fulfillment %s",
                    fulfillment_id,
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Automatic payout processing completed. "
                f"Prepared: {prepared_count}, "
                f"Skipped: {skipped_count}, "
                f"Failed: {failed_count}"
            )
        )
