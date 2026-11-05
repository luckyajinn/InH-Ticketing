from django.urls import path

from tickets import views

app_name = "tickets"

urlpatterns = [
    # Requesters
    path("tickets/", views.my_tickets, name="mine"),
    path("tickets/new/", views.new_ticket, name="new"),
    # Everyone, filtered by what they may see
    path("tickets/<int:number>/", views.ticket_detail, name="detail"),
    path("tickets/<int:number>/reply/", views.add_reply, name="reply"),
    path("tickets/<int:number>/resolve/", views.resolve, name="resolve"),
    path("tickets/<int:number>/reopen/", views.reopen, name="reopen"),
    path("attachments/<int:pk>/<path:filename>", views.download_attachment, name="attachment"),
    # IT
    path("queue/", views.queue, name="queue"),
    path("tickets/<int:number>/update/", views.update_properties, name="update"),
    path("tickets/<int:number>/assign-to-me/", views.assign_to_me, name="assign_to_me"),
]
