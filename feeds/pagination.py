# feeds/pagination.py
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import NotFound

class SafePageNumberPagination(PageNumberPagination):
    """
    Custom paginator that returns empty results instead of 404 for invalid pages.
    """
    def paginate_queryset(self, queryset, request, view=None):
        try:
            return super().paginate_queryset(queryset, request, view)
        except NotFound:
            self.page = []
            self.request = request
            return []
