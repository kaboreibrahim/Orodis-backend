from .models import Reservation


def staff_reservations():
    return Reservation.objects.select_related("table", "handled_by")
