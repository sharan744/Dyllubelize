from django.conf import settings
from django.db import models


class DeliveryConfirmation(models.Model):
    """Proof-of-delivery record for a single order within a dispatch."""

    order = models.OneToOneField(
        "orders.Order", on_delete=models.CASCADE, related_name="delivery"
    )
    dispatch = models.ForeignKey(
        "dispatchapp.Dispatch", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="deliveries",
    )
    delivered_at = models.DateTimeField("Delivery Date & Time")
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="deliveries_made",
    )
    received_by = models.CharField("Customer / Received By", max_length=200)
    signature_name = models.CharField(
        "Acknowledgement / Signature", max_length=200, blank=True,
        help_text="Name of the person who signed / acknowledged receipt.",
    )
    remarks = models.TextField("Delivery Remarks", blank=True)
    pod_file = models.FileField(
        "Proof of Delivery (POD)", upload_to="pod/", blank=True, null=True,
        help_text="Photo or scanned document, if required.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-delivered_at"]

    def __str__(self):
        return f"POD for {self.order.order_no}"
