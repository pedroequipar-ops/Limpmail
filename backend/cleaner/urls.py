from django.urls import path

from . import views

urlpatterns = [
    path('account/test-connection', views.test_connection),
    path('account', views.account_view),
    path('instruction', views.instruction_view),
    path('instruction/suggest', views.suggest_instruction),
    path('jobs', views.start_job),
    path('jobs/current', views.current_job),
    path('jobs/<int:job_id>/resume', views.resume_job),
    path('jobs/<int:job_id>/status', views.job_status),
    path('jobs/<int:job_id>/emails', views.job_emails),
    path('jobs/<int:job_id>/apply', views.apply_job),
    path('jobs/<int:job_id>/apply-status', views.apply_status),
    path('emails/<int:email_id>', views.update_email),
]
