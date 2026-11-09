(function ($) {
  'use strict';
  $(function () {
    var modalEl = document.getElementById('confirmDeleteModal');
    modalEl.addEventListener('show.bs.modal', function (event) {
      var trigger = event.relatedTarget;
      var url = trigger.getAttribute('data-delete-url');
      document.getElementById('confirmDeleteForm').action = url;
    });
  });
})(jQuery);
