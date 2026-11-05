/*
 * InH-Ticketing: small progressive enhancements. Every page works without
 * this file; it only saves clicks.
 */
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  // Forms marked data-autosubmit save as soon as a field changes
  // (the side panel on a ticket). Without JS, a Save button is shown instead.
  document.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
    form.addEventListener("change", function () {
      if (form.requestSubmit) form.requestSubmit(); else form.submit();
    });
  });

  // Whole queue rows are clickable; the subject link stays the real link.
  document.querySelectorAll("tr[data-href]").forEach(function (row) {
    row.addEventListener("click", function (event) {
      if (event.target.closest("a, button, input, select, label")) return;
      window.location.href = row.getAttribute("data-href");
    });
  });

  // Show the names of chosen files next to a file input.
  document.querySelectorAll("input[type=file][data-file-list]").forEach(function (input) {
    var target = document.getElementById(input.getAttribute("data-file-list"));
    if (!target) return;
    input.addEventListener("change", function () {
      var names = Array.prototype.map.call(input.files, function (f) { return f.name; });
      target.textContent = names.length ? "Attached: " + names.join(", ") : "";
    });
  });

  // Drag and drop onto a dropzone label fills its file input.
  document.querySelectorAll(".dropzone").forEach(function (zone) {
    var input = zone.querySelector("input[type=file]");
    if (!input) return;
    ["dragenter", "dragover"].forEach(function (name) {
      zone.addEventListener(name, function (e) { e.preventDefault(); zone.classList.add("is-over"); });
    });
    ["dragleave", "drop"].forEach(function (name) {
      zone.addEventListener(name, function () { zone.classList.remove("is-over"); });
    });
    zone.addEventListener("drop", function (e) {
      e.preventDefault();
      if (e.dataTransfer && e.dataTransfer.files.length) {
        input.files = e.dataTransfer.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  });

  // The composer's placeholder follows the Public / Internal choice.
  document.querySelectorAll(".composer").forEach(function (composer) {
    var text = composer.querySelector("textarea");
    if (!text) return;
    composer.querySelectorAll("input[name=visibility]").forEach(function (radio) {
      radio.addEventListener("change", function () {
        var attr = radio.value === "internal" ? "data-placeholder-internal" : "data-placeholder-public";
        text.placeholder = text.getAttribute(attr) || "";
      });
    });
  });
})();
