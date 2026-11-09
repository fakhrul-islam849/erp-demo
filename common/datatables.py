from django.db.models import Q
from django.http import JsonResponse
from django.views import View

class BaseDatatableView(View):
    """
    Generic server-side backend for a DataTables table configured with
    serverSide: true. Subclasses only need to define:

      columns              - ordered list of dicts, one per visible column:
                              {'search_fields': [...], 'order_field': '...'}
                              'search_fields': ORM lookup paths (can cross
                                  relations with '__') OR'd together when
                                  searching this column's text.
                              'order_field': ORM field to sort by when this
                                  column header is clicked. Omit/None for a
                                  column that can't be sorted (e.g. Actions).
      default_order_field  - field used when no explicit sort was requested
                              yet, e.g. '-date_joined'.
      get_queryset(self)   - returns the unfiltered base queryset.
      render_row(self, obj)- returns a dict of cell values for one row.
    """
    columns = []
    default_order_field = None

    def get_queryset(self):
        raise NotImplementedError

    def render_row(self, obj):
        raise NotImplementedError

    def get(self, request, *args, **kwargs):
        draw = int(request.GET.get('draw', 1))
        start = int(request.GET.get('start', 0))
        length = int(request.GET.get('length', 100))
        search_value = request.GET.get('search[value]', '').strip()

        queryset = self.get_queryset()
        total_count = queryset.count()

        if search_value:
            search_filter = Q()
            for column in self.columns:
                for field in column.get('search_fields', []):
                    search_filter |= Q(**{f'{field}__icontains': search_value})
            queryset = queryset.filter(search_filter)

        filtered_count = queryset.count()

        order_column_index = request.GET.get('order[0][column]')
        order_dir = request.GET.get('order[0][dir]', 'asc')

        if order_column_index is not None and self.columns:
            column = self.columns[int(order_column_index)]
            order_field = column.get('order_field')
            if order_field and order_dir == 'desc':
                order_field = f'-{order_field}'
        else:
            order_field = self.default_order_field

        if order_field:
            queryset = queryset.order_by(order_field)

        if length == -1:
            page = queryset[start:]
        else:
            page = queryset[start:start + length]

        data = [self.render_row(obj) for obj in page]

        return JsonResponse({
            'draw': draw,
            'recordsTotal': total_count,
            'recordsFiltered': filtered_count,
            'data': data,
        })