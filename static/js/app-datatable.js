(function($) {
    'use strict';
    window.initServerDatatable = function (selector, options) {
        var prefetchSize = options.prefetchSize || 100;
        var ajaxUrl = options.ajax;
        var cache = null; // { key, rows, recordsTotal, recordsFiltered }

        function cacheKey(requestData) {
        return JSON.stringify({
            search: requestData.search.value,
            order: requestData.order,
        });
        }

        function customAjax(requestData, callback) {
            var key = cacheKey(requestData);
            var sameQuery = cache && cache.key === key;

            if (sameQuery && requestData.start + requestData.length <= cache.rows.length) {
                callback({
                draw: requestData.draw,
                recordsTotal: cache.recordsTotal,
                recordsFiltered: cache.recordsFiltered,
                data: cache.rows.slice(requestData.start, requestData.start + requestData.length),
                });
                return;
            }

            var fetchStart = sameQuery ? cache.rows.length : 0;

            $.ajax({
                url: ajaxUrl,
                data: $.extend({}, requestData, { start: fetchStart, length: prefetchSize }),
                success: function (json) {
                if (sameQuery) {
                    cache.rows = cache.rows.concat(json.data);
                } else {
                    cache = {
                    key: key,
                    rows: json.data,
                    recordsTotal: json.recordsTotal,
                    recordsFiltered: json.recordsFiltered,
                    };
                }
                callback({
                    draw: requestData.draw,
                    recordsTotal: cache.recordsTotal,
                    recordsFiltered: cache.recordsFiltered,
                    data: cache.rows.slice(requestData.start, requestData.start + requestData.length),
                });
                },
            });
        }

        var defaults = {
            serverSide: true,
            processing: true,
            autoWidth: false,
            pageLength: 20,
            lengthMenu: [[20, 50, 100], [20, 50, 100]],
            language: { search: '' },
            drawCallback: function () {
                window.scrollBy(0, 1);
                window.scrollBy(0, -1);
            },
        };
        var settings = $.extend(true, {}, defaults, options);
        settings.ajax = customAjax;
        delete settings.prefetchSize;

        var table = $(selector).DataTable(settings);

        var wrapper = $(selector).closest('.dataTables_wrapper');
        wrapper.find('div[id$=_filter] input').attr('placeholder', 'Search').removeClass('form-control-sm');
        wrapper.find('div[id$=_length] select').removeClass('form-control-sm');

        return table;
    };
})(jQuery);