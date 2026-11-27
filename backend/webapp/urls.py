# SPDX-License-Identifier: AGPL-3.0-only
from django.urls import path
from backend.registration import registration as G
from . import results
from . import round_actions
from . import views as V
from . import tournament_archive
from . import deadlines
from . import audit
from . import roster
from . import match_logs
urlpatterns = [
    path('api/v1/health/', V.health),
    path('api/v1/auth/session/', V.session), path('api/v1/auth/login/', V.login_view),
    path('api/v1/auth/logout/', V.logout_view), path('api/v1/tournaments/', V.tournaments),
    path('api/v1/dependencies/', V.dependencies), path('api/v1/admin/operations/', V.operations),
    path('api/v1/admin/audit-logs/', audit.admin_audit),
    path('api/v1/matches/<str:mid>/replay/', V.replay),
    path('api/v1/matches/<str:mid>/logs/', match_logs.match_logs),
    path('api/v1/notifications/', V.notifications),
    path('api/v1/notifications/<str:nid>/', V.notification_detail),
    path('api/v1/me/notification-preferences/', V.notification_preferences),
    path('api/v1/tournaments/<str:tid>/analytics/', V.analytics),
    path('api/v1/tournaments/<str:tid>/analytics.csv', V.analytics_csv),
    path('api/v1/tournaments/<str:tid>/live/', V.live),
    path('api/v1/tournaments/<str:tid>/teams/<str:team>/', V.team_profile),
    path('api/v1/tournaments/<str:tid>/teams/<str:team>/submissions/', V.submissions),
    path('api/v1/tournaments/<str:tid>/submissions/<str:sid>/download/', V.download),
    path('api/v1/tournaments/<str:tid>/submissions/<str:sid>/validation/', V.submission_validation),
    path('api/v1/tournaments/<str:tid>/archive/', tournament_archive.archive),
    path('api/v1/tournaments/<str:tid>/extend-deadline/', deadlines.extend_deadline),
    path('api/v1/tournaments/<str:tid>/emergency-override/', deadlines.emergency_override),
    path('api/v1/tournaments/<str:tid>/audit-logs/', audit.tournament_audit),
    path('api/v1/tournaments/<str:tid>/roster/', roster.roster),
    path('api/v1/tournaments/<str:tid>/roster/import/', roster.import_roster),
    path('api/v1/tournaments/<str:tid>/roster/report/', roster.report),
    path('api/v1/tournaments/<str:tid>/roster/<str:entry_id>/', roster.correct_entry),
    path('api/v1/tournaments/<str:tid>/invitation-codes/', roster.invitation_codes),
    path('api/v1/tournaments/<str:tid>/invitation-codes/<str:code_id>/revoke/',
         roster.change_invitation_code, {'operation': G.revoke_code}),
    path('api/v1/tournaments/<str:tid>/invitation-codes/<str:code_id>/replace/',
         roster.change_invitation_code, {'operation': G.replace_code}),
    path('api/v1/tournaments/<str:tid>/disputes/', V.disputes),
    path('api/v1/tournaments/<str:tid>/disputes/<uuid:did>/', V.dispute_detail),
    path('api/v1/tournaments/<str:tid>/bracket/', results.bracket),
    path('api/v1/tournaments/<str:tid>/bracket/generate/', round_actions.generate),
    path('api/v1/tournaments/<str:tid>/map-pool/', round_actions.map_pool),
    path('api/v1/tournaments/<str:tid>/rounds/<int:round_number>/start/', round_actions.start),
    path('api/v1/matches/<str:mid>/', results.match_detail),
]
