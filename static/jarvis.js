(function () {
  function copyText(text, btn) {
    if (!text) return;
    navigator.clipboard.writeText(text).then(
      function () {
        if (btn) {
          var prev = btn.textContent;
          btn.textContent = "Copied";
          setTimeout(function () {
            btn.textContent = prev;
          }, 1400);
        }
      },
      function () {
        if (btn) btn.textContent = "Copy failed";
      }
    );
  }

  document.addEventListener("click", function (e) {
    var t = e.target;
    if (t && t.classList && t.classList.contains("jv-btn-copy")) {
      var sel = t.getAttribute("data-copy");
      if (sel) {
        var el = document.querySelector(sel);
        copyText(el ? el.textContent.trim() : "", t);
      } else if (t.getAttribute("data-copy-text")) {
        copyText(t.getAttribute("data-copy-text"), t);
      }
    }
  });
})();
