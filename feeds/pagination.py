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
            # Minimal page-like object compatible with DRF's Page interface
            class _EmptyPaginator:
                count = 0
                num_pages = 0

            class _EmptyPage:
                def __init__(self):
                    self.paginator = _EmptyPaginator()
                    self.number = 1
                    self.object_list = []

                def has_next(self): return False
                def has_previous(self): return False

            self.page = _EmptyPage()
            self.request = request
            return []
