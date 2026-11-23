from django.urls import path

from tickets import views

app_name = "tickets"

urlpatterns = [
    # Requesters
    path("tickets/", views.my_tickets, name="mine"),
    path("tickets/new/", views.new_ticket, name="new"),
    path("tickets/check-text/", views.check_text, name="check_text"),
    path("tickets/go/", views.go_to_ticket, name="go"),
    # Everyone, filtered by what they may see
    path("tickets/<int:number>/", views.ticket_detail, name="detail"),
    path("tickets/<int:number>/reply/", views.add_reply, name="reply"),
    path("tickets/<int:number>/resolve/", views.resolve, name="resolve"),
    path("tickets/<int:number>/reopen/", views.reopen, name="reopen"),
    path("attachments/<int:pk>/<path:filename>", views.download_attachment, name="attachment"),
    # IT
    path("queue/", views.queue, name="queue"),
    path("people/find/", views.find_people, name="find_people"),
    path("tickets/<int:number>/update/", views.update_properties, name="update"),
    path("tickets/<int:number>/assign-to-me/", views.assign_to_me, name="assign_to_me"),
    path("tickets/<int:number>/ask-to-move/", views.ask_to_move, name="ask_to_move"),
    path("tickets/<int:number>/move/", views.move_ticket, name="move"),
    path("tickets/<int:number>/unarchive/", views.unarchive, name="unarchive"),
    path("tickets/<int:number>/remove/", views.remove_content, name="remove"),
    path("tickets/<int:number>/documentation/", views.save_documentation, name="documentation"),
    # Admins
    path("reports/", views.reports_page, name="reports"),
    path("reports/requests.csv", views.reports_csv, name="reports_csv"),
    path("reports/documentation/", views.reports_documentation, name="reports_documentation"),
]
