# SPDX-License-Identifier: AGPL-3.0-only
from django.urls import path
from . import views as V
from . import tournament_archive
urlpatterns = [
    path('api/v1/health/', V.health),
    path('api/v1/auth/session/', V.session), path('api/v1/auth/login/', V.login_view),
    path('api/v1/auth/logout/', V.logout_view), path('api/v1/tournaments/', V.tournaments),
    path('api/v1/dependencies/', V.dependencies), path('api/v1/admin/operations/', V.operations),
    path('api/v1/notifications/', V.notifications),
    path('api/v1/notifications/<str:nid>/', V.notification_detail),
    path('api/v1/me/notification-preferences/', V.notification_preferences),
    path('api/v1/tournaments/<str:tid>/analytics/', V.analytics),
    path('api/v1/tournaments/<str:tid>/analytics.csv', V.analytics_csv),
    path('api/v1/tournaments/<str:tid>/live/', V.live),
    path('api/v1/tournaments/<str:tid>/teams/<str:team>/submissions/', V.submissions),
    path('api/v1/tournaments/<str:tid>/submissions/<str:sid>/download/', V.download),
    path('api/v1/tournaments/<str:tid>/archive/', tournament_archive.archive),
    path('api/v1/tournaments/<str:tid>/disputes/', V.disputes),
    path('api/v1/tournaments/<str:tid>/disputes/<uuid:did>/', V.dispute_detail),
]
